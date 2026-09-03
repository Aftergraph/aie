from __future__ import annotations

import http.client
import ssl
from urllib.parse import urlparse

from aie_runtime.errors import AIEError
from .identity import validate_x509_svid_der


def request_bytes_with_peer_identity(
    method: str,
    url: str,
    body: bytes,
    headers: dict[str, str],
    *,
    timeout: float,
    ssl_context: ssl.SSLContext,
    expected_peer_spiffe_id: str,
) -> tuple[int, bytes, dict[str, str]]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("SPIFFE peer verification requires https URL")
    port = parsed.port or 443
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    conn = http.client.HTTPSConnection(parsed.hostname, port, timeout=timeout, context=ssl_context)
    try:
        conn.connect()
        cert_der = conn.sock.getpeercert(binary_form=True) if conn.sock is not None else None
        actual = validate_x509_svid_der(cert_der or b"", verified=bool(cert_der))
        if actual != expected_peer_spiffe_id:
            raise AIEError("AIE-IDENT-002")
        conn.request(method, path, body=body if body else None, headers=headers)
        response = conn.getresponse()
        return int(response.status), response.read(), {k: v for k, v in response.getheaders()}
    finally:
        conn.close()


def post_bytes_with_peer_identity(
    url: str,
    body: bytes,
    headers: dict[str, str],
    *,
    timeout: float,
    ssl_context: ssl.SSLContext,
    expected_peer_spiffe_id: str,
) -> tuple[int, bytes, dict[str, str]]:
    return request_bytes_with_peer_identity(
        "POST", url, body, headers, timeout=timeout, ssl_context=ssl_context,
        expected_peer_spiffe_id=expected_peer_spiffe_id,
    )
