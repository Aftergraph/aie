from __future__ import annotations

from typing import Any, Mapping


class OTelEvidenceExporter:
    """Export AIE decision evidence as OpenTelemetry spans.

    OpenTelemetry is optional at package import time. Instantiating this adapter requires
    opentelemetry-api; SDK/exporter choice remains controlled by the embedding process.
    """

    def __init__(self, *, tracer_provider=None, tracer_name: str = "aie.gateway"):
        try:
            from opentelemetry import trace
        except Exception as exc:  # pragma: no cover - dependency/environment guard
            raise RuntimeError("OpenTelemetry API is required for OTelEvidenceExporter") from exc
        self._trace = trace
        self._tracer = trace.get_tracer(tracer_name, tracer_provider=tracer_provider)

    def emit(self, event: Mapping[str, Any], *, carrier: Mapping[str, str] | None = None) -> None:
        try:
            from opentelemetry.propagate import extract
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("OpenTelemetry propagation API is required") from exc
        context = extract(dict(carrier or {}))
        with self._tracer.start_as_current_span("aie.gateway.decision", context=context) as span:
            for key, value in event.items():
                if isinstance(value, (str, bool, int, float)):
                    span.set_attribute(key, value)
