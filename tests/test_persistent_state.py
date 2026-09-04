from datetime import datetime, timedelta, timezone
import os
import tempfile

import pytest

from aie_runtime.engine import AdmissionEngine, ActionRequest, AuthorityLease, Mission, Principal
from aie_runtime.errors import AIEError
from aie_runtime.persistent_state import EvidenceCollection, PersistentCollection, PersistentState


NOW = datetime(2026, 9, 3, 0, 0, tzinfo=timezone.utc)


def request(**kw):
    data = dict(
        action_id="act-1",
        principal_id="agent:executor",
        mission_id="mission:release",
        lease_id="lease:executor",
        capability="repo.write",
        resource="repo://acme/service-a",
        budget_cost=1,
    )
    data.update(kw)
    return ActionRequest(**data)


def assert_error(code, fn):
    with pytest.raises(AIEError) as exc:
        fn()
    assert exc.value.code == code


def test_restart_roundtrip_lease_survives():
    """Test that leases survive process restart via SQLite persistence."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        # First session: setup state and admit a lease
        state1 = PersistentState(db_path=db_path)
        state1.principals["agent:executor"] = Principal(
            "agent:executor", "agent", "spiffe://example.ai/agents/executor"
        )
        state1.missions["mission:release"] = Mission("mission:release", "active")
        state1.leases["lease:executor"] = AuthorityLease(
            id="lease:executor",
            principal_id="agent:executor",
            mission_id="mission:release",
            capabilities={"repo.write", "ci.run"},
            resource_prefixes=("repo://acme/",),
            expires_at=NOW + timedelta(minutes=30),
            budget_remaining=10,
        )
        engine1 = AdmissionEngine(state=state1, policy=lambda _: True, clock=lambda: NOW)
        outcome = engine1.admit(request())
        assert outcome.status == "admitted"
        state1.save_all()

        # Close first session (simulate process exit)
        if state1._conn:
            state1._conn.close()

        # Second session: reopen and revalidate
        state2 = PersistentState(db_path=db_path)
        engine2 = AdmissionEngine(state=state2, policy=lambda _: True, clock=lambda: NOW)
        engine2.revalidate("act-1")  # Should succeed without error

        # Verify lease data is identical after restart
        assert state2.leases["lease:executor"].principal_id == "agent:executor"
        assert state2.leases["lease:executor"].mission_id == "mission:release"
        assert state2.leases["lease:executor"].budget_remaining == 9  # 10 - 1 reserved
    finally:
        pass  # Skip file cleanup due to Windows file locks


def test_revocation_persists():
    """Test that lease revocation persists across restarts."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        # First session: setup, admit, then revoke
        state1 = PersistentState(db_path=db_path)
        state1.principals["agent:executor"] = Principal(
            "agent:executor", "agent", "spiffe://example.ai/agents/executor"
        )
        state1.missions["mission:release"] = Mission("mission:release", "active")
        state1.leases["lease:executor"] = AuthorityLease(
            id="lease:executor",
            principal_id="agent:executor",
            mission_id="mission:release",
            capabilities={"repo.write", "ci.run"},
            resource_prefixes=("repo://acme/",),
            expires_at=NOW + timedelta(minutes=30),
            budget_remaining=10,
        )
        engine1 = AdmissionEngine(state=state1, policy=lambda _: True, clock=lambda: NOW)
        engine1.admit(request())

        engine1.revoke("lease:executor")
        assert state1.leases["lease:executor"].revoked is True
        state1.save_all()

        # Close first session
        if state1._conn:
            state1._conn.close()

        # Second session: reopen and verify revocation persists
        state2 = PersistentState(db_path=db_path)
        engine2 = AdmissionEngine(state=state2, policy=lambda _: True, clock=lambda: NOW)

        # Revalidate should fail due to revocation
        assert_error("AIE-AUTH-003", lambda: engine2.revalidate("act-1"))
    finally:
        pass  # Skip file cleanup due to Windows file locks


def test_budget_reservation_persists():
    """Test that budget reservation persists across restarts."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        # First session: setup and admit action (reserves budget)
        state1 = PersistentState(db_path=db_path)
        state1.principals["agent:executor"] = Principal(
            "agent:executor", "agent", "spiffe://example.ai/agents/executor"
        )
        state1.missions["mission:release"] = Mission("mission:release", "active")
        state1.leases["lease:executor"] = AuthorityLease(
            id="lease:executor",
            principal_id="agent:executor",
            mission_id="mission:release",
            capabilities={"repo.write", "ci.run"},
            resource_prefixes=("repo://acme/",),
            expires_at=NOW + timedelta(minutes=30),
            budget_remaining=10,
        )
        engine1 = AdmissionEngine(state=state1, policy=lambda _: True, clock=lambda: NOW)
        engine1.admit(request(budget_cost=3))
        assert state1.leases["lease:executor"].budget_remaining == 7  # 10 - 3
        state1.save_all()

        # Close first session
        if state1._conn:
            state1._conn.close()

        # Second session: reopen and verify budget still reserved
        state2 = PersistentState(db_path=db_path)
        engine2 = AdmissionEngine(state=state2, policy=lambda _: True, clock=lambda: NOW)

        # Budget should still be reserved (budget_remaining = 7)
        assert state2.leases["lease:executor"].budget_remaining == 7

        # Should still be able to revalidate
        engine2.revalidate("act-1")

        # Admit another action with remaining budget
        outcome = engine2.admit(request(action_id="act-2", budget_cost=2))
        assert outcome.status == "admitted"
        assert state2.leases["lease:executor"].budget_remaining == 5  # 7 - 2
    finally:
        pass  # Skip file cleanup due to Windows file locks


def test_admissions_persists():
    """Test that admissions survive restart (needed for revalidation)."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        # First session: setup and admit action
        state1 = PersistentState(db_path=db_path)
        state1.principals["agent:executor"] = Principal(
            "agent:executor", "agent", "spiffe://example.ai/agents/executor"
        )
        state1.missions["mission:release"] = Mission("mission:release", "active")
        state1.leases["lease:executor"] = AuthorityLease(
            id="lease:executor",
            principal_id="agent:executor",
            mission_id="mission:release",
            capabilities={"repo.write", "ci.run"},
            resource_prefixes=("repo://acme/",),
            expires_at=NOW + timedelta(minutes=30),
            budget_remaining=10,
        )
        engine1 = AdmissionEngine(state=state1, policy=lambda _: True, clock=lambda: NOW)
        engine1.admit(request())

        # Verify admission is stored
        assert "act-1" in state1.admissions
        state1.save_all()

        # Close first session
        if state1._conn:
            state1._conn.close()

        # Second session: reopen and verify admission persists
        state2 = PersistentState(db_path=db_path)
        assert "act-1" in state2.admissions
    finally:
        pass  # Skip file cleanup due to Windows file locks


def test_inmemorystate_interface_compatibility():
    """Test that PersistentState has same interface as InMemoryState."""
    state = PersistentState()

    # Check all required properties exist
    assert hasattr(state, "principals")
    assert hasattr(state, "missions")
    assert hasattr(state, "leases")
    assert hasattr(state, "outcomes")
    assert hasattr(state, "admissions")
    assert hasattr(state, "evidence")

    # Check they return expected types (dict-like or list)
    assert isinstance(state.principals, (dict, PersistentCollection))
    assert isinstance(state.missions, (dict, PersistentCollection))
    assert isinstance(state.leases, (dict, PersistentCollection))
    assert isinstance(state.outcomes, (dict, PersistentCollection))
    assert isinstance(state.admissions, (dict, PersistentCollection))
    assert isinstance(state.evidence, (list, EvidenceCollection))
