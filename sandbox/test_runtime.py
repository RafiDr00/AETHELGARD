"""
Aethelgard v2 — Sandbox Runtime Verification Module

Usage:
    python -m sandbox.test_runtime

Verifies that the sandbox executor is correctly configured and that
container isolation policy is enforced. Always exits 0 when the security
contract is intact (even when Docker is not reachable from inside the
container, which is the expected state for DinD-less deployments).

Expected output:
    SANDBOX_OK
"""

from __future__ import annotations

import asyncio
import sys


def _check_policy() -> None:
    """Verify security policy flags on SandboxExecutor."""
    from sandbox.sandbox_executor import SandboxExecutor

    ex = SandboxExecutor()

    assert ex._require_container is True, \
        "FAIL: _require_container must be True — host execution fallback is prohibited"

    print("  [PASS] _require_container: True (container isolation enforced)")


def _check_blocked_when_docker_unavailable() -> None:
    """Verify fail-closed behaviour when Docker is not reachable."""
    from sandbox.sandbox_executor import SandboxExecutor

    ex = SandboxExecutor()
    ex._docker_available = False   # simulate no Docker (expected inside container)

    result = asyncio.run(ex.execute({"probe.py": "x = 1\n"}))

    assert result["passed"] is False, \
        "FAIL: execution must be blocked when Docker is not reachable"
    assert result.get("blocked_reason") == "container_isolation_required", \
        f"FAIL: unexpected blocked_reason: {result.get('blocked_reason')}"
    assert result["container_used"] is False, \
        "FAIL: container_used must be False when blocked"

    print("  [PASS] fail-closed: blocked with container_isolation_required")


def _check_ast_security_analyzer() -> None:
    """Verify the AST security analyzer catches dangerous code patterns."""
    from sandbox.sandbox_executor import analyze_code_ast

    # Should catch eval()
    violations = analyze_code_ast('eval("__import__(\'os\').system(\'rm -rf\')")', "test.py")
    assert any(v["name"] in ("eval", "getattr") or "banned" in v["type"] for v in violations), \
        f"FAIL: eval() not caught by AST analyzer. Got: {violations}"
    print("  [PASS] AST analyzer: eval() correctly flagged")

    # Should catch import os
    violations = analyze_code_ast("import os\nos.system('ls')", "test.py")
    assert any("os" in str(v) for v in violations), \
        f"FAIL: import os not caught. Got: {violations}"
    print("  [PASS] AST analyzer: import os correctly flagged")

    # Should allow clean code
    violations = analyze_code_ast("x = 1 + 2\nresult = x * 3\n", "safe.py")
    assert len(violations) == 0, \
        f"FAIL: clean code should have no violations. Got: {violations}"
    print("  [PASS] AST analyzer: clean code passes")


def main() -> int:
    print()
    print("=" * 55)
    print("  Aethelgard — Sandbox Runtime Verification")
    print("=" * 55)
    print()

    checks = [
        ("Security policy flags",         _check_policy),
        ("Fail-closed when Docker absent", _check_blocked_when_docker_unavailable),
        ("AST security analyzer",          _check_ast_security_analyzer),
    ]

    passed = 0
    failed = 0

    for name, fn in checks:
        print(f"[CHECK] {name}")
        try:
            fn()
            passed += 1
        except AssertionError as exc:
            print(f"  {exc}")
            failed += 1
        except Exception as exc:
            print(f"  [ERROR] Unexpected exception: {exc}")
            failed += 1

    print()
    print("─" * 55)
    print(f"  {passed} passed  |  {failed} failed")
    print("─" * 55)

    if failed == 0:
        print()
        print("SANDBOX_OK")
        print()
        return 0
    else:
        print()
        print("SANDBOX_FAIL")
        print()
        return 1


if __name__ == "__main__":
    sys.exit(main())
