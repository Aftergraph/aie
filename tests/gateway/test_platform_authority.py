import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone

from aie_runtime.gateway.core import AIEGateway
from aie_runtime.gateway.durable import SQLiteGatewayStore
from aie_runtime.gateway.http import create_http_server
from aie_runtime.gateway.policy import LocalPolicyAdapter
from aie_runtime.persistent_state import PersistentState

ORG_PRINCIPAL = "prn_" + "1" * 32
TENANT = "ten_" + "2" * 32
IDENTITY = "lume:access-sub-sha256:" + "3" * 64
PROFILE = {
    "issuer": "system:aftergraph-platform",
    "mission_id": "mis_lume_computer",
    "capabilities": ["computer"],
    "resource_prefixes": ["lume://computer/"],
    "budget": 100.0,
    "ttl_seconds": 3600,
}


def request_json(base, path, body, token="admin-secret"):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=2) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def build(tmp_path):
    state_path = tmp_path / "authority-state.db"
    state = PersistentState(db_path=str(state_path))
    gateway = AIEGateway(
        state=state,
        store=SQLiteGatewayStore(tmp_path / "gateway.db"),
        policy=LocalPolicyAdapter(lambda _: True),
        clock=lambda: datetime(2026, 10, 6, 19, 0, tzinfo=timezone.utc),
        platform_authority_profile=PROFILE,
    )
    server = create_http_server(
        gateway,
        host="127.0.0.1",
        port=0,
        admin_token="admin-secret",
        trust_header_identity=False,
    )
    return server, state_path


def test_platform_authority_ensure_is_admin_only_idempotent_and_persistent(tmp_path):
    server, state_path = build(tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    body = {
        "principal_id": ORG_PRINCIPAL,
        "tenant_id": TENANT,
        "identity_ref": IDENTITY,
        "idempotency_key": "lume-owner-computer-v1",
    }
    try:
        status, out = request_json(base, "/v1/platform-authority/ensure", body, token="wrong")
        assert status == 401

        status, first = request_json(base, "/v1/platform-authority/ensure", body)
        assert status == 200
        assert first["schema"] == "aie.platform-authority/1.0"
        assert first["authority_lease_id"].startswith("auth_")
        assert len(first["authority_lease_id"]) == len("auth_") + 32

        status, second = request_json(base, "/v1/platform-authority/ensure", body)
        assert status == 200
        assert second["authority_lease_id"] == first["authority_lease_id"]

        reopened = PersistentState(db_path=str(state_path))
        principal = reopened.principals.get(ORG_PRINCIPAL)
        lease = reopened.leases.get(first["authority_lease_id"])
        assert principal is not None
        assert principal.identity_ref == IDENTITY
        assert lease is not None
        assert lease.principal_id == ORG_PRINCIPAL
        assert lease.mission_id == PROFILE["mission_id"]
        assert lease.capabilities == {"computer"}
        assert lease.resource_prefixes == ("lume://computer/",)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_platform_authority_ensure_rejects_identity_rebind_and_scope_smuggling(tmp_path):
    server, _ = build(tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    body = {
        "principal_id": ORG_PRINCIPAL,
        "tenant_id": TENANT,
        "identity_ref": IDENTITY,
        "idempotency_key": "lume-owner-computer-v1",
    }
    try:
        assert request_json(base, "/v1/platform-authority/ensure", body)[0] == 200

        status, out = request_json(
            base,
            "/v1/platform-authority/ensure",
            {**body, "identity_ref": "lume:access-sub-sha256:" + "4" * 64},
        )
        assert status == 409
        assert out["error"] == "principal_rebind"

        status, out = request_json(
            base,
            "/v1/platform-authority/ensure",
            {**body, "capabilities": ["*"]},
        )
        assert status == 400
        assert out["error"] == "invalid_request"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
