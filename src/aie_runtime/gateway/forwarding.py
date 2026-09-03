from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .spiffe_http import request_bytes_with_peer_identity


class UpstreamTransportError(RuntimeError):
    pass


class UpstreamAuthenticationError(RuntimeError):
    pass


@dataclass(frozen=True)
class UpstreamResponse:
    status: int
    body: bytes
    headers: dict[str, str]


@dataclass(frozen=True)
class ForwardResult:
    decision: Any
    upstream: UpstreamResponse | None = None


_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "content-length",
}


def _is_aie_header(name: str) -> bool:
    lowered = name.lower()
    return lowered == "aie" or lowered.startswith("aie-") or lowered.startswith("x-aie-")


class HTTPUpstreamForwarder:
    def __init__(
        self,
        url: str,
        *,
        timeout: float = 5.0,
        ssl_context: ssl.SSLContext | None = None,
        ssl_context_provider: Callable[[], ssl.SSLContext] | None = None,
        fixed_headers: Mapping[str, str] | None = None,
        expected_peer_spiffe_id: str | None = None,
    ):
        self.url = url
        self.timeout = timeout
        self.ssl_context = ssl_context
        self.ssl_context_provider = ssl_context_provider
        self.fixed_headers = dict(fixed_headers or {})
        self.expected_peer_spiffe_id = expected_peer_spiffe_id

    def _headers(self, headers: Mapping[str, str]) -> dict[str, str]:
        connection_tokens = {
            token.strip().lower()
            for token in str(next((v for k, v in headers.items() if k.lower() == "connection"), "")).split(",")
            if token.strip()
        }
        blocked = _HOP_BY_HOP | connection_tokens
        forwarded = {
            k: v
            for k, v in headers.items()
            if k.lower() not in blocked and not _is_aie_header(k)
        }
        forwarded.update(self.fixed_headers)
        forwarded.setdefault("Content-Type", "application/json")
        return forwarded

    def _target_url(self, target: str | None) -> str:
        if target is None:
            return self.url
        return self.url.rstrip("/") + "/" + target.lstrip("/")

    def forward_http(
        self,
        *,
        method: str,
        target: str | None,
        headers: Mapping[str, str],
        raw_body: bytes = b"",
    ) -> UpstreamResponse:
        url = self._target_url(target)
        out_headers = self._headers(headers)
        ssl_context = self.ssl_context_provider() if self.ssl_context_provider is not None else self.ssl_context
        if self.expected_peer_spiffe_id is not None:
            if ssl_context is None:
                raise UpstreamTransportError("expected peer SPIFFE identity requires TLS context")
            try:
                status, response_body, response_headers = request_bytes_with_peer_identity(
                    method,
                    url,
                    raw_body,
                    out_headers,
                    timeout=self.timeout,
                    ssl_context=ssl_context,
                    expected_peer_spiffe_id=self.expected_peer_spiffe_id,
                )
                return UpstreamResponse(status, response_body, response_headers)
            except Exception as exc:
                from aie_runtime.errors import AIEError
                if isinstance(exc, AIEError) and exc.code == "AIE-IDENT-002":
                    raise UpstreamAuthenticationError(str(exc)) from exc
                raise UpstreamTransportError(str(exc)) from exc
        request = urllib.request.Request(
            url,
            data=raw_body or None,
            headers=out_headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=ssl_context) as response:
                return UpstreamResponse(
                    int(response.status),
                    response.read(),
                    {k: v for k, v in response.headers.items()},
                )
        except urllib.error.HTTPError as exc:
            return UpstreamResponse(int(exc.code), exc.read(), {k: v for k, v in exc.headers.items()})
        except Exception as exc:
            raise UpstreamTransportError(str(exc)) from exc

    def bind_http(self, *, method: str, target: str, raw_body: bytes = b""):
        parent = self

        class _BoundForwarder:
            def forward(self, *, protocol: str, headers: Mapping[str, str], body: Mapping[str, Any]):
                return parent.forward_http(method=method, target=target, headers=headers, raw_body=raw_body)

        return _BoundForwarder()

    def forward(self, *, protocol: str, headers: Mapping[str, str], body: Mapping[str, Any]) -> UpstreamResponse:
        raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return self.forward_http(method="POST", target=None, headers=headers, raw_body=raw)
