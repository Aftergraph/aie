from datetime import datetime, timedelta, timezone

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from aie_runtime.engine import AuthorityLease, Mission, Principal
from aie_runtime.gateway.core import AIEGateway
from aie_runtime.gateway.durable import SQLiteGatewayStore
from aie_runtime.gateway.identity import TransportIdentity
from aie_runtime.gateway.policy import LocalPolicyAdapter
from aie_runtime.gateway.telemetry import OTelEvidenceExporter
from aie_runtime.store import InMemoryState

NOW = datetime(2026, 9, 3, 1, 0, tzinfo=timezone.utc)


def test_gateway_decision_is_exported_as_child_of_incoming_trace(tmp_path):
    memory = InMemorySpanExporter(); provider = TracerProvider(); provider.add_span_processor(SimpleSpanProcessor(memory))
    state = InMemoryState()
    state.principals["p"] = Principal("p", "agent", "spiffe://example.org/agent/refund")
    state.missions["m"] = Mission("m", "RUNNING")
    state.leases["l"] = AuthorityLease("l", "p", "m", {"mcp.tools.call:refund_customer"}, ("mcp://tool/refund_customer",), NOW + timedelta(hours=1), 10)
    gateway = AIEGateway(
        state=state, store=SQLiteGatewayStore(tmp_path / "g.db"), policy=LocalPolicyAdapter(lambda _: True), clock=lambda: NOW,
        evidence_exporter=OTelEvidenceExporter(tracer_provider=provider),
    )
    headers = {
        "MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "tools/call", "Mcp-Name": "refund_customer",
        "AIE-Mission-Id": "m", "AIE-Authority-Lease": "l",
        "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
    }
    body = {"jsonrpc": "2.0", "id": "otel-gw-1", "method": "tools/call", "params": {"name": "refund_customer"}}
    decision = gateway.handle("mcp", headers, body, TransportIdentity("spiffe://example.org/agent/refund", True))
    assert decision.status == "admitted"
    spans = memory.get_finished_spans(); assert len(spans) == 1
    assert format(spans[0].context.trace_id, "032x") == "4bf92f3577b34da6a3ce929d0e0e4736"
