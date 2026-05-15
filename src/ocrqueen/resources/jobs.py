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

from ocrqueen._errors import APITimeoutError, ValidationError
from ocrqueen._http import HttpClient
from ocrqueen.resources.extract import ExtractJob

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


def _job_from_response(body: Any) -> ExtractJob:
    """Build an `ExtractJob` dataclass from an API response object."""
    if not isinstance(body, dict):
        raise ValidationError("unexpected job response shape")
    return ExtractJob(
        id=str(body.get("id", "")),
        status=str(body.get("status", "")),
        result=body.get("result"),
        error_code=body.get("error_code"),
        error_message=body.get("error_message"),
        raw=body,
    )
