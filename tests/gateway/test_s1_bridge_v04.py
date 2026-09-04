from __future__ import annotations

import http.client
import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from aie_runtime.gateway.bridge import create_spiffe_bridge
from aie_runtime.gateway.tls import build_client_ssl_context, build_server_ssl_context
from tls_material import issue_test_pki


class _EchoHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def _reply(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        payload = json.dumps({
            "method": self.command,
            "path": self.path,
            "custom": self.headers.get("X-MCP-Custom"),
            "host": self.headers.get("Host"),
            "body": body.decode("utf-8"),
        }).encode("utf-8")
        self.send_response(207)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Upstream", "echo")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    do_GET = _reply
    do_POST = _reply
    do_DELETE = _reply


def _serve(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def test_plain_client_bridge_forwards_arbitrary_method_path_headers_and_body_over_spiffe_mtls(tmp_path):
    pki = issue_test_pki(tmp_path / "pki")
    upstream_tls = build_server_ssl_context(
        certfile=pki["gw_b_crt"], keyfile=pki["gw_b_key"], cafile=pki["ca"], require_client_cert=True
    )
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), _EchoHandler)
    upstream.socket = upstream_tls.wrap_socket(upstream.socket, server_side=True)
    _serve(upstream)

    outbound = build_client_ssl_context(
        certfile=pki["gw_a_crt"], keyfile=pki["gw_a_key"], cafile=pki["ca"]
    )
    bridge = create_spiffe_bridge(
        upstream_base_url=f"https://127.0.0.1:{upstream.server_port}",
        host="127.0.0.1",
        port=0,
        outbound_ssl_context=outbound,
        expected_upstream_spiffe_id="spiffe://example.org/gateway/b",
    )
    _serve(bridge)
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{bridge.server_port}/mcp?x=1",
            data=b'{"hello":"world"}',
            method="DELETE",
            headers={"Content-Type": "application/json", "X-MCP-Custom": "preserve-me", "AIE-Secret": "drop-me", "Host": "conformance.invalid"},
        )
        with urllib.request.urlopen(req, timeout=3) as response:
            payload = json.loads(response.read())
            assert response.status == 207
            assert response.headers["X-Upstream"] == "echo"
        assert payload == {
            "method": "DELETE",
            "path": "/mcp?x=1",
            "custom": "preserve-me",
            "host": "conformance.invalid",
            "body": '{"hello":"world"}',
        }
    finally:
        bridge.shutdown(); bridge.server_close()
        upstream.shutdown(); upstream.server_close()


def test_server_bridge_enforces_expected_inbound_spiffe_identity(tmp_path):
    pki = issue_test_pki(tmp_path / "pki")
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), _EchoHandler)
    _serve(upstream)

    inbound_tls = build_server_ssl_context(
        certfile=pki["gw_b_crt"], keyfile=pki["gw_b_key"], cafile=pki["ca"], require_client_cert=True
    )
    bridge = create_spiffe_bridge(
        upstream_base_url=f"http://127.0.0.1:{upstream.server_port}",
        host="127.0.0.1",
        port=0,
        inbound_ssl_context=inbound_tls,
        expected_client_spiffe_ids={"spiffe://example.org/gateway/a"},
    )
    _serve(bridge)
    good = build_client_ssl_context(certfile=pki["gw_a_crt"], keyfile=pki["gw_a_key"], cafile=pki["ca"])
    wrong = build_client_ssl_context(certfile=pki["agent_crt"], keyfile=pki["agent_key"], cafile=pki["ca"])
    try:
        req = urllib.request.Request(f"https://127.0.0.1:{bridge.server_port}/mcp", data=b"{}", method="POST")
        with urllib.request.urlopen(req, context=good, timeout=3) as response:
            assert response.status == 207
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, context=wrong, timeout=3)
        assert exc.value.code == 403
    finally:
        bridge.shutdown(); bridge.server_close()
        upstream.shutdown(); upstream.server_close()


class _SseUpstream(BaseHTTPRequestHandler):
    """Upstream that emits an SSE event stream over three flushes, then a
    terminal zero-length chunk that closes the stream. Used to verify the
    bridge relays text/event-stream responses as chunked transfer-encoding
    rather than buffering them into a single Content-Length frame.
    """
    daemon = True

    def log_message(self, format, *args):  # noqa: A003
        return

    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        # NB: no Content-Length, no Transfer-Encoding: upstream uses chunked
        # transfer-encoding for an indefinite stream. The bridge must preserve
        # this when relaying to its client.
        self.end_headers()
        for frame in (b"event: open\ndata: hi\n\n", b"event: tick\ndata: 1\n\n", b"event: end\ndata: bye\n\n"):
            self.wfile.write(frame)
            self.wfile.flush()
        # Conclude the upstream chunked stream.
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()


def test_bridge_relays_sse_responses_as_chunked_transfer_encoding(tmp_path):
    # ponytail: bridge with no SPIFFE outbound verification streams a
    # text/event-stream upstream response as chunked transfer-encoding to the
    # client. With SPIFFE verification enabled, the same code path uses
    # request_stream_with_peer_identity and is covered by the SPIFFE-aware
    # tests above; this test exercises the plain HTTP streaming path.
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), _SseUpstream)
    _serve(upstream)

    bridge = create_spiffe_bridge(
        upstream_base_url=f"http://127.0.0.1:{upstream.server_port}",
        host="127.0.0.1",
        port=0,
    )
    _serve(bridge)
    try:
        # Read the response with a raw HTTP client so we can inspect the
        # transfer-encoding and chunked framing on the wire.
        conn = http.client.HTTPConnection("127.0.0.1", bridge.server_port, timeout=3)
        conn.request("GET", "/mcp", headers={"Accept": "text/event-stream"})
        response = conn.getresponse()
        assert response.status == 200
        assert response.getheader("Content-Type", "").startswith("text/event-stream")
        assert response.getheader("Transfer-Encoding", "").lower() == "chunked"
        # No Content-Length should be set on a chunked response.
        assert response.getheader("Content-Length") is None
        # Drain the chunked stream. http.client decodes the chunked framing
        # for us: each upstream SSE frame becomes one chunk in the response,
        # and the bridge's outgoing chunked terminator (0\r\n\r\n) appears at
        # the end of body.
        body = response.read()
        assert body.startswith(b"event: open\ndata: hi\n\n")
        assert b"event: tick\ndata: 1\n\n" in body
        assert b"event: end\ndata: bye\n\n" in body
        assert body.endswith(b"0\r\n\r\n")
    finally:
        bridge.shutdown(); bridge.server_close()
        upstream.shutdown(); upstream.server_close()
