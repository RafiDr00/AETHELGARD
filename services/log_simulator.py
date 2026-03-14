"""
Aethelgard v2 — Log Simulator

Generates realistic microservice log streams with configurable
anomaly injection. Simulates a cluster of services producing
structured telemetry data.
"""

from __future__ import annotations

import asyncio
import math
import random
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional, Tuple

from core.logging_config import get_logger
from core.models import LogEntry, ServiceMetric, Severity

logger = get_logger(__name__)


# Service definitions with baseline metrics
SERVICE_PROFILES = {
    "payment-api": {
        "baseline_latency": 180,
        "baseline_error_rate": 0.001,
        "baseline_cpu": 0.35,
        "baseline_memory": 0.45,
        "baseline_rps": 500,
        "endpoints": ["/api/v1/charge", "/api/v1/refund", "/api/v1/status"],
    },
    "user-service": {
        "baseline_latency": 120,
        "baseline_error_rate": 0.002,
        "baseline_cpu": 0.25,
        "baseline_memory": 0.40,
        "baseline_rps": 800,
        "endpoints": ["/api/v1/users", "/api/v1/auth", "/api/v1/profile"],
    },
    "order-service": {
        "baseline_latency": 200,
        "baseline_error_rate": 0.003,
        "baseline_cpu": 0.40,
        "baseline_memory": 0.55,
        "baseline_rps": 350,
        "endpoints": ["/api/v1/orders", "/api/v1/cart", "/api/v1/checkout"],
    },
    "inventory-service": {
        "baseline_latency": 90,
        "baseline_error_rate": 0.001,
        "baseline_cpu": 0.20,
        "baseline_memory": 0.30,
        "baseline_rps": 600,
        "endpoints": ["/api/v1/stock", "/api/v1/reserve", "/api/v1/release"],
    },
}


class AnomalyScenario:
    """Defines an anomaly injection scenario."""

    def __init__(
        self,
        name: str,
        target_service: str,
        anomaly_type: str,
        severity: Severity,
        latency_multiplier: float = 1.0,
        error_rate_multiplier: float = 1.0,
        cpu_multiplier: float = 1.0,
        memory_multiplier: float = 1.0,
        duration_seconds: int = 60,
    ):
        self.name = name
        self.target_service = target_service
        self.anomaly_type = anomaly_type
        self.severity = severity
        self.latency_multiplier = latency_multiplier
        self.error_rate_multiplier = error_rate_multiplier
        self.cpu_multiplier = cpu_multiplier
        self.memory_multiplier = memory_multiplier
        self.duration_seconds = duration_seconds
        self.start_time: Optional[float] = None
        self.active = False

    def activate(self) -> None:
        self.start_time = time.time()
        self.active = True

    def deactivate(self) -> None:
        self.active = False

    @property
    def is_expired(self) -> bool:
        if not self.start_time:
            return True
        return time.time() - self.start_time > self.duration_seconds


# Pre-defined anomaly scenarios
DEMO_SCENARIOS = {
    "payment_latency_spike": AnomalyScenario(
        name="Payment API Latency Spike",
        target_service="payment-api",
        anomaly_type="latency_spike",
        severity=Severity.CRITICAL,
        latency_multiplier=12.5,  # 180ms → 2250ms
        cpu_multiplier=1.2,
        duration_seconds=120,
    ),
    "user_service_errors": AnomalyScenario(
        name="User Service Error Rate Increase",
        target_service="user-service",
        anomaly_type="error_rate_increase",
        severity=Severity.HIGH,
        error_rate_multiplier=50.0,  # 0.2% → 10%
        latency_multiplier=2.0,
        duration_seconds=90,
    ),
    "order_memory_pressure": AnomalyScenario(
        name="Order Service Memory Pressure",
        target_service="order-service",
        anomaly_type="memory_pressure",
        severity=Severity.HIGH,
        memory_multiplier=2.1,  # 55% → ~95%+
        latency_multiplier=3.0,
        duration_seconds=180,
    ),
    "inventory_cpu_spike": AnomalyScenario(
        name="Inventory Service CPU Saturation",
        target_service="inventory-service",
        anomaly_type="cpu_saturation",
        severity=Severity.MEDIUM,
        cpu_multiplier=4.0,  # 20% → 80%+
        latency_multiplier=5.0,
        duration_seconds=60,
    ),
}


class LogSimulator:
    """
    Simulates a cluster of microservices producing structured
    log entries and telemetry metrics.
    
    Supports anomaly injection for demonstration and testing.
    """

    def __init__(self):
        self._service_profiles = SERVICE_PROFILES.copy()
        self._active_scenarios: List[AnomalyScenario] = []
        self._tick_count = 0
        self._running = False

    def inject_anomaly(self, scenario_name: str) -> AnomalyScenario:
        """
        Inject an anomaly scenario into the simulation.
        
        Args:
            scenario_name: Name of a pre-defined scenario
            
        Returns:
            The activated scenario
        """
        if scenario_name not in DEMO_SCENARIOS:
            raise ValueError(f"Unknown scenario: {scenario_name}")

        scenario = DEMO_SCENARIOS[scenario_name]
        scenario.activate()
        self._active_scenarios.append(scenario)

        logger.info(
            "anomaly_injected",
            scenario=scenario_name,
            service=scenario.target_service,
            type=scenario.anomaly_type,
            severity=scenario.severity.value,
        )

        return scenario

    def generate_metrics(self) -> List[ServiceMetric]:
        """
        Generate a batch of service metrics for all services.
        
        Applies active anomaly scenarios to affected services.
        """
        self._tick_count += 1
        metrics = []
        now = datetime.now(timezone.utc)

        # Clean up expired scenarios
        self._active_scenarios = [
            s for s in self._active_scenarios if not s.is_expired
        ]

        for service_name, profile in self._service_profiles.items():
            # Determine if this service has an active anomaly
            active_scenario = next(
                (s for s in self._active_scenarios if s.target_service == service_name and s.active),
                None,
            )

            # Generate metrics with natural variation
            jitter = lambda base, pct=0.1: base * (1 + random.uniform(-pct, pct))

            # Apply anomaly multipliers if active
            lat_mult = active_scenario.latency_multiplier if active_scenario else 1.0
            err_mult = active_scenario.error_rate_multiplier if active_scenario else 1.0
            cpu_mult = active_scenario.cpu_multiplier if active_scenario else 1.0
            mem_mult = active_scenario.memory_multiplier if active_scenario else 1.0

            # Add sinusoidal diurnal pattern
            diurnal = 1.0 + 0.2 * math.sin(self._tick_count * 0.05)

            metrics.extend([
                ServiceMetric(
                    service_name=service_name,
                    metric_name="response_time_ms",
                    value=round(jitter(profile["baseline_latency"] * lat_mult * diurnal), 1),
                    unit="ms",
                    timestamp=now,
                ),
                ServiceMetric(
                    service_name=service_name,
                    metric_name="error_rate",
                    value=round(min(jitter(profile["baseline_error_rate"] * err_mult), 1.0), 4),
                    unit="ratio",
                    timestamp=now,
                ),
                ServiceMetric(
                    service_name=service_name,
                    metric_name="cpu_usage",
                    value=round(min(jitter(profile["baseline_cpu"] * cpu_mult * diurnal), 0.99), 3),
                    unit="ratio",
                    timestamp=now,
                ),
                ServiceMetric(
                    service_name=service_name,
                    metric_name="memory_usage",
                    value=round(min(jitter(profile["baseline_memory"] * mem_mult), 0.99), 3),
                    unit="ratio",
                    timestamp=now,
                ),
            ])

        return metrics

    def generate_logs(self, count: int = 10) -> List[LogEntry]:
        """Generate a batch of realistic log entries."""
        logs = []
        now = datetime.now(timezone.utc)

        for _ in range(count):
            service = random.choice(list(self._service_profiles.keys()))
            profile = self._service_profiles[service]
            endpoint = random.choice(profile["endpoints"])

            # Check for active anomaly
            active_scenario = next(
                (s for s in self._active_scenarios if s.target_service == service and s.active),
                None,
            )

            if active_scenario and random.random() < 0.3:
                # Generate anomalous log
                logs.append(LogEntry(
                    timestamp=now,
                    service_name=service,
                    level="ERROR" if random.random() < 0.5 else "WARNING",
                    message=f"High latency detected on {endpoint}: "
                            f"{int(profile['baseline_latency'] * active_scenario.latency_multiplier)}ms",
                    metadata={
                        "endpoint": endpoint,
                        "latency_ms": int(profile["baseline_latency"] * active_scenario.latency_multiplier),
                        "anomaly_type": active_scenario.anomaly_type,
                    },
                    trace_id=str(uuid.uuid4()),
                ))
            else:
                # Generate normal log
                level = random.choices(
                    ["INFO", "DEBUG", "WARNING"],
                    weights=[0.8, 0.15, 0.05],
                )[0]
                logs.append(LogEntry(
                    timestamp=now,
                    service_name=service,
                    level=level,
                    message=f"Request handled: {endpoint} "
                            f"({int(profile['baseline_latency'] * random.uniform(0.8, 1.2))}ms)",
                    metadata={
                        "endpoint": endpoint,
                        "status_code": 200,
                        "method": "GET",
                    },
                    trace_id=str(uuid.uuid4()),
                ))

        return logs

    @property
    def active_anomaly_count(self) -> int:
        return len([s for s in self._active_scenarios if s.active and not s.is_expired])

    @property
    def services(self) -> List[str]:
        return list(self._service_profiles.keys())
