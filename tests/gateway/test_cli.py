import json
from datetime import datetime, timezone

from aie_runtime.gateway.cli import build_gateway_from_config


def test_build_gateway_from_config_loads_authority_and_local_policy(tmp_path):
    config = {
        "store": str(tmp_path / "gateway.db"),
        "principals": [
            {"id": "agent:refund", "type": "agent", "identity_ref": "spiffe://example.org/agent/refund"}
        ],
        "missions": [{"id": "mission:refunds", "state": "active"}],
        "leases": [
            {
                "id": "lease:refund",
                "principal_id": "agent:refund",
                "mission_id": "mission:refunds",
                "capabilities": ["mcp.tools.call:refund_customer"],
                "resource_prefixes": ["mcp://tool/refund_customer"],
                "expires_at": "2026-09-03T03:00:00+00:00",
                "budget_remaining": 10,
            }
        ],
        "policy": {"type": "local", "decision": "allow"},
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")

    gateway = build_gateway_from_config(path, clock=lambda: datetime(2026, 9, 3, 1, 0, tzinfo=timezone.utc))

    assert "agent:refund" in gateway.state.principals
    assert "mission:refunds" in gateway.state.missions
    assert "lease:refund" in gateway.state.leases
    assert gateway.policy.evaluate({}) is True


def test_build_gateway_from_config_supports_opa_policy(tmp_path):
    config = {
        "store": str(tmp_path / "gateway.db"),
        "principals": [],
        "missions": [],
        "leases": [],
        "policy": {"type": "opa", "url": "http://127.0.0.1:8181/v1/data/aie/allow"},
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")

    gateway = build_gateway_from_config(path)
    assert gateway.policy.url.endswith("/v1/data/aie/allow")
