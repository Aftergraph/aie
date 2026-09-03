import json

from aie_runtime.gateway.cli import build_server_options_from_config
from aie_runtime.gateway.forwarding import HTTPUpstreamForwarder
from tls_material import issue_test_pki


def test_build_server_options_loads_forwarding_tls_and_federation(tmp_path):
    pki = issue_test_pki(tmp_path / "pki")
    config = {
        "tls": {
            "certfile": str(pki["gw_a_crt"]), "keyfile": str(pki["gw_a_key"]), "cafile": str(pki["ca"]),
            "require_client_cert": True,
        },
        "upstreams": {
            "mcp": {"url": "http://127.0.0.1:9001/mcp", "timeout": 4.0},
            "a2a": {"url": "http://127.0.0.1:9002/a2a"},
        },
        "federation": {
            "source_gateway": "spiffe://example.org/gateway/a",
            "trusted_peers": ["spiffe://example.org/gateway/b"],
            "client_tls": {"certfile": str(pki["gw_a_crt"]), "keyfile": str(pki["gw_a_key"]), "cafile": str(pki["ca"])},
            "peers": [
                {"url": "https://127.0.0.1:9444/federation/revocations", "expected_spiffe_id": "spiffe://example.org/gateway/b"}
            ],
        },
    }
    path = tmp_path / "config.json"; path.write_text(json.dumps(config), encoding="utf-8")
    options = build_server_options_from_config(path)
    assert options["ssl_context"].verify_mode != 0
    assert isinstance(options["forwarders"]["mcp"], HTTPUpstreamForwarder)
    assert options["forwarders"]["mcp"].timeout == 4.0
    assert options["federation_trust"] == {"spiffe://example.org/gateway/b"}
    assert options["revocation_replicator"].expected_peer_spiffe_ids["https://127.0.0.1:9444/federation/revocations"] == "spiffe://example.org/gateway/b"


def test_build_server_options_can_source_tls_from_workload_api(tmp_path, monkeypatch):
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from aie_runtime.gateway.workload_api import WorkloadAPISVID

    pki = issue_test_pki(tmp_path / "pki-workload")
    leaf = x509.load_pem_x509_certificate(pki["gw_a_crt"].read_bytes())
    ca = x509.load_pem_x509_certificate(pki["ca"].read_bytes())
    key = serialization.load_pem_private_key(pki["gw_a_key"].read_bytes(), password=None)
    material = WorkloadAPISVID(
        spiffe_id="spiffe://example.org/gateway/a",
        x509_svid=leaf.public_bytes(serialization.Encoding.DER),
        x509_svid_key=key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()),
        bundle=ca.public_bytes(serialization.Encoding.DER),
        hint="gateway",
    )

    class FakeClient:
        def __init__(self, endpoint):
            assert endpoint == "unix:///run/spire/sockets/agent.sock"
        def fetch_x509_svid(self, *, timeout, hint):
            assert timeout == 2.5
            assert hint == "gateway"
            return material

    monkeypatch.setattr("aie_runtime.gateway.cli.WorkloadAPIClient", FakeClient)
    config = {
        "workload_api": {
            "endpoint": "unix:///run/spire/sockets/agent.sock",
            "hint": "gateway",
            "timeout": 2.5,
        },
        "tls": {"source": "workload_api", "require_client_cert": True},
        "upstreams": {
            "mcp": {
                "url": "https://127.0.0.1:9443/mcp",
                "tls": {"source": "workload_api"},
                "expected_spiffe_id": "spiffe://example.org/upstream/mcp",
            }
        },
        "federation": {
            "source_gateway": "spiffe://example.org/gateway/a",
            "trusted_peers": ["spiffe://example.org/gateway/b"],
            "client_tls": {"source": "workload_api"},
            "peers": [],
        },
    }
    path = tmp_path / "workload-config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    options = build_server_options_from_config(path)
    assert options["ssl_context"].verify_mode != 0
    assert options["forwarders"]["mcp"].ssl_context is not None
    assert options["workload_spiffe_id"] == "spiffe://example.org/gateway/a"
