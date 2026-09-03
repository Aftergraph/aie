from __future__ import annotations

from typing import Any

from .identity import TransportIdentity
from .model import GatewayDecision, NormalizedAction


def build_gateway_evidence(
    action: NormalizedAction,
    decision: GatewayDecision,
    identity: TransportIdentity,
    *,
    principal_id: str,
    mission_id: str,
    lease_id: str,
) -> dict[str, Any]:
    operation_name = "execute_tool" if action.protocol == "mcp" and action.operation == "tools/call" else "invoke_agent"
    event: dict[str, Any] = {
        "event_type": "gateway.decision",
        "aie.action.id": action.action_id,
        "aie.principal.id": principal_id,
        "aie.mission.id": mission_id,
        "aie.lease.id": lease_id,
        "aie.protocol": action.protocol,
        "aie.protocol.version": action.protocol_version,
        "aie.capability": action.capability,
        "aie.resource": action.resource,
        "aie.decision": decision.status,
        "gen_ai.operation.name": operation_name,
    }
    if identity.spiffe_id:
        event["aie.identity.spiffe_id"] = identity.spiffe_id
    if decision.error_code:
        event["aie.error_code"] = decision.error_code
    return event
