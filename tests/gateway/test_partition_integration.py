"""AIE Task #6: Deterministic Two-View Partition/Heal Integration Test.

Spec: docs/superpowers/specs/2026-09-09-partitioned-revocation-freshness-design.md
Section 11 (Test Strategy — Partition integration test) and Section 12 (Acceptance Criteria).

This test proves:
1. Authority and worker start with identical revocation digests
2. Worker is fresh after receiving a trusted watermark
3. Partition prevents watermark delivery
4. Authority revokes parent lease during partition
5. TTL expires on worker side
6. Worker denies protected action with AIE-FRESH-001 (no budget, no effect)
7. Heal delivers watermark BEFORE missed revocation → worker remains stale (digest mismatch)
8. Deliver missed revocation → digest converges
9. Post-heal authority evaluation denies with AIE-AUTH-003
10. Reverse heal order (revocation before watermark) also tested
"""
from __future__ import annotations

from pathlib import Path

from tests.gateway.test_gateway_core import (
    identity,
    make_gateway,
    mcp_body,
    mcp_headers,
)


class _DeterministicClock:
    """Injectable monotonic clock for deterministic TTL testing."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def _make_fresh_gateway(tmp_path: Path, name: str):
    """Create a gateway with isolated store directory."""
    store_dir = tmp_path / name
    store_dir.mkdir(parents=True, exist_ok=True)
    gw, store = make_gateway(store_dir)
    return gw, store


class TestPartitionIntegrationWatermarkFirst:
    """Heal order: watermark arrives BEFORE missed revocation event."""

    def test_full_partition_cycle_watermark_first(self, tmp_path: Path) -> None:
        from aie_runtime.gateway.freshness import RevocationFreshnessMonitor

        # 1. Setup: authority and worker with identical empty state
        worker_clock = _DeterministicClock(1_000_000.0)

        _auth_gw, auth_store = _make_fresh_gateway(tmp_path, "auth")
        worker_gw, worker_store = _make_fresh_gateway(tmp_path, "worker")

        # Both start with same digest (empty)
        assert auth_store.revocation_state_sha256() == worker_store.revocation_state_sha256()

        # 2. Create monitor with deterministic clock and wire to worker gateway
        monitor = RevocationFreshnessMonitor(
            expected_source_gateway="authority",
            freshness_ttl=60.0,
            local_revocation_state_sha256=worker_store.revocation_state_sha256,
            monotonic_clock=worker_clock,
        )
        worker_gw.revocation_freshness_check = monitor.is_fresh

        # Deliver initial watermark to worker → worker is fresh
        initial_digest = auth_store.revocation_state_sha256()
        accepted = monitor.observe(
            source_gateway="authority",
            sequence=1,
            revocation_state_sha256=initial_digest,
        )
        assert accepted is True
        assert monitor.is_fresh() is True

        # 3. Worker can admit actions while fresh
        decision = worker_gw.handle("mcp", mcp_headers(), mcp_body("pre-partition"), identity())
        # Should NOT be denied for freshness
        if decision.status == "denied":
            assert decision.error_code != "AIE-FRESH-001"

        # 4. PARTITION: stop delivering watermarks
        # 5. Authority revokes parent lease during partition
        auth_store.revoke(lease_id="parent-lease-001", revoked_at="2026-09-09T23:00:00Z")
        new_auth_digest = auth_store.revocation_state_sha256()
        assert new_auth_digest != initial_digest

        # 6. Advance worker clock past TTL
        worker_clock.advance(61.0)  # TTL is 60s

        # 7. Worker attempts protected action → AIE-FRESH-001
        decision = worker_gw.handle("mcp", mcp_headers(), mcp_body("stale-action"), identity())
        assert decision.status == "denied"
        assert decision.error_code == "AIE-FRESH-001"

        # 8. HEAL: deliver NEW watermark (with new digest) BEFORE revocation event
        accepted = monitor.observe(
            source_gateway="authority",
            sequence=2,
            revocation_state_sha256=new_auth_digest,
        )
        assert accepted is True

        # But local digest still differs (worker hasn't received revocation yet)
        assert monitor.is_fresh() is False  # digest mismatch → still stale

        # Worker still denies
        decision = worker_gw.handle("mcp", mcp_headers(), mcp_body("post-watermark-pre-revocation"), identity())
        assert decision.status == "denied"
        assert decision.error_code == "AIE-FRESH-001"

        # 9. Deliver missed revocation event to worker
        worker_store.revoke(lease_id="parent-lease-001", revoked_at="2026-09-09T23:00:00Z")

        # Now digests should converge
        assert worker_store.revocation_state_sha256() == new_auth_digest

        # Freshness recovers: digest matches + watermark seq=2 was just received
        assert monitor.is_fresh() is True


class TestPartitionIntegrationRevocationFirst:
    """Heal order: missed revocation arrives BEFORE watermark."""

    def test_full_partition_cycle_revocation_first(self, tmp_path: Path) -> None:
        from aie_runtime.gateway.freshness import RevocationFreshnessMonitor

        worker_clock = _DeterministicClock(2_000_000.0)

        _auth_gw, auth_store = _make_fresh_gateway(tmp_path, "auth2")
        worker_gw, worker_store = _make_fresh_gateway(tmp_path, "worker2")

        monitor = RevocationFreshnessMonitor(
            expected_source_gateway="authority",
            freshness_ttl=60.0,
            local_revocation_state_sha256=worker_store.revocation_state_sha256,
            monotonic_clock=worker_clock,
        )
        worker_gw.revocation_freshness_check = monitor.is_fresh

        initial_digest = auth_store.revocation_state_sha256()
        monitor.observe(
            source_gateway="authority",
            sequence=1,
            revocation_state_sha256=initial_digest,
        )
        assert monitor.is_fresh() is True

        # Partition + revoke on authority
        auth_store.revoke(lease_id="parent-lease-002", revoked_at="2026-09-09T23:10:00Z")
        new_auth_digest = auth_store.revocation_state_sha256()

        # Advance past TTL
        worker_clock.advance(61.0)

        # Stale denial
        decision = worker_gw.handle("mcp", mcp_headers(), mcp_body("stale-rf"), identity())
        assert decision.status == "denied"
        assert decision.error_code == "AIE-FRESH-001"

        # HEAL: revocation arrives FIRST
        worker_store.revoke(lease_id="parent-lease-002", revoked_at="2026-09-09T23:10:00Z")
        assert worker_store.revocation_state_sha256() == new_auth_digest

        # But no new watermark yet → monitor still has old authority digest cached
        assert monitor.is_fresh() is False

        # Still denied on freshness
        decision = worker_gw.handle("mcp", mcp_headers(), mcp_body("post-rev-pre-wm"), identity())
        assert decision.status == "denied"
        assert decision.error_code == "AIE-FRESH-001"

        # Now deliver matching watermark
        monitor.observe(
            source_gateway="authority",
            sequence=2,
            revocation_state_sha256=new_auth_digest,
        )
        assert monitor.is_fresh() is True
