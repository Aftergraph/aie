from __future__ import annotations

import http.client
import os
import ssl
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

from .identity import validate_x509_svid_der
from .spiffe_http import request_stream_with_peer_identity

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

    def _send_stream(self, status: int, headers: Mapping[str, str], stream: Iterable[bytes]) -> None:
        # ponytail: relay each chunk from the upstream stream as a single
        # chunked-encoding frame and flush after every write so the client
        # sees frames as soon as the upstream produces them. Closing the
        # stream is the caller's responsibility (the connection is closed
        # by the upstream function once iteration ends).
        self.send_response(status)
        for key, value in headers.items():
            if key.lower() in _HOP_BY_HOP or key.lower() == "content-length":
                continue
            self.send_header(key, value)
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        if self.command == "HEAD":
            return
        for chunk in stream:
            if not chunk:
                # ponytail: an empty chunk is the upstream's signal that
                # the chunked stream is exhausted (the chunked terminator
                # already returned b"" from read). Break instead of
                # continue, otherwise the next read blocks forever waiting
                # for more bytes that never come and the bridge hangs
                # even after the SSE frame was delivered.
                break
            self.wfile.write(f"{len(chunk):x}\r\n".encode("ascii") + chunk + b"\r\n")
            self.wfile.flush()
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

    def _proxy(self) -> None:
        if not self._client_allowed():
            self._send_raw(403, b'{"error":"spiffe_identity_denied"}', {"Content-Type": "application/json"})
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(length) if length else b""
        headers = _sanitize_headers({k: v for k, v in self.headers.items()})
        url = self.server.upstream_base_url + self.path
        context = self.server.outbound_context()
        # ponytail: debug logging for SEP-2575 diagnostics. Gated on
        # AIE_BRIDGE_DEBUG and rate-limited to avoid log flooding. Only
        # logs POST /mcp with subscriptions/listen method.
        _debug = os.environ.get("AIE_BRIDGE_DEBUG") == "1"
        _debug_count = getattr(self.server, "_debug_post_count", 0)
        if _debug and self.command == "POST" and b"subscriptions/listen" in body and _debug_count < 3:
            self.server._debug_post_count = _debug_count + 1
            _is_listen = b'"method":"subscriptions/listen"' in body or b'"method": "subscriptions/listen"' in body
            print(
                f"[bridge] POST {self.path} body_len={len(body)} is_listen={_is_listen}",
                file=sys.stderr,
                flush=True,
            )
        try:
            if self.server.expected_upstream_spiffe_id is not None:
                if context is None:
                    raise RuntimeError("expected upstream SPIFFE identity requires TLS")
                status, response_headers, stream = request_stream_with_peer_identity(
                    self.command,
                    url,
                    body,
                    headers,
                    timeout=self.server.timeout,
                    ssl_context=context,
                    expected_peer_spiffe_id=self.server.expected_upstream_spiffe_id,
                )
            else:
                status, response_headers, stream = _request_stream(
                    self.command, url, body, headers, timeout=self.server.timeout, ssl_context=context
                )
        except Exception as exc:
            if _debug and self.command == "POST" and b"subscriptions/listen" in body:
                print(
                    f"[bridge] POST {self.path} upstream_exc={type(exc).__name__}: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
            self._send_raw(502, b'{"error":"bridge_upstream_failure"}', {"Content-Type": "application/json"})
            return
        if _debug and self.command == "POST" and b"subscriptions/listen" in body:
            _ct = response_headers.get("content-type", "?")
            print(
                f"[bridge] POST {self.path} upstream_status={status} content_type={_ct} "
                f"is_event_stream={_is_event_stream(response_headers)}",
                file=sys.stderr,
                flush=True,
            )
        if _is_event_stream(response_headers):
            # ponytail: relay the SSE stream chunk-by-chunk so SEP-2575
            # notifications/subscriptions/listen and any text/event-stream
            # response are not buffered into a single Content-Length frame.
            self._send_stream(status, response_headers, stream)
            return
        # Non-streaming response: drain into memory and send buffered. This
        # preserves the previous Content-Length-based contract for everything
        # else.
        chunks = bytearray()
        try:
            for chunk in stream:
                chunks.extend(chunk)
        finally:
            stream.close()
        self._send_raw(status, bytes(chunks), response_headers)

    do_GET = _proxy
    do_POST = _proxy
    do_PUT = _proxy
    do_PATCH = _proxy
    do_DELETE = _proxy
    do_OPTIONS = _proxy
    do_HEAD = _proxy


def _is_event_stream(headers: Mapping[str, str]) -> bool:
    """True if any header advertises an SSE / event-stream response."""
    for key, value in headers.items():
        if key.lower() != "content-type":
            continue
        media_type = value.split(";", 1)[0].strip().lower()
        if media_type == "text/event-stream":
            return True
    return False


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


def _request_stream(
    method: str,
    url: str,
    body: bytes,
    headers: Mapping[str, str],
    *,
    timeout: float,
    ssl_context: ssl.SSLContext | None,
):
    """Stream the upstream response body to the caller.

    Returns (status, headers, chunk_iterable). The caller MUST iterate the
    iterable to completion (or call its `close()` method) so the underlying
    HTTPSConnection is released.
    """
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
    conn.request(method, path, body=body if body else None, headers=dict(headers))
    response = conn.getresponse()
    response_headers = {k: v for k, v in response.getheaders()}

    class _Stream:
        def __init__(self):
            self._closed = False

        def __iter__(self):
            return self

        def __next__(self):
            chunk = response.read(8192)
            if not chunk:
                self._close()
                raise StopIteration
            return chunk

        def close(self) -> None:
            self._close()

        def _close(self) -> None:
            if self._closed:
                return
            self._closed = True
            try:
                conn.close()
            except Exception:
                pass

    return int(response.status), response_headers, _Stream()


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
