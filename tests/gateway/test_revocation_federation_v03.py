import pytest

from aie_runtime.gateway.federation import FreshnessWatermarkReplicator, RevocationReplicator


def test_revocation_replicator_pushes_canonical_event_to_all_peers():
    calls = []

    def post(url, payload, timeout):
        calls.append((url, payload, timeout))
        return {"accepted": True}

    replicator = RevocationReplicator(
        ["https://gw-b.example/federation/revocations", "https://gw-c.example/federation/revocations"],
        source_gateway="spiffe://example.org/gateway/a",
        http_post=post,
    )
    result = replicator.publish("lease:refund", revoked_at="2026-09-03T01:00:00+00:00")
    assert result == 2
    assert len(calls) == 2
    assert calls[0][1] == {
        "version": "aie-revocation/0.3",
        "lease_id": "lease:refund",
        "revoked_at": "2026-09-03T01:00:00+00:00",
        "source_gateway": "spiffe://example.org/gateway/a",
    }


def test_freshness_replicator_pushes_canonical_watermark_to_all_peers():
    calls = []

    def post(url, payload, timeout):
        calls.append((url, payload, timeout))
        return {"accepted": True}

    replicator = FreshnessWatermarkReplicator(
        [
            "https://gw-b.example/federation/revocation-freshness",
            "https://gw-c.example/federation/revocation-freshness",
        ],
        source_gateway="spiffe://example.org/gateway/a",
        http_post=post,
    )

    assert replicator.publish(sequence=42, revocation_state_sha256="a" * 64) == 2
    assert len(calls) == 2
    assert calls[0][1] == {
        "version": "aie-revocation-freshness/0.1",
        "source_gateway": "spiffe://example.org/gateway/a",
        "sequence": 42,
        "revocation_state_sha256": "a" * 64,
    }


@pytest.mark.parametrize(
    ("sequence", "digest"),
    [
        (True, "a" * 64),
        (-1, "a" * 64),
        (1, "A" * 64),
        (1, "abc"),
        (1, "a" * 63),
        (1, "g" * 64),
    ],
)
def test_freshness_replicator_rejects_invalid_payload_before_network(sequence, digest):
    calls = []

    def post(url, payload, timeout):
        calls.append((url, payload, timeout))
        return {"accepted": True}

    replicator = FreshnessWatermarkReplicator(
        ["https://gw-b.example/federation/revocation-freshness"],
        source_gateway="spiffe://example.org/gateway/a",
        http_post=post,
    )

    with pytest.raises(ValueError):
        replicator.publish(sequence=sequence, revocation_state_sha256=digest)

    assert calls == []
