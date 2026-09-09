"""AIE Task #4: Freshness Watermark Transport.

Spec: docs/superpowers/specs/2026-09-09-partitioned-revocation-freshness-design.md
Section 6.4 — Freshness watermark transport.

Defines canonical federation payload (aie-revocation-freshness/0.1),
validates structure/version/digest, enforces monotonic sequence per source,
and binds source identity to authenticated transport.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

SUPPORTED_VERSION = "aie-revocation-freshness/0.1"
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ParsedWatermark:
    """Validated freshness watermark payload."""

    version: str
    source_gateway: str
    sequence: int
    revocation_state_sha256: str


def parse_watermark_payload(
    payload: dict[str, Any],
    source_identity: str,
) -> ParsedWatermark | None:
    """Parse and validate a freshness watermark payload.

    Returns ParsedWatermark if valid, None otherwise.
    Rejects wrong version, missing fields, invalid digest, or identity mismatch.
    """
    if not isinstance(payload, dict):
        return None

    version = payload.get("version")
    if version != SUPPORTED_VERSION:
        return None

    source_gateway = payload.get("source_gateway")
    if not isinstance(source_gateway, str) or not source_gateway:
        return None

    # Source identity must match authenticated transport identity
    if source_gateway != source_identity:
        return None

    sequence = payload.get("sequence")
    if not isinstance(sequence, int) or sequence < 0:
        return None

    digest = payload.get("revocation_state_sha256")
    if not isinstance(digest, str) or not _DIGEST_RE.match(digest):
        return None

    return ParsedWatermark(
        version=version,
        source_gateway=source_gateway,
        sequence=sequence,
        revocation_state_sha256=digest,
    )


class WatermarkTransportHandler:
    """Handles incoming freshness watermarks with monotonic sequence enforcement.

    Tracks last accepted sequence per source gateway. Rejects stale,
    duplicate, or unauthenticated watermarks.
    """

    def __init__(self) -> None:
        self._last_seq: dict[str, int] = {}

    def apply(self, payload: dict[str, Any], source_identity: str) -> bool:
        """Apply a watermark payload. Returns True if accepted, False if rejected."""
        parsed = parse_watermark_payload(payload, source_identity)
        if parsed is None:
            return False

        last = self._last_seq.get(parsed.source_gateway, -1)
        if parsed.sequence <= last:
            return False

        self._last_seq[parsed.source_gateway] = parsed.sequence
        return True
