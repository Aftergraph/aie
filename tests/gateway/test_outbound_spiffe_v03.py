import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from aie_runtime.errors import AIEError
from aie_runtime.gateway.spiffe_http import post_bytes_with_peer_identity
from aie_runtime.gateway.tls import build_client_ssl_context, build_server_ssl_context
from tls_material import issue_test_pki


class QuietServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        return


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args): return
    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0")); self.rfile.read(n)
        raw = b'{"ok":true}'
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)


def test_outbound_https_verifies_expected_peer_spiffe_uri_san(tmp_path):
    pki = issue_test_pki(tmp_path / "pki")
    server_ctx = build_server_ssl_context(certfile=pki["gw_b_crt"], keyfile=pki["gw_b_key"], cafile=pki["ca"], require_client_cert=True)
    server = QuietServer(("127.0.0.1", 0), Handler)
    server.socket = server_ctx.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    client_ctx = build_client_ssl_context(certfile=pki["gw_a_crt"], keyfile=pki["gw_a_key"], cafile=pki["ca"])
    try:
        status, body, _ = post_bytes_with_peer_identity(
            f"https://127.0.0.1:{server.server_port}/x", b"{}", {"Content-Type": "application/json"},
            timeout=3, ssl_context=client_ctx, expected_peer_spiffe_id="spiffe://example.org/gateway/b",
        )
        assert status == 200
        assert body == b'{"ok":true}'
        with pytest.raises(AIEError) as exc:
            post_bytes_with_peer_identity(
                f"https://127.0.0.1:{server.server_port}/x", b"{}", {"Content-Type": "application/json"},
                timeout=3, ssl_context=client_ctx, expected_peer_spiffe_id="spiffe://example.org/gateway/other",
            )
        assert exc.value.code == "AIE-IDENT-002"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
