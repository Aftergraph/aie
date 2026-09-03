from __future__ import annotations

import http.client
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

from .identity import validate_x509_svid_der
from .spiffe_http import request_bytes_with_peer_identity

_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "content-length",
}


def _sanitize_headers(headers: Mapping[str, str]) -> dict[str, str]:
    connection = next((v for k, v in headers.items() if k.lower() == "connection"), "")
    connection_tokens = {part.strip().lower() for part in connection.split(",") if part.strip()}
    blocked = _HOP_BY_HOP | connection_tokens
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in blocked
        and not key.lower().startswith("aie-")
        and not key.lower().startswith("x-aie-")
    }


class SPIFFEBridgeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address,
        handler,
        *,
        upstream_base_url: str,
        timeout: float,
        inbound_ssl_context: ssl.SSLContext | None,
        inbound_tls_context_provider: Any | None,
        expected_client_spiffe_ids: set[str],
        outbound_ssl_context: ssl.SSLContext | None,
        outbound_ssl_context_provider: Callable[[], ssl.SSLContext] | None,
        expected_upstream_spiffe_id: str | None,
    ):
        super().__init__(server_address, handler)
        self.upstream_base_url = upstream_base_url.rstrip("/")
        self.timeout = timeout
        self.inbound_ssl_context = inbound_ssl_context
        self.inbound_tls_context_provider = inbound_tls_context_provider
        self.inbound_tls_enabled = inbound_ssl_context is not None or inbound_tls_context_provider is not None
        self.expected_client_spiffe_ids = set(expected_client_spiffe_ids)
        self.outbound_ssl_context = outbound_ssl_context
        self.outbound_ssl_context_provider = outbound_ssl_context_provider
        self.expected_upstream_spiffe_id = expected_upstream_spiffe_id
        if inbound_ssl_context is not None:
            self.socket = inbound_ssl_context.wrap_socket(self.socket, server_side=True)

    def get_request(self):
        sock, addr = super().get_request()
        if self.inbound_tls_context_provider is not None:
            try:
                sock = self.inbound_tls_context_provider.server_context().wrap_socket(sock, server_side=True)
            except Exception:
                sock.close()
                raise
        return sock, addr

    def outbound_context(self) -> ssl.SSLContext | None:
        if self.outbound_ssl_context_provider is not None:
            return self.outbound_ssl_context_provider()
        return self.outbound_ssl_context


class _BridgeHandler(BaseHTTPRequestHandler):
    server: SPIFFEBridgeServer

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _client_allowed(self) -> bool:
        if not self.server.expected_client_spiffe_ids:
            return True
        if not self.server.inbound_tls_enabled:
            return False
        try:
            cert = self.connection.getpeercert(binary_form=True)
            actual = validate_x509_svid_der(cert or b"", verified=bool(cert))
        except Exception:
            return False
        return actual in self.server.expected_client_spiffe_ids

    def _send_raw(self, status: int, body: bytes, headers: Mapping[str, str]) -> None:
        self.send_response(status)
        for key, value in headers.items():
            if key.lower() in _HOP_BY_HOP or key.lower() == "content-length":
                continue
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _proxy(self) -> None:
        if not self._client_allowed():
            self._send_raw(403, b'{"error":"spiffe_identity_denied"}', {"Content-Type": "application/json"})
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(length) if length else b""
        headers = _sanitize_headers({k: v for k, v in self.headers.items()})
        url = self.server.upstream_base_url + self.path
        context = self.server.outbound_context()
        try:
            if self.server.expected_upstream_spiffe_id is not None:
                if context is None:
                    raise RuntimeError("expected upstream SPIFFE identity requires TLS")
                status, response_body, response_headers = request_bytes_with_peer_identity(
                    self.command,
                    url,
                    body,
                    headers,
                    timeout=self.server.timeout,
                    ssl_context=context,
                    expected_peer_spiffe_id=self.server.expected_upstream_spiffe_id,
                )
            else:
                status, response_body, response_headers = _request_bytes(
                    self.command, url, body, headers, timeout=self.server.timeout, ssl_context=context
                )
        except Exception:
            self._send_raw(502, b'{"error":"bridge_upstream_failure"}', {"Content-Type": "application/json"})
            return
        self._send_raw(status, response_body, response_headers)

    do_GET = _proxy
    do_POST = _proxy
    do_PUT = _proxy
    do_PATCH = _proxy
    do_DELETE = _proxy
    do_OPTIONS = _proxy
    do_HEAD = _proxy


def _request_bytes(
    method: str,
    url: str,
    body: bytes,
    headers: Mapping[str, str],
    *,
    timeout: float,
    ssl_context: ssl.SSLContext | None,
) -> tuple[int, bytes, dict[str, str]]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("bridge upstream must be http(s)")
    conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    kwargs: dict[str, Any] = {"timeout": timeout}
    if parsed.scheme == "https":
        kwargs["context"] = ssl_context
    conn = conn_cls(parsed.hostname, parsed.port, **kwargs)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    try:
        conn.request(method, path, body=body if body else None, headers=dict(headers))
        response = conn.getresponse()
        return int(response.status), response.read(), {k: v for k, v in response.getheaders()}
    finally:
        conn.close()


def create_spiffe_bridge(
    *,
    upstream_base_url: str,
    host: str = "127.0.0.1",
    port: int = 0,
    timeout: float = 5.0,
    inbound_ssl_context: ssl.SSLContext | None = None,
    inbound_tls_context_provider: Any | None = None,
    expected_client_spiffe_ids: set[str] | None = None,
    outbound_ssl_context: ssl.SSLContext | None = None,
    outbound_ssl_context_provider: Callable[[], ssl.SSLContext] | None = None,
    expected_upstream_spiffe_id: str | None = None,
) -> SPIFFEBridgeServer:
    return SPIFFEBridgeServer(
        (host, port),
        _BridgeHandler,
        upstream_base_url=upstream_base_url,
        timeout=timeout,
        inbound_ssl_context=inbound_ssl_context,
        inbound_tls_context_provider=inbound_tls_context_provider,
        expected_client_spiffe_ids=set(expected_client_spiffe_ids or set()),
        outbound_ssl_context=outbound_ssl_context,
        outbound_ssl_context_provider=outbound_ssl_context_provider,
        expected_upstream_spiffe_id=expected_upstream_spiffe_id,
    )
