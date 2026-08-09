"""OpenTelemetry tracing + logging instrumentation for the Jarvis ingest worker.

Enabled when OTEL_EXPORTER_OTLP_ENDPOINT is set (e.g. http://alloy:4318).
Left unset, setup is a no-op so local/pytest runs don't need Alloy.
"""

from __future__ import annotations

import logging

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logger = logging.getLogger(__name__)


def setup_telemetry(*, endpoint: str | None, service_name: str) -> None:
    if not endpoint:
        return

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    traces_endpoint = endpoint.rstrip("/")
    if not traces_endpoint.endswith("/v1/traces"):
        traces_endpoint = f"{traces_endpoint}/v1/traces"

    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=traces_endpoint)))
    trace.set_tracer_provider(provider)

    LoggingInstrumentor().instrument(set_logging_format=True)
    logger.info("OpenTelemetry tracing enabled → %s (service=%s)", traces_endpoint, service_name)
