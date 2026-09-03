from __future__ import annotations

import json
import threading
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from aie_runtime.engine import AuthorityLease, Mission, Principal
from aie_runtime.gateway.core import AIEGateway
from aie_runtime.gateway.durable import SQLiteGatewayStore
from aie_runtime.gateway.forwarding import HTTPUpstreamForwarder
from aie_runtime.gateway.identity import TransportIdentity
from aie_runtime.gateway.policy import LocalPolicyAdapter
from aie_runtime.store import InMemoryState

NOW = datetime(2026, 9, 3, 1, 0, tzinfo=timezone.utc)


def make_gateway(tmp_path, *, bindings=None, protocol_passthrough_on_parse_error=False):
    state = InMemoryState()
    state.principals["p"] = Principal("p", "agent", "spiffe://example.org/client/conformance")
    state.missions["m"] = Mission("m", "active")
    state.leases["l"] = AuthorityLease(
        "l",
        "p",
        "m",
        {
            "mcp.tools.call:refund_customer",
            "mcp.server.discover",
            "mcp.transport.forward",
        },
        ("mcp://tool/refund_customer", "mcp://method/server/discover", "mcp://transport/http"),
        NOW + timedelta(hours=1),
        100,
    )
    return AIEGateway(
        state=state,
        store=SQLiteGatewayStore(tmp_path / "g.db"),
        policy=LocalPolicyAdapter(lambda _: True),
        clock=lambda: NOW,
        authority_bindings=bindings or {},
        protocol_passthrough_on_parse_error=protocol_passthrough_on_parse_error,
    )


def identity():
    return TransportIdentity("spiffe://example.org/client/conformance", verified=True, source="spiffe-mtls")


def mcp_body(action_id="s1-1"):
    return {
        "jsonrpc": "2.0",
        "id": action_id,
        "method": "tools/call",
        "params": {"name": "refund_customer", "arguments": {"amount": 1}},
        "_meta": {
            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientInfo": {"name": "official-conformance", "version": "test"},
            "io.modelcontextprotocol/clientCapabilities": {},
        },
    }


def mcp_headers():
    return {
        "MCP-Protocol-Version": "2026-07-28",
        "Mcp-Method": "tools/call",
        "Mcp-Name": "refund_customer",
    }


def test_mtls_identity_binding_allows_unmodified_official_mcp_request(tmp_path):
    gateway = make_gateway(
        tmp_path,
        bindings={"spiffe://example.org/client/conformance": ("m", "l")},
    )
    decision = gateway.handle("mcp", mcp_headers(), mcp_body(), identity())
    assert decision.status == "admitted"


def test_partial_explicit_authority_headers_do_not_fall_back_to_identity_binding(tmp_path):
    gateway = make_gateway(
        tmp_path,
        bindings={"spiffe://example.org/client/conformance": ("m", "l")},
    )
    headers = {**mcp_headers(), "AIE-Mission-Id": "m"}
    decision = gateway.handle("mcp", headers, mcp_body("s1-partial"), identity())
    assert decision.status == "denied"
    assert decision.error_code == "AIE-AUTH-001"


class HeaderEchoUpstream(BaseHTTPRequestHandler):
    received_headers = {}
    received_body = None

    def log_message(self, format, *args):
        return

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        type(self).received_headers = {k.lower(): v for k, v in self.headers.items()}
        type(self).received_body = json.loads(self.rfile.read(n))
        raw = json.dumps({"jsonrpc": "2.0", "id": type(self).received_body["id"], "result": {"ok": True}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-MCP-Upstream", "preserved")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def test_forwarder_is_mcp_semantically_transparent_but_strips_aie_headers():
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), HeaderEchoUpstream)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    try:
        forwarder = HTTPUpstreamForwarder(f"http://127.0.0.1:{upstream.server_port}/mcp")
        body = mcp_body("transparent-1")
        response = forwarder.forward(
            protocol="mcp",
            headers={
                **mcp_headers(),
                "Authorization": "Bearer mcp-token",
                "X-Custom-Conformance": "preserve-me",
                "Mcp-Param-Region": "eu",
                "AIE-Mission-Id": "m",
                "AIE-Authority-Lease": "l",
                "AIE-Budget-Cost": "4",
                "Connection": "close",
                "Host": "conformance.invalid",
            },
            body=body,
        )
        assert response.status == 200
        received = HeaderEchoUpstream.received_headers
        assert received["authorization"] == "Bearer mcp-token"
        assert received["x-custom-conformance"] == "preserve-me"
        assert received["mcp-param-region"] == "eu"
        assert "aie-mission-id" not in received
        assert "aie-authority-lease" not in received
        assert "aie-budget-cost" not in received
        assert received["host"] == "conformance.invalid"
        assert HeaderEchoUpstream.received_body == body
        assert response.headers["X-MCP-Upstream"] == "preserved"
    finally:
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=2)

class CaptureForwarder:
    def __init__(self):
        self.calls = []

    def forward(self, *, protocol, headers, body):
        from aie_runtime.gateway.forwarding import UpstreamResponse
        self.calls.append((protocol, dict(headers), dict(body)))
        return UpstreamResponse(400, b'{"jsonrpc":"2.0","id":"raw-1","error":{"code":-32600}}', {"Content-Type": "application/json"})


def test_protocol_parse_error_remains_fail_closed_by_default(tmp_path):
    gateway = make_gateway(
        tmp_path,
        bindings={"spiffe://example.org/client/conformance": ("m", "l")},
    )
    forwarder = CaptureForwarder()
    body = {"jsonrpc": "2.0", "id": "raw-1", "params": {}}
    result = gateway.forward("mcp", {}, body, identity(), forwarder)
    assert result.decision.status == "denied"
    assert result.decision.error_code == "AIE-PROTO-001"
    assert forwarder.calls == []


def test_opt_in_protocol_parse_error_passthrough_authorizes_transport_and_forwards_unchanged(tmp_path):
    gateway = make_gateway(
        tmp_path,
        bindings={"spiffe://example.org/client/conformance": ("m", "l")},
        protocol_passthrough_on_parse_error=True,
    )
    forwarder = CaptureForwarder()
    headers = {"Host": "conformance.invalid", "X-MCP-Custom": "preserve-me"}
    body = {"jsonrpc": "2.0", "id": "raw-1", "params": {}}
    result = gateway.forward("mcp", headers, body, identity(), forwarder)
    assert result.decision.status == "admitted"
    assert result.upstream is not None and result.upstream.status == 400
    assert forwarder.calls == [("mcp", headers, body)]


def test_opt_in_protocol_passthrough_uses_stable_synthetic_action_id_when_request_has_no_id(tmp_path):
    gateway = make_gateway(
        tmp_path,
        bindings={"spiffe://example.org/client/conformance": ("m", "l")},
        protocol_passthrough_on_parse_error=True,
    )
    forwarder = CaptureForwarder()
    body = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
    first = gateway.forward("mcp", {}, body, identity(), forwarder)
    second = gateway.forward("mcp", {}, body, identity(), forwarder)
    assert first.decision.status == "admitted"
    assert first.decision.action_id.startswith("raw-")
    assert second.decision.status == "prior-outcome"
    assert second.decision.action_id == first.decision.action_id
    assert len(forwarder.calls) == 1
