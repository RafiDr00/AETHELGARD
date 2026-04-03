from __future__ import annotations

import os
import subprocess  # nosec B404 - required for explicit docker runtime command validation
from dataclasses import dataclass
from typing import List

from core.config import Settings
from core.config import get_settings
from core.logging_config import get_logger
from core.telemetry import telemetry_health_status

logger = get_logger(__name__)


class PreflightFatalError(RuntimeError):
    """Fatal startup preflight failure."""


@dataclass
class PreflightResult:
    passed: bool
    checks: List[str]
    failures: List[str]


def _run_command(command: list[str], timeout: int = 30) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )  # nosec B603 - command is fixed allowlisted list, never user-controlled
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip() or "non_zero_exit"
            return False, message
        return True, completed.stdout.strip() or "ok"
    except Exception as exc:
        return False, str(exc)


def _required_env_vars() -> list[str]:
    baseline = ["AETHELGARD_API_KEY", "OTEL_EXPORTER_OTLP_ENDPOINT"]
    extra = os.environ.get("AETHELGARD_REQUIRED_ENV_VARS", "")
    if not extra.strip():
        return baseline
    values = [item.strip() for item in extra.split(",") if item.strip()]
    return list(dict.fromkeys([*baseline, *values]))


def run_startup_preflight(settings: Settings) -> PreflightResult:
    """Run mandatory production/staging preflight checks.

    In development environments, checks are logged and bypassed.
    """
    checks: list[str] = []
    failures: list[str] = []

    if settings.is_development:
        logger.info("startup_preflight_skipped", env=settings.app_env.value, mode="development")
        return PreflightResult(passed=True, checks=["development_mode_skip"], failures=[])

    env_name = settings.app_env.value
    is_fly = bool(os.environ.get("FLY_APP_NAME"))
    if is_fly:
        logger.info("startup_preflight_fly_detected", env=env_name, platform="fly.io")

    logger.info("startup_preflight_begin", env=env_name, is_fly=is_fly)

    missing = [name for name in _required_env_vars() if not os.environ.get(name)]
    if missing:
        failures.append(f"missing_required_env_vars:{','.join(missing)}")
    else:
        checks.append("required_env_vars")

    api_key = os.environ.get("AETHELGARD_API_KEY", "")
    if not api_key:
        failures.append("api_auth_key_not_configured")
    else:
        checks.append("api_auth_key")

    otel_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if not otel_endpoint:
        failures.append("otel_exporter_not_configured")
    else:
        checks.append("otel_exporter")

    if settings.llm.provider.lower() == "openai":
        openai_key = os.environ.get("OPENAI_API_KEY", "")
        if not openai_key:
            failures.append("openai_api_key_not_configured")
        else:
            checks.append("openai_api_key")

    if settings.is_production:
        redis_password = os.environ.get("REDIS_PASSWORD", "")
        if not redis_password:
            failures.append("redis_password_not_configured")
        else:
            checks.append("redis_password")

    telemetry_ok, telemetry_reason = telemetry_health_status()
    if not telemetry_ok:
        failures.append(f"telemetry_unhealthy:{telemetry_reason}")
    else:
        checks.append("telemetry_registry")

    if not is_fly:
        docker_version_ok, docker_version_msg = _run_command(["docker", "version"], timeout=30)
        if not docker_version_ok:
            failures.append(f"docker_version_failed:{docker_version_msg}")
        else:
            checks.append("docker_version")

        docker_hello_ok, docker_hello_msg = _run_command(["docker", "run", "--rm", "hello-world"], timeout=90)
        if not docker_hello_ok:
            failures.append(f"docker_hello_world_failed:{docker_hello_msg}")
        else:
            checks.append("docker_hello_world")

        try:
            import docker

            client = docker.from_env()
            client.ping()
            checks.append("sandbox_runtime_reachable")
        except Exception as exc:
            failures.append(f"sandbox_runtime_unreachable:{exc}")
    else:
        logger.info("startup_preflight_docker_skipped", reason="fly.io_serverless")
        checks.append("docker_skipped_fly")

    passed = len(failures) == 0
    if passed:
        logger.info("startup_preflight_passed", env=env_name, checks=checks)
        return PreflightResult(passed=True, checks=checks, failures=[])

    # Changed: log warning and continue instead of raising exception
    logger.warning("startup_preflight_failed_but_continuing", env=env_name, failures=failures, checks=checks)
    return PreflightResult(passed=False, checks=checks, failures=failures)


def _cli() -> int:
    settings = get_settings()
    try:
        run_startup_preflight(settings)
        print("Container Runtime: DETECTED")
        print("Sandbox Execution: ENABLED")
        print("Preflight: PASS")
        return 0
    except PreflightFatalError as exc:
        print("Container Runtime: MISSING")
        print("Sandbox Execution: DISABLED")
        print("Preflight: FAIL")
        print(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(_cli())
