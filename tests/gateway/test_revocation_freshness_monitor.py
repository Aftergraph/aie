"""Tests for RevocationFreshnessMonitor.

Spec: docs/superpowers/plans/2026-09-09-revocation-freshness-watermark.md Task 2
"""
from __future__ import annotations

import math
import threading

import pytest

from aie_runtime.gateway.freshness import RevocationFreshnessMonitor


def test_monitor_starts_stale_and_becomes_fresh_on_matching_watermark():
    now = [10.0]
    digest = ["a" * 64]
    monitor = RevocationFreshnessMonitor(
        expected_source_gateway="spiffe://example.org/gateway/a",
        freshness_ttl=5.0,
        local_revocation_state_sha256=lambda: digest[0],
        monotonic_clock=lambda: now[0],
    )
    assert monitor.is_fresh() is False
    assert monitor.observe(
        source_gateway="spiffe://example.org/gateway/a",
        sequence=1,
        revocation_state_sha256="a" * 64,
    ) is True
    assert monitor.is_fresh() is True


def test_monitor_expires_by_local_monotonic_ttl():
    now = [10.0]
    monitor = RevocationFreshnessMonitor(
        expected_source_gateway="spiffe://example.org/gateway/a",
        freshness_ttl=5.0,
        local_revocation_state_sha256=lambda: "a" * 64,
        monotonic_clock=lambda: now[0],
    )
    monitor.observe(source_gateway="spiffe://example.org/gateway/a", sequence=1, revocation_state_sha256="a" * 64)
    now[0] = 15.001
    assert monitor.is_fresh() is False


def test_duplicate_or_lower_sequence_cannot_extend_freshness():
    now = [10.0]
    monitor = RevocationFreshnessMonitor(
        expected_source_gateway="spiffe://example.org/gateway/a",
        freshness_ttl=5.0,
        local_revocation_state_sha256=lambda: "a" * 64,
        monotonic_clock=lambda: now[0],
    )
    assert monitor.observe(source_gateway="spiffe://example.org/gateway/a", sequence=5, revocation_state_sha256="a" * 64)
    now[0] = 14.0
    assert monitor.observe(source_gateway="spiffe://example.org/gateway/a", sequence=5, revocation_state_sha256="a" * 64) is False
    assert monitor.observe(source_gateway="spiffe://example.org/gateway/a", sequence=4, revocation_state_sha256="a" * 64) is False
    now[0] = 15.001
    assert monitor.is_fresh() is False


def test_new_watermark_does_not_restore_freshness_until_local_digest_matches():
    now = [10.0]
    local = ["a" * 64]
    monitor = RevocationFreshnessMonitor(
        expected_source_gateway="spiffe://example.org/gateway/a",
        freshness_ttl=5.0,
        local_revocation_state_sha256=lambda: local[0],
        monotonic_clock=lambda: now[0],
    )
    assert monitor.observe(source_gateway="spiffe://example.org/gateway/a", sequence=2, revocation_state_sha256="b" * 64)
    assert monitor.is_fresh() is False
    local[0] = "b" * 64
    assert monitor.is_fresh() is True


def test_wrong_source_rejected():
    monitor = RevocationFreshnessMonitor(
        expected_source_gateway="spiffe://example.org/gateway/a",
        freshness_ttl=5.0,
        local_revocation_state_sha256=lambda: "a" * 64,
    )
    assert monitor.observe(source_gateway="spiffe://evil.org/gateway/x", sequence=1, revocation_state_sha256="a" * 64) is False
    assert monitor.is_fresh() is False


def test_bool_as_sequence_rejected():
    monitor = RevocationFreshnessMonitor(
        expected_source_gateway="spiffe://example.org/gateway/a",
        freshness_ttl=5.0,
        local_revocation_state_sha256=lambda: "a" * 64,
    )
    # bool is subclass of int in Python; spec says type(sequence) is int
    assert monitor.observe(source_gateway="spiffe://example.org/gateway/a", sequence=True, revocation_state_sha256="a" * 64) is False


def test_negative_sequence_rejected():
    monitor = RevocationFreshnessMonitor(
        expected_source_gateway="spiffe://example.org/gateway/a",
        freshness_ttl=5.0,
        local_revocation_state_sha256=lambda: "a" * 64,
    )
    assert monitor.observe(source_gateway="spiffe://example.org/gateway/a", sequence=-1, revocation_state_sha256="a" * 64) is False


def test_uppercase_digest_rejected():
    monitor = RevocationFreshnessMonitor(
        expected_source_gateway="spiffe://example.org/gateway/a",
        freshness_ttl=5.0,
        local_revocation_state_sha256=lambda: "a" * 64,
    )
    assert monitor.observe(source_gateway="spiffe://example.org/gateway/a", sequence=1, revocation_state_sha256="A" * 64) is False


def test_malformed_digest_rejected():
    monitor = RevocationFreshnessMonitor(
        expected_source_gateway="spiffe://example.org/gateway/a",
        freshness_ttl=5.0,
        local_revocation_state_sha256=lambda: "a" * 64,
    )
    assert monitor.observe(source_gateway="spiffe://example.org/gateway/a", sequence=1, revocation_state_sha256="abc") is False
    assert monitor.observe(source_gateway="spiffe://example.org/gateway/a", sequence=1, revocation_state_sha256="g" * 64) is False


def test_ttl_zero_or_negative_raises():
    with pytest.raises(ValueError):
        RevocationFreshnessMonitor(
            expected_source_gateway="spiffe://example.org/gateway/a",
            freshness_ttl=0.0,
            local_revocation_state_sha256=lambda: "a" * 64,
        )
    with pytest.raises(ValueError):
        RevocationFreshnessMonitor(
            expected_source_gateway="spiffe://example.org/gateway/a",
            freshness_ttl=-1.0,
            local_revocation_state_sha256=lambda: "a" * 64,
        )


def test_non_finite_ttl_raises():
    for invalid_ttl in (math.nan, math.inf):
        with pytest.raises(ValueError):
            RevocationFreshnessMonitor(
                expected_source_gateway="spiffe://example.org/gateway/a",
                freshness_ttl=invalid_ttl,
                local_revocation_state_sha256=lambda: "a" * 64,
            )


def test_non_finite_clock_cannot_confirm_watermark():
    for invalid_now in (math.nan, math.inf, -math.inf):
        monitor = RevocationFreshnessMonitor(
            expected_source_gateway="spiffe://example.org/gateway/a",
            freshness_ttl=5.0,
            local_revocation_state_sha256=lambda: "a" * 64,
            monotonic_clock=lambda invalid_now=invalid_now: invalid_now,
        )
        assert monitor.observe(
            source_gateway="spiffe://example.org/gateway/a",
            sequence=1,
            revocation_state_sha256="a" * 64,
        ) is False
        assert monitor.last_sequence is None


def test_non_finite_clock_makes_confirmed_state_stale():
    now = [10.0]
    monitor = RevocationFreshnessMonitor(
        expected_source_gateway="spiffe://example.org/gateway/a",
        freshness_ttl=5.0,
        local_revocation_state_sha256=lambda: "a" * 64,
        monotonic_clock=lambda: now[0],
    )
    assert monitor.observe(
        source_gateway="spiffe://example.org/gateway/a",
        sequence=1,
        revocation_state_sha256="a" * 64,
    ) is True

    now[0] = math.nan
    assert monitor.is_fresh() is False


def test_monitor_rechecks_ttl_after_local_digest_read():
    now = [10.0]

    def slow_digest() -> str:
        now[0] += 1.0
        return "a" * 64

    monitor = RevocationFreshnessMonitor(
        expected_source_gateway="spiffe://example.org/gateway/a",
        freshness_ttl=5.0,
        local_revocation_state_sha256=slow_digest,
        monotonic_clock=lambda: now[0],
    )
    assert monitor.observe(
        source_gateway="spiffe://example.org/gateway/a",
        sequence=1,
        revocation_state_sha256="a" * 64,
    ) is True

    now[0] = 14.5
    assert monitor.is_fresh() is False


def test_concurrent_observations_cannot_publish_mixed_sequence_and_digest_state():
    rendezvous = threading.Barrier(2)
    high_done = threading.Event()

    class InterleavingClock:
        def __call__(self) -> float:
            name = threading.current_thread().name
            if name not in {"freshness-low", "freshness-high"}:
                return 11.5
            try:
                rendezvoused = rendezvous.wait(timeout=0.1) >= 0
            except threading.BrokenBarrierError:
                rendezvoused = False
            if name == "freshness-low" and rendezvoused:
                assert high_done.wait(timeout=1.0)
                return 10.0
            return 11.0

    monitor = RevocationFreshnessMonitor(
        expected_source_gateway="spiffe://example.org/gateway/a",
        freshness_ttl=5.0,
        local_revocation_state_sha256=lambda: "a" * 64,
        monotonic_clock=InterleavingClock(),
    )

    def observe_low() -> None:
        assert monitor.observe(
            source_gateway="spiffe://example.org/gateway/a",
            sequence=1,
            revocation_state_sha256="a" * 64,
        ) is True

    def observe_high() -> None:
        assert monitor.observe(
            source_gateway="spiffe://example.org/gateway/a",
            sequence=2,
            revocation_state_sha256="b" * 64,
        ) is True
        high_done.set()

    low = threading.Thread(target=observe_low, name="freshness-low")
    high = threading.Thread(target=observe_high, name="freshness-high")
    low.start()
    high.start()
    low.join(timeout=2.0)
    high.join(timeout=2.0)

    assert not low.is_alive()
    assert not high.is_alive()
    assert monitor.last_sequence == 2
    assert monitor.authority_revocation_state_sha256 == "b" * 64
    assert monitor.is_fresh() is False


def test_restart_starts_stale():
    """Simulates monitor restart: new instance always starts stale regardless of prior state."""
    now = [10.0]
    monitor = RevocationFreshnessMonitor(
        expected_source_gateway="spiffe://example.org/gateway/a",
        freshness_ttl=5.0,
        local_revocation_state_sha256=lambda: "a" * 64,
        monotonic_clock=lambda: now[0],
    )
    # Even though local digest matches what authority would send, no watermark received yet
    assert monitor.is_fresh() is False
    assert monitor.status()["last_sequence"] is None
    assert monitor.status()["authority_revocation_state_sha256"] is None


def test_status_reflects_current_state():
    now = [10.0]
    monitor = RevocationFreshnessMonitor(
        expected_source_gateway="spiffe://example.org/gateway/a",
        freshness_ttl=5.0,
        local_revocation_state_sha256=lambda: "a" * 64,
        monotonic_clock=lambda: now[0],
    )
    status = monitor.status()
    assert status["fresh"] is False
    assert status["last_sequence"] is None
    assert status["age_seconds"] is None

    monitor.observe(source_gateway="spiffe://example.org/gateway/a", sequence=7, revocation_state_sha256="a" * 64)
    now[0] = 12.5
    status = monitor.status()
    assert status["fresh"] is True
    assert status["last_sequence"] == 7
    assert status["age_seconds"] == pytest.approx(2.5)
    assert status["authority_revocation_state_sha256"] == "a" * 64
