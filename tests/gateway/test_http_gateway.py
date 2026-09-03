import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from aie_runtime.engine import AuthorityLease, Mission, Principal
from aie_runtime.gateway.core import AIEGateway
from aie_runtime.gateway.durable import SQLiteGatewayStore
from aie_runtime.gateway.http import create_http_server
from aie_runtime.gateway.policy import LocalPolicyAdapter
from aie_runtime.store import InMemoryState

NOW = datetime(2026, 9, 3, 1, 0, tzinfo=timezone.utc)


def build_server(tmp_path):
    state = InMemoryState()
    state.principals["agent:refund"] = Principal("agent:refund", "agent", "spiffe://example.org/agent/refund")
    state.missions["mission:refunds"] = Mission("mission:refunds", "active")
    state.leases["lease:refund"] = AuthorityLease(
        id="lease:refund",
        principal_id="agent:refund",
        mission_id="mission:refunds",
        capabilities={"mcp.tools.call:refund_customer", "a2a.message.send"},
        resource_prefixes=("mcp://tool/refund_customer", "a2a://message/"),
        expires_at=NOW + timedelta(hours=1),
        budget_remaining=10,
    )
    store = SQLiteGatewayStore(tmp_path / "gateway.db")
    gateway = AIEGateway(state=state, store=store, policy=LocalPolicyAdapter(lambda _: True), clock=lambda: NOW)
    server = create_http_server(
        gateway,
        host="127.0.0.1",
        port=0,
        admin_token="admin-secret",
        trust_header_identity=True,
    )
    return server, store


def request_json(base, method, path, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(base + path, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def common_headers():
    return {
        "Content-Type": "application/json",
        "X-AIE-Verified-Spiffe-ID": "spiffe://example.org/agent/refund",
        "X-AIE-Identity-Verified": "true",
        "AIE-Mission-Id": "mission:refunds",
        "AIE-Authority-Lease": "lease:refund",
        "AIE-Budget-Cost": "1",
    }


def test_http_gateway_health_mcp_a2a_revocation_and_evidence(tmp_path):
    server, store = build_server(tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        status, payload = request_json(base, "GET", "/healthz")
        assert status == 200
        assert payload["status"] == "ok"

        headers = common_headers() | {
            "MCP-Protocol-Version": "2026-07-28",
            "Mcp-Method": "tools/call",
            "Mcp-Name": "refund_customer",
        }
        status, payload = request_json(
            base,
            "POST",
            "/mcp",
            {"jsonrpc": "2.0", "id": "mcp-http-1", "method": "tools/call", "params": {"name": "refund_customer", "arguments": {"secret": "x"}}},
            headers,
        )
        assert status == 200
        assert payload["status"] == "admitted"

        a2a_headers = common_headers() | {"A2A-Version": "1.0"}
        status, payload = request_json(
            base,
            "POST",
            "/a2a",
            {"jsonrpc": "2.0", "id": "a2a-http-1", "method": "message/send", "params": {"message": {"messageId": "msg-1", "parts": [{"kind": "text", "text": "secret"}]}}},
            a2a_headers,
        )
        assert status == 200
        assert payload["status"] == "admitted"

        status, payload = request_json(
            base,
            "POST",
            "/revocations",
            {"lease_id": "lease:refund"},
            {"Content-Type": "application/json", "Authorization": "Bearer admin-secret"},
        )
        assert status == 200
        assert payload["revoked"] == "lease:refund"

        status, payload = request_json(
            base,
            "POST",
            "/mcp",
            {"jsonrpc": "2.0", "id": "mcp-http-2", "method": "tools/call", "params": {"name": "refund_customer"}},
            headers,
        )
        assert status == 403
        assert payload["error_code"] == "AIE-AUTH-003"

        status, payload = request_json(
            base,
            "GET",
            "/evidence",
            headers={"Authorization": "Bearer admin-secret"},
        )
        assert status == 200
        assert len(payload["events"]) >= 3
        assert "secret" not in repr(payload["events"])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_management_routes_require_admin_token(tmp_path):
    server, _ = build_server(tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        status, _ = request_json(base, "GET", "/evidence")
        assert status == 401
        status, _ = request_json(base, "POST", "/revocations", {"lease_id": "lease:refund"}, {"Content-Type": "application/json"})
        assert status == 401
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
