"""Unit tests for Job.to_dict() serialisation."""
from datetime import datetime, timezone

import pytest

from domain.job import Job, JobStatus


def _completed_job() -> Job:
    """Return a Job that has started and finished, mimicking a real pipeline run."""
    job = Job(scenario="payment_latency_spike")
    job.status = JobStatus.COMPLETED
    job.started_at = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    job.finished_at = datetime(2024, 6, 1, 12, 0, 47, 500_000, tzinfo=timezone.utc)
    return job


def test_to_dict_contains_started_at():
    d = _completed_job().to_dict()
    assert "started_at" in d
    assert d["started_at"] == "2024-06-01T12:00:00+00:00"


def test_to_dict_contains_finished_at():
    d = _completed_job().to_dict()
    assert "finished_at" in d
    assert d["finished_at"] == "2024-06-01T12:00:47.500000+00:00"


def test_to_dict_contains_duration_seconds():
    d = _completed_job().to_dict()
    assert "duration_seconds" in d
    assert d["duration_seconds"] == pytest.approx(47.5)


def test_to_dict_datetime_fields_are_strings():
    d = _completed_job().to_dict()
    for field in ("started_at", "finished_at", "created_at"):
        assert isinstance(d[field], str), f"{field!r} should be a str, got {type(d[field])}"


def test_to_dict_none_timestamps_when_not_set():
    job = Job(scenario="payment_latency_spike")
    d = job.to_dict()
    assert d["started_at"] is None
    assert d["finished_at"] is None
    assert d["duration_seconds"] is None


def test_to_dict_status_is_string_value():
    d = _completed_job().to_dict()
    assert d["status"] == "completed"
    assert isinstance(d["status"], str)
