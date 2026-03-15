import asyncio
import time
import httpx
from datetime import datetime, timezone
from typing import List, Optional, Dict

from core.logging_config import get_logger
from core.models import ServiceMetric
from listener.real_metrics import get_metrics_buffer

logger = get_logger(__name__)

class PrometheusScraper:
    """
    Scrapes metrics from Prometheus and pushes them into the Aethelgard MetricsBuffer.
    Enables DetectionAgent to work with real-world telemetry from external services.
    """

    def __init__(
        self,
        prometheus_url: str = "http://localhost:9090",
        scrape_interval: float = 10.0,
    ):
        self.prometheus_url = prometheus_url
        self.scrape_interval = scrape_interval
        self.buffer = get_metrics_buffer()
        self._running = False
        self._client = httpx.AsyncClient(timeout=5.0)

    async def start(self):
        self._running = True
        logger.info("prometheus_scraper_started", url=self.prometheus_url)
        while self._running:
            try:
                await self._scrape_cycle()
            except Exception as e:
                logger.error("prometheus_scrape_failed", error=str(e))
            await asyncio.sleep(self.scrape_interval)

    async def stop(self):
        self._running = False
        await self._client.aclose()
        logger.info("prometheus_scraper_stopped")

    async def _scrape_cycle(self):
        # Query Prometheus for various metrics
        # We use 'instant queries' for the latest values
        queries = {
            "response_time_ms": 'rate(http_request_duration_seconds_sum[1m]) / rate(http_request_duration_seconds_count[1m]) * 1000',
            "error_rate": 'sum(rate(http_requests_total{http_status=~"5.."}[1m])) / sum(rate(http_requests_total[1m]))',
            "request_rate": 'sum(rate(http_requests_total[1m]))',
            "memory_usage": 'service_memory_usage_bytes',
            "db_connections": 'db_connection_pool_active'
        }

        now = datetime.now(timezone.utc)
        
        for metric_name, query in queries.items():
            try:
                result = await self._query_prometheus(query)
                for item in result:
                    service = item.get("metric", {}).get("service", "payment-service")
                    value = float(item.get("value", [0, 0])[1])
                    
                    if value is None or (value != value): # NaN check
                        continue

                    # Push to shared buffer
                    await self.buffer.write(ServiceMetric(
                        service_name=service,
                        metric_name=metric_name,
                        value=round(value, 3),
                        unit=self._infer_unit(metric_name),
                        timestamp=now,
                        labels=item.get("metric", {})
                    ))
            except Exception as e:
                logger.debug("query_failed", query=query, error=str(e))

    async def _query_prometheus(self, query: str) -> List[Dict]:
        url = f"{self.prometheus_url}/api/v1/query"
        params = {"query": query}
        resp = await self._client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "success":
            return data.get("data", {}).get("result", [])
        return []

    def _infer_unit(self, name: str) -> str:
        if "time" in name or "ms" in name: return "ms"
        if "rate" in name: return "req/s"
        if "ratio" in name or "error_rate" in name: return "ratio"
        if "memory" in name: return "bytes"
        return "count"
