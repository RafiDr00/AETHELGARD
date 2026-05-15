"""
Aethelgard v2 — Application Entry Point

Initializes and runs the autonomous DevOps platform.
Starts all subsystems: event bus, agents, listener, and API server.
"""

from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

import uvicorn

from core.config import get_settings
from core.logging_config import setup_logging, get_logger
from core.preflight import run_startup_preflight


async def start_platform():
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

    run_startup_preflight(settings)

    # Initialize knowledge engine
    from knowledge.rag_engine import RAGEngine
    knowledge_engine = RAGEngine()
    await knowledge_engine.initialize()

    # Seed knowledge from playbooks
    playbooks_dir = Path(__file__).parent / "knowledge" / "playbooks"
    if playbooks_dir.exists():
        for playbook in playbooks_dir.glob("*.md"):
            await knowledge_engine.ingest_playbook(str(playbook))
            logger.info("playbook_loaded", file=playbook.name)

    logger.info("knowledge_engine_ready", documents=knowledge_engine.document_count)

    # Initialize sandbox
    from sandbox.sandbox_executor import SandboxExecutor
    sandbox = SandboxExecutor()
    await sandbox.initialize()

    # Initialize agent orchestrator
    from agents.orchestrator import AgentOrchestrator
    orchestrator = AgentOrchestrator(
        knowledge_engine=knowledge_engine,
        sandbox_executor=sandbox,
    )
    await orchestrator.initialize()

    logger.info("orchestrator_ready", mode="direct")

    # Start API server
    logger.info(
        "api_server_starting",
        host=settings.app_host,
        port=settings.app_port,
    )

    # Store orchestrator and engines in app state for the API
    from api import app
    app.state.orchestrator = orchestrator
    app.state.knowledge_engine = knowledge_engine
    app.state.sandbox = sandbox

    config = uvicorn.Config(
        app="api:app",
        host=settings.app_host,
        port=settings.app_port,
        log_level=settings.log_level.lower(),
        reload=settings.is_development,
    )
    server = uvicorn.Server(config)
    await server.serve()


def main():
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
