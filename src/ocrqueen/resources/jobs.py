"""Jobs resource — `client.jobs.get / list / cancel / wait`.

Wraps the `/v1/jobs` endpoints on the OCRQueen API.

The `wait` helper is the SDK's flagship convenience: a customer who
just wants "submit a doc, get the result, no plumbing" should write
two lines, not a polling loop. We do the polling for them with
sensible exponential backoff.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

from ocrqueen._errors import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    ValidationError,
)
from ocrqueen._http import HttpClient
from ocrqueen.resources.extract import ExtractJob, _job_from_body

JobStatus = Literal["queued", "processing", "completed", "failed", "cancelled"]

# Terminal statuses — `wait()` stops polling when the job lands on one of these.
_TERMINAL_STATUSES: frozenset[str] = frozenset(("completed", "failed", "cancelled"))

# Polling defaults. Start short so a fast extraction (a few pages of clean
# text) feels instant; back off to avoid hammering the server when a job is
# slow. Numbers chosen to align with the server's typical work time.
_DEFAULT_POLL_INTERVAL_S = 1.0
_DEFAULT_POLL_MAX_INTERVAL_S = 5.0
_DEFAULT_WAIT_TIMEOUT_S = 5 * 60  # 5 minutes — most jobs finish well under this


@dataclass
class JobList:
    """Result of `jobs.list()` — a page of jobs plus the cursor for the next."""

    jobs: list[ExtractJob]
    # Pagination cursor returned by the server. None when there is no
    # further page. Customers pass this back as `cursor=` on the next call.
    next_cursor: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


# ── Resource ─────────────────────────────────────────────────────────


class JobsResource:
    """`GET / DELETE /v1/jobs/*` wrappers."""

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    # ── retrieve ─────────────────────────────────────────────────
    def get(self, job_id: str) -> ExtractJob:
        """Fetch a single job by id.

        Raises:
            NotFoundError: job doesn't exist (or belongs to a different
                customer — the server returns 404 either way for privacy).
        """
        if not job_id:
            raise ValidationError("job_id is required")
        response = self._http.request("GET", f"/v1/jobs/{job_id}")
        return _job_from_response(response.json())

    # ── list ─────────────────────────────────────────────────────
    def list(
        self,
        *,
        status: JobStatus | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> JobList:
        """List the customer's jobs, most recent first.

        Args:
            status: filter by status (`queued`, `processing`, `completed`,
                `failed`, `cancelled`). None for all.
            limit: 1..100. Server caps higher values silently.
            cursor: pagination cursor from a prior call's `next_cursor`.
        """
        if not 1 <= limit <= 100:
            raise ValidationError("limit must be in 1..100")
        params: dict[str, Any] = {"limit": limit}
        if status is not None:
            params["status"] = status
        if cursor is not None:
            params["cursor"] = cursor
        response = self._http.request("GET", "/v1/jobs", params=params)
        body = response.json()
        if not isinstance(body, dict):
            raise ValidationError("unexpected response shape from /v1/jobs")
        # Server shape: {"jobs": [...], "next_cursor": "..."}
        jobs_raw = body.get("jobs") or []
        items = [_job_from_response(item) for item in jobs_raw if isinstance(item, dict)]
        return JobList(
            jobs=items,
            next_cursor=body.get("next_cursor"),
            raw=body,
        )

    # ── cancel ───────────────────────────────────────────────────
    def cancel(self, job_id: str) -> ExtractJob:
        """Cancel a queued or in-flight job. Reservation refunded if any.

        Cancellation is idempotent — calling on an already-terminal job
        returns the existing terminal state without raising.
        """
        if not job_id:
            raise ValidationError("job_id is required")
        response = self._http.request("DELETE", f"/v1/jobs/{job_id}")
        return _job_from_response(response.json())

    # ── fetch_image (proxy URLs from patent figures + image blocks) ──
    def fetch_image(self, url_or_path: str) -> bytes:
        """Download an image referenced from an extraction result.

        The API returns stable proxy paths on patent figures
        (`drawings[i].image_url`) and general image blocks
        (`pages[].blocks[].url`) of the form
        ``/v1/jobs/{job_id}/{figures|images}/{id}``. Calling them
        with the SDK's API key returns a `302` redirect to a
        short-lived signed R2 URL; this helper performs the two-step
        dance and returns the raw image bytes.

        Pass either a full URL or just the path — both work:

        >>> img = client.jobs.fetch_image(figure.image_url)
        >>> img = client.jobs.fetch_image("/v1/jobs/abc/figures/0")

        Raises:
            ValidationError: empty / malformed URL.
            NotFoundError: figure or image block doesn't exist.
            APIError: unexpected status or non-redirect from the API.
        """
        if not url_or_path:
            raise ValidationError("url_or_path is required")
        path = _proxy_path(url_or_path)
        # Hit our API with auth; the route returns a 302. Security
        # invariant I5 keeps redirects unfollowed by default, so we
        # extract the Location header ourselves.
        response = self._http.request_raw(
            "GET",
            path,
            expect_status=(200, 301, 302, 303, 307, 308),
        )
        if 200 <= response.status_code < 300:
            return response.content
        location = response.headers.get("location")
        if not location:
            raise ValidationError(
                f"image proxy returned {response.status_code} without a Location header"
            )
        # The Location points at R2 (or another presigned host) — fetch
        # the bytes directly without sending our API key.
        import httpx as _httpx

        try:
            r2 = _httpx.get(location, timeout=60.0, follow_redirects=False)
        except _httpx.TimeoutException as exc:
            raise APITimeoutError(f"image fetch timed out: {exc}") from exc
        except _httpx.TransportError as exc:
            raise APIConnectionError(f"image fetch failed: {exc}") from exc
        if r2.status_code != 200:
            raise APIError(
                f"image storage returned {r2.status_code}",
                status_code=r2.status_code,
            )
        return r2.content

    # ── purge (GDPR erasure) ─────────────────────────────────────
    def purge(self, job_id: str) -> None:
        """Hard-erase a job's source bytes + extracted content.

        Deletes the source file from object storage and clears the
        extracted result + request options from the database. The job
        row remains as a billing tombstone (id, customer, page count,
        timestamps) so usage reports stay accurate.

        Requires the `jobs:write` scope on the API key. This is
        deliberately separate from `extract:write` so you can issue
        read-only keys to dashboards / pipelines that fetch results
        without being able to delete them.

        Idempotent — calling on an already-purged job is a no-op.

        Raises:
            NotFoundError: job doesn't exist (or belongs to a different
                customer — the server returns 404 either way).
            AuthenticationError: key is missing the `jobs:write` scope.
        """
        if not job_id:
            raise ValidationError("job_id is required")
        self._http.request("POST", f"/v1/jobs/{job_id}/purge")

    # ── wait (the ergonomic killer feature) ──────────────────────
    def wait(
        self,
        job_or_id: ExtractJob | str,
        *,
        timeout_seconds: float = _DEFAULT_WAIT_TIMEOUT_S,
        poll_interval_seconds: float = _DEFAULT_POLL_INTERVAL_S,
        max_poll_interval_seconds: float = _DEFAULT_POLL_MAX_INTERVAL_S,
    ) -> ExtractJob:
        """Poll the job until it reaches a terminal status.

        Returns the final job (status `completed`, `failed`, or `cancelled`).

        We back off exponentially: first poll after `poll_interval_seconds`,
        then double each time up to `max_poll_interval_seconds`. The first
        call is preceded by NO sleep — small docs that finish in <1s feel
        instant.

        Args:
            job_or_id: an `ExtractJob` from `client.extract.create(...)`
                OR a raw job_id string.
            timeout_seconds: give up after this many seconds. Default 5 min.
            poll_interval_seconds: initial interval (default 1s).
            max_poll_interval_seconds: ceiling for backoff (default 5s).

        Raises:
            APITimeoutError: deadline reached before terminal status.
            ValidationError: bad timeout/interval values, or empty job_id.
        """
        if timeout_seconds <= 0:
            raise ValidationError("timeout_seconds must be positive")
        if poll_interval_seconds <= 0 or max_poll_interval_seconds <= 0:
            raise ValidationError("poll intervals must be positive")
        if max_poll_interval_seconds < poll_interval_seconds:
            raise ValidationError("max_poll_interval_seconds must be >= poll_interval_seconds")

        job_id = job_or_id.id if isinstance(job_or_id, ExtractJob) else job_or_id
        if not job_id:
            raise ValidationError("job has no id; cannot poll")

        deadline = time.monotonic() + timeout_seconds
        interval = poll_interval_seconds

        # First fetch — no sleep. Catches the case where the caller already
        # has a terminal job (e.g. content-cache hit returned status=completed).
        current = self.get(job_id)
        while current.status not in _TERMINAL_STATUSES:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise APITimeoutError(
                    f"job {job_id} did not reach a terminal status within "
                    f"{timeout_seconds}s (last status: {current.status})"
                )
            time.sleep(min(interval, remaining))
            interval = min(interval * 2, max_poll_interval_seconds)
            current = self.get(job_id)

        return current


# ── Helpers ──────────────────────────────────────────────────────────


def _proxy_path(url_or_path: str) -> str:
    """Return the path portion of an OCRQueen image-proxy URL.

    Customers can pass either ``/v1/jobs/{id}/figures/0`` or the full
    ``https://api.ocrqueen.com/v1/jobs/{id}/figures/0`` — we don't make
    them strip the origin themselves.
    """
    from urllib.parse import urlparse as _urlparse

    if url_or_path.startswith("/"):
        return url_or_path
    parsed = _urlparse(url_or_path)
    if not parsed.scheme:
        return "/" + url_or_path.lstrip("/")
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    return path


def _job_from_response(body: Any) -> ExtractJob:
    """Build an `ExtractJob` from an API response object.

    Thin wrapper around `extract._job_from_body` so every job-returning
    endpoint maps the same wire fields.
    """
    return _job_from_body(body)
