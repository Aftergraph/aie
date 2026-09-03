from aie_runtime.gateway.evidence import build_gateway_evidence
from aie_runtime.gateway.identity import TransportIdentity
from aie_runtime.gateway.model import GatewayDecision, NormalizedAction


def test_gateway_evidence_is_metadata_only():
    action = NormalizedAction(
        protocol="mcp",
        protocol_version="2026-07-28",
        action_id="a-1",
        capability="mcp.tools.call:refund",
        resource="mcp://tool/refund",
        operation="tools/call",
        subject_id="refund",
        metadata={"jsonrpc": "2.0"},
    )
    decision = GatewayDecision(status="admitted", action_id="a-1", protocol="mcp")
    identity = TransportIdentity(spiffe_id="spiffe://example.org/agent/refund", verified=True)

    event = build_gateway_evidence(
        action,
        decision,
        identity,
        principal_id="principal-1",
        mission_id="mission-1",
        lease_id="lease-1",
    )

    assert event["event_type"] == "gateway.decision"
    assert event["aie.action.id"] == "a-1"
    assert event["aie.protocol"] == "mcp"
    assert event["aie.capability"] == "mcp.tools.call:refund"
    assert event["aie.decision"] == "admitted"
    assert event["gen_ai.operation.name"] == "execute_tool"
    assert event["aie.identity.spiffe_id"] == "spiffe://example.org/agent/refund"
    assert "gen_ai.agent.id" not in event
    serialized = repr(event)
    assert "arguments" not in serialized
    assert "parts" not in serialized
    assert "prompt" not in serialized


def test_gateway_evidence_records_error_without_payload():
    action = NormalizedAction(
        protocol="a2a",
        protocol_version="1.0",
        action_id="a2a-1",
        capability="a2a.message.send",
        resource="a2a://message/m-1",
        operation="message/send",
    )
    decision = GatewayDecision(
        status="denied",
        action_id="a2a-1",
        protocol="a2a",
        error_code="AIE-AUTH-003",
    )
    identity = TransportIdentity(spiffe_id="spiffe://example.org/agent/a", verified=True)

    event = build_gateway_evidence(
        action,
        decision,
        identity,
        principal_id="p",
        mission_id="m",
        lease_id="l",
    )
    assert event["aie.error_code"] == "AIE-AUTH-003"
    assert event["gen_ai.operation.name"] == "invoke_agent"
