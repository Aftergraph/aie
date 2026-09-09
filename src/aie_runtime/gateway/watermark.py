"""AIE Task #3: Freshness Watermark Publisher.

Spec: docs/superpowers/specs/2026-09-09-partitioned-revocation-freshness-design.md
Section 4.B — Monotonic freshness watermark with revocation-state digest and bounded TTL.

The publisher emits authenticated, monotonically increasing freshness confirmations.
Each confirmation carries a SHA-256 digest of the authority's canonical revocation state.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any


class FreshnessWatermarkPublisher:
    """Publishes signed freshness watermarks with monotonic sequence numbers.

    Each watermark binds the authority's current revocation-state digest to a
    monotonically increasing sequence number, signed with the authority key.
    Sequence state persists across restarts via an atomic file write.
    """

    def __init__(
        self,
        authority_key: bytes,
        state_dir: Path,
        revocation_state_provider: Callable[[], dict[str, Any]],
    ) -> None:
        self._authority_key = authority_key
        self._state_dir = Path(state_dir)
        self._revocation_state_provider = revocation_state_provider
        self._state_file = self._state_dir / "watermark-seq.json"
        self._seq = self._load_seq()

    def _load_seq(self) -> int:
        """Load persisted sequence number, returning 0 if not found."""
        if not self._state_file.exists():
            return 0
        try:
            data = json.loads(self._state_file.read_text())
            return int(data.get("seq", 0))
        except (json.JSONDecodeError, ValueError, OSError):
            return 0

    def _save_seq(self, seq: int) -> None:
        """Atomically persist sequence number."""
        self._state_dir.mkdir(parents=True, exist_ok=True)
        tmp = self._state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"seq": seq}))
        tmp.replace(self._state_file)

    def publish(self) -> dict[str, Any]:
        """Publish a signed freshness watermark.

        Returns:
            Dict with keys: seq, digest, signature, timestamp_ns

        Raises:
            RuntimeError: If revocation state provider fails (fail-closed).
        """
        # Fail-closed: any exception from provider propagates
        revocation_state = self._revocation_state_provider()

        # Canonical JSON digest
        canonical = json.dumps(revocation_state, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode()).hexdigest()

        # Monotonic sequence
        self._seq += 1
        seq = self._seq

        # Monotonic nanosecond timestamp
        timestamp_ns = time.monotonic_ns()

        # Sign: HMAC-SHA256 over seq|digest|timestamp_ns
        message = f"{seq}|{digest}|{timestamp_ns}".encode()
        signature = hmac.new(self._authority_key, message, hashlib.sha256).hexdigest()

        # Persist sequence atomically
        self._save_seq(seq)

        return {
            "seq": seq,
            "digest": digest,
            "signature": signature,
            "timestamp_ns": timestamp_ns,
        }


def verify_watermark(watermark: dict[str, Any], authority_key: bytes) -> bool:
    """Verify a freshness watermark signature.

    Args:
        watermark: Dict with seq, digest, signature, timestamp_ns.
        authority_key: The authority key used to sign.

    Returns:
        True if signature is valid, False otherwise.
    """
    try:
        seq = watermark["seq"]
        digest = watermark["digest"]
        timestamp_ns = watermark["timestamp_ns"]
        signature = watermark["signature"]

        message = f"{seq}|{digest}|{timestamp_ns}".encode()
        expected = hmac.new(authority_key, message, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
    except (KeyError, TypeError, ValueError):
        return False
