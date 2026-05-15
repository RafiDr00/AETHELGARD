"""
Aethelgard v2 — Log Listener

Listens for incoming log streams from microservices,
parses structured data, extracts metrics, and produces
events to the event bus.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List, Optional

from core.logging_config import get_logger
from core.models import LogEntry, ServiceMetric
from experiments.scenario_runner import LogSimulator

logger = get_logger(__name__)


class LogListener:
    """
    Log ingestion pipeline that collects logs from services,
    parses them into structured entries, and feeds them to
    the detection pipeline.
    """

    def __init__(self, simulator: LogSimulator):
        self._simulator = simulator
        self._metric_callbacks: List[Callable] = []
        self._log_callbacks: List[Callable] = []
        self._running = False
        self._poll_interval = 2.0  # seconds

    def on_metrics(self, callback: Callable) -> None:
        """Register a callback for new metrics batches."""
        self._metric_callbacks.append(callback)

    def on_logs(self, callback: Callable) -> None:
        """Register a callback for new log batches."""
        self._log_callbacks.append(callback)

    async def start(self) -> None:
        """Start the log listener polling loop."""
        self._running = True
        logger.info("log_listener_started", poll_interval=self._poll_interval)

        while self._running:
            try:
                # Generate metrics and logs
                metrics = self._simulator.generate_metrics()
                logs = self._simulator.generate_logs(count=5)

                # Dispatch to callbacks
                for callback in self._metric_callbacks:
                    await callback(metrics)

                for callback in self._log_callbacks:
                    await callback(logs)

            except Exception as e:
                logger.error("log_listener_error", error=str(e))

            await asyncio.sleep(self._poll_interval)

    async def stop(self) -> None:
        """Stop the log listener."""
        self._running = False
        logger.info("log_listener_stopped")

    async def collect_once(self) -> tuple:
        """Collect a single batch of metrics and logs."""
        metrics = self._simulator.generate_metrics()
        logs = self._simulator.generate_logs(count=5)
        return metrics, logs
