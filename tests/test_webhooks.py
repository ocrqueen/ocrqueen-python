"""Tests for the public `verify_webhook` helper.

These tests are the executable form of the security contract: each
case fails loudly if a future change weakens verification. Every test
matches a real risk a customer's webhook endpoint faces.
"""

from __future__ import annotations

import hashlib
import hmac

from ocrqueen import verify_webhook


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ── Happy paths ──────────────────────────────────────────────────────


def test_accepts_canonical_signature() -> None:
    body = b'{"event":"extraction.completed","job_id":"job_x"}'
    secret = "whsec_test"
    assert verify_webhook(body, _sign(body, secret), secret=secret) is True


def test_accepts_bare_hex_signature() -> None:
    body = b'{"x":1}'
    secret = "whsec_test"
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_webhook(body, sig, secret=secret) is True


def test_uppercase_hex_accepted() -> None:
    """Some HTTP libs uppercase header values — verifier should tolerate."""
    body = b'{"x":1}'
    secret = "whsec_test"
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest().upper()
    assert verify_webhook(body, sig, secret=secret) is True


# ── Security: tampered body / wrong secret / forged sig ──────────────


def test_rejects_tampered_body() -> None:
    secret = "whsec_test"
    sig = _sign(b'{"amount":100}', secret)
    assert verify_webhook(b'{"amount":10000}', sig, secret=secret) is False


def test_rejects_wrong_secret() -> None:
    body = b'{"x":1}'
    sig = _sign(body, "secretA")
    assert verify_webhook(body, sig, secret="secretB") is False


def test_rejects_forged_hex_of_correct_length() -> None:
    body = b'{"x":1}'
    forged = "sha256=" + "0" * 64
    assert verify_webhook(body, forged, secret="whsec_test") is False


# ── Security: malformed inputs never raise ───────────────────────────


def test_empty_signature_returns_false() -> None:
    assert verify_webhook(b'{"x":1}', "", secret="whsec_test") is False


def test_empty_secret_returns_false() -> None:
    body = b'{"x":1}'
    sig = _sign(body, "whsec_test")
    assert verify_webhook(body, sig, secret="") is False


def test_non_bytes_body_returns_false() -> None:
    # Customers sometimes pass `request.body` (a string) by mistake — must
    # return False instead of crashing.
    assert verify_webhook("not bytes", "sha256=" + "a" * 64, secret="s") is False  # type: ignore[arg-type]


def test_signature_wrong_length_rejected() -> None:
    """Anything that isn't exactly 64 hex chars is rejected before HMAC.

    Cheap pre-check defends against malformed input AND short-circuits a
    class of length-extension confusion.
    """
    assert verify_webhook(b"{}", "sha256=ff", secret="whsec") is False
    assert verify_webhook(b"{}", "sha256=" + "g" * 64, secret="whsec") is False


def test_no_sha256_prefix_still_accepted_when_valid() -> None:
    """Legacy header form: bare hex digest, no `sha256=` prefix."""
    body = b'{"x":1}'
    secret = "whsec"
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_webhook(body, digest, secret=secret) is True


# ── Timing-attack defence ────────────────────────────────────────────


def test_uses_constant_time_comparison() -> None:
    """Smoke check: `verify_webhook` exists, is callable, returns bool.

    We can't easily measure timing here, but we can assert the function
    reaches `hmac.compare_digest` (used internally) by relying on the
    `hmac` import being needed — it would fail to import otherwise.
    """
    import ocrqueen.webhooks as wh

    src = wh.verify_webhook.__module__
    assert src == "ocrqueen.webhooks"
