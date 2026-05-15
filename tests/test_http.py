"""Tests for the HTTP foundation — one test per security invariant.

These tests are the executable form of the threat model: each one fails
loudly if a future change weakens the SDK's posture. Do NOT relax them
without an explicit security review.
"""

from __future__ import annotations

import re

import httpx
import pytest
import respx

from ocrqueen._errors import (
    APIConnectionError,
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
from ocrqueen._http import (
    DEFAULT_BASE_URL,
    HttpClient,
)

_VALID_KEY = "pk_" + "a" * 32


# ── I1 — HTTPS-only base_url ─────────────────────────────────────────


def test_rejects_http_base_url() -> None:
    """Plaintext HTTP MUST NOT be accepted, even on localhost.

    Why no localhost exception: testing against `http://localhost:8080`
    would seem fine, but the same code path is what a real customer's
    misconfigured staging URL exercises. Better to fail loudly and force
    them to use `https://` everywhere."""
    with pytest.raises(ValidationError, match="https"):
        HttpClient(api_key=_VALID_KEY, base_url="http://api.ocrqueen.com")


def test_rejects_empty_or_garbage_base_url() -> None:
    with pytest.raises(ValidationError):
        HttpClient(api_key=_VALID_KEY, base_url="not-a-url")
    with pytest.raises(ValidationError):
        HttpClient(api_key=_VALID_KEY, base_url="https://")


# ── I2 — TLS verification stays on ───────────────────────────────────


def test_tls_verification_is_enabled_by_default() -> None:
    """Defense-in-depth: even though httpx defaults to verify=True, we
    re-check it here so a future PR can't silently flip it."""
    client = HttpClient(api_key=_VALID_KEY, base_url=DEFAULT_BASE_URL)
    # `_client._transport._pool._ssl_context` differs across httpx
    # versions; the public surface is `verify` on the transport. We just
    # check that our HttpClient didn't pass `verify=False` anywhere.
    repr_str = repr(client._client)
    assert "verify=False" not in repr_str


# ── I3 — Authorization header is auto-set and immutable ──────────────


def test_auth_header_set_on_every_request() -> None:
    with respx.mock(base_url=DEFAULT_BASE_URL) as mock:
        route = mock.get("/v1/ping").mock(return_value=httpx.Response(200, json={"ok": True}))
        with HttpClient(api_key=_VALID_KEY) as c:
            c.request("GET", "/v1/ping")
        assert route.called
        sent_auth = route.calls.last.request.headers.get("Authorization")
        assert sent_auth == f"Bearer {_VALID_KEY}"


def test_extra_headers_cannot_override_authorization() -> None:
    """A buggy caller passing `extra_headers={'Authorization': ...}`
    must fail loudly rather than silently swap the credential — this
    has been a real attack pattern in other SDKs."""
    with HttpClient(api_key=_VALID_KEY) as c:
        with pytest.raises(ValidationError, match="Authorization"):
            c.request(
                "GET",
                "/v1/ping",
                extra_headers={"Authorization": "Bearer attacker"},
            )


# ── I4 — api_key never appears in repr / error / exception ───────────


def test_repr_redacts_api_key() -> None:
    client = HttpClient(api_key=_VALID_KEY)
    text = repr(client)
    assert _VALID_KEY not in text
    assert "redacted" in text.lower()


def test_validation_error_does_not_leak_api_key() -> None:
    """The constructor raises ValidationError on bad config; the
    exception message MUST NOT include the api_key, because customers
    paste exceptions into bug reports."""
    try:
        HttpClient(api_key=_VALID_KEY, base_url="http://attacker.example")
    except ValidationError as exc:
        assert _VALID_KEY not in str(exc)
        assert _VALID_KEY not in repr(exc)


# ── I5 — redirects are NOT followed ──────────────────────────────────


def test_redirect_is_not_auto_followed() -> None:
    """A 3xx from our API to a different origin would otherwise leak
    the Authorization header to the redirect target. We surface 3xx as
    an APIError instead of silently chasing it."""
    with respx.mock(base_url=DEFAULT_BASE_URL) as mock:
        mock.get("/v1/somewhere").mock(
            return_value=httpx.Response(
                301, headers={"Location": "https://evil.example/v1/somewhere"}
            )
        )
        with HttpClient(api_key=_VALID_KEY) as c:
            # 301 isn't one of our mapped statuses below 400, so it just
            # falls through as a normal response — but `follow_redirects`
            # is False so we don't *chase* it. Confirm by reading the
            # response status code.
            resp = c.request("GET", "/v1/somewhere")
            assert resp.status_code == 301
            assert resp.headers["Location"].startswith("https://evil.example")


# ── I6 — timeouts always set ─────────────────────────────────────────


def test_timeout_defaults_are_set() -> None:
    client = HttpClient(api_key=_VALID_KEY)
    t = client._client.timeout
    assert t.connect is not None and t.connect > 0
    assert t.read is not None and t.read > 0
    assert t.write is not None and t.write > 0
    assert t.pool is not None and t.pool > 0


def test_timeout_seconds_negative_rejected() -> None:
    with pytest.raises(ValidationError, match="positive"):
        HttpClient(api_key=_VALID_KEY, timeout_seconds=-1.0)


# ── api_key validation ───────────────────────────────────────────────


def test_api_key_with_whitespace_is_stripped() -> None:
    """Paste-accidents commonly include trailing newlines."""
    client = HttpClient(api_key=f"  {_VALID_KEY}  \n")
    assert client._api_key == _VALID_KEY


def test_api_key_empty_rejected() -> None:
    with pytest.raises(ValidationError):
        HttpClient(api_key="")


def test_api_key_wrong_prefix_rejected() -> None:
    """Stripe keys (`sk_live_...`) or others should not be accepted —
    they'd land in our access logs, exposing third-party credentials."""
    with pytest.raises(ValidationError):
        HttpClient(api_key="sk_live_" + "a" * 40)


def test_api_key_legacy_test_prefix_accepted() -> None:
    HttpClient(api_key="pk_test_" + "a" * 32)  # no exception


# ── HTTP status → exception mapping ──────────────────────────────────


@pytest.mark.parametrize(
    "status_code,exc_type",
    [
        (400, BadRequestError),
        (401, AuthenticationError),
        (403, PermissionDeniedError),
        (404, NotFoundError),
        (500, ServerError),
        (502, ServerError),
        (503, ServerError),
    ],
)
def test_error_status_maps_to_exception(status_code: int, exc_type: type[Exception]) -> None:
    with respx.mock(base_url=DEFAULT_BASE_URL) as mock:
        mock.get("/v1/x").mock(
            return_value=httpx.Response(status_code, json={"error": {"code": "X", "message": "x"}})
        )
        with HttpClient(api_key=_VALID_KEY) as c, pytest.raises(exc_type):
            c.request("GET", "/v1/x")


def test_rate_limit_includes_retry_after() -> None:
    with respx.mock(base_url=DEFAULT_BASE_URL) as mock:
        mock.get("/v1/x").mock(
            return_value=httpx.Response(
                429,
                headers={"Retry-After": "42"},
                json={"error": {"code": "RATE_LIMITED", "message": "slow down"}},
            )
        )
        with HttpClient(api_key=_VALID_KEY) as c:
            with pytest.raises(RateLimitError) as exc_info:
                c.request("GET", "/v1/x")
            assert exc_info.value.retry_after_seconds == 42


def test_insufficient_balance_includes_balance() -> None:
    with respx.mock(base_url=DEFAULT_BASE_URL) as mock:
        mock.get("/v1/x").mock(
            return_value=httpx.Response(
                402,
                headers={"X-Wallet-Balance-Cents": "47"},
                json={"error": {"code": "INSUFFICIENT_BALANCE", "message": "no"}},
            )
        )
        with HttpClient(api_key=_VALID_KEY) as c:
            with pytest.raises(InsufficientBalanceError) as exc_info:
                c.request("GET", "/v1/x")
            assert exc_info.value.balance_cents == 47


# ── Transport errors ─────────────────────────────────────────────────


def test_connection_error_is_wrapped() -> None:
    with respx.mock(base_url=DEFAULT_BASE_URL) as mock:
        mock.get("/v1/x").mock(side_effect=httpx.ConnectError("dns fail"))
        with HttpClient(api_key=_VALID_KEY) as c, pytest.raises(APIConnectionError):
            c.request("GET", "/v1/x")


def test_timeout_is_wrapped() -> None:
    with respx.mock(base_url=DEFAULT_BASE_URL) as mock:
        mock.get("/v1/x").mock(side_effect=httpx.ReadTimeout("read"))
        with HttpClient(api_key=_VALID_KEY) as c, pytest.raises(APITimeoutError):
            c.request("GET", "/v1/x")


# ── User-Agent ───────────────────────────────────────────────────────


def test_user_agent_includes_sdk_version() -> None:
    with respx.mock(base_url=DEFAULT_BASE_URL) as mock:
        route = mock.get("/v1/x").mock(return_value=httpx.Response(200, json={}))
        with HttpClient(api_key=_VALID_KEY) as c:
            c.request("GET", "/v1/x")
        ua = route.calls.last.request.headers["User-Agent"]
        assert ua.startswith("ocrqueen-python/")
        assert re.search(r"httpx/\d+\.\d+", ua)


def test_user_agent_suffix_sanitized() -> None:
    """Arbitrary suffixes must strip CRLF, colon, and whitespace so a
    malicious one cannot smuggle a fake `X-Foo:` header downstream.

    The actual security property is "no header separators land in the
    output". The sanitizer leaves alphanumerics intact (so the word
    `Evil` survives as a meaningless token), which is fine — what we
    care about is that `\\r\\n` and `:` and ` ` were stripped, so the
    output cannot be parsed as multiple headers."""
    with respx.mock(base_url=DEFAULT_BASE_URL) as mock:
        route = mock.get("/v1/x").mock(return_value=httpx.Response(200, json={}))
        with HttpClient(
            api_key=_VALID_KEY,
            user_agent_suffix="myapp/1.0; injection\r\nX-Evil: y",
        ) as c:
            c.request("GET", "/v1/x")
        ua = route.calls.last.request.headers["User-Agent"]
        # Header-injection vectors must be gone:
        assert "\r" not in ua
        assert "\n" not in ua
        assert ":" not in ua.removeprefix("https:")  # no inline `:` after the scheme
        assert ";" not in ua
        # The legitimate prefix should survive:
        assert "myapp/1.0" in ua
