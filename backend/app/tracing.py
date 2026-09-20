"""OpenTelemetry helpers (3.1).

The one module that imports `opentelemetry`. Two entry points: `configure_tracing`
installs the OTLP exporter at app startup, and `span` is the context manager the
rest of the backend wraps work in.

Two rules this module exists to hold:

- **Off by default.** `settings.otel_enabled` is False, so the test suite needs no
  collector and CI needs no service container. `span()` still works when nothing
  is installed — OpenTelemetry's default tracer returns a non-recording span — so
  callers never branch on whether tracing is on.
- **Attributes carry ids, counts and durations, never payloads.** No embedding
  vectors (512 floats), no note text, no user questions. A trace is for finding
  where the time and the calls went, and an exporter is a place data leaves from.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from app.config import settings

_configured = False

# Values OpenTelemetry accepts for an attribute. Anything else is stringified by
# the caller before it gets here; None is dropped (OTel raises on it).
_Scalar = str | bool | int | float


def _tracer() -> Any:
    """Indirection so tests can substitute a tracer bound to an in-memory
    exporter. The global tracer provider can only be set once per process, so a
    test that installed one would silently export nothing in every later test."""
    from opentelemetry import trace

    return trace.get_tracer("wavepoint")


def _install_exporter() -> None:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": "wavepoint-backend"}))
    endpoint = settings.otel_exporter_otlp_endpoint.rstrip("/") + "/v1/traces"
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)


def configure_tracing() -> None:
    """Install the OTLP exporter. A no-op when disabled, and idempotent.

    Idempotence is not decoration: `create_app()` runs once per test in the
    `client` fixture, and a second install would add a second span processor that
    lives for the rest of the process.
    """
    global _configured
    if not settings.otel_enabled or _configured:
        return
    _install_exporter()
    _configured = True


@contextmanager
def span(name: str, **attributes: _Scalar | None) -> Iterator[Any]:
    """Run a block inside a span. Safe whether or not tracing is configured.

    `None`-valued attributes are dropped rather than passed through, so callers
    can hand optional values straight in without a conditional at each site.
    """
    with _tracer().start_as_current_span(name) as current:
        for key, value in attributes.items():
            if value is not None:
                current.set_attribute(key, value)
        yield current
