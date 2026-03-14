"""
Aethelgard v2 — Application Entry Point

Thin launcher: configures uvicorn and hands control to the FastAPI app.

ALL service initialization (RAGEngine, SandboxExecutor, AgentOrchestrator,
LogSimulator, RealLogListener) is performed in the FastAPI lifespan declared
in api.py.  Do NOT add service init here — it would run a second time on
every uvicorn worker reload and leak the first set of objects.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

import uvicorn

from core.config import get_settings
from core.logging_config import setup_logging, get_logger


async def start_platform() -> None:
    """Start the Aethelgard v2 platform."""
    settings = get_settings()
    setup_logging(log_level=settings.log_level)
    logger = get_logger("aethelgard.main")

    logger.info(
        "platform_starting",
        app=settings.app_name,
        version=settings.app_version,
        env=settings.app_env.value,
    )

    # Service initialization happens inside the FastAPI lifespan (api.py).
    # Uvicorn triggers lifespan.startup on the first worker before serving
    # any request, guaranteeing all app.state.* objects are set.
    config = uvicorn.Config(
        app="api:app",
        host=settings.app_host,
        port=settings.app_port,
        log_level=settings.log_level.lower(),
        reload=settings.is_development,
    )
    server = uvicorn.Server(config)
    await server.serve()


def main() -> None:
    """Main entry point."""
    try:
        asyncio.run(start_platform())
    except KeyboardInterrupt:
        print("\n[Aethelgard] Platform shutdown initiated.")
    except Exception as e:
        print(f"\n[Aethelgard] Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
