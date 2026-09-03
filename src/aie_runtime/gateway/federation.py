from __future__ import annotations

import json
import ssl
import urllib.request
from typing import Any, Callable

from .spiffe_http import post_bytes_with_peer_identity


def _default_post(url: str, payload: dict[str, Any], timeout: float, ssl_context: ssl.SSLContext | None = None):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout, context=ssl_context) as response:
        raw = response.read()
        return json.loads(raw.decode("utf-8")) if raw else {"accepted": response.status < 300}


class RevocationReplicator:
    def __init__(
        self,
        peers: list[str],
        *,
        source_gateway: str,
        timeout: float = 3.0,
        ssl_context: ssl.SSLContext | None = None,
        http_post: Callable[[str, dict[str, Any], float], dict[str, Any]] | None = None,
        expected_peer_spiffe_ids: dict[str, str] | None = None,
    ):
        self.peers = list(peers)
        self.source_gateway = source_gateway
        self.timeout = timeout
        self.ssl_context = ssl_context
        self.http_post = http_post
        self.expected_peer_spiffe_ids = dict(expected_peer_spiffe_ids or {})

    def publish(self, lease_id: str, *, revoked_at: str) -> int:
        event = {
            "version": "aie-revocation/0.3",
            "lease_id": lease_id,
            "revoked_at": revoked_at,
            "source_gateway": self.source_gateway,
        }
        accepted = 0
        for peer in self.peers:
            if self.http_post is not None:
                result = self.http_post(peer, event, self.timeout)
            elif peer in self.expected_peer_spiffe_ids:
                if self.ssl_context is None:
                    raise RuntimeError("federated peer SPIFFE verification requires TLS context")
                raw = json.dumps(event, separators=(",", ":")).encode("utf-8")
                status, response_body, _ = post_bytes_with_peer_identity(
                    peer, raw, {"Content-Type": "application/json"}, timeout=self.timeout,
                    ssl_context=self.ssl_context, expected_peer_spiffe_id=self.expected_peer_spiffe_ids[peer],
                )
                result = json.loads(response_body.decode("utf-8")) if response_body else {"accepted": status < 300}
            else:
                result = _default_post(peer, event, self.timeout, self.ssl_context)
            if result.get("accepted") is True:
                accepted += 1
        return accepted
