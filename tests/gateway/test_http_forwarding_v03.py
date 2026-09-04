import http.client
import json
import threading
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from aie_runtime.engine import AuthorityLease, Mission, Principal
from aie_runtime.gateway.core import AIEGateway
from aie_runtime.gateway.durable import SQLiteGatewayStore
from aie_runtime.gateway.forwarding import HTTPUpstreamForwarder
from aie_runtime.gateway.http import create_http_server
from aie_runtime.gateway.policy import LocalPolicyAdapter
from aie_runtime.store import InMemoryState

NOW = datetime(2026, 9, 3, 1, 0, tzinfo=timezone.utc)


class Upstream(BaseHTTPRequestHandler):
    def log_message(self, format, *args): return
    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(n))
        raw = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": {"forwarded": True}}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        # SEP-2575 standalone SSE stream: emit three frames, then end.
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        for frame in (b"event: open\ndata: hi\n\n", b"event: tick\ndata: 1\n\n", b"event: end\ndata: bye\n\n"):
            self.wfile.write(frame)
            self.wfile.flush()
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()


def gateway(tmp_path):
    state = InMemoryState()
    state.principals["p"] = Principal("p", "agent", "spiffe://example.org/agent/refund")
    state.missions["m"] = Mission("m", "active")
    state.leases["l"] = AuthorityLease("l", "p", "m", {"mcp.tools.call:refund_customer", "a2a.message.send"}, ("mcp://tool/refund_customer", "a2a://message/"), NOW + timedelta(hours=1), 10)
    return AIEGateway(state=state, store=SQLiteGatewayStore(tmp_path / "g.db"), policy=LocalPolicyAdapter(lambda _: True), clock=lambda: NOW)


def test_http_surface_returns_real_upstream_response_after_admission(tmp_path):
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    ut = threading.Thread(target=upstream.serve_forever, daemon=True); ut.start()
    server = create_http_server(
        gateway(tmp_path), host="127.0.0.1", port=0, admin_token="admin", trust_header_identity=True,
        forwarders={"mcp": HTTPUpstreamForwarder(f"http://127.0.0.1:{upstream.server_port}/")},
    )
    gt = threading.Thread(target=server.serve_forever, daemon=True); gt.start()
    try:
        body = {"jsonrpc": "2.0", "id": "proxy-1", "method": "tools/call", "params": {"name": "refund_customer"}}
        headers = {
            "Content-Type": "application/json", "X-AIE-Verified-Spiffe-ID": "spiffe://example.org/agent/refund", "X-AIE-Identity-Verified": "true",
            "MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "tools/call", "Mcp-Name": "refund_customer",
            "AIE-Mission-Id": "m", "AIE-Authority-Lease": "l",
        }
        req = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/mcp", data=json.dumps(body).encode(), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=3) as response:
            payload = json.loads(response.read())
            assert response.status == 200
            assert payload["result"]["forwarded"] is True
    finally:
        server.shutdown(); server.server_close(); upstream.shutdown(); upstream.server_close(); gt.join(timeout=2); ut.join(timeout=2)


def test_http_surface_forwards_a2a_1_0_response_after_same_aie_admission(tmp_path):
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    ut = threading.Thread(target=upstream.serve_forever, daemon=True); ut.start()
    server = create_http_server(
        gateway(tmp_path), host="127.0.0.1", port=0, admin_token="admin", trust_header_identity=True,
        forwarders={"a2a": HTTPUpstreamForwarder(f"http://127.0.0.1:{upstream.server_port}/")},
    )
    gt = threading.Thread(target=server.serve_forever, daemon=True); gt.start()
    try:
        body = {"jsonrpc": "2.0", "id": "a2a-proxy-1", "method": "message/send", "params": {"message": {"messageId": "msg-1", "parts": [{"kind": "text", "text": "hello"}]}}}
        headers = {
            "Content-Type": "application/json", "X-AIE-Verified-Spiffe-ID": "spiffe://example.org/agent/refund", "X-AIE-Identity-Verified": "true",
            "A2A-Version": "1.0", "AIE-Mission-Id": "m", "AIE-Authority-Lease": "l",
        }
        req = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/a2a", data=json.dumps(body).encode(), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=3) as response:
            payload = json.loads(response.read())
            assert response.status == 200
            assert payload["result"]["forwarded"] is True
    finally:
        server.shutdown(); server.server_close(); upstream.shutdown(); upstream.server_close(); gt.join(timeout=2); ut.join(timeout=2)


def test_http_surface_relays_get_mcp_as_chunked_sse_stream(tmp_path):
    # ponytail: GET /mcp opens the SEP-2575 standalone SSE stream. The
    # gateway must relay the upstream text/event-stream response as
    # chunked transfer-encoding, not buffer it into a single Content-Length
    # frame. Without this, notifications/subscriptions/listen hangs and the
    # conformance client times out.
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    ut = threading.Thread(target=upstream.serve_forever, daemon=True); ut.start()
    server = create_http_server(
        gateway(tmp_path), host="127.0.0.1", port=0, admin_token="admin", trust_header_identity=True,
        forwarders={"mcp": HTTPUpstreamForwarder(f"http://127.0.0.1:{upstream.server_port}/")},
    )
    gt = threading.Thread(target=server.serve_forever, daemon=True); gt.start()
    try:
        # Use a raw HTTP connection so we can verify Transfer-Encoding on
        # the wire rather than letting urllib collapse it for us.
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        conn.request("GET", "/mcp", headers={"Accept": "text/event-stream"})
        response = conn.getresponse()
        assert response.status == 200
        assert response.getheader("Content-Type", "").startswith("text/event-stream")
        assert response.getheader("Transfer-Encoding", "").lower() == "chunked"
        body = response.read()
        assert body.startswith(b"event: open\ndata: hi\n\n")
        assert b"event: tick\ndata: 1\n\n" in body
        assert body.endswith(b"0\r\n\r\n")
    finally:
        server.shutdown(); server.server_close(); upstream.shutdown(); upstream.server_close(); gt.join(timeout=2); ut.join(timeout=2)
