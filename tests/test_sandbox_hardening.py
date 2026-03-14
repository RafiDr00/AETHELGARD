import pytest
import sys

from sandbox.sandbox_executor import SandboxExecutor


@pytest.mark.asyncio
async def test_container_policy_blocks_when_docker_unavailable():
    executor = SandboxExecutor()
    executor._docker_available = False

    result = await executor.execute({"safe.py": "x = 1\n"})

    assert not result["passed"]
    assert result.get("blocked_reason") == "container_isolation_required"
    assert result["container_used"] is False


@pytest.mark.asyncio
async def test_docker_execution_uses_required_security_flags(monkeypatch):
    captured = {}

    class _FakeContainers:
        def run(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return b"ok"

    class _FakeClient:
        containers = _FakeContainers()

    class _FakeDockerModule:
        @staticmethod
        def from_env():
            return _FakeClient()

    monkeypatch.setitem(sys.modules, "docker", _FakeDockerModule())

    executor = SandboxExecutor()
    executor._docker_available = True

    result = await executor.execute({"safe.py": "x = 1\n"})

    assert result["container_used"] is True
    kwargs = captured["kwargs"]
    assert kwargs["network_disabled"] is True
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["security_opt"] == ["no-new-privileges:true"]
    assert kwargs["pids_limit"] == 64
    assert kwargs["mem_limit"] == "256m"
