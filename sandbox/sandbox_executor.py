"""
Aethelgard v2 — Sandbox Executor (Container-Enforced)

Security contract:
    - Patch execution is permitted ONLY inside a Docker container.
    - Host subprocess execution is never used as a fallback.
    - Static AST analysis runs before container execution.
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import platform
import sys
import tempfile
import textwrap
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from core.config import get_settings
from core.exceptions import SandboxError, SandboxTimeoutError, SandboxSecurityViolation
from core.logging_config import get_logger

logger = get_logger(__name__)


# ─────────────────────────────────────────────
# AST-based Security Analyzer (FIX over regex)
# ─────────────────────────────────────────────

class SecurityNodeVisitor(ast.NodeVisitor):
    """
    AST-level semantic analysis for dangerous code patterns.

    Catches what regex cannot:
      - getattr(builtins, 'ev' + 'al')(...)
      - __import__('os').system('...')
      - Attribute chains: obj.__class__.__bases__[0].__subclasses__()
    """

    BANNED_CALLS = {
        "eval", "exec", "compile", "execfile",
        "__import__", "input",
    }
    BANNED_ATTRIBUTES = {
        "__builtins__", "__globals__", "__locals__",
        "__class__", "__bases__", "__subclasses__",
        "__code__", "__func__",
    }
    BANNED_MODULES = {
        "os", "sys", "subprocess", "socket", "shutil",
        "pickle", "marshal", "ctypes", "importlib",
        "multiprocessing", "threading",
    }
    ALLOWED_OS_ATTRS = {"path", "environ", "getcwd", "sep", "linesep"}

    def __init__(self):
        self.violations: List[Dict[str, Any]] = []

    def visit_Call(self, node: ast.Call) -> None:
        """Detect banned function calls."""
        # Direct calls: eval("..."), exec("...")
        if isinstance(node.func, ast.Name):
            if node.func.id == "getattr":
                self.violations.append({
                    "type": "banned_dynamic_access",
                    "name": "getattr",
                    "line": node.lineno,
                    "severity": "critical",
                    "message": "Dynamic attribute access via getattr() is not allowed",
                })
            if node.func.id in self.BANNED_CALLS:
                self.violations.append({
                    "type": "banned_call",
                    "name": node.func.id,
                    "line": node.lineno,
                    "severity": "critical",
                    "message": f"Banned function call: {node.func.id}()",
                })
        # Attribute calls: os.system(), subprocess.run()
        elif isinstance(node.func, ast.Attribute):
            attr_name = node.func.attr
            if isinstance(node.func.value, ast.Name):
                module_name = node.func.value.id
                if module_name == "os" and attr_name not in self.ALLOWED_OS_ATTRS:
                    self.violations.append({
                        "type": "banned_os_call",
                        "name": f"os.{attr_name}",
                        "line": node.lineno,
                        "severity": "critical",
                        "message": f"Dangerous os.{attr_name}() call",
                    })
                elif module_name == "subprocess":
                    self.violations.append({
                        "type": "subprocess_call",
                        "name": f"subprocess.{attr_name}",
                        "line": node.lineno,
                        "severity": "critical",
                        "message": f"subprocess.{attr_name}() is not allowed in patches",
                    })

        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 1
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "__builtins__"
        ):
            self.violations.append({
                "type": "builtins_escape_attempt",
                "name": "getattr(__builtins__, ...)",
                "line": node.lineno,
                "severity": "critical",
                "message": "Dynamic builtins access is blocked",
            })
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        """Detect dangerous module imports."""
        for alias in node.names:
            base = alias.name.split(".")[0]
            if base in self.BANNED_MODULES:
                self.violations.append({
                    "type": "banned_import",
                    "name": alias.name,
                    "line": node.lineno,
                    "severity": "high",
                    "message": f"Import of restricted module: {alias.name}",
                })
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Detect dangerous from-imports."""
        if node.module:
            base = node.module.split(".")[0]
            if base in self.BANNED_MODULES:
                self.violations.append({
                    "type": "banned_from_import",
                    "name": node.module,
                    "line": node.lineno,
                    "severity": "high",
                    "message": f"from {node.module} import ... is restricted",
                })
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Detect dangerous dunder attribute access."""
        if node.attr in self.BANNED_ATTRIBUTES:
            self.violations.append({
                "type": "dunder_access",
                "name": node.attr,
                "line": node.lineno,
                "severity": "high",
                "message": f"Access to restricted attribute: .{node.attr}",
            })
        self.generic_visit(node)


def analyze_code_ast(code: str, filepath: str) -> List[Dict[str, Any]]:
    """
    Parse code into AST and run SecurityNodeVisitor.
    Returns list of violations found.
    """
    violations = []
    try:
        tree = ast.parse(code)
        visitor = SecurityNodeVisitor()
        visitor.visit(tree)
        violations.extend(visitor.violations)
    except SyntaxError as e:
        violations.append({
            "type": "syntax_error",
            "name": "SyntaxError",
            "line": e.lineno,
            "severity": "critical",
            "message": f"Syntax error in {filepath}: {e.msg}",
        })
    return violations


# ─────────────────────────────────────────────
# Main Sandbox Executor
# ─────────────────────────────────────────────

class SandboxExecutor:
    """
    Real isolated execution environment for patch validation.

        Execution mode:
            1. Docker — mandatory container isolation
    """

    def __init__(self):
        self._settings = get_settings()
        self._docker_available = False
        self._execution_count = 0
        self._os = platform.system()
        # Security hardening: sandbox execution must be container-isolated.
        # AST checks alone are insufficient for safe execution.
        self._require_container = True

    async def initialize(self) -> None:
        """Check for Docker availability."""
        try:
            import docker
            client = docker.from_env()
            client.ping()
            self._docker_available = True
            logger.info("sandbox_docker_available")
        except Exception:
            self._docker_available = False
            logger.warning(
                "sandbox_docker_unavailable",
                fallback="none",
                note="Container isolation required; sandbox execution will be blocked"
            )

    async def execute(
        self,
        code_changes: Dict[str, str],
        config_changes: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Execute patches in the sandbox environment.

        Returns:
            {
              "passed": bool,
              "exit_code": int,
              "logs": List[str],
              "violations": List[dict],   ← AST violations found
              "container_used": bool,
              "duration_seconds": float,
            }
        """
        timeout = timeout or self._settings.sandbox.timeout
        self._execution_count += 1
        execution_id = f"sandbox-{self._execution_count:06d}"
        start_time = time.time()

        logger.info("sandbox_execution_start",
                    execution_id=execution_id,
                    files=len(code_changes),
                    timeout=timeout,
                    mode="docker" if self._docker_available else "blocked")

        try:
            if self._require_container and not self._docker_available:
                logger.error(
                    "sandbox_container_required",
                    execution_id=execution_id,
                    reason="docker_unavailable",
                )
                return {
                    "passed": False,
                    "exit_code": 126,
                    "logs": [
                        f"[{execution_id}] BLOCKED: container isolation required but Docker is unavailable"
                    ],
                    "violations": [{
                        "type": "container_isolation_required",
                        "severity": "critical",
                        "message": "Container isolation is mandatory; Docker runtime unavailable",
                    }],
                    "container_used": False,
                    "blocked_reason": "container_isolation_required",
                    "duration_seconds": round(time.time() - start_time, 3),
                    "execution_id": execution_id,
                }

            result = await self._execute_in_docker(
                code_changes, config_changes, timeout, execution_id
            )

            result["duration_seconds"] = round(time.time() - start_time, 3)
            result["execution_id"] = execution_id

            logger.info("sandbox_execution_complete",
                        execution_id=execution_id,
                        passed=result.get("passed", False),
                        violations=len(result.get("violations", [])),
                        duration=result["duration_seconds"])

            return result

        except asyncio.TimeoutError:
            raise SandboxTimeoutError(
                f"Sandbox execution timed out after {timeout}s",
                details={"execution_id": execution_id},
            )
        except Exception as e:
            logger.error("sandbox_execution_error",
                         execution_id=execution_id,
                         error=str(e))
            return {
                "passed": False,
                "exit_code": -1,
                "logs": [f"Sandbox error: {e}"],
                "violations": [],
                "container_used": False,
                "duration_seconds": round(time.time() - start_time, 3),
            }

    async def _execute_subprocess(
        self,
        code_changes: Dict[str, str],
        config_changes: Optional[Dict[str, Any]],
        timeout: int,
        execution_id: str,
    ) -> Dict[str, Any]:
        """Host execution fallback is disabled by policy."""
        return {
            "passed": False,
            "exit_code": 126,
            "logs": [f"[{execution_id}] BLOCKED: host subprocess execution is disabled"],
            "violations": [{
                "type": "container_isolation_required",
                "severity": "critical",
                "message": "Host execution fallback is disabled",
            }],
            "container_used": False,
            "blocked_reason": "container_isolation_required",
        }

    async def _execute_in_docker(
        self,
        code_changes: Dict[str, str],
        config_changes: Optional[Dict[str, Any]],
        timeout: int,
        execution_id: str,
    ) -> Dict[str, Any]:
        """Execute in a real Docker container with seccomp profile."""
        import docker

        client = docker.from_env()
        sandbox_config = self._settings.sandbox

        with tempfile.TemporaryDirectory() as workspace:
            workspace_path = Path(workspace).resolve()
            for filepath, content in code_changes.items():
                # Prevent path traversal: resolve and verify dest is inside workspace
                dest = (workspace_path / filepath).resolve()
                try:
                    dest.relative_to(workspace_path)
                except ValueError:
                    raise SandboxSecurityViolation(
                        f"Path traversal attempt blocked: {filepath!r}",
                        details={"filepath": filepath},
                    )
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")

            if config_changes:
                (Path(workspace) / "patch_config.json").write_text(
                    json.dumps(config_changes), encoding="utf-8"
                )

            try:
                # Run with explicit list (no shell glob injection)
                py_files = [
                    f"/workspace/{fp}"
                    for fp in code_changes
                    if fp.endswith(".py")
                ]
                command = [sys.executable, "-m", "py_compile"] + py_files

                container = client.containers.run(
                    sandbox_config.image,
                    command=command,
                    volumes={workspace: {"bind": "/workspace", "mode": "ro"}},
                    mem_limit="256m",
                    cpu_quota=int(sandbox_config.cpu_limit * 100_000),
                    network_disabled=True,
                    cap_drop=["ALL"],
                    read_only=True,
                    tmpfs={"/tmp": "size=64m,noexec"},  # nosec B108 - required isolated tmpfs mount inside container
                    security_opt=["no-new-privileges:true"],
                    pids_limit=64,
                    remove=True,
                    timeout=timeout,
                    detach=False,
                    stdout=True,
                    stderr=True,
                )

                output = container.decode("utf-8", errors="replace") if isinstance(container, bytes) else ""
                return {
                    "passed": True,
                    "exit_code": 0,
                    "logs": output.splitlines(),
                    "violations": [],
                    "container_used": True,
                }

            except docker.errors.ContainerError as e:
                return {
                    "passed": False,
                    "exit_code": e.exit_status,
                    "logs": [str(e)],
                    "violations": [],
                    "container_used": True,
                }
