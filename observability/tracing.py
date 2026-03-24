import time
from contextlib import asynccontextmanager, contextmanager
from typing import Any, Dict
import os

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry import propagate

_SERVICE_NAME = "aethelgard-v2"
_OTEL_ENDPOINT = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")

_resource = Resource.create({
    SERVICE_NAME: _SERVICE_NAME,
    "service.version": "2.0.0",
    "deployment.environment": os.environ.get("APP_ENV", "development"),
})

_provider = TracerProvider(resource=_resource)

if _OTEL_ENDPOINT:
    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        _otlp_exporter = OTLPSpanExporter(endpoint=_OTEL_ENDPOINT, insecure=True)
        _provider.add_span_processor(BatchSpanProcessor(_otlp_exporter))
    except Exception as e:
        print(f"[OTEL] OTLP exporter failed: {e} - falling back to console")
        _provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
else:
    if os.environ.get("OTEL_CONSOLE_EXPORT", "false").lower() == "true":
        _provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

trace.set_tracer_provider(_provider)
tracer = trace.get_tracer(_SERVICE_NAME, "2.0.0")

@contextmanager
def agent_span(agent_type: str, operation: str, attributes: Dict[str, Any] = None):
    with tracer.start_as_current_span(
        f"agent.{agent_type}.{operation}",
        attributes={"agent.type": agent_type, "agent.operation": operation, **(attributes or {})},
    ) as span:
        start_time = time.time()
        try:
            yield span
        except Exception as e:
            span.set_status(trace.StatusCode.ERROR, str(e))
            span.record_exception(e)
            raise
        finally:
            duration = time.time() - start_time
            span.set_attribute("agent.duration_ms", round(duration * 1000, 2))

@asynccontextmanager
async def pipeline_span(correlation_id: str, scenario: str = "unknown"):
    with tracer.start_as_current_span(
        "pipeline.run",
        attributes={"pipeline.correlation_id": correlation_id, "pipeline.scenario": scenario},
    ) as span:
        start_time = time.time()
        try:
            yield span
        except Exception as e:
            span.set_status(trace.StatusCode.ERROR, str(e))
            span.record_exception(e)
            raise
        finally:
            duration = time.time() - start_time
            span.set_attribute("pipeline.duration_ms", round(duration * 1000, 2))

def get_trace_context() -> Dict[str, str]:
    ctx: Dict[str, str] = {}
    propagate.inject(ctx)
    return ctx

def get_current_trace_id() -> str:
    span = trace.get_current_span()
    ctx = span.get_span_context()
    return format(ctx.trace_id, "032x") if ctx and ctx.is_valid else ""

def get_current_span_id() -> str:
    span = trace.get_current_span()
    ctx = span.get_span_context()
    return format(ctx.span_id, "016x") if ctx and ctx.is_valid else ""
