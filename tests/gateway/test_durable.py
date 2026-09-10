import hashlib
import json

from aie_runtime.gateway.durable import SQLiteGatewayStore


def _expected_revocation_digest(rows):
    """Compute expected digest matching SQLiteGatewayStore.revocation_state_sha256.

    Per SDD spec section 6.2, source_gateway is excluded from the digest.
    Only lease_id and revoked_at participate.
    """
    canonical = [{"lease_id": r["lease_id"], "revoked_at": r["revoked_at"]} for r in rows]
    raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def test_revocation_state_sha256_is_canonical_and_order_independent(tmp_path):
    a = SQLiteGatewayStore(tmp_path / "a.db")
    b = SQLiteGatewayStore(tmp_path / "b.db")
    revocations = [
        ("lease:b", "2026-09-09T17:00:02+00:00", "spiffe://example.org/gateway/a"),
        ("lease:a", "2026-09-09T17:00:01+00:00", "spiffe://example.org/gateway/a"),
    ]
    for lease_id, revoked_at, source in revocations:
        a.revoke(lease_id, revoked_at=revoked_at, source_gateway=source)
    for lease_id, revoked_at, source in reversed(revocations):
        b.revoke(lease_id, revoked_at=revoked_at, source_gateway=source)

    expected = _expected_revocation_digest([
        {"lease_id": "lease:a", "revoked_at": "2026-09-09T17:00:01+00:00", "source_gateway": "spiffe://example.org/gateway/a"},
        {"lease_id": "lease:b", "revoked_at": "2026-09-09T17:00:02+00:00", "source_gateway": "spiffe://example.org/gateway/a"},
    ])
    assert a.revocation_state_sha256() == expected
    assert b.revocation_state_sha256() == expected


def test_revocation_state_sha256_changes_when_revocation_truth_changes(tmp_path):
    store = SQLiteGatewayStore(tmp_path / "gateway.db")
    before = store.revocation_state_sha256()
    store.revoke("lease:parent", revoked_at="2026-09-09T17:00:00+00:00", source_gateway="local-admin")
    assert store.revocation_state_sha256() != before


def test_revocation_state_sha256_is_empty_store_stable(tmp_path):
    a = SQLiteGatewayStore(tmp_path / "a.db")
    b = SQLiteGatewayStore(tmp_path / "b.db")
    assert a.revocation_state_sha256() == b.revocation_state_sha256()


def test_revocation_state_sha256_ignores_source_gateway_metadata(tmp_path):
    authority = SQLiteGatewayStore(tmp_path / "authority.db")
    worker = SQLiteGatewayStore(tmp_path / "worker.db")
    authority.revoke("lease:parent", revoked_at="2026-09-09T17:00:00+00:00", source_gateway="spiffe://example.org/gateway/a")
    worker.revoke("lease:parent", revoked_at="2026-09-09T17:00:00+00:00", source_gateway="spiffe://example.org/gateway/b")
    assert authority.revocation_state_sha256() == worker.revocation_state_sha256()


def test_revocation_state_sha256_duplicate_insert_ignore_does_not_change(tmp_path):
    store = SQLiteGatewayStore(tmp_path / "gateway.db")
    first = store.revocation_state_sha256()
    store.revoke("lease:parent", revoked_at="2026-09-09T17:00:00+00:00", source_gateway="local-admin")
    second = store.revocation_state_sha256()
    store.revoke("lease:parent", revoked_at="2026-09-09T17:00:00+00:00", source_gateway="local-admin")
    assert store.revocation_state_sha256() == second
