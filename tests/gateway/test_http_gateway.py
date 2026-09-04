import http.client
import json
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

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


def test_gateway_get_mcp_streams_text_event_stream_as_chunked_and_terminates(tmp_path):
    """GET /mcp is the SEP-2575 notifications/subscriptions/listen path.

    The upstream keeps the stream open after the initial ack and produces a
    second SSE frame. The gateway must relay every frame as a chunked body
    and finish with the `0\\r\\n\\r\\n` terminator. Regression: the previous
    `if not chunk: continue` loop blocked forever on the upstream's chunked
    terminator and never wrote the trailing `0\\r\\n\\r\\n`, so the SEP-2575
    conformance client timed out waiting for the rest of the stream.
    """
    from aie_runtime.gateway.forwarding import UpstreamStreamResponse

    @dataclass
    class StubStream:
        # ponytail: simulate a real chunked-HTTP upstream. The first two
        # non-empty frames are the SEP-2575 ack and the post-subscription
        # tools/list_changed notification. The third read returns b""
        # (the chunked-encoding terminator `0\r\n\r\n`); the next read
        # blocks because the upstream has nothing more to send. The
        # previous bug (`if not chunk: continue`) loops on the b"" and
        # then blocks forever on the next read; the fix breaks out so the
        # gateway can write its own 0-length terminator and close the body.
        chunks: list[bytes]
        index: int = 0

        def __iter__(self):
            return self

        def __next__(self) -> bytes:
            if self.index >= len(self.chunks):
                # ponytail: match the real upstream's behavior after the
                # chunked terminator — block instead of StopIteration so
                # the `continue`-vs-`break` regression is observable.
                import time
                time.sleep(60)
                raise AssertionError("stub stream should not be drained past the terminator")
            value = self.chunks[self.index]
            self.index += 1
            return value

        def close(self) -> None:
            pass

    class StubForwarder:
        def forward(self, *, protocol: str, headers, body):
            raise AssertionError("forward should not be called on the GET /mcp SSE path")

        def forward_stream(self, *, method: str, headers, body):
            assert method == "GET"
            frame_one = b"event: message\ndata: {\"jsonrpc\":\"2.0\",\"method\":\"notifications/subscriptions/ack\"}\n\n"
            frame_two = b"event: message\ndata: {\"jsonrpc\":\"2.0\",\"method\":\"notifications/tools/list_changed\"}\n\n"
            # ponytail: the trailing b"" is the upstream's chunked-encoding
            # terminator (`0\r\n\r\n` rendered as an empty read). With the
            # old `if not chunk: continue` bug, the relay hung here and
            # never wrote its own body terminator to the client.
            return UpstreamStreamResponse(
                status=200,
                headers={"Content-Type": "text/event-stream"},
                stream=StubStream([frame_one, frame_two, b""]),
            )

    server, _ = build_server(tmp_path)
    server.forwarders["mcp"] = StubForwarder()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    raw = b""
    sock = None
    try:
        # Use a raw socket so we can inspect the chunked-encoded body
        # verbatim. http.client dechunks automatically on read(); we need
        # the on-wire form to confirm the gateway wrote the 0-length
        # terminator (the regression was that it never did).
        import socket
        sock = socket.create_connection(("127.0.0.1", server.server_port), timeout=5)
        request = (
            b"GET /mcp HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
            b"X-AIE-Verified-Spiffe-ID: spiffe://example.org/agent/refund\r\n"
            b"X-AIE-Identity-Verified: true\r\n"
            b"Connection: close\r\n\r\n"
        )
        sock.sendall(request)
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            raw += chunk
    finally:
        if sock is not None:
            sock.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    # ponytail: the gateway must produce well-formed chunked-encoding:
    # each SSE frame becomes a length-prefixed chunk and the body ends
    # with the mandatory 0-length terminator followed by CRLFCRLF.
    head, _, body = raw.partition(b"\r\n\r\n")
    assert b"200 OK" in head, f"expected 200 OK status line, got head: {head!r}"
    assert b"Transfer-Encoding: chunked" in head, f"expected chunked header, got head: {head!r}"
    assert b"event: message" in body, f"expected at least one SSE frame in body, got: {body!r}"
    assert body.endswith(b"0\r\n\r\n"), f"body must end with chunked terminator, got: {body!r}"


def test_gateway_post_mcp_subscriptions_listen_streams_response_as_chunked(tmp_path):
    """POST /mcp with `subscriptions/listen` is the SEP-2575 stream path.

    The request is a JSON-RPC method call whose response IS the SSE stream
    (the ack is the first frame). The gateway must relay the upstream's
    chunked-encoded stream instead of buffering it into a single
    Content-Length body. Regression: the previous `do_POST` path called
    `forward()` which buffers, so the conformance client saw a single
    buffered response and reported "Failed to open or receive frames
    from the subscriptions/listen stream endpoint".
    """
    from aie_runtime.gateway.forwarding import UpstreamStreamResponse

    @dataclass
    class StubStream:
        chunks: list[bytes]
        index: int = 0

        def __iter__(self):
            return self

        def __next__(self) -> bytes:
            if self.index >= len(self.chunks):
                import time
                time.sleep(60)
                raise AssertionError("stub stream should not be drained past the terminator")
            value = self.chunks[self.index]
            self.index += 1
            return value

        def close(self) -> None:
            pass

    class StubForwarder:
        def __init__(self):
            self.received_method = None
            self.received_body = None

        def forward(self, *, protocol, headers, body):
            raise AssertionError("forward (buffered) should not be called for subscriptions/listen")

        def forward_stream(self, *, method, headers, body):
            self.received_method = method
            self.received_body = body
            frame_one = b"event: message\ndata: {\"jsonrpc\":\"2.0\",\"method\":\"notifications/subscriptions/acknowledged\",\"params\":{\"_meta\":{\"io.modelcontextprotocol/subscriptionId\":\"listen-1\"}}}\n\n"
            frame_two = b"event: message\ndata: {\"jsonrpc\":\"2.0\",\"method\":\"notifications/tools/list_changed\"}\n\n"
            return UpstreamStreamResponse(
                status=200,
                headers={"Content-Type": "text/event-stream"},
                stream=StubStream([frame_one, frame_two, b""]),
            )

    server, _ = build_server(tmp_path)
    stub = StubForwarder()
    server.forwarders["mcp"] = stub
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    raw = b""
    sock = None
    try:
        import socket
        import json as _json
        sock = socket.create_connection(("127.0.0.1", server.server_port), timeout=5)
        request_body = _json.dumps({
            "jsonrpc": "2.0",
            "id": "listen-1",
            "method": "subscriptions/listen",
            "params": {"notifications": {"toolsListChanged": True}},
        }).encode("utf-8")
        request = (
            b"POST /mcp HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: " + str(len(request_body)).encode() + b"\r\n"
            b"X-AIE-Verified-Spiffe-ID: spiffe://example.org/agent/refund\r\n"
            b"X-AIE-Identity-Verified: true\r\n"
            b"Connection: close\r\n\r\n"
        ) + request_body
        sock.sendall(request)
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            raw += chunk
    finally:
        if sock is not None:
            sock.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    head, _, body = raw.partition(b"\r\n\r\n")
    assert b"200 OK" in head, f"expected 200 OK, got head: {head!r}"
    assert b"Transfer-Encoding: chunked" in head, f"expected chunked response, got head: {head!r}"
    assert b"event: message" in body, f"expected SSE frames in body, got: {body!r}"
    assert body.endswith(b"0\r\n\r\n"), f"body must end with chunked terminator, got: {body!r}"
    # The forward_stream path must have been called (not the buffered forward).
    assert stub.received_method == "POST"
    assert stub.received_body.get("method") == "subscriptions/listen"
