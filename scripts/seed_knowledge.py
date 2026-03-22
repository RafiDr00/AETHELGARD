"""
Aethelgard — Knowledge Base Seeder

Seeds the RAG knowledge base with remediation playbooks
and historical data for agent reasoning.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.table import Table

from core.logging_config import setup_logging, get_logger
from knowledge.rag_engine import RAGEngine

console = Console()


async def seed():
    """Seed the knowledge base with all playbooks."""
    setup_logging(log_level="WARNING")
    
    console.print("[bold cyan]🏗️ Aethelgard — Knowledge Base Seeder[/bold cyan]\n")

    engine = RAGEngine()
    await engine.initialize()

    playbooks_dir = Path(__file__).parent.parent / "knowledge" / "playbooks"

    if not playbooks_dir.exists():
        console.print("[red]✗ Playbooks directory not found![/red]")
        return

    table = Table(title="Playbooks Loaded")
    table.add_column("File", style="cyan")
    table.add_column("Category", style="green")
    table.add_column("Size", style="yellow")
    table.add_column("Status", style="green")

    count = 0
    for playbook_path in sorted(playbooks_dir.glob("*.md")):
        content = playbook_path.read_text(encoding="utf-8")
        doc_id = await engine.ingest_playbook(str(playbook_path))
        
        table.add_row(
            playbook_path.name,
            "playbook",
            f"{len(content)} chars",
            f"✓ {doc_id}",
        )
        count += 1

    # Add some synthetic historical remediations
    sample_remediations = [
        {
            "anomaly_type": "latency_spike",
            "service_name": "api-gateway",
            "root_cause": "Worker pool exhaustion due to blocking I/O",
            "fix_description": "Increased uvicorn workers from 2 to 8, enabled uvloop",
            "was_successful": True,
            "duration_seconds": 42.5,
        },
        {
            "anomaly_type": "error_rate_increase",
            "service_name": "payment-service",
            "root_cause": "Upstream dependency timeout",
            "fix_description": "Added circuit breaker with 5s timeout and fallback",
            "was_successful": True,
            "duration_seconds": 38.2,
        },
        {
            "anomaly_type": "memory_pressure",
            "service_name": "analytics-worker",
            "root_cause": "Memory leak in data processing pipeline",
            "fix_description": "Implemented periodic pod restart policy (every 6h)",
            "was_successful": True,
            "duration_seconds": 55.8,
        },
    ]

    for remediation in sample_remediations:
        await engine.store_remediation(remediation)
        count += 1

    console.print(table)
    console.print(f"\n[green]✓ Loaded {count} documents into knowledge base[/green]")
    console.print(f"[green]✓ Categories: {engine.categories}[/green]")


def main():
    asyncio.run(seed())


if __name__ == "__main__":
    main()
