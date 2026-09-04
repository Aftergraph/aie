from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .spiffe_http import post_bytes_with_peer_identity, request_stream_with_peer_identity


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
class UpstreamStreamResponse:
    status: int
    headers: dict[str, str]
    stream: Any  # Iterable[bytes]; drained by the HTTP layer


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


def _is_event_stream(headers: Mapping[str, str]) -> bool:
    for key, value in headers.items():
        if key.lower() != "content-type":
            continue
        media_type = value.split(";", 1)[0].strip().lower()
        if media_type == "text/event-stream":
            return True
    return False



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

    def forward(self, *, protocol: str, headers: Mapping[str, str], body: Mapping[str, Any]) -> UpstreamResponse:
        raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        out_headers = self._headers(headers)
        ssl_context = self.ssl_context_provider() if self.ssl_context_provider is not None else self.ssl_context
        if self.expected_peer_spiffe_id is not None:
            if ssl_context is None:
                raise UpstreamTransportError("expected peer SPIFFE identity requires TLS context")
            try:
                status, response_body, response_headers = post_bytes_with_peer_identity(
                    self.url, raw, out_headers, timeout=self.timeout, ssl_context=ssl_context,
                    expected_peer_spiffe_id=self.expected_peer_spiffe_id,
                )
                return UpstreamResponse(status, response_body, response_headers)
            except Exception as exc:
                from aie_runtime.errors import AIEError
                if isinstance(exc, AIEError) and exc.code == "AIE-IDENT-002":
                    raise UpstreamAuthenticationError(str(exc)) from exc
                raise UpstreamTransportError(str(exc)) from exc
        request = urllib.request.Request(
            self.url,
            data=raw,
            headers=out_headers,
            method="POST",
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

    def forward_stream(self, *, method: str, headers: Mapping[str, str], body: Mapping[str, Any]) -> UpstreamStreamResponse:
        """Forward to upstream and return a streaming response for SSE-shaped
        bodies. The HTTP layer drains the chunk iterable to the client.

        The upstream URL is invoked with the same method the gateway received
        (typically POST for JSON-RPC requests, GET for SEP-2575 standalone
        SSE streams). For non-POST methods, the body is sent as-is and the
        request is treated as a transport-level relay.
        """
        out_headers = self._headers(headers)
        ssl_context = self.ssl_context_provider() if self.ssl_context_provider is not None else self.ssl_context
        if method.upper() == "POST":
            raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        else:
            raw = b""
        if self.expected_peer_spiffe_id is not None:
            if ssl_context is None:
                raise UpstreamTransportError("expected peer SPIFFE identity requires TLS context")
            try:
                status, response_headers, stream = request_stream_with_peer_identity(
                    method.upper(), self.url, raw, out_headers, timeout=self.timeout, ssl_context=ssl_context,
                    expected_peer_spiffe_id=self.expected_peer_spiffe_id,
                )
                return UpstreamStreamResponse(status, response_headers, stream)
            except Exception as exc:
                from aie_runtime.errors import AIEError
                if isinstance(exc, AIEError) and exc.code == "AIE-IDENT-002":
                    raise UpstreamAuthenticationError(str(exc)) from exc
                raise UpstreamTransportError(str(exc)) from exc
        # Non-SPIFFE streaming path: open a plain urllib request and stream
        # the body via a chunk iterator that calls read(N) on the underlying
        # response. urllib only supports a streaming response when the
        # caller reads it incrementally; the chunked-encoding terminator is
        # implicit when the response is closed by the upstream.
        request = urllib.request.Request(
            self.url, data=raw if raw else None, headers=out_headers, method=method.upper()
        )
        try:
            response = urllib.request.urlopen(request, timeout=self.timeout, context=ssl_context)
        except urllib.error.HTTPError as exc:
            # HTTP errors carry their own body; return it as a single-chunk
            # stream so the HTTP layer can relay it with the right status.
            response = exc  # type: ignore[assignment]
        except Exception as exc:
            raise UpstreamTransportError(str(exc)) from exc
        response_headers = {k: v for k, v in response.headers.items()}

        closed = False

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
                nonlocal closed
                if closed or self._closed:
                    return
                self._closed = True
                closed = True
                try:
                    response.close()
                except Exception:
                    pass

        return UpstreamStreamResponse(int(response.status), response_headers, _Stream())
