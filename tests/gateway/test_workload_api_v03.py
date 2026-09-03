from __future__ import annotations

from concurrent import futures
from pathlib import Path
import tempfile

import grpc

from aie_runtime.gateway.workload_api import (
    WorkloadAPIClient,
    parse_workload_endpoint,
)


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


def _x509_svid_response() -> bytes:
    svid = b''.join(
        [
            _field(1, b'spiffe://example.org/gateway/a'),
            _field(2, b'leaf-der-chain'),
            _field(3, b'pkcs8-key'),
            _field(4, b'trust-bundle'),
            _field(5, b'gateway'),
        ]
    )
    return _field(1, svid)


def test_parse_workload_endpoint_supports_unix_and_tcp():
    assert parse_workload_endpoint('unix:///run/spire/sockets/agent.sock') == 'unix:/run/spire/sockets/agent.sock'
    assert parse_workload_endpoint('tcp://127.0.0.1:8081') == '127.0.0.1:8081'


def test_fetch_x509_svid_uses_official_rpc_and_security_metadata():
    seen = {}

    def fetch(request: bytes, context):
        seen['request'] = request
        seen['metadata'] = dict(context.invocation_metadata())
        yield _x509_svid_response()

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
    handler = grpc.unary_stream_rpc_method_handler(
        fetch,
        request_deserializer=lambda raw: raw,
        response_serializer=lambda raw: raw,
    )
    generic = grpc.method_handlers_generic_handler(
        'SpiffeWorkloadAPI', {'FetchX509SVID': handler}
    )
    server.add_generic_rpc_handlers((generic,))
    port = server.add_insecure_port('127.0.0.1:0')
    server.start()
    try:
        client = WorkloadAPIClient(f'tcp://127.0.0.1:{port}')
        material = client.fetch_x509_svid(timeout=2.0)
    finally:
        server.stop(0).wait()

    assert seen['request'] == b''
    assert seen['metadata']['workload.spiffe.io'] == 'true'
    assert material.spiffe_id == 'spiffe://example.org/gateway/a'
    assert material.x509_svid == b'leaf-der-chain'
    assert material.x509_svid_key == b'pkcs8-key'
    assert material.bundle == b'trust-bundle'
    assert material.hint == 'gateway'


def test_fetch_x509_svid_selects_first_identity_as_default():
    def response_with_two() -> bytes:
        first = b''.join([
            _field(1, b'spiffe://example.org/first'),
            _field(2, b'first-cert'), _field(3, b'first-key'), _field(4, b'bundle')
        ])
        second = b''.join([
            _field(1, b'spiffe://example.org/second'),
            _field(2, b'second-cert'), _field(3, b'second-key'), _field(4, b'bundle')
        ])
        return _field(1, first) + _field(1, second)

    def fetch(request: bytes, context):
        yield response_with_two()

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
    server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler(
        'SpiffeWorkloadAPI',
        {'FetchX509SVID': grpc.unary_stream_rpc_method_handler(fetch, request_deserializer=lambda x: x, response_serializer=lambda x: x)},
    ),))
    port = server.add_insecure_port('127.0.0.1:0')
    server.start()
    try:
        material = WorkloadAPIClient(f'tcp://127.0.0.1:{port}').fetch_x509_svid(timeout=2.0)
    finally:
        server.stop(0).wait()
    assert material.spiffe_id == 'spiffe://example.org/first'


def test_workload_api_material_builds_mtls_contexts(tmp_path):
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from aie_runtime.gateway.workload_api import WorkloadAPISVID, build_ssl_contexts_from_svid
    from tls_material import issue_test_pki

    pki = issue_test_pki(tmp_path / 'pki-material')
    leaf = x509.load_pem_x509_certificate(pki['gw_a_crt'].read_bytes())
    ca = x509.load_pem_x509_certificate(pki['ca'].read_bytes())
    key = serialization.load_pem_private_key(pki['gw_a_key'].read_bytes(), password=None)
    material = WorkloadAPISVID(
        spiffe_id='spiffe://example.org/gateway/a',
        x509_svid=leaf.public_bytes(serialization.Encoding.DER),
        x509_svid_key=key.private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        bundle=ca.public_bytes(serialization.Encoding.DER),
    )

    server_ctx, client_ctx = build_ssl_contexts_from_svid(material, require_client_cert=True)
    assert server_ctx.verify_mode == __import__('ssl').CERT_REQUIRED
    assert client_ctx.verify_mode == __import__('ssl').CERT_REQUIRED
