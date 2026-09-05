import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from aie_runtime.engine import AuthorityLease, Mission, Principal
from aie_runtime.gateway.core import AIEGateway
from aie_runtime.gateway.durable import SQLiteGatewayStore
from aie_runtime.gateway.forwarding import HTTPUpstreamForwarder, UpstreamTransportError
from aie_runtime.gateway.identity import TransportIdentity
from aie_runtime.gateway.policy import LocalPolicyAdapter
from aie_runtime.store import InMemoryState

NOW = datetime(2026, 9, 3, 1, 0, tzinfo=timezone.utc)


def make_gateway(tmp_path):
    state = InMemoryState()
    state.principals["agent:refund"] = Principal("agent:refund", "agent", "spiffe://example.org/agent/refund")
    state.missions["mission:refunds"] = Mission("mission:refunds", "RUNNING")
    state.leases["lease:refund"] = AuthorityLease(
        id="lease:refund",
        principal_id="agent:refund",
        mission_id="mission:refunds",
        capabilities={"mcp.tools.call:refund_customer"},
        resource_prefixes=("mcp://tool/refund_customer",),
        expires_at=NOW + timedelta(hours=1),
        budget_remaining=10,
    )
    store = SQLiteGatewayStore(tmp_path / "gateway.db")
    return AIEGateway(
        state=state,
        store=store,
        policy=LocalPolicyAdapter(lambda _: True),
        clock=lambda: NOW,
    ), store


def headers():
    return {
        "MCP-Protocol-Version": "2026-07-28",
        "Mcp-Method": "tools/call",
        "Mcp-Name": "refund_customer",
        "AIE-Mission-Id": "mission:refunds",
        "AIE-Authority-Lease": "lease:refund",
        "AIE-Budget-Cost": "2",
        "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
    }


def body(action_id="fwd-1"):
    return {
        "jsonrpc": "2.0",
        "id": action_id,
        "method": "tools/call",
        "params": {"name": "refund_customer", "arguments": {"amount": 100}},
    }


class EchoHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        self.server.received = {
            "path": self.path,
            "headers": {k: v for k, v in self.headers.items()},
            "body": payload,
        }
        raw = json.dumps({"jsonrpc": "2.0", "id": payload["id"], "result": {"ok": True}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Upstream", "echo")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def test_admitted_request_is_forwarded_and_budget_commits_only_after_response(tmp_path):
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), EchoHandler)
    upstream.received = None
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    gateway, store = make_gateway(tmp_path)
    try:
        forwarder = HTTPUpstreamForwarder(f"http://127.0.0.1:{upstream.server_port}/mcp")
        result = gateway.forward(
            "mcp",
            headers(),
            body(),
            TransportIdentity("spiffe://example.org/agent/refund", True),
            forwarder,
        )
        assert result.decision.status == "admitted"
        assert result.upstream.status == 200
        assert json.loads(result.upstream.body)["result"]["ok"] is True
        assert upstream.received["body"]["params"]["arguments"]["amount"] == 100
        assert upstream.received["headers"]["Mcp-Method"] == "tools/call"
        assert {k.lower(): v for k, v in upstream.received["headers"].items()}["traceparent"] == headers()["traceparent"]
        assert "AIE-Authority-Lease" not in upstream.received["headers"]
        assert store.remaining_budget("lease:refund") == 8.0
        assert store.get_outcome("fwd-1")["status"] == "admitted"
    finally:
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=2)


def test_transport_failure_becomes_terminal_uncertain_and_is_not_blindly_replayed(tmp_path):
    gateway, store = make_gateway(tmp_path)

    class BrokenForwarder:
        def forward(self, *, protocol, headers, body):
            raise UpstreamTransportError("connection lost")

    first = gateway.forward(
        "mcp",
        headers(),
        body("fwd-uncertain"),
        TransportIdentity("spiffe://example.org/agent/refund", True),
        BrokenForwarder(),
    )
    second = gateway.forward(
        "mcp",
        headers(),
        body("fwd-uncertain"),
        TransportIdentity("spiffe://example.org/agent/refund", True),
        BrokenForwarder(),
    )
    assert first.decision.status == "uncertain"
    assert first.decision.error_code == "AIE-UPSTREAM-002"
    assert second.decision.status == "prior-outcome"
    assert store.remaining_budget("lease:refund") == 8.0
    assert store.reservation_state("fwd-uncertain") == "committed"


def test_upstream_identity_failure_is_deterministic_deny_and_rolls_back_budget(tmp_path):
    from aie_runtime.gateway.forwarding import UpstreamAuthenticationError

    gateway, store = make_gateway(tmp_path)

    class WrongPeerForwarder:
        def forward(self, *, protocol, headers, body):
            raise UpstreamAuthenticationError("unexpected SPIFFE ID")

    result = gateway.forward(
        "mcp",
        headers(),
        body("fwd-peer-deny"),
        TransportIdentity("spiffe://example.org/agent/refund", True),
        WrongPeerForwarder(),
    )
    assert result.decision.status == "denied"
    assert result.decision.error_code == "AIE-UPSTREAM-001"
    assert store.remaining_budget("lease:refund") == 10.0
    assert store.reservation_state("fwd-peer-deny") == "rolled_back"
