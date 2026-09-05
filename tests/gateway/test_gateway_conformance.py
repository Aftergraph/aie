import threading
from datetime import datetime, timedelta, timezone

from aie_runtime.engine import AuthorityLease, Mission, Principal
from aie_runtime.gateway.conformance import run_gateway_conformance
from aie_runtime.gateway.core import AIEGateway
from aie_runtime.gateway.durable import SQLiteGatewayStore
from aie_runtime.gateway.http import create_http_server
from aie_runtime.gateway.policy import LocalPolicyAdapter
from aie_runtime.store import InMemoryState

NOW = datetime(2026, 9, 3, 1, 0, tzinfo=timezone.utc)


def build_server(tmp_path):
    state = InMemoryState()
    state.principals["agent:refund"] = Principal("agent:refund", "agent", "spiffe://example.org/agent/refund")
    state.missions["mission:refunds"] = Mission("mission:refunds", "RUNNING")
    state.leases["lease:refund"] = AuthorityLease(
        id="lease:refund",
        principal_id="agent:refund",
        mission_id="mission:refunds",
        capabilities={"mcp.tools.call:refund_customer", "a2a.message.send"},
        resource_prefixes=("mcp://tool/refund_customer", "a2a://message/"),
        expires_at=NOW + timedelta(hours=1),
        budget_remaining=20,
    )
    gateway = AIEGateway(
        state=state,
        store=SQLiteGatewayStore(tmp_path / "gateway.db"),
        policy=LocalPolicyAdapter(lambda _: True),
        clock=lambda: NOW,
    )
    return create_http_server(
        gateway,
        host="127.0.0.1",
        port=0,
        admin_token="admin-secret",
        trust_header_identity=True,
    )


def test_black_box_gateway_conformance_reports_all_checks_passed(tmp_path):
    server = build_server(tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        report = run_gateway_conformance(
            f"http://127.0.0.1:{server.server_port}",
            admin_token="admin-secret",
            spiffe_id="spiffe://example.org/agent/refund",
            mission_id="mission:refunds",
            lease_id="lease:refund",
            mcp_tool="refund_customer",
        )
        assert report["passed"] is True
        assert report["summary"]["failed"] == 0
        assert report["summary"]["passed"] == 5
        assert [c["id"] for c in report["checks"]] == [
            "GW-HEALTH-001",
            "GW-MCP-ADMIT-001",
            "GW-REPLAY-001",
            "GW-A2A-ADMIT-001",
            "GW-REVOKE-001",
        ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
