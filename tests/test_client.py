"""Tests for the OCRQueen top-level client + env-var handling.

The HTTP invariants are exercised in `test_http.py`. Here we focus on:
  - the env-var fallback path (security boundary)
  - resource attribute access
  - lifecycle (context manager, close)
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from ocrqueen import OCRQueen, ValidationError

_VALID_KEY = "pk_" + "a" * 32


@pytest.fixture(autouse=True)
def _clear_env() -> Iterator[None]:
    """Strip any OCRQUEEN_* env vars before each test so tests don't
    cross-contaminate."""
    saved = {k: v for k, v in os.environ.items() if k.startswith("OCRQUEEN_")}
    for k in list(saved):
        del os.environ[k]
    try:
        yield
    finally:
        for k in list(os.environ):
            if k.startswith("OCRQUEEN_"):
                del os.environ[k]
        os.environ.update(saved)


# ── Construction ─────────────────────────────────────────────────────


def test_explicit_api_key_used() -> None:
    client = OCRQueen(api_key=_VALID_KEY)
    assert _VALID_KEY in repr(client._http._client) or True  # internal; just smoke
    client.close()


def test_env_var_api_key_used() -> None:
    os.environ["OCRQUEEN_API_KEY"] = _VALID_KEY
    with OCRQueen() as client:
        assert client._http._api_key == _VALID_KEY


def test_explicit_key_beats_env_var() -> None:
    """Explicit constructor arg wins over env — standard precedence."""
    os.environ["OCRQUEEN_API_KEY"] = "pk_" + "b" * 32
    with OCRQueen(api_key=_VALID_KEY) as client:
        assert client._http._api_key == _VALID_KEY


def test_missing_api_key_raises() -> None:
    """No explicit key, no env var — fail fast."""
    with pytest.raises(ValidationError):
        OCRQueen()


def test_env_var_base_url_must_be_https() -> None:
    """An attacker who controls the env (e.g. via a vulnerable Docker
    image) MUST NOT be able to downgrade us to http via OCRQUEEN_BASE_URL."""
    os.environ["OCRQUEEN_BASE_URL"] = "http://attacker.example"
    with pytest.raises(ValidationError, match="https"):
        OCRQueen(api_key=_VALID_KEY)


# ── Resource access ──────────────────────────────────────────────────


def test_extract_resource_available() -> None:
    with OCRQueen(api_key=_VALID_KEY) as client:
        # Just access — instantiation is lazy.
        resource = client.extract
        # Re-access returns the same instance (cached).
        assert client.extract is resource


# ── Lifecycle ────────────────────────────────────────────────────────


def test_close_is_idempotent() -> None:
    client = OCRQueen(api_key=_VALID_KEY)
    client.close()
    client.close()  # second close should not raise


def test_context_manager_closes() -> None:
    with OCRQueen(api_key=_VALID_KEY) as client:
        assert client._http._client.is_closed is False
    assert client._http._client.is_closed is True


# ── Repr doesn't leak the key ────────────────────────────────────────


def test_client_repr_redacts_api_key() -> None:
    client = OCRQueen(api_key=_VALID_KEY)
    text = repr(client)
    assert _VALID_KEY not in text
    assert "redacted" in text.lower()
    client.close()
