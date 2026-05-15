"""Public client — what users instantiate.

    from ocrqueen import OCRQueen
    client = OCRQueen(api_key="pk_...")
    job = client.extract.create(file=open("paper.pdf", "rb"))

The client itself is intentionally thin: it owns the HTTP transport and
exposes resource sub-objects (`client.extract`, `client.jobs`, etc.).
Each resource is a separate file in `resources/`. We do this Stripe-style
so the call sites read naturally and the surface area is grouped by
domain rather than dumped on a single class.

Lifecycle:
  - The client owns an HTTP connection pool. Reuse one client per
    process; constructing one per call is wasteful (TLS handshake every
    time) AND opens you up to file-descriptor exhaustion.
  - Always close it (`client.close()` or use as a context manager).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from ocrqueen._http import DEFAULT_BASE_URL, HttpClient

if TYPE_CHECKING:
    from ocrqueen.resources.extract import ExtractResource
    from ocrqueen.resources.jobs import JobsResource


class OCRQueen:
    """Top-level SDK entry point.

    Args:
        api_key: Your OCRQueen API key (`pk_...`). Required. We also
            accept the `OCRQUEEN_API_KEY` env var if `api_key` is None;
            explicit is safer though — env vars get logged in places
            you don't expect.
        base_url: Override for self-hosted / dev. MUST be `https://`.
            Defaults to the public API.
        timeout_seconds: Single-value timeout override applied to all
            phases. Leave `None` for the per-phase defaults
            (recommended).
        user_agent_suffix: Optional ASCII tag identifying your app, e.g.
            `"myapp/1.2.3"`. Helps us debug your support tickets.

    Raises:
        ValidationError: bad `api_key` format, non-https base_url, or
            non-positive timeout. Raised immediately at construction
            so misconfiguration fails fast.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        user_agent_suffix: str | None = None,
    ) -> None:
        if api_key is None:
            api_key = os.environ.get("OCRQUEEN_API_KEY", "")
        # `base_url` precedence: explicit > env > default. The env var is
        # validated by the same code path so an attacker-controlled env
        # cannot smuggle in an http:// URL.
        if base_url is None:
            base_url = os.environ.get("OCRQUEEN_BASE_URL", DEFAULT_BASE_URL)

        self._http = HttpClient(
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            user_agent_suffix=user_agent_suffix,
        )

        # Resources are lazily imported so `import ocrqueen` stays cheap
        # — users who never call `client.extract` don't pay the import
        # cost. The properties below populate on first access.
        self._extract: ExtractResource | None = None
        self._jobs: JobsResource | None = None

    # ── Resources ────────────────────────────────────────────────────

    @property
    def extract(self) -> ExtractResource:
        """Document extraction — submit files, get structured data back."""
        if self._extract is None:
            # Lazy import avoids a top-level circular if `resources.*`
            # ever needs to refer back to `OCRQueen` types.
            from ocrqueen.resources.extract import ExtractResource

            self._extract = ExtractResource(self._http)
        return self._extract

    @property
    def jobs(self) -> JobsResource:
        """Job lifecycle — `get`, `list`, `cancel`, `wait`."""
        if self._jobs is None:
            from ocrqueen.resources.jobs import JobsResource

            self._jobs = JobsResource(self._http)
        return self._jobs

    # ── Lifecycle ────────────────────────────────────────────────────

    def close(self) -> None:
        """Release the HTTP connection pool. Idempotent."""
        self._http.close()

    def __enter__(self) -> OCRQueen:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def __repr__(self) -> str:
        # Delegates to HttpClient.__repr__, which already redacts the
        # api_key. Keep this in sync if HttpClient's repr changes.
        return f"OCRQueen(http={self._http!r})"
