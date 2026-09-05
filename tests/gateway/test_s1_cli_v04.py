from __future__ import annotations

import json
from datetime import datetime, timezone

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from aie_runtime.gateway.cli import build_gateway_from_config, build_server_options_from_config
from aie_runtime.gateway.workload_api import RotatingTLSContextProvider, WorkloadAPISVID, WorkloadAPISVIDWatcher
from tls_material import issue_test_pki


def test_config_loads_transparent_authority_binding(tmp_path):
    config = {
        "store": str(tmp_path / "g.db"),
        "principals": [{"id": "p", "type": "agent", "identity_ref": "spiffe://example.org/client/conformance"}],
        "missions": [{"id": "m", "state": "RUNNING"}],
        "leases": [{
            "id": "l", "principal_id": "p", "mission_id": "m",
            "capabilities": ["mcp.tools.call:refund_customer"],
            "resource_prefixes": ["mcp://tool/refund_customer"],
            "expires_at": "2026-09-03T05:00:00+00:00", "budget_remaining": 10,
        }],
        "authority_bindings": [{
            "spiffe_id": "spiffe://example.org/client/conformance",
            "mission_id": "m",
            "lease_id": "l",
        }],
        "policy": {"type": "local", "decision": "allow"},
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    gateway = build_gateway_from_config(path, clock=lambda: datetime(2026, 9, 3, 1, 0, tzinfo=timezone.utc))
    assert gateway.authority_bindings == {"spiffe://example.org/client/conformance": ("m", "l")}


def test_config_can_enable_live_workload_api_rotation_for_inbound_and_upstream_tls(tmp_path, monkeypatch):
    pki = issue_test_pki(tmp_path / "pki")
    leaf = x509.load_pem_x509_certificate(pki["gw_a_crt"].read_bytes())
    ca = x509.load_pem_x509_certificate(pki["ca"].read_bytes())
    key = serialization.load_pem_private_key(pki["gw_a_key"].read_bytes(), password=None)
    material = WorkloadAPISVID(
        spiffe_id="spiffe://example.org/gateway/a",
        x509_svid=leaf.public_bytes(serialization.Encoding.DER),
        x509_svid_key=key.private_bytes(
            serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ),
        bundle=ca.public_bytes(serialization.Encoding.DER),
        hint="gateway",
    )

    class FakeClient:
        def __init__(self, endpoint):
            self.endpoint = endpoint
        def fetch_x509_svid(self, *, timeout, hint):
            return material
        def subscribe_x509_svid(self, *, timeout=None, hint=None):
            raise AssertionError("watcher must not start during configuration build")

    monkeypatch.setattr("aie_runtime.gateway.cli.WorkloadAPIClient", FakeClient)
    config = {
        "workload_api": {
            "endpoint": "unix:///run/spire/sockets/agent.sock",
            "hint": "gateway",
            "timeout": 2.0,
            "watch": True,
            "reconnect_delay": 0.25,
        },
        "tls": {"source": "workload_api", "require_client_cert": True},
        "upstreams": {
            "mcp": {
                "url": "https://mcp.internal/mcp",
                "tls": {"source": "workload_api"},
                "expected_spiffe_id": "spiffe://example.org/upstream/mcp",
            }
        },
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    options = build_server_options_from_config(path)
    assert options["ssl_context"] is None
    assert isinstance(options["tls_context_provider"], RotatingTLSContextProvider)
    assert isinstance(options["_svid_watcher"], WorkloadAPISVIDWatcher)
    forwarder = options["forwarders"]["mcp"]
    assert forwarder.ssl_context is None
    assert forwarder.ssl_context_provider is not None
    assert forwarder.ssl_context_provider() is options["tls_context_provider"].client_context()
