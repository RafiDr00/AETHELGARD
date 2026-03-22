"""
Aethelgard — Quick Start

Runs the full platform demo.
Usage:
    python quickstart.py
"""

from __future__ import annotations

import asyncio
import io
import os
import sys
import time
from pathlib import Path

# Force UTF-8
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    os.environ["PYTHONIOENCODING"] = "utf-8"

sys.path.insert(0, str(Path(__file__).parent))


def check_deps():
    """Check that required packages are installed."""
    missing = []
    for pkg in ["pydantic", "structlog", "rich", "numpy"]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)

    if missing:
        print(f"[!] Missing packages: {', '.join(missing)}")
        print(f"[!] Install with: python -m pip install {' '.join(missing)}")
        sys.exit(1)


async def run_demo_pipeline():
    """Run the full autonomous remediation pipeline demo."""
    from rich.console import Console
    from rich.panel import Panel

    console = Console(force_terminal=True)

    console.print(Panel.fit(
        "[bold cyan]Aethelgard[/bold cyan]\n"
        "[dim]Autonomous DevOps Platform — Quick Start[/dim]\n\n"
        "Running live demo: Payment API Latency Spike scenario",
        border_style="cyan",
    ))

    from core.logging_config import setup_logging
    from knowledge.rag_engine import RAGEngine
    from sandbox.sandbox_executor import SandboxExecutor
    from agents.orchestrator import AgentOrchestrator
    from services.log_simulator import LogSimulator

    setup_logging(log_level="WARNING")

    # Init
    console.print("\n[bold]Initializing platform...[/bold]")
    knowledge = RAGEngine()
    await knowledge.initialize()

    playbooks_dir = Path(__file__).parent / "knowledge" / "playbooks"
    if playbooks_dir.exists():
        for pb in playbooks_dir.glob("*.md"):
            await knowledge.ingest_playbook(str(pb))

    sandbox = SandboxExecutor()
    await sandbox.initialize()

    orchestrator = AgentOrchestrator(knowledge_engine=knowledge, sandbox_executor=sandbox)
    simulator = LogSimulator()

    console.print(f"  [green]✓[/green] Knowledge base: {knowledge.document_count} documents")
    console.print(f"  [green]✓[/green] 5 agents ready")
    console.print(f"  [green]✓[/green] Sandbox: {'Docker' if sandbox._docker_available else 'Simulated'}")

    # Build baseline
    console.print("\n[bold]Building baseline...[/bold]")
    for _ in range(15):
        m = simulator.generate_metrics()
        await orchestrator.detection_agent.collect_baseline(m)
    console.print("  [green]✓[/green] 15 samples collected, baseline established")

    # Inject anomaly
    console.print("\n[bold red]Injecting anomaly: payment_latency_spike[/bold red]")
    simulator.inject_anomaly("payment_latency_spike")
    metrics = simulator.generate_metrics()

    lat = next((m.value for m in metrics if m.service_name == "payment-api" and m.metric_name == "response_time_ms"), 0)
    console.print(f"  [red]⚡[/red] payment-api/response_time_ms: {lat:.0f}ms (baseline: ~180ms)")

    # Run pipeline
    console.print("\n[bold cyan]Running autonomous remediation pipeline...[/bold cyan]")
    t0 = time.time()
    record = await orchestrator.run_full_pipeline(metrics)
    elapsed = time.time() - t0

    if record:
        console.print(f"\n[bold green]SUCCESS[/bold green] — {elapsed:.2f}s (target: <60s)\n")
        console.print(f"  Stage 1 Detection :  {record.anomaly.anomaly_type} | severity={record.anomaly.severity.value}")
        console.print(f"  Stage 2 Diagnosis :  {record.diagnosis.root_cause[:65]}...")
        console.print(f"  Stage 3 Remediation: {record.patch.description[:65]}...")
        console.print(f"  Stage 4 Validation:  risk={record.validation.risk_score:.2f} ({record.validation.risk_level.value})")
        console.print(f"  Stage 5 Deployment:  {record.deployment.status} via {record.deployment.deployment_strategy}")
        console.print(f"\n  MTTD  : {record.mttd_seconds*1000:.0f}ms")
        console.print(f"  MTTR  : {record.mttr_seconds:.2f}s")
        console.print(f"  ROI   : ${orchestrator.get_metrics().roi_dollars:.2f}")
    else:
        console.print("[yellow]No anomaly detected — baseline may need more samples[/yellow]")

    console.print("[bold cyan]API docs:[/bold cyan]  uvicorn api:app --reload  →  http://localhost:8000/docs")
    console.print("[dim]─────────────────────────────────────────[/dim]")


def main():
    check_deps()

    try:
        asyncio.run(run_demo_pipeline())
    except KeyboardInterrupt:
        print("\nAborted.")
        return


if __name__ == "__main__":
    main()
