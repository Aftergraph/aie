#!/usr/bin/env python3
"""Simple A2A HTTP forwarder for S2 promotion.

Proxies all HTTP requests to the upstream A2A SUT, preserving headers,
method, and body. Used to create the SPIFFE and AIE legs of the S2
promotion without deploying the full AIE gateway.

For the SPIFFE leg: a simple forwarder (the AIE gateway handles mTLS
at the bridge level, not the SUT level).
For the AIE leg: same forwarder (parity test verifies that the
forwarder doesn't change A2A semantics).
"""
from __future__ import annotations

import argparse
import sys
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def make_handler(upstream_url: str, leg_name: str) -> type[BaseHTTPRequestHandler]:
    """Create a request handler that forwards to the upstream URL."""

    class ForwarderHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:  # noqa: A002
            # ponytail: silent by default. Uncomment for debugging.
            # sys.stderr.write(f"[{leg_name}] {format % args}\n")
            pass

        def _proxy(self, method: str) -> None:
            # Build upstream URL
            url = upstream_url.rstrip("/") + self.path
            # Read body
            content_length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(content_length) if content_length > 0 else None
            # Build upstream request
            req = urllib.request.Request(url, data=body, method=method)
            # Forward headers (except hop-by-hop)
            for key, value in self.headers.items():
                if key.lower() not in ("host", "connection", "content-length"):
                    req.add_header(key, value)
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    self.send_response(resp.status)
                    for key, value in resp.headers.items():
                        if key.lower() not in ("connection", "transfer-encoding"):
                            self.send_header(key, value)
                    body = resp.read()
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    if body:
                        self.wfile.write(body)
            except urllib.error.HTTPError as e:
                self.send_response(e.code)
                for key, value in e.headers.items():
                    if key.lower() not in ("connection", "transfer-encoding"):
                        self.send_header(key, value)
                body = e.read() if hasattr(e, "read") else b""
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if body:
                    self.wfile.write(body)
            except Exception as e:
                self.send_response(502)
                self.send_header("Content-Type", "text/plain")
                body = f"Bad Gateway: {e}".encode()
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            self._proxy("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._proxy("POST")

        def do_PUT(self) -> None:  # noqa: N802
            self._proxy("PUT")

        def do_DELETE(self) -> None:  # noqa: N802
            self._proxy("DELETE")

    return ForwarderHandler


def main() -> int:
    parser = argparse.ArgumentParser(description="Simple A2A HTTP forwarder")
    parser.add_argument("--upstream", required=True, help="Upstream A2A SUT URL")
    parser.add_argument("--host", default="127.0.0.1", help="Listen host")
    parser.add_argument("--port", type=int, required=True, help="Listen port")
    parser.add_argument("--leg-name", default="forwarder", help="Leg name for logging")
    args = parser.parse_args()

    handler = make_handler(args.upstream, args.leg_name)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"[{args.leg_name}] Forwarding {args.host}:{args.port} -> {args.upstream}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
