from __future__ import annotations

import json

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from aie_runtime.gateway.bridge_cli import build_bridge_from_config
from aie_runtime.gateway.workload_api import WorkloadAPISVID
from tls_material import issue_test_pki


def _material(pki, cert_name, key_name, spiffe_id):
    leaf = x509.load_pem_x509_certificate(pki[cert_name].read_bytes())
    ca = x509.load_pem_x509_certificate(pki["ca"].read_bytes())
    key = serialization.load_pem_private_key(pki[key_name].read_bytes(), password=None)
    return WorkloadAPISVID(
        spiffe_id=spiffe_id,
        x509_svid=leaf.public_bytes(serialization.Encoding.DER),
        x509_svid_key=key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()),
        bundle=ca.public_bytes(serialization.Encoding.DER),
    )


def test_client_bridge_config_uses_workload_api_for_dynamic_outbound_tls(monkeypatch, tmp_path):
    pki = issue_test_pki(tmp_path / "pki")
    material = _material(pki, "gw_a_crt", "gw_a_key", "spiffe://example.org/gateway/a")

    class FakeClient:
        def __init__(self, endpoint): self.endpoint = endpoint
        def fetch_x509_svid(self, *, timeout, hint): return material
        def subscribe_x509_svid(self, *, timeout=None, hint=None): raise RuntimeError("not started in unit test")

    monkeypatch.setattr("aie_runtime.gateway.bridge_cli.WorkloadAPIClient", FakeClient)
    config = tmp_path / "bridge.json"
    config.write_text(json.dumps({
        "listen": {"host": "127.0.0.1", "port": 19080},
        "workload_api": {"endpoint": "unix:///tmp/spire-agent/public/api.sock", "watch": True},
        "upstream": {"url": "https://127.0.0.1:18443", "tls": {"source": "workload_api"}, "expected_spiffe_id": "spiffe://example.org/gateway/b"}
    }))
    built = build_bridge_from_config(config)
    try:
        assert built.server.inbound_tls_enabled is False
        assert built.server.outbound_ssl_context_provider is not None
        assert built.server.expected_upstream_spiffe_id == "spiffe://example.org/gateway/b"
        assert built.watcher is not None
    finally:
        built.server.server_close()


def test_server_bridge_config_uses_workload_api_for_inbound_tls_and_expected_client(monkeypatch, tmp_path):
    pki = issue_test_pki(tmp_path / "pki")
    material = _material(pki, "gw_b_crt", "gw_b_key", "spiffe://example.org/gateway/b")

    class FakeClient:
        def __init__(self, endpoint): self.endpoint = endpoint
        def fetch_x509_svid(self, *, timeout, hint): return material
        def subscribe_x509_svid(self, *, timeout=None, hint=None): raise RuntimeError("not started in unit test")

    monkeypatch.setattr("aie_runtime.gateway.bridge_cli.WorkloadAPIClient", FakeClient)
    config = tmp_path / "bridge.json"
    config.write_text(json.dumps({
        "listen": {"host": "127.0.0.1", "port": 18443, "tls": {"source": "workload_api"}},
        "workload_api": {"endpoint": "unix:///tmp/spire-agent/public/api.sock", "watch": True},
        "expected_client_spiffe_ids": ["spiffe://example.org/gateway/a"],
        "upstream": {"url": "http://127.0.0.1:3000"}
    }))
    built = build_bridge_from_config(config)
    try:
        assert built.server.inbound_tls_enabled is True
        assert built.server.inbound_tls_context_provider is not None
        assert built.server.expected_client_spiffe_ids == {"spiffe://example.org/gateway/a"}
        assert built.server.expected_upstream_spiffe_id is None
        assert built.watcher is not None
    finally:
        built.server.server_close()
