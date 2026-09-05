from __future__ import annotations

import json
import ssl
import threading
import time
import urllib.request
from concurrent import futures
from datetime import datetime, timedelta, timezone

import grpc
from cryptography import x509
from cryptography.hazmat.primitives import serialization

from aie_runtime.engine import AuthorityLease, Mission, Principal
from aie_runtime.gateway.core import AIEGateway
from aie_runtime.gateway.durable import SQLiteGatewayStore
from aie_runtime.gateway.http import create_http_server
from aie_runtime.gateway.policy import LocalPolicyAdapter
from aie_runtime.gateway.tls import build_client_ssl_context
from aie_runtime.gateway.workload_api import (
    RotatingTLSContextProvider,
    WorkloadAPIClient,
    WorkloadAPISVID,
    WorkloadAPISVIDWatcher,
)
from aie_runtime.store import InMemoryState
from tls_material import issue_test_pki

NOW = datetime(2026, 9, 3, 1, 0, tzinfo=timezone.utc)


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _field(number: int, payload: bytes) -> bytes:
    return _varint((number << 3) | 2) + _varint(len(payload)) + payload


def _response(spiffe_id: str, cert: bytes = b"cert", key: bytes = b"key", bundle: bytes = b"bundle") -> bytes:
    svid = b"".join([
        _field(1, spiffe_id.encode()),
        _field(2, cert),
        _field(3, key),
        _field(4, bundle),
        _field(5, b"gateway"),
    ])
    return _field(1, svid)


def _material(pki) -> WorkloadAPISVID:
    leaf = x509.load_pem_x509_certificate(pki["gw_a_crt"].read_bytes())
    ca = x509.load_pem_x509_certificate(pki["ca"].read_bytes())
    key = serialization.load_pem_private_key(pki["gw_a_key"].read_bytes(), password=None)
    return WorkloadAPISVID(
        spiffe_id="spiffe://example.org/gateway/a",
        x509_svid=leaf.public_bytes(serialization.Encoding.DER),
        x509_svid_key=key.private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        bundle=ca.public_bytes(serialization.Encoding.DER),
        hint="gateway",
    )


def _gateway(tmp_path):
    state = InMemoryState()
    state.principals["p"] = Principal("p", "agent", "spiffe://example.org/agent/refund")
    state.missions["m"] = Mission("m", "RUNNING")
    state.leases["l"] = AuthorityLease(
        "l", "p", "m", {"mcp.tools.call:refund_customer"}, ("mcp://tool/refund_customer",),
        NOW + timedelta(hours=1), 10,
    )
    return AIEGateway(
        state=state,
        store=SQLiteGatewayStore(tmp_path / "gateway.db"),
        policy=LocalPolicyAdapter(lambda _: True),
        clock=lambda: NOW,
        authority_bindings={"spiffe://example.org/agent/refund": ("m", "l")},
    )


def _request(base: str, context: ssl.SSLContext, action_id: str):
    body = {"jsonrpc": "2.0", "id": action_id, "method": "tools/call", "params": {"name": "refund_customer"}}
    headers = {
        "Content-Type": "application/json",
        "MCP-Protocol-Version": "2026-07-28",
        "Mcp-Method": "tools/call",
        "Mcp-Name": "refund_customer",
    }
    req = urllib.request.Request(base + "/mcp", data=json.dumps(body).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=3, context=context) as response:
        return response.status, json.loads(response.read())


def test_workload_api_stream_yields_each_rotation_update():
    def fetch(request: bytes, context):
        yield _response("spiffe://example.org/gateway/a", b"cert-a", b"key-a", b"bundle-a")
        yield _response("spiffe://example.org/gateway/a", b"cert-b", b"key-b", b"bundle-b")

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
    server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler(
        "SpiffeWorkloadAPI",
        {"FetchX509SVID": grpc.unary_stream_rpc_method_handler(fetch, request_deserializer=lambda x: x, response_serializer=lambda x: x)},
    ),))
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    try:
        values = list(WorkloadAPIClient(f"tcp://127.0.0.1:{port}").stream_x509_svid(timeout=2.0, hint="gateway"))
    finally:
        server.stop(0).wait()
    assert [v.x509_svid for v in values] == [b"cert-a", b"cert-b"]


def test_rotating_tls_provider_swaps_server_and_trust_bundle_without_restart(tmp_path):
    pki1 = issue_test_pki(tmp_path / "pki-1")
    pki2 = issue_test_pki(tmp_path / "pki-2")
    provider = RotatingTLSContextProvider(_material(pki1), require_client_cert=True)
    server = create_http_server(
        _gateway(tmp_path), host="127.0.0.1", port=0, admin_token="admin", tls_context_provider=provider
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"https://127.0.0.1:{server.server_port}"
    try:
        client1 = build_client_ssl_context(certfile=pki1["agent_crt"], keyfile=pki1["agent_key"], cafile=pki1["ca"])
        assert _request(base, client1, "rotate-before")[0] == 200
        old_generation = provider.generation

        provider.update(_material(pki2))
        assert provider.generation == old_generation + 1

        client2 = build_client_ssl_context(certfile=pki2["agent_crt"], keyfile=pki2["agent_key"], cafile=pki2["ca"])
        assert _request(base, client2, "rotate-after")[0] == 200

        try:
            _request(base, client1, "rotate-old-client")
        except Exception:
            pass
        else:
            raise AssertionError("old trust bundle remained active after atomic rotation")
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_watcher_applies_stream_updates_to_provider(tmp_path):
    pki1 = issue_test_pki(tmp_path / "watch-1")
    pki2 = issue_test_pki(tmp_path / "watch-2")
    m1 = _material(pki1)
    m2 = _material(pki2)

    def response_for(material: WorkloadAPISVID) -> bytes:
        return _response(material.spiffe_id, material.x509_svid, material.x509_svid_key, material.bundle)

    def fetch(request: bytes, context):
        yield response_for(m1)
        time.sleep(0.05)
        yield response_for(m2)
        while context.is_active():
            time.sleep(0.05)

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
    server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler(
        "SpiffeWorkloadAPI",
        {"FetchX509SVID": grpc.unary_stream_rpc_method_handler(fetch, request_deserializer=lambda x: x, response_serializer=lambda x: x)},
    ),))
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    provider = RotatingTLSContextProvider(m1, require_client_cert=True)
    watcher = WorkloadAPISVIDWatcher(
        WorkloadAPIClient(f"tcp://127.0.0.1:{port}"), provider, hint="gateway", reconnect_delay=0.01
    )
    try:
        watcher.start()
        deadline = time.time() + 3
        while provider.generation < 3 and time.time() < deadline:
            time.sleep(0.02)
        assert provider.generation >= 3
    finally:
        watcher.stop(); watcher.join(timeout=2); server.stop(0).wait()
