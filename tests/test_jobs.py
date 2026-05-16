"""Tests for the jobs resource: get / list / cancel / wait.

`wait()` is exercised against a stubbed `get()` to keep the tests fast
and deterministic — no real sleeps long enough to matter, no HTTP."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import httpx
import pytest
import respx

from ocrqueen import OCRQueen
from ocrqueen._errors import APITimeoutError, NotFoundError, ValidationError
from ocrqueen.resources.extract import ExtractJob

_VALID_KEY = "pk_" + "a" * 32
_API_URL = "https://api.ocrqueen.com"


# ── get ──────────────────────────────────────────────────────────────


def test_get_returns_job() -> None:
    with respx.mock(base_url=_API_URL) as mock:
        mock.get("/v1/jobs/job_abc").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "job_abc",
                    "status": "completed",
                    "result": {"source": {"page_count": 3}},
                },
            )
        )
        with OCRQueen(api_key=_VALID_KEY) as client:
            job = client.jobs.get("job_abc")
        assert job.id == "job_abc"
        assert job.status == "completed"
        assert isinstance(job.result, dict)


def test_get_404_raises_notfound() -> None:
    with respx.mock(base_url=_API_URL) as mock:
        mock.get("/v1/jobs/missing").mock(
            return_value=httpx.Response(404, json={"error": {"code": "NOT_FOUND", "message": "no"}})
        )
        with OCRQueen(api_key=_VALID_KEY) as client, pytest.raises(NotFoundError):
            client.jobs.get("missing")


def test_get_empty_id_rejected() -> None:
    with OCRQueen(api_key=_VALID_KEY) as client, pytest.raises(ValidationError):
        client.jobs.get("")


# ── list ─────────────────────────────────────────────────────────────


def test_list_returns_jobs_and_cursor() -> None:
    with respx.mock(base_url=_API_URL) as mock:
        mock.get("/v1/jobs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "jobs": [
                        {"id": "job_1", "status": "completed"},
                        {"id": "job_2", "status": "queued"},
                    ],
                    "next_cursor": "abc",
                },
            )
        )
        with OCRQueen(api_key=_VALID_KEY) as client:
            page = client.jobs.list()
        assert len(page.jobs) == 2
        assert page.jobs[0].id == "job_1"
        assert page.next_cursor == "abc"


def test_list_passes_filters() -> None:
    with respx.mock(base_url=_API_URL) as mock:
        route = mock.get("/v1/jobs").mock(
            return_value=httpx.Response(200, json={"jobs": [], "next_cursor": None})
        )
        with OCRQueen(api_key=_VALID_KEY) as client:
            client.jobs.list(status="completed", limit=10, cursor="prev")
        url = str(route.calls.last.request.url)
        assert "status=completed" in url
        assert "limit=10" in url
        assert "cursor=prev" in url


def test_list_limit_out_of_range_rejected() -> None:
    with OCRQueen(api_key=_VALID_KEY) as client:
        with pytest.raises(ValidationError):
            client.jobs.list(limit=0)
        with pytest.raises(ValidationError):
            client.jobs.list(limit=101)


# ── cancel ───────────────────────────────────────────────────────────


def test_cancel_returns_updated_job() -> None:
    with respx.mock(base_url=_API_URL) as mock:
        mock.delete("/v1/jobs/job_x").mock(
            return_value=httpx.Response(200, json={"id": "job_x", "status": "cancelled"})
        )
        with OCRQueen(api_key=_VALID_KEY) as client:
            job = client.jobs.cancel("job_x")
        assert job.status == "cancelled"


# ── purge ───────────────────────────────────────────────────────────


def test_purge_hits_post_endpoint() -> None:
    with respx.mock(base_url=_API_URL) as mock:
        route = mock.post("/v1/jobs/job_y/purge").mock(return_value=httpx.Response(204))
        with OCRQueen(api_key=_VALID_KEY) as client:
            assert client.jobs.purge("job_y") is None
        assert route.called


def test_purge_empty_id_rejected() -> None:
    with OCRQueen(api_key=_VALID_KEY) as client:
        with pytest.raises(ValidationError):
            client.jobs.purge("")


# ── wait ─────────────────────────────────────────────────────────────


def test_wait_returns_immediately_when_terminal() -> None:
    """If the first poll lands on a terminal status, no sleeping happens."""
    with respx.mock(base_url=_API_URL) as mock:
        mock.get("/v1/jobs/job_done").mock(
            return_value=httpx.Response(200, json={"id": "job_done", "status": "completed"})
        )
        with OCRQueen(api_key=_VALID_KEY) as client:
            job = client.jobs.wait("job_done")
        assert job.status == "completed"


def test_wait_polls_until_terminal() -> None:
    """Stub get() to return queued → processing → completed.

    Uses a small poll interval to keep the test fast.
    """
    states = ["queued", "processing", "completed"]
    call_count = {"n": 0}

    def fake_get(job_id: str) -> ExtractJob:
        n = call_count["n"]
        call_count["n"] += 1
        return ExtractJob(id=job_id, status=states[min(n, len(states) - 1)])

    with OCRQueen(api_key=_VALID_KEY) as client:
        with patch.object(client.jobs, "get", side_effect=fake_get):
            job = client.jobs.wait(
                "job_x",
                poll_interval_seconds=0.001,
                max_poll_interval_seconds=0.005,
            )
    assert job.status == "completed"
    assert call_count["n"] == 3


def test_wait_times_out() -> None:
    """If the job never reaches terminal, raise APITimeoutError, not hang."""

    def always_queued(job_id: str) -> ExtractJob:
        return ExtractJob(id=job_id, status="queued")

    with OCRQueen(api_key=_VALID_KEY) as client:
        with patch.object(client.jobs, "get", side_effect=always_queued):
            with pytest.raises(APITimeoutError):
                client.jobs.wait(
                    "job_x",
                    timeout_seconds=0.05,
                    poll_interval_seconds=0.01,
                    max_poll_interval_seconds=0.02,
                )


def test_wait_accepts_extract_job_or_str() -> None:
    """Both shapes should resolve to the same job_id."""
    job_obj = ExtractJob(id="job_x", status="queued")

    def fake_get(job_id: str) -> ExtractJob:
        assert job_id == "job_x"
        return ExtractJob(id="job_x", status="completed")

    with OCRQueen(api_key=_VALID_KEY) as client:
        with patch.object(client.jobs, "get", side_effect=fake_get):
            j1 = client.jobs.wait(job_obj)
            j2 = client.jobs.wait("job_x")
    assert j1.status == "completed" == j2.status


def test_wait_rejects_bad_timeouts() -> None:
    with OCRQueen(api_key=_VALID_KEY) as client:
        with pytest.raises(ValidationError):
            client.jobs.wait("job_x", timeout_seconds=0)
        with pytest.raises(ValidationError):
            client.jobs.wait("job_x", poll_interval_seconds=-1)
        with pytest.raises(ValidationError):
            client.jobs.wait(
                "job_x",
                poll_interval_seconds=10,
                max_poll_interval_seconds=1,
            )


def test_wait_empty_job_id_rejected() -> None:
    empty_job = ExtractJob(id="", status="queued")
    with OCRQueen(api_key=_VALID_KEY) as client:
        with pytest.raises(ValidationError):
            client.jobs.wait(empty_job)
        with pytest.raises(ValidationError):
            client.jobs.wait("")


# ── client.jobs cached ───────────────────────────────────────────────


def test_jobs_resource_cached() -> None:
    with OCRQueen(api_key=_VALID_KEY) as client:
        assert client.jobs is client.jobs


# ── silence Any-typed helpers (placeholder for future fields) ────────


def test_jobs_list_handles_garbage_items() -> None:
    """If the server unexpectedly returns a non-dict entry, skip it
    instead of crashing the caller."""
    with respx.mock(base_url=_API_URL) as mock:
        mock.get("/v1/jobs").mock(
            return_value=httpx.Response(
                200,
                json={"jobs": [{"id": "job_1", "status": "completed"}, "garbage"]},
            )
        )
        with OCRQueen(api_key=_VALID_KEY) as client:
            page = client.jobs.list()
        assert [j.id for j in page.jobs] == ["job_1"]


# Keep mypy quiet about the imported `Any` we use only in fixtures.
_ = Any
