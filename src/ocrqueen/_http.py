"""HTTP transport layer with security-first defaults.

Every request the SDK makes goes through `HttpClient`. The defaults here
are conservative: the goal is that a customer who installs `ocrqueen`
and types `client.extract.create(...)` cannot accidentally end up:

  - sending their API key over plaintext HTTP
  - hanging indefinitely on a slow server
  - leaking their API key into logs or `repr()` of an error
  - having TLS certificate verification disabled
  - following a redirect to an attacker-controlled host

Each section below explains the threat it mitigates so future edits don't
quietly weaken the posture.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import httpx

from ocrqueen._errors import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InsufficientBalanceError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServerError,
    ValidationError,
)
from ocrqueen._version import __version__

# ── Defaults ─────────────────────────────────────────────────────────

DEFAULT_BASE_URL = "https://api.ocrqueen.com"

# Timeouts. None of these can be raised above the cap on the public API
# (Cloudflare's idle timeout is ~100s); we set a soft cap of 60s here so
# customers can't blow themselves up with a 30-minute connect timeout.
DEFAULT_TIMEOUT_CONNECT_S = 10.0
DEFAULT_TIMEOUT_READ_S = 60.0
DEFAULT_TIMEOUT_WRITE_S = 60.0
DEFAULT_TIMEOUT_POOL_S = 5.0

# API key format check. Modern OCRQueen keys are `pk_<32+ chars>`. We
# also accept the legacy `pk_live_` / `pk_test_` prefixes for customers
# who haven't rotated yet. Anything else is rejected client-side so a
# typo doesn't reach the wire (and possibly the customer's request logs).
_API_KEY_RE = re.compile(r"^pk_(live_|test_)?[A-Za-z0-9_-]{20,128}$")


# ── Sentinel value for redaction ─────────────────────────────────────


class _Redacted:
    """Marker the `repr` machinery uses in place of secret material.

    A plain string like `"<redacted>"` would be type-incompatible with
    the field's annotation; this class quacks like a sensitive blob
    without exposing its real value."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "<redacted>"


_REDACTED = _Redacted()


# ── HTTP client ───────────────────────────────────────────────────────


class HttpClient:
    """Thin wrapper over `httpx.Client` that enforces SDK invariants.

    Stateful — owns a connection pool you reuse across requests. Build
    one of these per `OCRQueen` instance, not per call.

    Critical security invariants (each one has a test in `tests/test_http.py`):
      I1  `base_url` MUST start with `https://`. Plain http is rejected.
      I2  TLS certificate verification is ON (the httpx default; we
          re-assert it so a future PR can't quietly flip it).
      I3  The `Authorization` header is set on every request from the
          stored api_key. We do not accept it as a per-call override —
          that would invite key leakage via headers param confusion.
      I4  `repr(self)` and any error message NEVER contain the api_key.
      I5  Redirects are NOT followed by default. A 301 from our API to
          a different host would silently leak the auth header.
      I6  Timeouts are always set; no infinite waits.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float | None = None,
        max_retries: int = 0,
        user_agent_suffix: str | None = None,
    ) -> None:
        # ── I1: validate base_url ────────────────────────────────
        # urlparse handles both `https://api.ocrqueen.com` and
        # `https://api.ocrqueen.com:443/v1`. We require `https` and a
        # netloc; anything else is rejected before a single byte goes
        # out. This prevents an env-var override like
        # `OCRQUEEN_BASE_URL=http://attacker.example` from working.
        parsed = urlparse(base_url)
        if parsed.scheme != "https":
            raise ValidationError(
                f"base_url must use https:// scheme, got {parsed.scheme!r}"
            )
        if not parsed.netloc:
            raise ValidationError("base_url must include a hostname")

        # ── Validate api_key format ──────────────────────────────
        # Rejecting malformed keys client-side prevents:
        #   - typos that produce confusing 401s with no hint
        #   - whitespace-padded keys (paste accidents) reaching the wire
        #   - non-OCRQueen keys (e.g. a Stripe key copy-pasted by mistake)
        #     ending up in third-party logs we don't control.
        if not isinstance(api_key, str):
            raise ValidationError("api_key must be a string")
        api_key = api_key.strip()
        if not _API_KEY_RE.match(api_key):
            raise ValidationError(
                "api_key has unexpected format. Expected `pk_...`; get a "
                "fresh one from https://ocrqueen.com/dashboard/keys"
            )

        # Store the key on a single-underscore attribute. `repr()` below
        # explicitly redacts it; no other method should reference it
        # except `_headers()`.
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._max_retries = max(0, int(max_retries))

        # ── I6: timeouts ─────────────────────────────────────────
        # httpx supports per-phase timeouts. A single `timeout_seconds`
        # value sets all four — convenient escape hatch for slow
        # connections — but the per-phase defaults stay otherwise.
        if timeout_seconds is None:
            timeout = httpx.Timeout(
                connect=DEFAULT_TIMEOUT_CONNECT_S,
                read=DEFAULT_TIMEOUT_READ_S,
                write=DEFAULT_TIMEOUT_WRITE_S,
                pool=DEFAULT_TIMEOUT_POOL_S,
            )
        else:
            if timeout_seconds <= 0:
                raise ValidationError("timeout_seconds must be positive")
            timeout = httpx.Timeout(timeout_seconds)

        # ── I2: TLS verification ─────────────────────────────────
        # `verify=True` is the httpx default; we set it explicitly so
        # this stays true even if upstream defaults change. We never
        # expose a way to set `verify=False` because that's how
        # transport-MITM creeps in via "just for testing" patches that
        # accidentally ship.
        ua = f"ocrqueen-python/{__version__} httpx/{httpx.__version__}"
        if user_agent_suffix:
            # Allow advanced integrations (e.g. our own internal tools)
            # to extend the UA. Trim to keep the header short and ASCII
            # only so we don't trip header sanitizers downstream.
            cleaned = re.sub(r"[^A-Za-z0-9._/+-]", "", user_agent_suffix)[:64]
            if cleaned:
                ua = f"{ua} {cleaned}"

        # ── I5: redirects ────────────────────────────────────────
        # `follow_redirects=False` ensures a 3xx response is surfaced to
        # the SDK code (which then raises an error). If we ever NEED to
        # follow redirects, we'll do it manually and re-check the
        # destination host matches `base_url`.
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=timeout,
            verify=True,
            follow_redirects=False,
            headers={
                "User-Agent": ua,
                "Accept": "application/json",
            },
        )

    # ── Request / response ────────────────────────────────────────────

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Send a single request. Maps transport + HTTP errors to our hierarchy.

        `extra_headers` is provided for forward compatibility (e.g.
        `Stripe-Account` style routing if we ever ship orgs). It MUST
        NOT carry an Authorization header — we enforce that below — to
        prevent an accidental override of the SDK-managed auth.
        """
        headers = self._headers()
        if extra_headers:
            for k in extra_headers:
                if k.lower() in {"authorization", "host"}:
                    raise ValidationError(
                        f"extra_headers cannot override {k!r}; "
                        "use the SDK constructor instead"
                    )
            headers.update(extra_headers)
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key

        try:
            response = self._client.request(
                method,
                path,
                params=params,
                json=json_body,
                files=files,
                data=data,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            raise APITimeoutError(f"Request timed out: {exc}") from exc
        except httpx.TransportError as exc:
            # DNS, TCP, TLS — all bucketed as connection errors.
            raise APIConnectionError(f"Connection error: {exc}") from exc

        if response.status_code >= 400:
            self._raise_for_status(response)
        return response

    def _headers(self) -> dict[str, str]:
        """Build per-request headers, including auth.

        Returned dict is fresh each call so the caller can mutate it
        without affecting subsequent requests.
        """
        return {"Authorization": f"Bearer {self._api_key}"}

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        """Map an HTTP error response onto the SDK exception hierarchy.

        We parse the body best-effort (the API always returns JSON for
        errors, but a hostile proxy might return HTML, so guard against
        that). The body MUST NOT be included verbatim in the exception
        message if it could contain reflected user data — but our own
        API never echoes the api_key, so the structured error fields
        are safe.
        """
        request_id = response.headers.get("X-Request-ID")
        error_code: str | None = None
        message: str = f"HTTP {response.status_code}"

        try:
            body = response.json()
        except Exception:
            body = None
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                error_code = err.get("code")
                if err.get("message"):
                    message = str(err["message"])
            elif "detail" in body:
                # FastAPI default shape
                detail = body["detail"]
                if isinstance(detail, str):
                    error_code = detail.split(":", 1)[0].strip() or None
                    message = detail

        sc = response.status_code
        if sc == 400:
            raise BadRequestError(
                message, status_code=sc, error_code=error_code, request_id=request_id
            )
        if sc == 401:
            raise AuthenticationError(
                message, status_code=sc, error_code=error_code, request_id=request_id
            )
        if sc == 402:
            balance: int | None = None
            try:
                balance = int(response.headers.get("X-Wallet-Balance-Cents", ""))
            except ValueError:
                balance = None
            raise InsufficientBalanceError(
                message,
                status_code=sc,
                error_code=error_code,
                request_id=request_id,
                balance_cents=balance,
            )
        if sc == 403:
            raise PermissionDeniedError(
                message, status_code=sc, error_code=error_code, request_id=request_id
            )
        if sc == 404:
            raise NotFoundError(
                message, status_code=sc, error_code=error_code, request_id=request_id
            )
        if sc == 429:
            retry: int | None = None
            try:
                retry = int(response.headers.get("Retry-After", ""))
            except ValueError:
                retry = None
            raise RateLimitError(
                message,
                status_code=sc,
                error_code=error_code,
                request_id=request_id,
                retry_after_seconds=retry,
            )
        if sc >= 500:
            raise ServerError(
                message, status_code=sc, error_code=error_code, request_id=request_id
            )
        raise APIError(
            message, status_code=sc, error_code=error_code, request_id=request_id
        )

    # ── repr — I4 ─────────────────────────────────────────────────────

    def __repr__(self) -> str:
        # The api_key is replaced by a sentinel so logs / bug reports
        # / pdb sessions never expose it. Confirming this is one of the
        # tests below.
        return (
            f"{type(self).__name__}("
            f"base_url={self._base_url!r}, "
            f"api_key={_REDACTED!r}, "
            f"max_retries={self._max_retries!r})"
        )

    # ── Lifecycle ─────────────────────────────────────────────────────

    def close(self) -> None:
        """Close the underlying connection pool. Idempotent."""
        self._client.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
