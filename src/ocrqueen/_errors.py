"""Exception hierarchy for the SDK.

All exceptions descend from `OCRQueenError` so customers can catch them
with a single except. Specific subclasses let them branch on the
recoverable cases (rate limit, insufficient balance) without parsing
error message strings.

Design rule: an exception MUST NEVER carry the customer's API key in
any form. Many bug reports include `repr(exc)` — leaking the key there
is a silent credential exposure. We assert this in the test suite.
"""

from __future__ import annotations


class OCRQueenError(Exception):
    """Base for every exception this SDK raises.

    Carries the HTTP status code (or `None` for transport errors) and
    the OCRQueen error code from the response body (e.g. `RATE_LIMITED`,
    `INSUFFICIENT_BALANCE`). Both are optional so transport-layer
    exceptions can use the same hierarchy without faking fields.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        # `request_id` is the X-Request-ID header the API echoes back —
        # gold for support tickets. Surface it so customers can paste it
        # into bug reports.
        self.request_id = request_id

    def __repr__(self) -> str:
        # Deterministic repr that NEVER includes auth material. The base
        # Exception repr is fine — but we override here so future fields
        # can't accidentally leak via `print(exc)` if they get added.
        return (
            f"{type(self).__name__}("
            f"message={self.message!r}, "
            f"status_code={self.status_code!r}, "
            f"error_code={self.error_code!r}, "
            f"request_id={self.request_id!r})"
        )


# ── Transport / network ───────────────────────────────────────────────


class APIConnectionError(OCRQueenError):
    """Could not reach the API at all — DNS failure, TCP reset, TLS
    handshake failure, etc. Usually a network-side problem; retry is
    safe (we haven't sent anything the server might have processed)."""


class APITimeoutError(APIConnectionError):
    """Request did not complete within the configured timeout. Retry is
    safe ONLY for idempotent operations (GET, or POST with
    `Idempotency-Key`) — otherwise the server may have started
    processing and a blind retry could double-bill."""


# ── HTTP-layer ────────────────────────────────────────────────────────


class APIError(OCRQueenError):
    """Generic 4xx/5xx response that doesn't fit a specific subclass."""


class AuthenticationError(APIError):
    """401 — API key missing, malformed, or revoked.

    NOT retryable. Surface this clearly to the user; their key is the
    problem, not the network."""


class PermissionDeniedError(APIError):
    """403 — key is valid but lacks the scope needed for this call.

    NOT retryable. The customer needs to issue a new key with the right
    scope set."""


class NotFoundError(APIError):
    """404 — resource doesn't exist (e.g. job_id from a different
    customer, or a deleted key)."""


class RateLimitError(APIError):
    """429 — too many requests in the current window.

    Carries `retry_after_seconds` from the `Retry-After` header so a
    retry policy can sleep precisely instead of guessing."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        request_id: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=status_code,
            error_code=error_code,
            request_id=request_id,
        )
        self.retry_after_seconds = retry_after_seconds


class InsufficientBalanceError(APIError):
    """402 — wallet balance is below the cost of this request.

    Carries `balance_cents` from the `X-Wallet-Balance-Cents` header so
    the caller can render an accurate top-up prompt."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        request_id: str | None = None,
        balance_cents: int | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=status_code,
            error_code=error_code,
            request_id=request_id,
        )
        self.balance_cents = balance_cents


class BadRequestError(APIError):
    """400 — request was rejected before processing (bad MIME type,
    file too large, malformed options, etc.)."""


class ServerError(APIError):
    """5xx — something went wrong on our side. Retryable for idempotent
    operations only."""


# ── Validation ────────────────────────────────────────────────────────


class ValidationError(OCRQueenError):
    """A constructor argument failed local validation BEFORE any network
    call.

    Example: an `api_key` that doesn't match the expected `pk_...` shape,
    or a `base_url` that isn't `https://`. We raise this client-side so
    customers see an immediate error rather than a confusing 401."""
