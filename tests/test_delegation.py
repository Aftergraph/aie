from datetime import datetime, timedelta, timezone

import pytest

from aie_runtime.engine import AdmissionEngine, AuthorityLease, Mission, Principal
from aie_runtime.errors import AIEError
from aie_runtime.store import InMemoryState

NOW = datetime(2026, 9, 3, tzinfo=timezone.utc)


def engine_with_parent():
    state = InMemoryState()
    state.principals["agent:parent"] = Principal("agent:parent", "agent", "spiffe://example.ai/agents/parent")
    state.principals["agent:child"] = Principal("agent:child", "agent", "spiffe://example.ai/agents/child")
    state.missions["mission:x"] = Mission("mission:x", "RUNNING")
    state.leases["lease:parent"] = AuthorityLease(
        id="lease:parent",
        principal_id="agent:parent",
        mission_id="mission:x",
        capabilities={"repo.read", "repo.write"},
        resource_prefixes=("repo://acme/",),
        expires_at=NOW + timedelta(hours=1),
        budget_remaining=10,
        depth=0,
        max_delegation_depth=2,
    )
    return AdmissionEngine(state, policy=lambda _: True, clock=lambda: NOW)


def test_d1_child_scope_must_be_subset_of_parent():
    e = engine_with_parent()
    with pytest.raises(AIEError) as exc:
        e.delegate(
            parent_lease_id="lease:parent",
            child_lease_id="lease:child",
            child_principal_id="agent:child",
            capabilities={"ci.run"},
            resource_prefixes=("repo://acme/",),
            budget=2,
            ttl=timedelta(minutes=10),
        )
    assert exc.value.code == "AIE-DELEG-001"


def test_d1_delegation_depth_is_bounded():
    e = engine_with_parent()
    e.state.leases["lease:parent"].depth = 2
    with pytest.raises(AIEError) as exc:
        e.delegate(
            parent_lease_id="lease:parent",
            child_lease_id="lease:child",
            child_principal_id="agent:child",
            capabilities={"repo.read"},
            resource_prefixes=("repo://acme/",),
            budget=2,
            ttl=timedelta(minutes=10),
        )
    assert exc.value.code == "AIE-DELEG-002"


def test_d1_delegated_budget_is_conserved_and_reserved_from_parent():
    e = engine_with_parent()
    child = e.delegate(
        parent_lease_id="lease:parent",
        child_lease_id="lease:child",
        child_principal_id="agent:child",
        capabilities={"repo.read"},
        resource_prefixes=("repo://acme/service-a",),
        budget=4,
        ttl=timedelta(minutes=10),
    )
    assert child.budget_remaining == 4
    assert e.state.leases["lease:parent"].budget_remaining == 6


def test_d1_cannot_delegate_more_budget_than_parent_has():
    e = engine_with_parent()
    with pytest.raises(AIEError) as exc:
        e.delegate(
            parent_lease_id="lease:parent",
            child_lease_id="lease:child",
            child_principal_id="agent:child",
            capabilities={"repo.read"},
            resource_prefixes=("repo://acme/",),
            budget=11,
            ttl=timedelta(minutes=10),
        )
    assert exc.value.code == "AIE-BUDGET-001"


def test_d1_parent_revocation_propagates_to_descendants():
    e = engine_with_parent()
    e.delegate(
        parent_lease_id="lease:parent",
        child_lease_id="lease:child",
        child_principal_id="agent:child",
        capabilities={"repo.read"},
        resource_prefixes=("repo://acme/",),
        budget=2,
        ttl=timedelta(minutes=10),
    )
    e.revoke("lease:parent")
    assert e.state.leases["lease:parent"].revoked is True
    assert e.state.leases["lease:child"].revoked is True
