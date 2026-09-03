from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from aie_runtime.gateway.telemetry import OTelEvidenceExporter


def test_otel_exporter_emits_decision_span_with_aie_attributes_and_parent_context():
    memory = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(memory))
    exporter = OTelEvidenceExporter(tracer_provider=provider)
    event = {
        "event_type": "gateway.decision",
        "aie.action.id": "a-1",
        "aie.principal.id": "agent:a",
        "aie.decision": "admitted",
        "gen_ai.operation.name": "execute_tool",
    }
    exporter.emit(
        event,
        carrier={"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"},
    )
    spans = memory.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "aie.gateway.decision"
    assert span.attributes["aie.action.id"] == "a-1"
    assert span.attributes["aie.decision"] == "admitted"
    assert format(span.context.trace_id, "032x") == "4bf92f3577b34da6a3ce929d0e0e4736"
