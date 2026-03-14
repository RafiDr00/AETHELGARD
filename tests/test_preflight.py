import sys

import pytest

from core.config import Environment, Settings
from core.preflight import PreflightFatalError, run_startup_preflight


def test_preflight_skips_in_development(monkeypatch):
    settings = Settings(app_env=Environment.DEVELOPMENT)
    result = run_startup_preflight(settings)
    assert result.passed


def test_preflight_fails_without_required_env(monkeypatch):
    settings = Settings(app_env=Environment.PRODUCTION)

    monkeypatch.delenv("AETHELGARD_API_KEY", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

    # Keep docker checks deterministic in unit test.
    monkeypatch.setattr("core.preflight._run_command", lambda *args, **kwargs: (True, "ok"))

    class _FakeClient:
        def ping(self):
            return True

    class _FakeDocker:
        @staticmethod
        def from_env():
            return _FakeClient()

    monkeypatch.setitem(sys.modules, "docker", _FakeDocker())

    with pytest.raises(PreflightFatalError):
        run_startup_preflight(settings)


def test_preflight_fails_when_telemetry_unhealthy(monkeypatch):
    settings = Settings(app_env=Environment.STAGING)

    monkeypatch.setenv("AETHELGARD_API_KEY", "prod-key")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
    monkeypatch.setattr("core.preflight._run_command", lambda *args, **kwargs: (True, "ok"))
    monkeypatch.setattr("core.preflight.telemetry_health_status", lambda: (False, "missing_metric"))

    class _FakeClient:
        def ping(self):
            return True

    class _FakeDocker:
        @staticmethod
        def from_env():
            return _FakeClient()

    monkeypatch.setitem(sys.modules, "docker", _FakeDocker())

    with pytest.raises(PreflightFatalError):
        run_startup_preflight(settings)
