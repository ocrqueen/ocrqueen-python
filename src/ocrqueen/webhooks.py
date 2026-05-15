"""Webhook signature verification — public helper for customers.

OCRQueen signs every outbound webhook (extraction.completed,
extraction.failed) with an HMAC-SHA256 over the raw body, keyed by the
webhook endpoint's signing secret. The signature ships in the
`OCRQueen-Signature` header in the form `sha256=<hex>`.

CUSTOMER USAGE:

    from ocrqueen import verify_webhook

    @app.post("/webhook")
    async def receive(request):
        raw = await request.body()
        sig = request.headers.get("OCRQueen-Signature", "")
        if not verify_webhook(raw, sig, secret=MY_WEBHOOK_SECRET):
            raise HTTPException(401)
        # safe to act on payload
        ...

SECURITY RULES (every one has a test):

  1. ALWAYS use the RAW request body — do NOT `json.loads()` and
     `json.dumps()` again; that re-serialization changes byte order /
     spacing and breaks the HMAC.
  2. Comparison is constant-time (`hmac.compare_digest`) to defeat
     timing attacks.
  3. Returns False (NOT raises) on every failure mode: missing
     signature, malformed header, secret typo, body tampered, wrong
     digest length. The customer's handler can then return 401.
  4. We never log the secret or the expected signature anywhere.
"""

from __future__ import annotations

import hashlib
import hmac

__all__ = ["verify_webhook"]


def verify_webhook(
    body: bytes,
    signature_header: str,
    *,
    secret: str,
) -> bool:
    """Verify the `OCRQueen-Signature` header against the raw body.

    Args:
        body: the raw request body bytes — NOT a re-serialized dict.
        signature_header: the `OCRQueen-Signature` header value. Accepts
            either `sha256=<hex>` (canonical) or a bare hex digest.
        secret: the webhook endpoint's signing secret, from the dashboard.

    Returns:
        True iff the signature matches. False on every other case — never
        raises so a hostile request can't crash the handler.
    """
    if not isinstance(body, (bytes, bytearray)):
        return False
    if not isinstance(signature_header, str) or not signature_header:
        return False
    if not isinstance(secret, str) or not secret:
        return False

    # Strip the canonical `sha256=` prefix; tolerate the legacy bare-hex form.
    candidate = signature_header.strip()
    if candidate.startswith("sha256="):
        candidate = candidate.removeprefix("sha256=")
    # Reject anything that's not a 64-char hex string before doing HMAC —
    # cheap rejection of obviously-malformed input.
    if len(candidate) != 64 or not all(c in "0123456789abcdefABCDEF" for c in candidate):
        return False

    expected = hmac.new(
        secret.encode("utf-8"),
        bytes(body),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, candidate.lower())
