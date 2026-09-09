"""RED tests for AIE Task #4: Freshness Watermark Transport.

Spec source: docs/superpowers/specs/2026-09-09-partitioned-revocation-freshness-design.md
Section 6.4 — Freshness watermark transport.

The transport must:
1. Define canonical federation payload (aie-revocation-freshness/0.1)
2. Validate payload structure and version
3. Extract sequence, digest, and source identity
4. Reject malformed, wrong-version, or unauthenticated payloads
5. Pass validated data to RevocationFreshnessMonitor
"""
from __future__ import annotations

import pytest


class TestFreshnessWatermarkTransportRed:
    """RED phase: these tests MUST fail until Task #4 GREEN implementation."""

    def test_module_exists(self) -> None:
        """watermark_transport module must exist."""
        from aie_runtime.gateway import watermark_transport  # noqa: F401

    def test_parse_valid_payload(self) -> None:
        """parse_watermark_payload must accept valid canonical payload."""
        from aie_runtime.gateway.watermark_transport import parse_watermark_payload

        payload = {
            "version": "aie-revocation-freshness/0.1",
            "source_gateway": "spiffe://example.org/gateway/a",
            "sequence": 42,
            "revocation_state_sha256": "a" * 64,
        }
        result = parse_watermark_payload(payload, source_identity="spiffe://example.org/gateway/a")
        assert result is not None
        assert result.sequence == 42
        assert result.revocation_state_sha256 == "a" * 64
        assert result.source_gateway == "spiffe://example.org/gateway/a"

    def test_reject_wrong_version(self) -> None:
        """parse_watermark_payload must reject unknown versions."""
        from aie_runtime.gateway.watermark_transport import parse_watermark_payload

        payload = {
            "version": "aie-revocation-freshness/99.0",
            "source_gateway": "spiffe://example.org/gateway/a",
            "sequence": 1,
            "revocation_state_sha256": "b" * 64,
        }
        assert parse_watermark_payload(payload, source_identity="spiffe://example.org/gateway/a") is None

    def test_reject_missing_fields(self) -> None:
        """parse_watermark_payload must reject payloads with missing required fields."""
        from aie_runtime.gateway.watermark_transport import parse_watermark_payload

        incomplete = {"version": "aie-revocation-freshness/0.1", "sequence": 1}
        assert parse_watermark_payload(incomplete, source_identity="x") is None

    def test_reject_invalid_digest_length(self) -> None:
        """parse_watermark_payload must reject non-64-char hex digests."""
        from aie_runtime.gateway.watermark_transport import parse_watermark_payload

        payload = {
            "version": "aie-revocation-freshness/0.1",
            "source_gateway": "spiffe://example.org/gateway/a",
            "sequence": 1,
            "revocation_state_sha256": "short",
        }
        assert parse_watermark_payload(payload, source_identity="spiffe://example.org/gateway/a") is None

    def test_reject_non_monotonic_sequence(self) -> None:
        """apply_watermark must reject sequences <= last accepted."""
        from aie_runtime.gateway.watermark_transport import WatermarkTransportHandler

        handler = WatermarkTransportHandler()
        valid = {
            "version": "aie-revocation-freshness/0.1",
            "source_gateway": "gw-a",
            "sequence": 10,
            "revocation_state_sha256": "c" * 64,
        }
        assert handler.apply(valid, source_identity="gw-a") is True

        stale = {**valid, "sequence": 9}
        assert handler.apply(stale, source_identity="gw-a") is False

    def test_reject_duplicate_sequence(self) -> None:
        """apply_watermark must reject duplicate sequences."""
        from aie_runtime.gateway.watermark_transport import WatermarkTransportHandler

        handler = WatermarkTransportHandler()
        valid = {
            "version": "aie-revocation-freshness/0.1",
            "source_gateway": "gw-b",
            "sequence": 5,
            "revocation_state_sha256": "d" * 64,
        }
        assert handler.apply(valid, source_identity="gw-b") is True
        assert handler.apply(valid, source_identity="gw-b") is False

    def test_source_identity_must_match(self) -> None:
        """apply_watermark must reject payloads where source_gateway != authenticated identity."""
        from aie_runtime.gateway.watermark_transport import WatermarkTransportHandler

        handler = WatermarkTransportHandler()
        payload = {
            "version": "aie-revocation-freshness/0.1",
            "source_gateway": "spiffe://evil.org/gateway/x",
            "sequence": 1,
            "revocation_state_sha256": "e" * 64,
        }
        assert handler.apply(payload, source_identity="spiffe://trusted.org/gateway/y") is False
