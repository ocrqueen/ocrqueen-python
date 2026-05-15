"""Tests for `client.extract.create(...)`.

The HTTP layer is mocked with respx; we only verify the resource's own
behavior: file normalization, multipart shape, idempotency-key
plumbing, error mapping, and oversize rejection.
"""

from __future__ import annotations

import io
from pathlib import Path

import httpx
import pytest
import respx

from ocrqueen import OCRQueen, ValidationError
from ocrqueen.resources.extract import _MAX_UPLOAD_BYTES, _read_file

_VALID_KEY = "pk_" + "a" * 32
_API_URL = "https://api.ocrqueen.com"


# ── _read_file: input normalization ──────────────────────────────────


def test_read_file_accepts_bytes() -> None:
    name, data = _read_file(b"hello world")
    assert name == "upload.bin"
    assert data == b"hello world"


def test_read_file_accepts_path(tmp_path: Path) -> None:
    p = tmp_path / "doc.pdf"
    p.write_bytes(b"%PDF-1.4 fake")
    name, data = _read_file(p)
    assert name == "doc.pdf"
    assert data == b"%PDF-1.4 fake"


def test_read_file_accepts_str_path(tmp_path: Path) -> None:
    p = tmp_path / "doc.pdf"
    p.write_bytes(b"%PDF-1.4 fake")
    name, _data = _read_file(str(p))
    assert name == "doc.pdf"


def test_read_file_accepts_file_like() -> None:
    buf = io.BytesIO(b"hello")
    buf.name = "stream.pdf"
    name, data = _read_file(buf)
    assert name == "stream.pdf"
    assert data == b"hello"


def test_read_file_rejects_directory(tmp_path: Path) -> None:
    """A directory path should fail clearly, not raise a confusing
    OSError downstream."""
    with pytest.raises(ValidationError):
        _read_file(tmp_path)


def test_read_file_rejects_nonexistent(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _read_file(tmp_path / "missing.pdf")


def test_read_file_rejects_oversize_path(tmp_path: Path) -> None:
    p = tmp_path / "big.pdf"
    # Write 1 byte past the cap by truncating — no need to actually
    # allocate 100MB on disk.
    with p.open("wb") as f:
        f.truncate(_MAX_UPLOAD_BYTES + 1)
    with pytest.raises(ValidationError, match="exceeds"):
        _read_file(p)


def test_read_file_rejects_text_file_like() -> None:
    """Text-mode handles produce `str`, not bytes — would silently break
    the multipart encoder. Reject upfront."""
    buf = io.StringIO("not bytes")
    with pytest.raises(ValidationError, match="binary mode"):
        _read_file(buf)  # type: ignore[arg-type]


def test_read_file_rewinds_seekable_handle() -> None:
    """Pre-read the file then pass the handle — we should still get all
    its bytes."""
    buf = io.BytesIO(b"abcdefg")
    buf.read(3)  # advance past 'abc'
    _name, data = _read_file(buf)
    assert data == b"abcdefg"


# ── create(): happy path ─────────────────────────────────────────────


def test_create_sends_multipart_with_options() -> None:
    with respx.mock(base_url=_API_URL) as mock:
        route = mock.post("/v1/extract").mock(
            return_value=httpx.Response(202, json={"id": "job_abc", "status": "queued"})
        )
        with OCRQueen(api_key=_VALID_KEY) as client:
            job = client.extract.create(file=b"%PDF-1.4", profile="advanced")
        assert route.called
        req = route.calls.last.request
        # Multipart content-type
        assert "multipart/form-data" in req.headers["Content-Type"]
        # Body contains both the file and the options field
        body = req.content
        assert b'name="file"' in body
        assert b'name="options"' in body
        assert b'"extraction_profile": "advanced"' in body
        assert job.id == "job_abc"
        assert job.status == "queued"


def test_create_passes_idempotency_key() -> None:
    with respx.mock(base_url=_API_URL) as mock:
        route = mock.post("/v1/extract").mock(
            return_value=httpx.Response(202, json={"id": "job_abc", "status": "queued"})
        )
        with OCRQueen(api_key=_VALID_KEY) as client:
            client.extract.create(file=b"%PDF-1.4", idempotency_key="my-key-123")
        assert route.calls.last.request.headers["Idempotency-Key"] == "my-key-123"


def test_create_explicit_options_wins_over_profile_arg() -> None:
    """If the user passes both `profile="advanced"` and
    `options={"extraction_profile": "standard"}`, the explicit dict
    wins. Document the precedence by testing it."""
    with respx.mock(base_url=_API_URL) as mock:
        route = mock.post("/v1/extract").mock(
            return_value=httpx.Response(202, json={"id": "job_abc", "status": "queued"})
        )
        with OCRQueen(api_key=_VALID_KEY) as client:
            client.extract.create(
                file=b"%PDF-1.4",
                profile="advanced",
                options={"extraction_profile": "standard"},
            )
        body = route.calls.last.request.content
        assert b'"extraction_profile": "standard"' in body


# ── create(): error paths ────────────────────────────────────────────


def test_create_oversize_bytes_rejected() -> None:
    with OCRQueen(api_key=_VALID_KEY) as client:
        with pytest.raises(ValidationError, match="exceeds"):
            client.extract.create(file=b"\x00" * (_MAX_UPLOAD_BYTES + 1))


def test_create_404_surfaces_as_typed_exception() -> None:
    from ocrqueen import NotFoundError

    with respx.mock(base_url=_API_URL) as mock:
        mock.post("/v1/extract").mock(
            return_value=httpx.Response(404, json={"error": {"code": "NOT_FOUND", "message": "x"}})
        )
        with OCRQueen(api_key=_VALID_KEY) as client, pytest.raises(NotFoundError):
            client.extract.create(file=b"%PDF-1.4")
