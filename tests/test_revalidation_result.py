from datetime import datetime, timedelta, timezone

import pytest

from aie_runtime.engine import (
    ActionRequest,
    AdmissionEngine,
    AuthorityLease,
    Mission,
    Principal,
    RevalidationResult,
)
from aie_runtime.errors import AIEError
from aie_runtime.store import InMemoryState


NOW = datetime(2026, 9, 20, 0, 0, tzinfo=timezone.utc)


def _admitted_engine():
    state = InMemoryState()
    state.principals["prn_test"] = Principal("prn_test", "agent", "spiffe://aftergraph.test/prn")
    state.missions["mis_test"] = Mission("mis_test", "RUNNING")
    state.leases["auth_test"] = AuthorityLease(
        id="auth_test",
        principal_id="prn_test",
        mission_id="mis_test",
        capabilities={"repo.write"},
        resource_prefixes=("repo://aftergraph/",),
        expires_at=NOW + timedelta(minutes=30),
        budget_remaining=10,
    )
    engine = AdmissionEngine(state=state, policy=lambda _: True, clock=lambda: NOW)
    engine.admit(ActionRequest(
        action_id="act_test",
        principal_id="prn_test",
        mission_id="mis_test",
        lease_id="auth_test",
        capability="repo.write",
        resource="repo://aftergraph/runtime",
        budget_cost=1,
    ))
    return engine


def test_revalidation_returns_exact_live_authority_lease_identity():
    engine = _admitted_engine()

    result = engine.revalidate("act_test")

    assert result == RevalidationResult(
        action_id="act_test",
        authority_lease_id="auth_test",
    )
    event = engine.state.evidence[-1]
    assert event.event_type == "action.revalidated"
    assert event.attributes == {
        "actionId": "act_test",
        "leaseId": "auth_test",
    }


@pytest.mark.parametrize("mode,code", [
    ("revoked", "AIE-AUTH-003"),
    ("expired", "AIE-AUTH-002"),
])
def test_revalidation_rejects_before_success_result_when_authority_is_not_live(mode, code):
    engine = _admitted_engine()
    lease = engine.state.leases["auth_test"]
    if mode == "revoked":
        lease.revoked = True
    else:
        lease.expires_at = NOW - timedelta(seconds=1)

    with pytest.raises(AIEError) as exc:
        engine.revalidate("act_test")

    assert exc.value.code == code
    assert engine.state.evidence[-1].event_type != "action.revalidated"
