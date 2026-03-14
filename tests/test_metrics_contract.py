from prometheus_client import generate_latest


def test_critical_metrics_exist_in_registry() -> None:
    # Ensure telemetry module registers all metric families.
    import core.telemetry  # noqa: F401

    scrape = generate_latest().decode("utf-8")
    required = {
        "aethelgard_pipeline_runs_total",
        "aethelgard_react_iterations_total",
        "aethelgard_react_timeouts_total",
        "aethelgard_dedup_suppression_ratio",
        "aethelgard_anomalies_detected_total",
        "aethelgard_remediations_total",
        "aethelgard_agent_stage_duration_seconds",
        "aethelgard_validation_failures_total",
        "aethelgard_agent_latency_seconds",
    }
    missing = sorted(name for name in required if name not in scrape)
    assert not missing, f"Missing metric families: {missing}"


def test_critical_metrics_present_in_prometheus_scrape() -> None:
    # Ensure metrics are exported in Prometheus text format.
    import core.telemetry  # noqa: F401

    scrape = generate_latest().decode("utf-8")
    for metric_name in (
        "aethelgard_pipeline_runs_total",
        "aethelgard_validation_failures_total",
        "aethelgard_agent_latency_seconds",
        "aethelgard_dedup_suppression_ratio",
    ):
        assert metric_name in scrape, f"{metric_name} missing from scrape output"
