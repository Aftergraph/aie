import json
import ssl
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

from aie_runtime.engine import AuthorityLease, Mission, Principal
from aie_runtime.gateway.core import AIEGateway
from aie_runtime.gateway.durable import SQLiteGatewayStore
from aie_runtime.gateway.http import create_http_server
from aie_runtime.gateway.policy import LocalPolicyAdapter
from aie_runtime.gateway.tls import build_client_ssl_context, build_server_ssl_context
from aie_runtime.store import InMemoryState
from tls_material import issue_test_pki

NOW = datetime(2026, 9, 3, 1, 0, tzinfo=timezone.utc)


def build_gateway(tmp_path):
    state = InMemoryState()
    state.principals["agent:refund"] = Principal("agent:refund", "agent", "spiffe://example.org/agent/refund")
    state.missions["mission:refunds"] = Mission("mission:refunds", "active")
    state.leases["lease:refund"] = AuthorityLease(
        id="lease:refund",
        principal_id="agent:refund",
        mission_id="mission:refunds",
        capabilities={"mcp.tools.call:refund_customer"},
        resource_prefixes=("mcp://tool/refund_customer",),
        expires_at=NOW + timedelta(hours=1),
        budget_remaining=10,
    )
    return AIEGateway(
        state=state,
        store=SQLiteGatewayStore(tmp_path / "gateway.db"),
        policy=LocalPolicyAdapter(lambda _: True),
        clock=lambda: NOW,
    )


def request(base, context):
    body = {"jsonrpc": "2.0", "id": "mtls-1", "method": "tools/call", "params": {"name": "refund_customer"}}
    headers = {
        "Content-Type": "application/json",
        "MCP-Protocol-Version": "2026-07-28",
        "Mcp-Method": "tools/call",
        "Mcp-Name": "refund_customer",
        "AIE-Mission-Id": "mission:refunds",
        "AIE-Authority-Lease": "lease:refund",
    }
    req = urllib.request.Request(base + "/mcp", data=json.dumps(body).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=3, context=context) as response:
        return response.status, json.loads(response.read())


def test_https_gateway_uses_verified_client_certificate_spiffe_identity(tmp_path):
    pki = issue_test_pki(tmp_path / "pki")
    server_ctx = build_server_ssl_context(
        certfile=pki["gw_a_crt"], keyfile=pki["gw_a_key"], cafile=pki["ca"], require_client_cert=True
    )
    server = create_http_server(
        build_gateway(tmp_path), host="127.0.0.1", port=0, admin_token="admin", ssl_context=server_ctx
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"https://127.0.0.1:{server.server_port}"
    try:
        no_client_ctx = ssl.create_default_context(cafile=str(pki["ca"]))
        no_client_ctx.check_hostname = False
        with pytest.raises(Exception):
            request(base, no_client_ctx)

        client_ctx = build_client_ssl_context(certfile=pki["agent_crt"], keyfile=pki["agent_key"], cafile=pki["ca"])
        status, payload = request(base, client_ctx)
        assert status == 200
        assert payload["status"] == "admitted"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
