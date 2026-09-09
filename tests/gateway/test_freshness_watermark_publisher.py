"""RED tests for AIE Task #3: Freshness Watermark Publisher.

Spec source: docs/superpowers/specs/2026-09-09-partitioned-revocation-freshness-design.md
Section 4.B — Monotonic freshness watermark with revocation-state digest and bounded TTL.

The publisher must:
1. Emit monotonically increasing sequence numbers
2. Include SHA-256 digest of canonical revocation state
3. Sign each watermark with authority key
4. Never decrease sequence number across restarts
5. Fail closed if revocation state is unavailable
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


def _make_publisher(tmp_path: Path, **overrides):
    """Import and instantiate FreshnessWatermarkPublisher."""
    from aie_runtime.gateway.watermark import FreshnessWatermarkPublisher

    defaults = {
        "authority_key": b"test-authority-key-32bytes-long!",
        "state_dir": tmp_path / "watermark-state",
        "revocation_state_provider": lambda: {"revoked": []},
    }
    defaults.update(overrides)
    return FreshnessWatermarkPublisher(**defaults)


class TestFreshnessWatermarkPublisherRed:
    """RED phase: these tests MUST fail until Task #3 GREEN implementation."""

    def test_module_exists(self) -> None:
        """FreshnessWatermarkPublisher module must exist."""
        from aie_runtime.gateway import watermark  # noqa: F401

    def test_class_exists(self, tmp_path: Path) -> None:
        """FreshnessWatermarkPublisher class must be importable."""
        _make_publisher(tmp_path)

    def test_publish_returns_signed_watermark(self, tmp_path: Path) -> None:
        """publish() must return a dict with seq, digest, signature, timestamp."""
        pub = _make_publisher(tmp_path)
        wm = pub.publish()

        assert isinstance(wm, dict)
        assert "seq" in wm
        assert "digest" in wm
        assert "signature" in wm
        assert "timestamp_ns" in wm
        assert isinstance(wm["seq"], int)
        assert isinstance(wm["digest"], str)
        assert len(wm["digest"]) == 64  # SHA-256 hex

    def test_sequence_monotonically_increases(self, tmp_path: Path) -> None:
        """Each publish() call must produce strictly increasing seq."""
        pub = _make_publisher(tmp_path)
        seqs = [pub.publish()["seq"] for _ in range(5)]
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == 5  # all unique

    def test_digest_reflects_revocation_state(self, tmp_path: Path) -> None:
        """Digest must change when revocation state changes."""
        state = {"revoked": []}
        pub = _make_publisher(tmp_path, revocation_state_provider=lambda: state)

        wm1 = pub.publish()
        state["revoked"].append("lease-abc")
        wm2 = pub.publish()

        assert wm1["digest"] != wm2["digest"]

    def test_digest_is_sha256_of_canonical_json(self, tmp_path: Path) -> None:
        """Digest must equal SHA-256 of canonical JSON revocation state."""
        state = {"revoked": ["lease-xyz"]}
        pub = _make_publisher(tmp_path, revocation_state_provider=lambda: state)
        wm = pub.publish()

        canonical = json.dumps(state, sort_keys=True, separators=(",", ":"))
        expected = hashlib.sha256(canonical.encode()).hexdigest()
        assert wm["digest"] == expected

    def test_signature_verifies_with_authority_key(self, tmp_path: Path) -> None:
        """Signature must verify against authority public key."""
        from aie_runtime.gateway.watermark import verify_watermark

        key = b"test-authority-key-32bytes-long!"
        pub = _make_publisher(tmp_path, authority_key=key)
        wm = pub.publish()

        assert verify_watermark(wm, key) is True

    def test_signature_fails_with_wrong_key(self, tmp_path: Path) -> None:
        """Signature must NOT verify with wrong key."""
        from aie_runtime.gateway.watermark import verify_watermark

        pub = _make_publisher(tmp_path, authority_key=b"correct-key-32bytes-padding!!")
        wm = pub.publish()

        assert verify_watermark(wm, b"wrong-key-32bytes-padding!!!!!") is False

    def test_sequence_persists_across_restart(self, tmp_path: Path) -> None:
        """Sequence must not reset after publisher restart."""
        pub1 = _make_publisher(tmp_path)
        seq_before = pub1.publish()["seq"]

        # New publisher instance, same state_dir
        pub2 = _make_publisher(tmp_path)
        seq_after = pub2.publish()["seq"]

        assert seq_after > seq_before

    def test_fail_closed_when_revocation_unavailable(self, tmp_path: Path) -> None:
        """Must raise when revocation state provider fails."""
        def broken():
            raise RuntimeError("revocation store down")

        pub = _make_publisher(tmp_path, revocation_state_provider=broken)

        with pytest.raises(RuntimeError, match="revocation store down"):
            pub.publish()

    def test_timestamp_is_monotonic_ns(self, tmp_path: Path) -> None:
        """Timestamps must be nanosecond monotonic, not wall clock."""
        pub = _make_publisher(tmp_path)
        ts = [pub.publish()["timestamp_ns"] for _ in range(3)]
        assert ts == sorted(ts)
        assert all(isinstance(t, int) for t in ts)
        assert all(t > 1_000_000_000 for t in ts)  # reasonable ns value
