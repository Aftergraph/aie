from __future__ import annotations

import json
import ssl
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping
from urllib.parse import urlsplit

from .core import AIEGateway
from .identity import TransportIdentity, validate_x509_svid_der
from .model import ProtocolError
from .protocols.a2a_http_json import is_a2a_http_json_nonstreaming, normalize_a2a_http_json_request


class GatewayHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address,
        RequestHandlerClass,
        *,
        gateway: AIEGateway,
        admin_token: str,
        trust_header_identity: bool,
        ssl_context: ssl.SSLContext | None = None,
        tls_context_provider: Any | None = None,
        forwarders: Mapping[str, Any] | None = None,
        federation_trust: set[str] | None = None,
        revocation_replicator: Any | None = None,
    ):
        super().__init__(server_address, RequestHandlerClass)
        self.gateway = gateway
        self.admin_token = admin_token
        self.trust_header_identity = trust_header_identity
        self.ssl_context = ssl_context
        self.tls_context_provider = tls_context_provider
        self.tls_enabled = ssl_context is not None or tls_context_provider is not None
        self.forwarders = dict(forwarders or {})
        self.federation_trust = set(federation_trust or set())
        self.revocation_replicator = revocation_replicator
        if ssl_context is not None:
            self.socket = ssl_context.wrap_socket(self.socket, server_side=True)

    def get_request(self):
        sock, addr = super().get_request()
        if self.tls_context_provider is not None:
            try:
                context = self.tls_context_provider.server_context()
                sock = context.wrap_socket(sock, server_side=True)
            except Exception:
                sock.close()
                raise
        return sock, addr


class _GatewayHandler(BaseHTTPRequestHandler):
    server: GatewayHTTPServer

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _raw(self, status: int, body: bytes, headers: Mapping[str, str] | None = None) -> None:
        self.send_response(status)
        emitted_content_type = False
        for key, value in (headers or {}).items():
            if key.lower() in {"content-length", "connection", "transfer-encoding"}:
                continue
            if key.lower() == "content-type":
                emitted_content_type = True
            self.send_header(key, value)
        if not emitted_content_type:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self._raw(status, raw, {"Content-Type": "application/json"})

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("JSON body must be an object")
            return value
        except Exception as exc:
            raise ValueError("invalid JSON body") from exc

    def _authorized(self) -> bool:
        expected = f"Bearer {self.server.admin_token}"
        return bool(self.server.admin_token) and self.headers.get("Authorization") == expected

    def _transport_identity(self) -> TransportIdentity:
        if self.server.tls_enabled:
            try:
                cert_der = self.connection.getpeercert(binary_form=True)
                spiffe_id = validate_x509_svid_der(cert_der or b"", verified=bool(cert_der))
                return TransportIdentity(spiffe_id, verified=True, source="spiffe-mtls")
            except Exception:
                return TransportIdentity(None, verified=False, source="spiffe-mtls")
        if not self.server.trust_header_identity:
            return TransportIdentity(None, verified=False, source="http")
        verified = self.headers.get("X-AIE-Identity-Verified", "").lower() == "true"
        spiffe_id = self.headers.get("X-AIE-Verified-Spiffe-ID")
        return TransportIdentity(spiffe_id, verified=verified, source="trusted-header-reference")

    def _decision_response(self, decision) -> None:
        payload = {
            "status": decision.status,
            "action_id": decision.action_id,
            "protocol": decision.protocol,
            "error_code": decision.error_code,
            "prior": decision.prior,
        }
        if decision.status == "admitted":
            status = 200
        elif decision.status == "prior-outcome":
            status = 409
        elif decision.status == "uncertain":
            status = 502
        else:
            status = 403
        self._json(status, payload)

    def _a2a_http_json(self) -> bool:
        parsed = urlsplit(self.path)
        if not is_a2a_http_json_nonstreaming(self.command, parsed.path):
            return False
        forwarder = self.server.forwarders.get("a2a_http_json")
        if forwarder is None:
            return False

        raw = b""
        body: dict[str, Any] = {}
        if self.command in {"POST", "PUT", "PATCH"}:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b"{}"
                value = json.loads(raw.decode("utf-8"))
                if not isinstance(value, dict):
                    raise ValueError("JSON body must be an object")
                body = value
            except Exception:
                self._json(400, {"error": "invalid_json"})
                return True

        headers = {key: value for key, value in self.headers.items()}
        try:
            normalized = normalize_a2a_http_json_request(
                method=self.command,
                path=parsed.path,
                query=parsed.query,
                headers=headers,
                body=body,
            )
        except ProtocolError as exc:
            self._json(400 if exc.code == "AIE-PROTO-002" else 404, {"error_code": exc.code})
            return True

        if normalized.tenant:
            headers["AIE-A2A-Tenant"] = normalized.tenant
        headers["AIE-A2A-Binding"] = "HTTP+JSON"
        identity = self._transport_identity()
        target = parsed.path + (("?" + parsed.query) if parsed.query else "")
        result = self.server.gateway.forward(
            "a2a",
            headers,
            normalized.admission_body,
            identity,
            forwarder.bind_http(method=self.command, target=target, raw_body=raw),
        )
        if result.upstream is not None:
            self._raw(result.upstream.status, result.upstream.body, result.upstream.headers)
            return True
        self._decision_response(result.decision)
        return True

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._json(200, {"status": "ok", "gateway_version": "0.3.0"})
            return
        if self.path == "/evidence":
            if not self._authorized():
                self._json(401, {"error": "unauthorized"})
                return
            self._json(200, {"events": self.server.gateway.store.list_evidence()})
            return
        if self._a2a_http_json():
            return
        self._json(404, {"error": "not_found"})

    def _federated_revocation(self) -> None:
        identity = self._transport_identity()
        if not identity.verified or identity.spiffe_id not in self.server.federation_trust:
            self._json(403, {"error": "federation_identity_denied"})
            return
        try:
            body = self._read_json()
            if body.get("version") != "aie-revocation/0.3":
                raise ValueError("unsupported revocation version")
            if body.get("source_gateway") != identity.spiffe_id:
                raise ValueError("source gateway mismatch")
            lease_id = str(body["lease_id"])
            revoked_at = str(body["revoked_at"])
        except Exception:
            self._json(400, {"error": "invalid_revocation"})
            return
        self.server.gateway.store.revoke(lease_id, revoked_at=revoked_at, source_gateway=identity.spiffe_id)
        self._json(200, {"accepted": True, "lease_id": lease_id})

    def do_POST(self) -> None:
        if self.path == "/federation/revocations":
            self._federated_revocation()
            return

        if self.path == "/revocations":
            if not self._authorized():
                self._json(401, {"error": "unauthorized"})
                return
            try:
                body = self._read_json()
                lease_id = str(body["lease_id"])
            except Exception:
                self._json(400, {"error": "invalid_request"})
                return
            revoked_at = datetime.now(timezone.utc).isoformat()
            self.server.gateway.store.revoke(lease_id, revoked_at=revoked_at, source_gateway="local-admin")
            replicated = 0
            if self.server.revocation_replicator is not None:
                try:
                    replicated = self.server.revocation_replicator.publish(lease_id, revoked_at=revoked_at)
                except Exception:
                    replicated = 0
            self._json(200, {"revoked": lease_id, "replicated": replicated})
            return

        if self._a2a_http_json():
            return

        if self.path not in {"/mcp", "/a2a"}:
            self._json(404, {"error": "not_found"})
            return

        try:
            body = self._read_json()
        except ValueError:
            self._json(400, {"error": "invalid_json"})
            return
        protocol = self.path[1:]
        headers = {key: value for key, value in self.headers.items()}
        identity = self._transport_identity()
        forwarder = self.server.forwarders.get(protocol)
        if forwarder is not None:
            result = self.server.gateway.forward(protocol, headers, body, identity, forwarder)
            if result.upstream is not None:
                self._raw(result.upstream.status, result.upstream.body, result.upstream.headers)
                return
            decision = result.decision
        else:
            decision = self.server.gateway.handle(protocol, headers, body, identity)
        self._decision_response(decision)


def create_http_server(
    gateway: AIEGateway,
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    admin_token: str,
    trust_header_identity: bool = False,
    ssl_context: ssl.SSLContext | None = None,
    tls_context_provider: Any | None = None,
    forwarders: Mapping[str, Any] | None = None,
    federation_trust: set[str] | None = None,
    revocation_replicator: Any | None = None,
) -> GatewayHTTPServer:
    return GatewayHTTPServer(
        (host, port),
        _GatewayHandler,
        gateway=gateway,
        admin_token=admin_token,
        trust_header_identity=trust_header_identity,
        ssl_context=ssl_context,
        tls_context_provider=tls_context_provider,
        forwarders=forwarders,
        federation_trust=federation_trust,
        revocation_replicator=revocation_replicator,
    )
