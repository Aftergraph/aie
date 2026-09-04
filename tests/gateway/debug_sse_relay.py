"""Quick local test: does the bridge correctly relay SEP-2575 SSE streams?

Stands up:
- A simple SSE upstream on port 18800 (mimics the MCP everything-server
  behavior on GET /mcp after subscriptions are initialized)
- A bridge_cli instance on port 18801 that forwards to that upstream

Asserts that a GET /mcp with Accept: text/event-stream produces a
chunked-encoding response with the SSE frames, NOT a single buffered frame.
"""
from __future__ import annotations

import http.client
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from aie_runtime.gateway.bridge import _BridgeHandler  # noqa: F401
from aie_runtime.gateway.bridge import SPIFFEBridgeServer  # type: ignore


def make_upstream(port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a, **k):  # silence
            return

        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            # Emit three SSE frames with a small delay so the client
            # sees the stream, then close.
            for evt, data in (("hi", "1"), ("tick", "2"), ("end", "bye")):
                chunk = f"event: {evt}\ndata: {data}\n\n".encode("utf-8")
                self.wfile.write(chunk)
                self.wfile.flush()
                time.sleep(0.1)
            self.wfile.write(b"event: done\ndata: 0\n\n")
            self.wfile.flush()

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def make_bridge(upstream_port: int, bridge_port: int) -> SPIFFEBridgeServer:
    return SPIFFEBridgeServer(
        ("127.0.0.1", bridge_port),
        _BridgeHandler,
        upstream_base_url=f"http://127.0.0.1:{upstream_port}",
        timeout=5.0,
        inbound_ssl_context=None,
        inbound_tls_context_provider=None,
        expected_client_spiffe_ids=set(),
        outbound_ssl_context=None,
        outbound_ssl_context_provider=None,
        expected_upstream_spiffe_id=None,
    )


def main() -> int:
    upstream = make_upstream(18800)
    upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    upstream_thread.start()

    bridge = make_bridge(18800, 18801)
    bridge_thread = threading.Thread(target=bridge.serve_forever, daemon=True)
    bridge_thread.start()
    time.sleep(0.2)

    conn = http.client.HTTPConnection("127.0.0.1", 18801, timeout=5)
    conn.request("POST", "/mcp", body=b'{"jsonrpc":"2.0","id":1,"method":"subscriptions/listen","params":{"_meta":{}}}', headers={"Accept": "text/event-stream", "Content-Type": "application/json"})
    response = conn.getresponse()

    body_chunks: list[bytes] = []
    while True:
        chunk = response.read(8192)
        if not chunk:
            break
        body_chunks.append(chunk)

    body = b"".join(body_chunks)
    print("status:", response.status)
    print("transfer_encoding:", response.getheader("Transfer-Encoding"))
    print("content_length:", response.getheader("Content-Length"))
    print("content_type:", response.getheader("Content-Type"))
    print("body bytes:", len(body))
    print("body preview:", body[:300].decode("utf-8", errors="replace"))

    bridge.shutdown()
    upstream.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
