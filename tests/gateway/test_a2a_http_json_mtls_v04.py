import json
import ssl
import threading
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from aie_runtime.engine import AuthorityLease, Mission, Principal
from aie_runtime.gateway.a2a_http_json import A2AHTTPJSONForwarder, create_a2a_http_json_server
from aie_runtime.gateway.core import AIEGateway
from aie_runtime.gateway.durable import SQLiteGatewayStore
from aie_runtime.gateway.policy import LocalPolicyAdapter
from aie_runtime.gateway.tls import build_client_ssl_context, build_server_ssl_context
from aie_runtime.store import InMemoryState
from tls_material import issue_test_pki

NOW = datetime(2026, 9, 3, 1, 0, tzinfo=timezone.utc)


class Upstream(BaseHTTPRequestHandler):
    seen = 0

    def log_message(self, *args):
        return

    def do_POST(self):
        type(self).seen += 1
        length = int(self.headers.get("Content-Length", "0"))
        if length:
            self.rfile.read(length)
        payload = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def test_http_json_binding_uses_real_mtls_spiffe_identity(tmp_path):
    pki = issue_test_pki(tmp_path / "pki")
    state = InMemoryState()
    state.principals["p"] = Principal("p", "agent", "spiffe://example.org/agent/refund")
    state.missions["m"] = Mission("m", "RUNNING")
    state.leases["l"] = AuthorityLease(
        "l",
        "p",
        "m",
        {"a2a.message.send"},
        ("a2a://message/",),
        NOW + timedelta(hours=1),
        10,
    )
    gateway = AIEGateway(
        state=state,
        store=SQLiteGatewayStore(tmp_path / "mtls.db"),
        policy=LocalPolicyAdapter(lambda _: True),
        clock=lambda: NOW,
    )
    Upstream.seen = 0
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    server_context = build_server_ssl_context(
        certfile=pki["gw_a_crt"],
        keyfile=pki["gw_a_key"],
        cafile=pki["ca"],
        require_client_cert=True,
    )
    server = create_a2a_http_json_server(
        gateway,
        A2AHTTPJSONForwarder(f"http://127.0.0.1:{upstream.server_port}/api"),
        ssl_context=server_context,
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"https://127.0.0.1:{server.server_port}/message:send"
    body = json.dumps({"message": {"messageId": "mtls-1"}}).encode()
    headers = {
        "AIE-Mission-Id": "m",
        "AIE-Authority-Lease": "l",
        "A2A-Version": "1.0",
        "Content-Type": "application/json",
    }
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        no_client = ssl.create_default_context(cafile=str(pki["ca"]))
        no_client.check_hostname = False
        with pytest.raises(Exception):
            urllib.request.urlopen(request, timeout=2, context=no_client)

        client = build_client_ssl_context(
            certfile=pki["agent_crt"],
            keyfile=pki["agent_key"],
            cafile=pki["ca"],
        )
        with urllib.request.urlopen(request, timeout=2, context=client) as response:
            assert response.status == 200
        assert Upstream.seen == 1
    finally:
        server.shutdown()
        upstream.shutdown()
