from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit, urlunsplit

from aie_runtime.errors import AIEError
from .core import AIEGateway
from .forwarding import UpstreamAuthenticationError, UpstreamResponse, UpstreamTransportError
from .identity import TransportIdentity, validate_x509_svid_der
from .model import ProtocolError
from .spiffe_http import request_bytes_with_peer_identity


def _canonical_segment(value: str) -> str:
    decoded = unquote(value)
    if not decoded or any(ch in decoded for ch in ("/", "\\", "\x00")):
        raise ProtocolError("AIE-PROTO-002", "invalid encoded A2A path identifier")
    return decoded


def _admission(
    method: str,
    raw_path: str,
    headers: Mapping[str, str],
    body: Mapping[str, Any],
    configured_tenant: str | None = None,
) -> tuple[dict[str, str], dict[str, Any]]:
    parsed = urlsplit(raw_path)
    segments = [segment for segment in parsed.path.split("/") if segment]
    tenant = configured_tenant
    if tenant is not None:
        if not segments or _canonical_segment(segments[0]) != tenant:
            raise ProtocolError(
                "AIE-PROTO-002",
                "HTTP+JSON tenant path does not match configured AgentInterface tenant",
            )
        segments.pop(0)
    path = "/" + "/".join(segments)
    out_headers = dict(headers)
    if tenant:
        out_headers["AIE-A2A-Tenant"] = tenant

    if method == "POST" and path == "/message:send":
        message = body.get("message") if isinstance(body.get("message"), Mapping) else {}
        message_id = str(message.get("messageId") or "")
        if not message_id:
            raise ProtocolError("AIE-PROTO-002", "message.messageId is required")
        internal = {"jsonrpc": "2.0", "id": message_id, "method": "message/send", "params": dict(body)}
    elif method == "GET" and path == "/tasks":
        internal = {"jsonrpc": "2.0", "id": "read-" + uuid.uuid4().hex, "method": "tasks/list", "params": {}}
    elif method == "GET" and len(segments) == 2 and segments[0] == "tasks":
        task_id = _canonical_segment(segments[1])
        internal = {"jsonrpc": "2.0", "id": "read-" + uuid.uuid4().hex, "method": "tasks/get", "params": {"id": task_id}}
    elif method == "POST" and len(segments) == 2 and segments[0] == "tasks" and segments[1].endswith(":cancel"):
        task_id = _canonical_segment(segments[1][:-7])
        prefix = f"{tenant}:" if tenant else ""
        internal = {"jsonrpc": "2.0", "id": f"cancel:{prefix}{task_id}", "method": "tasks/cancel", "params": {"id": task_id}}
    elif path == "/message:stream" or (
        method == "POST"
        and len(segments) == 2
        and segments[0] == "tasks"
        and segments[1].endswith(":subscribe")
    ):
        raise ProtocolError("AIE-PROTO-001", "HTTP+JSON streaming is not implemented")
    else:
        raise ProtocolError("AIE-PROTO-001", f"unsupported A2A HTTP+JSON operation: {method} {path}")
    return out_headers, internal


def _forward_headers(headers: Mapping[str, str]) -> dict[str, str]:
    hop = {
        "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
        "te", "trailer", "transfer-encoding", "upgrade", "content-length",
    }
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in hop
        and not (key.lower() == "aie" or key.lower().startswith("aie-") or key.lower().startswith("x-aie-"))
    }


class A2AHTTPJSONForwarder:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 5.0,
        ssl_context: ssl.SSLContext | None = None,
        expected_peer_spiffe_id: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.ssl_context = ssl_context
        self.expected_peer_spiffe_id = expected_peer_spiffe_id

    def bind(self, *, method: str, path: str, raw_body: bytes):
        parent = self

        class Bound:
            def forward(self, *, protocol: str, headers: Mapping[str, str], body: Mapping[str, Any]) -> UpstreamResponse:
                return parent.request(method, path, headers, raw_body)

        return Bound()

    def request(self, method: str, path: str, headers: Mapping[str, str], raw_body: bytes) -> UpstreamResponse:
        base = urlsplit(self.base_url)
        relative = urlsplit(path)
        target = urlunsplit((
            base.scheme,
            base.netloc,
            base.path.rstrip("/") + "/" + relative.path.lstrip("/"),
            relative.query,
            "",
        ))
        out_headers = _forward_headers(headers)
        if self.expected_peer_spiffe_id:
            if self.ssl_context is None:
                raise UpstreamTransportError("SPIFFE peer verification requires TLS context")
            try:
                status, payload, response_headers = request_bytes_with_peer_identity(
                    method,
                    target,
                    raw_body,
                    out_headers,
                    timeout=self.timeout,
                    ssl_context=self.ssl_context,
                    expected_peer_spiffe_id=self.expected_peer_spiffe_id,
                )
                return UpstreamResponse(status, payload, response_headers)
            except AIEError as exc:
                if exc.code == "AIE-IDENT-002":
                    raise UpstreamAuthenticationError(str(exc)) from exc
                raise UpstreamTransportError(str(exc)) from exc
            except Exception as exc:
                raise UpstreamTransportError(str(exc)) from exc

        request = urllib.request.Request(target, data=raw_body or None, headers=out_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=self.ssl_context) as response:
                return UpstreamResponse(int(response.status), response.read(), dict(response.headers.items()))
        except urllib.error.HTTPError as exc:
            return UpstreamResponse(int(exc.code), exc.read(), dict(exc.headers.items()))
        except Exception as exc:
            raise UpstreamTransportError(str(exc)) from exc


class A2AHTTPJSONServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address,
        *,
        gateway: AIEGateway,
        forwarder: A2AHTTPJSONForwarder,
        tenant: str | None = None,
        trust_header_identity: bool = False,
        ssl_context: ssl.SSLContext | None = None,
    ):
        super().__init__(address, _Handler)
        self.gateway = gateway
        self.forwarder = forwarder
        self.tenant = tenant
        self.trust_header_identity = trust_header_identity
        self.tls_enabled = ssl_context is not None
        if ssl_context is not None:
            self.socket = ssl_context.wrap_socket(self.socket, server_side=True)


class _Handler(BaseHTTPRequestHandler):
    server: A2AHTTPJSONServer

    def log_message(self, *args) -> None:
        return

    def _identity(self) -> TransportIdentity:
        if self.server.tls_enabled:
            try:
                der = self.connection.getpeercert(binary_form=True)
                spiffe_id = validate_x509_svid_der(der or b"", verified=bool(der))
                return TransportIdentity(spiffe_id, True, "spiffe-mtls")
            except Exception:
                return TransportIdentity(None, False, "spiffe-mtls")
        if self.server.trust_header_identity:
            return TransportIdentity(
                self.headers.get("X-AIE-Verified-Spiffe-ID"),
                self.headers.get("X-AIE-Identity-Verified", "").lower() == "true",
                "trusted-header-reference",
            )
        return TransportIdentity(None, False, "http")

    def _send(self, status: int, payload: dict[str, Any] | bytes, headers: Mapping[str, str] | None = None) -> None:
        raw = payload if isinstance(payload, bytes) else json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        emitted_content_type = False
        for key, value in (headers or {}).items():
            if key.lower() not in {"content-length", "connection", "transfer-encoding"}:
                self.send_header(key, value)
                emitted_content_type = emitted_content_type or key.lower() == "content-type"
        if not emitted_content_type:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _handle(self, method: str) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode()) if raw else {}
            if not isinstance(body, dict):
                raise ValueError
            headers = {key: value for key, value in self.headers.items()}
            admission_headers, internal = _admission(method, self.path, headers, body, self.server.tenant)
        except ProtocolError as exc:
            self._send(400, {"error_code": exc.code})
            return
        except Exception:
            self._send(400, {"error_code": "AIE-PROTO-002"})
            return

        result = self.server.gateway.forward(
            "a2a",
            admission_headers,
            internal,
            self._identity(),
            self.server.forwarder.bind(method=method, path=self.path, raw_body=raw),
        )
        if result.upstream:
            self._send(result.upstream.status, result.upstream.body, result.upstream.headers)
            return
        decision = result.decision
        status = 409 if decision.status == "prior-outcome" else 502 if decision.status == "uncertain" else 403
        self._send(status, {
            "status": decision.status,
            "action_id": decision.action_id,
            "error_code": decision.error_code,
            "prior": decision.prior,
        })

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")


def create_a2a_http_json_server(
    gateway: AIEGateway,
    forwarder: A2AHTTPJSONForwarder,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    tenant: str | None = None,
    trust_header_identity: bool = False,
    ssl_context: ssl.SSLContext | None = None,
) -> A2AHTTPJSONServer:
    return A2AHTTPJSONServer(
        (host, port),
        gateway=gateway,
        forwarder=forwarder,
        tenant=tenant,
        trust_header_identity=trust_header_identity,
        ssl_context=ssl_context,
    )
