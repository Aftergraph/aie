from pathlib import Path

import pytest

from aie_runtime.errors import AIEError
from aie_runtime.gateway.durable import SQLiteGatewayStore


def make_store(tmp_path: Path) -> SQLiteGatewayStore:
    return SQLiteGatewayStore(tmp_path / "gateway.db")


def test_outcome_persists_across_store_instances(tmp_path):
    store = make_store(tmp_path)
    store.put_outcome("action-1", status="admitted", protocol="mcp", error_code=None)
    reopened = make_store(tmp_path)
    assert reopened.get_outcome("action-1") == {
        "action_id": "action-1",
        "status": "admitted",
        "protocol": "mcp",
        "error_code": None,
        "fingerprint": None,
    }


def test_revocation_persists(tmp_path):
    store = make_store(tmp_path)
    store.revoke("lease-1")
    reopened = make_store(tmp_path)
    assert reopened.is_revoked("lease-1") is True
    assert reopened.is_revoked("lease-2") is False


def test_budget_reservation_commit_conserves_budget(tmp_path):
    store = make_store(tmp_path)
    store.initialize_budget("lease-1", 10.0)
    store.reserve_budget("lease-1", "action-1", 3.0)
    assert store.remaining_budget("lease-1") == 7.0
    store.commit_budget("action-1")
    assert store.remaining_budget("lease-1") == 7.0
    assert store.reservation_state("action-1") == "committed"


def test_budget_reservation_rollback_restores_budget(tmp_path):
    store = make_store(tmp_path)
    store.initialize_budget("lease-1", 10.0)
    store.reserve_budget("lease-1", "action-1", 3.0)
    store.rollback_budget("action-1")
    assert store.remaining_budget("lease-1") == 10.0
    assert store.reservation_state("action-1") == "rolled_back"


def test_budget_reservation_fails_when_insufficient(tmp_path):
    store = make_store(tmp_path)
    store.initialize_budget("lease-1", 2.0)
    with pytest.raises(AIEError) as exc:
        store.reserve_budget("lease-1", "action-1", 3.0)
    assert exc.value.code == "AIE-BUDGET-001"
    assert store.remaining_budget("lease-1") == 2.0


def test_evidence_persists_and_is_ordered(tmp_path):
    store = make_store(tmp_path)
    store.append_evidence({"event_type": "first", "aie.action.id": "a"})
    store.append_evidence({"event_type": "second", "aie.action.id": "b"})
    events = make_store(tmp_path).list_evidence()
    assert [event["event_type"] for event in events] == ["first", "second"]


def test_outcome_can_transition_from_in_flight_to_terminal(tmp_path):
    store = make_store(tmp_path)
    store.put_outcome("stream-1", status="in-flight", protocol="a2a", error_code=None)
    store.put_outcome("stream-1", status="admitted", protocol="a2a", error_code=None)
    assert store.get_outcome("stream-1")["status"] == "admitted"


import hashlib
import json


def _expected_digest(rows: list[dict]) -> str:
    payload = json.dumps(
        rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def test_revocation_state_sha256_empty(tmp_path):
    store = make_store(tmp_path)
    digest = store.revocation_state_sha256()
    assert digest == _expected_digest([])
    assert isinstance(digest, str)
    assert len(digest) == 64
    assert digest == digest.lower()


def test_revocation_state_sha256_order_independent(tmp_path):
    (tmp_path / "a").mkdir(parents=True, exist_ok=True)
    (tmp_path / "b").mkdir(parents=True, exist_ok=True)
    store_a = make_store(tmp_path / "a")
    store_b = make_store(tmp_path / "b")
    # Insert in different orders
    store_a.revoke("lease-1", revoked_at="2026-09-09T00:00:00+00:00", source_gateway="gw-a")
    store_a.revoke("lease-2", revoked_at="2026-09-09T00:00:01+00:00", source_gateway="gw-b")
    store_b.revoke("lease-2", revoked_at="2026-09-09T00:00:01+00:00", source_gateway="gw-b")
    store_b.revoke("lease-1", revoked_at="2026-09-09T00:00:00+00:00", source_gateway="gw-a")
    assert store_a.revocation_state_sha256() == store_b.revocation_state_sha256()


def test_revocation_state_sha256_mutation_changes_digest(tmp_path):
    store = make_store(tmp_path)
    d0 = store.revocation_state_sha256()
    store.revoke("lease-1", source_gateway="gw-x")
    d1 = store.revocation_state_sha256()
    assert d0 != d1
    # We can't predict revoked_at exactly, so verify structure differently:
    # Just confirm the new digest matches a fresh computation from DB state
    with store._connect() as con:
        rows = [
            {"lease_id": r["lease_id"], "revoked_at": r["revoked_at"], "source_gateway": r["source_gateway"]}
            for r in con.execute("SELECT lease_id, revoked_at, source_gateway FROM revocations ORDER BY lease_id ASC").fetchall()
        ]
    assert d1 == _expected_digest(rows)
