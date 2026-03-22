"""
Aethelgard — Live Demo Runner

Runs a complete autonomous remediation demonstration:

1. Simulates a payment API latency spike (200ms → 2500ms)
2. Detection agent identifies the anomaly
3. Diagnosis agent traces root cause (worker pool exhaustion)
4. Remediation agent generates infrastructure fix
5. Validation agent tests in sandbox
6. Deployment agent rolls out the fix
7. Metrics updated with MTTD, MTTR, ROI

Target: Complete remediation in < 60 seconds
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from datetime import datetime

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

import io
import os

# Force UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    os.environ["PYTHONIOENCODING"] = "utf-8"

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import box


console = Console(force_terminal=True)


def print_header():
    """Print the demo header."""
    console.print()
    console.print(Panel.fit(
        "[bold cyan]AETHELGARD[/bold cyan]\n"
        "[dim]Engineering Demo — Incident Response Simulation[/dim]\n\n"
        "[yellow]Scenario:[/yellow] Service Latency Spike\n"
        "[yellow]Status:[/yellow] Running autonomous diagnostics",
        border_style="cyan",
        title="[bold]RECOVERY LOG[/bold]",
        subtitle="[dim]Press Ctrl+C to abort[/dim]",
    ))
    console.print()


    console.print(f"\n[bold cyan]Stage {stage_num}:[/bold cyan] [bold]{title}[/bold]")
    console.print(f"   [dim]{description}[/dim]")


async def run_demo():
    """Execute the full demo pipeline."""
    from core.logging_config import setup_logging
    from knowledge.rag_engine import RAGEngine
    from sandbox.sandbox_executor import SandboxExecutor
    from agents.orchestrator import AgentOrchestrator
    from services.log_simulator import LogSimulator
    from core.models import ServiceMetric

    setup_logging(log_level="WARNING")  # Suppress verbose logs for demo

    print_header()
    pipeline_start = time.time()

    # Initialization
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Initializing platform...", total=None)

        # Knowledge engine
        knowledge = RAGEngine()
        await knowledge.initialize()

        playbooks_dir = Path(__file__).parent.parent / "knowledge" / "playbooks"
        if playbooks_dir.exists():
            for pb in playbooks_dir.glob("*.md"):
                await knowledge.ingest_playbook(str(pb))

        # Sandbox
        sandbox = SandboxExecutor()
        await sandbox.initialize()

        # Orchestrator
        orchestrator = AgentOrchestrator(
            knowledge_engine=knowledge,
            sandbox_executor=sandbox,
        )

        # Simulator
        simulator = LogSimulator()

        progress.update(task, description="✓ Platform initialized")

    console.print(f"   [green]✓[/green] Knowledge base: {knowledge.document_count} documents loaded")
    console.print(f"   [green]✓[/green] 5 agents ready (Detection, Diagnosis, Remediation, Validation, Deployment)")
    console.print(f"   [green]✓[/green] Sandbox executor ready")

    # Baseline Collection
    console.print("\n[bold yellow]📈 Collecting baseline metrics...[/bold yellow]")

    # Build up normal metric history
    for i in range(15):
        metrics = simulator.generate_metrics()
        # Feed to detection agent to build rolling window
        await orchestrator.detection_agent.collect_baseline(metrics)

    console.print("   [green]✓[/green] 15 baseline metric samples collected")
    console.print("   [dim]   All services healthy: payment-api, user-service, order-service, inventory-service[/dim]")

    # Anomaly Injection
    console.print("\n[bold red][FAIL] INJECTING ANOMALY[/bold red]")
    console.print("   [red]Payment API latency spike: 180ms -> 2250ms[/red]")
    console.print("   [red]Simulated worker pool exhaustion[/red]")

    scenario = simulator.inject_anomaly("payment_latency_spike")
    anomaly_inject_time = time.time()

    # Generate anomalous metrics
    anomalous_metrics = simulator.generate_metrics()

    # Show anomalous metric values
    console.print("\n   [yellow]Anomalous metrics:[/yellow]")
    for m in anomalous_metrics:
        if m.service_name == "payment-api":
            indicator = "[ERR]" if m.metric_name == "response_time_ms" else "[WARN]"
            console.print(f"   {indicator} {m.service_name}/{m.metric_name}: {m.value} {m.unit}")

    console.print("\n[bold cyan]REMEDIATION PIPELINE ACTIVATED[/bold cyan]")

    # Run the full pipeline through the orchestrator
    record = await orchestrator.run_full_pipeline(anomalous_metrics)

    if record:
        pipeline_duration = time.time() - pipeline_start

        # Execution Results

        # Stage 1: Detection
        print_stage(1, "DETECTION", "Anomaly identification via statistical analysis")
        console.print(f"   [green]✓[/green] Anomaly detected: [bold]{record.anomaly.anomaly_type}[/bold]")
        console.print(f"   [green]✓[/green] Service: {record.anomaly.service_name}")
        console.print(f"   [green]✓[/green] Severity: [red]{record.anomaly.severity.value}[/red]")
        console.print(f"   [green]✓[/green] Confidence: {record.anomaly.confidence:.0%}")
        console.print(f"   [green]✓[/green] Detection latency: {record.anomaly.detection_latency_ms:.0f}ms")

        # Stage 2: Diagnosis
        print_stage(2, "DIAGNOSIS", "Root cause analysis with ReAct reasoning")
        console.print(f"   [green]✓[/green] Root cause: [bold]{record.diagnosis.root_cause}[/bold]")
        console.print(f"   [green]✓[/green] Category: {record.diagnosis.root_cause_category}")
        console.print(f"   [green]✓[/green] Confidence: {record.diagnosis.confidence:.0%}")
        console.print(f"   [green]✓[/green] Reasoning steps: {len(record.diagnosis.reasoning_chain)}")
        if record.diagnosis.recommended_actions:
            console.print(f"   [green]✓[/green] Recommended: {record.diagnosis.recommended_actions[0]}")

        # Stage 3: Remediation
        print_stage(3, "REMEDIATION", "Patch generation with RAG knowledge")
        console.print(f"   [green]✓[/green] Patch type: [bold]{record.patch.patch_type}[/bold]")
        console.print(f"   [green]✓[/green] Description: {record.patch.description}")
        console.print(f"   [green]✓[/green] Code changes: {len(record.patch.code_changes)} files")
        console.print(f"   [green]✓[/green] Config changes: {len(record.patch.config_changes)} items")

        # Stage 4: Validation
        print_stage(4, "VALIDATION", "Multi-stage safety pipeline")
        console.print(f"   [green]ok[/green] Static analysis: {'PASSED' if record.validation.static_analysis_passed else 'FAILED'}")
        console.print(f"   [green]ok[/green] Policy check: {'PASSED' if record.validation.policy_check_passed else 'FAILED'}")
        console.print(f"   [green]ok[/green] Tests: {'PASSED' if record.validation.tests_passed else 'FAILED'}")
        console.print(f"   [green]ok[/green] Sandbox: {'PASSED' if record.validation.sandbox_execution_passed else 'FAILED'}")
        console.print(f"   [green]ok[/green] Risk score: [bold]{record.validation.risk_score:.2f}[/bold] ({record.validation.risk_level.value})")
        console.print(f"   [green]ok[/green] Auto-deploy: {'YES' if record.validation.is_safe_for_auto_deploy else 'NO'}")

        # Stage 5: Deployment
        print_stage(5, "DEPLOYMENT", "Autonomous rollout to cluster")
        console.print(f"   [green]ok[/green] Status: [bold green]{record.deployment.status}[/bold green]")
        console.print(f"   [green]ok[/green] Strategy: {record.deployment.deployment_strategy}")
        console.print(f"   [green]ok[/green] Health check: {'PASSED' if record.deployment.health_check_passed else 'FAILED'}")
        console.print(f"   [green]ok[/green] Rollback: {'Triggered' if record.deployment.rollback_triggered else 'Not needed'}")
        if record.deployment.image_tag:
            console.print(f"   [green]ok[/green] Image: {record.deployment.image_tag}")

        # Stage 6: Metrics
        print_stage(6, "METRICS", "Platform performance tracking")
        metrics = orchestrator.get_metrics()

        # Summary Report
        console.print()

        results_table = Table(
            title="🏆 Remediation Results",
            box=box.ROUNDED,
            border_style="cyan",
            show_header=True,
            header_style="bold cyan",
        )
        results_table.add_column("Metric", style="bold")
        results_table.add_column("Value", style="green")

        results_table.add_row("Total Duration", f"{pipeline_duration:.2f} seconds")
        results_table.add_row("MTTD (Mean Time to Detect)", f"{record.mttd_seconds * 1000:.0f}ms")
        results_table.add_row("MTTR (Mean Time to Repair)", f"{record.mttr_seconds:.2f} seconds")
        results_table.add_row("Autonomous", "Yes" if record.was_successful else "No")
        results_table.add_row("Human Intervention", "Not Required" if not record.manual_intervention_required else "Required")
        results_table.add_row("", "")
        results_table.add_row("Anomalies Detected", str(metrics.total_anomalies_detected))
        results_table.add_row("Fixes Deployed", str(metrics.total_fixes_deployed))
        results_table.add_row("Resolution Rate", f"{metrics.autonomous_resolution_rate:.0%}")
        results_table.add_row("Engineering Hours Saved", f"{metrics.engineering_hours_saved:.1f} hours")
        results_table.add_row("ROI", f"${metrics.roi_dollars:,.2f}")
        results_table.add_row("", "")
        results_table.add_row("Manual Workflows Reduced", f"{metrics.manual_workflows_reduced_pct:.0f}%")
        results_table.add_row("Infrastructure Inefficiency Reduced", f"{metrics.infrastructure_inefficiency_reduced_pct:.0f}%")

        console.print(results_table)

        # Target check
        target_met = pipeline_duration < 60
        console.print(Panel(
            f"{'[bold green][SUCCESS] TARGET MET[/bold green]' if target_met else '[bold red][FAIL] TARGET MISSED[/bold red]'}\n"
            f"Autonomous remediation completed in [bold]{pipeline_duration:.2f}[/bold] seconds "
            f"(target: < 60 seconds)",
            border_style="green" if target_met else "red",
        ))

        # Learning
        console.print("\n[bold cyan]📚 LEARNING SYSTEM[/bold cyan]")
        console.print(f"   [green]✓[/green] Remediation record stored for future reference")
        console.print(f"   [green]✓[/green] Knowledge base updated: {knowledge.document_count} total entries")
        console.print(f"   [dim]   Future similar incidents will benefit from this remediation[/dim]")

    else:
        console.print("\n[yellow]⚠️ No anomaly detected in this run.[/yellow]")
        console.print("[dim]Try running again — the anomaly injection may need stronger signals.[/dim]")


async def run_multi_scenario_demo():
    """Run multiple anomaly scenarios to build up metrics."""
    from core.logging_config import setup_logging
    from knowledge.rag_engine import RAGEngine
    from sandbox.sandbox_executor import SandboxExecutor
    from agents.orchestrator import AgentOrchestrator
    from services.log_simulator import LogSimulator

    setup_logging(log_level="WARNING")
    console.print(Panel.fit(
        "[bold cyan]AETHELGARD  — Multi-Scenario Demo[/bold cyan]\n"
        "[dim]Running all anomaly scenarios to demonstrate learning[/dim]",
        border_style="cyan",
    ))

    knowledge = RAGEngine()
    await knowledge.initialize()
    playbooks_dir = Path(__file__).parent.parent / "knowledge" / "playbooks"
    if playbooks_dir.exists():
        for pb in playbooks_dir.glob("*.md"):
            await knowledge.ingest_playbook(str(pb))

    sandbox = SandboxExecutor()
    await sandbox.initialize()
    orchestrator = AgentOrchestrator(knowledge_engine=knowledge, sandbox_executor=sandbox)
    simulator = LogSimulator()

    scenarios = [
        "payment_latency_spike",
        "user_service_errors",
        "order_memory_pressure",
        "inventory_cpu_spike",
    ]

    for scenario_name in scenarios:
        console.print(f"\n{'═' * 60}")
        console.print(f"[bold]Running scenario: {scenario_name}[/bold]")

        sim = LogSimulator()  # Fresh simulator per scenario
        # Build baseline
        for _ in range(15):
            m = sim.generate_metrics()
            await orchestrator.detection_agent.collect_baseline(m)

        sim.inject_anomaly(scenario_name)
        metrics = sim.generate_metrics()
        record = await orchestrator.run_full_pipeline(metrics)

        if record:
            console.print(f"   [green]✓[/green] {record.anomaly.service_name}: {record.anomaly.anomaly_type}")
            console.print(f"   [green]✓[/green] Fix: {record.patch.description[:60]}...")
            console.print(f"   [green]✓[/green] Duration: {record.mttr_seconds:.2f}s")

    # Final metrics
    final_metrics = orchestrator.get_metrics()
    console.print(f"\n{'═' * 60}")
    console.print(Panel(
        f"[bold]Total Anomalies:[/bold] {final_metrics.total_anomalies_detected}\n"
        f"[bold]Fixes Deployed:[/bold] {final_metrics.total_fixes_deployed}\n"
        f"[bold]Resolution Rate:[/bold] {final_metrics.autonomous_resolution_rate:.0%}\n"
        f"[bold]Hours Saved:[/bold] {final_metrics.engineering_hours_saved:.1f}\n"
        f"[bold]ROI:[/bold] ${final_metrics.roi_dollars:,.2f}",
        title="Multi-Scenario Results",
        border_style="green",
    ))


def main():
    """Main demo entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Aethelgard — Demo Runner")
    parser.add_argument("--multi", action="store_true", help="Run all scenarios")
    args = parser.parse_args()

    try:
        if args.multi:
            asyncio.run(run_multi_scenario_demo())
        else:
            asyncio.run(run_demo())
    except KeyboardInterrupt:
        console.print("\n[yellow]Demo aborted by user.[/yellow]")


if __name__ == "__main__":
    main()
