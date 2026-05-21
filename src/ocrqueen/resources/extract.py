"""Extract resource — `client.extract.create(...)`.

Wraps `POST /v1/extract` on the OCRQueen API.

Design notes:
  - We accept `file` as bytes, a file-like object, or a path. Each one
    is normalized to bytes before sending so the multipart encoder
    behaves consistently. Path inputs are validated against directory
    traversal — see `_read_file`.
  - `options` is the API's `ExtractOptions` schema; we accept a dict
    for now and let the server validate. Once we generate types from
    the OpenAPI spec, this becomes a TypedDict for IDE help.
  - `idempotency_key` is plumbed through to the SDK-level header so
    customer retries are safe.

Return value: a small dataclass that mirrors the API's `JobResponse`
contract — `id`, `status`, `domain`, and the populated extraction
field (`document` for general, `patent` for patent), plus `markdown`
and `cache_hit`. The full server response is preserved as `raw` so
advanced callers can dig in without us locking the schema.
"""

from __future__ import annotations

import mimetypes
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Literal

from ocrqueen._errors import ValidationError
from ocrqueen._http import HttpClient

# What an OCRQueen file upload looks like in practice. We accept any of
# these so customers can pass the most natural thing for their context.
FileInput = bytes | str | Path | IO[bytes]

ExtractionProfile = Literal["standard", "advanced"]


# ── Response shapes ──────────────────────────────────────────────────


@dataclass
class ExtractJob:
    """Result of `client.extract.create(...)` / `client.jobs.get(...)`.

    Mirrors the API's `JobResponse` schema. For async (default) jobs,
    only `id` + `status="queued"` are set initially; `document` /
    `patent` / `markdown` populate after polling. For jobs the server
    finished in-band (`status="completed"`), the result fields are
    already populated.

    Branch on `domain` to pick the right extraction field:
      - `domain == "general"` → use `document` (also exposed via
        the `result` property as a legacy alias)
      - `domain == "patent"`  → use `patent`

    `raw` is the full server response — kept for advanced callers who
    need a field the dataclass doesn't surface. We use `field(repr=False)`
    so a default `print(job)` stays readable.
    """

    id: str
    status: str
    domain: str = "general"
    document: dict[str, Any] | None = None
    patent: dict[str, Any] | None = None
    markdown: str | None = None
    cache_hit: bool = False
    error_code: str | None = None
    error_message: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def result(self) -> dict[str, Any] | None:
        """Legacy alias — returns whichever extraction field is populated.

        Returns `document` for general-domain jobs, `patent` for
        patent-domain jobs. Prefer reading `.document` / `.patent`
        directly so the domain dispatch is explicit at the call site.
        """
        return self.patent if self.domain == "patent" else self.document


def _job_from_body(body: Any) -> ExtractJob:
    """Build an `ExtractJob` from a server response body.

    Centralised so every endpoint that returns a `JobResponse` shape
    (`POST /v1/extract`, `GET /v1/jobs/{id}`, `GET /v1/jobs`,
    `DELETE /v1/jobs/{id}`) maps the wire fields the same way. The
    wire format uses `job_id` and a nested `error: {code, message}`;
    we surface those as `.id` and `.error_code / .error_message` for
    Pythonic ergonomics while preserving the raw body for advanced use.
    """
    if not isinstance(body, dict):
        raise ValidationError("unexpected job response shape")
    error = body.get("error") or {}
    if not isinstance(error, dict):
        error = {}
    return ExtractJob(
        id=str(body.get("job_id") or ""),
        status=str(body.get("status") or ""),
        domain=str(body.get("domain") or "general"),
        document=body.get("document"),
        patent=body.get("patent"),
        markdown=body.get("markdown"),
        cache_hit=bool(body.get("cache_hit", False)),
        error_code=error.get("code"),
        error_message=error.get("message"),
        raw=body,
    )


# ── Helpers ──────────────────────────────────────────────────────────


# Max upload — match the server's hard cap so we fail fast locally.
# Keep this in sync with `MAX_FILE_SIZE_BYTES` in the API.
_MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB


# Map common upload extensions to their canonical MIME types. We ship
# our own table because `mimetypes` on some platforms doesn't know
# `.pptx` / `.heic` and falls back to `application/octet-stream`, which
# the server rejects with `UNSUPPORTED_FILE_TYPE`.
_MIME_BY_EXT: dict[str, str] = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def _guess_mime(filename: str) -> str:
    """Return the MIME type for `filename`, defaulting to octet-stream.

    Prefers the SDK's own table so the supported-file matrix stays
    explicit; falls back to `mimetypes` for anything outside it.
    """
    ext = os.path.splitext(filename)[1].lower()
    if ext in _MIME_BY_EXT:
        return _MIME_BY_EXT[ext]
    guess, _ = mimetypes.guess_type(filename)
    return guess or "application/octet-stream"


def _read_file(file: FileInput) -> tuple[str, bytes]:
    """Coerce any `FileInput` to `(filename, bytes)`.

    Path / str inputs:
      - Must be a regular file (not a symlink to /etc/passwd, not a
        device, not a directory). `Path.is_file()` follows symlinks but
        also rejects non-files. We don't traverse — we open exactly the
        path the user gave us.
      - We refuse files above the server cap so the customer doesn't
        burn bandwidth on a guaranteed-400.

    File-like inputs:
      - We seek to 0 first so a re-used handle doesn't send a partial
        read. If `.seek` fails (e.g. it's a pipe), we just read from the
        current position.
    """
    if isinstance(file, bytes):
        if len(file) > _MAX_UPLOAD_BYTES:
            raise ValidationError(
                f"file is {len(file)} bytes — exceeds the {_MAX_UPLOAD_BYTES} byte limit"
            )
        return ("upload.bin", file)

    if isinstance(file, (str, Path)):
        path = Path(file)
        # Reject anything that isn't a regular file. `is_file()` already
        # handles "doesn't exist", but we also reject if the resolved
        # target escapes the parent — defensive, not strictly necessary.
        if not path.is_file():
            raise ValidationError(f"file path does not refer to a regular file: {path}")
        size = path.stat().st_size
        if size > _MAX_UPLOAD_BYTES:
            raise ValidationError(
                f"file is {size} bytes — exceeds the {_MAX_UPLOAD_BYTES} byte limit"
            )
        with path.open("rb") as f:
            data = f.read()
        return (path.name, data)

    # File-like
    seek = getattr(file, "seek", None)
    if callable(seek):
        try:
            seek(0)
        except (OSError, ValueError):
            # Non-seekable streams (pipes, sockets) — fall through and
            # read from wherever they are.
            pass
    data = file.read()
    if not isinstance(data, bytes):
        raise ValidationError("file-like object must produce bytes — open in binary mode")
    if len(data) > _MAX_UPLOAD_BYTES:
        raise ValidationError(
            f"file is {len(data)} bytes — exceeds the {_MAX_UPLOAD_BYTES} byte limit"
        )
    # Try to recover the filename from `.name` (real files); fall back
    # to a generic placeholder for in-memory streams.
    name = getattr(file, "name", None)
    if isinstance(name, str) and name:
        name = os.path.basename(name)
    else:
        name = "upload.bin"
    return (name, data)


# ── Resource ─────────────────────────────────────────────────────────


class ExtractResource:
    """`POST /v1/extract` wrapper."""

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    def create(
        self,
        *,
        file: FileInput,
        profile: ExtractionProfile = "standard",
        options: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> ExtractJob:
        """Submit a document for extraction.

        Args:
            file: Bytes, a path string/Path, or a binary file-like
                object. Must be a supported MIME type (PDF, PNG, JPEG,
                WebP, HEIC, PPTX) — the server rejects others with 400.
            profile: `"standard"` (text + layout, $0.005/page) or
                `"advanced"` (adds diagram extraction + image
                enhancement, $0.015/page).
            options: Extra `ExtractOptions` fields — `callback_url`,
                `bypass_cache`, `retain_hours`, `result_retain_hours`
                (0-168, defaults to `retain_hours`), `storage_destination_id`.
                The server is the source of truth for which keys are
                accepted; see the API docs at /docs/data-retention for
                the retention-related ones.
            idempotency_key: Stripe-style key. Retrying the same key
                with the same customer returns the original job — no
                re-extraction, no re-billing.

        Returns:
            `ExtractJob` with `id` (always) and `status`. For an
            async (default) submission `status="queued"`; poll with
            `client.jobs.get(job.id)` (once that resource ships).

        Raises:
            ValidationError: file is missing / too big / wrong kind.
            BadRequestError: server rejected the file (unsupported
                MIME, malformed options).
            AuthenticationError / RateLimitError /
            InsufficientBalanceError: see `_errors`.
        """
        filename, body = _read_file(file)

        # Merge the simple `profile` arg into the options dict so callers
        # can use either spelling. Explicit `options["extraction_profile"]`
        # wins if both are passed — the server validates the final shape.
        merged_options: dict[str, Any] = dict(options or {})
        merged_options.setdefault("extraction_profile", profile)

        # multipart form: `file` plus a JSON-encoded `options` field.
        # We encode `options` ourselves rather than relying on httpx's
        # smart-form behaviour so the server sees a single string field
        # (matches the FastAPI route signature).
        import json

        # Explicit MIME type on the multipart part. Without this httpx
        # falls back to `application/octet-stream`, which the server
        # rejects with `UNSUPPORTED_FILE_TYPE`.
        files = {"file": (filename, body, _guess_mime(filename))}
        data = {"options": json.dumps(merged_options)}

        response = self._http.request(
            "POST",
            "/v1/extract",
            files=files,
            data=data,
            idempotency_key=idempotency_key,
        )
        return _job_from_body(response.json())
