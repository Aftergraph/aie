from aie_runtime.gateway.federation import RevocationReplicator


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
