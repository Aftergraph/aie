import threading
from datetime import datetime, timezone

from aie_runtime.gateway.durable import SQLiteGatewayStore
from aie_runtime.gateway.federation import RevocationReplicator
from aie_runtime.gateway.http import create_http_server
from aie_runtime.gateway.policy import LocalPolicyAdapter
from aie_runtime.gateway.core import AIEGateway
from aie_runtime.gateway.tls import build_client_ssl_context, build_server_ssl_context
from aie_runtime.store import InMemoryState
from tls_material import issue_test_pki


def test_revocation_propagates_between_gateways_over_mutual_tls(tmp_path):
    pki = issue_test_pki(tmp_path / "pki")
    store_b = SQLiteGatewayStore(tmp_path / "b.db")
    gateway_b = AIEGateway(state=InMemoryState(), store=store_b, policy=LocalPolicyAdapter(lambda _: True))
    server_ctx = build_server_ssl_context(certfile=pki["gw_b_crt"], keyfile=pki["gw_b_key"], cafile=pki["ca"], require_client_cert=True)
    server_b = create_http_server(
        gateway_b, host="127.0.0.1", port=0, admin_token="admin", ssl_context=server_ctx,
        federation_trust={"spiffe://example.org/gateway/a"},
    )
    thread = threading.Thread(target=server_b.serve_forever, daemon=True); thread.start()
    try:
        client_ctx = build_client_ssl_context(certfile=pki["gw_a_crt"], keyfile=pki["gw_a_key"], cafile=pki["ca"])
        replicator = RevocationReplicator(
            [f"https://127.0.0.1:{server_b.server_port}/federation/revocations"],
            source_gateway="spiffe://example.org/gateway/a", ssl_context=client_ctx,
            expected_peer_spiffe_ids={f"https://127.0.0.1:{server_b.server_port}/federation/revocations": "spiffe://example.org/gateway/b"},
        )
        assert replicator.publish("lease:shared", revoked_at=datetime.now(timezone.utc).isoformat()) == 1
        assert store_b.is_revoked("lease:shared") is True
    finally:
        server_b.shutdown(); server_b.server_close(); thread.join(timeout=2)
