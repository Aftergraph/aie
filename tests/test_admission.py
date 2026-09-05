from datetime import datetime, timedelta, timezone

import pytest

from aie_runtime.engine import AdmissionEngine, ActionRequest, AuthorityLease, Mission, Principal
from aie_runtime.errors import AIEError
from aie_runtime.store import InMemoryState

NOW = datetime(2026, 9, 3, 0, 0, tzinfo=timezone.utc)


def base_engine(*, policy=lambda _: True):
    state = InMemoryState()
    state.principals["agent:executor"] = Principal("agent:executor", "agent", "spiffe://example.ai/agents/executor")
    state.missions["mission:release"] = Mission("mission:release", "RUNNING")
    state.leases["lease:executor"] = AuthorityLease(
        id="lease:executor",
        principal_id="agent:executor",
        mission_id="mission:release",
        capabilities={"repo.write", "ci.run"},
        resource_prefixes=("repo://acme/",),
        expires_at=NOW + timedelta(minutes=30),
        budget_remaining=10,
    )
    return AdmissionEngine(state=state, policy=policy, clock=lambda: NOW)


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


def test_c0_requires_resolvable_principal_and_mission():
    engine = base_engine()
    assert_error("AIE-AUTH-001", lambda: engine.admit(request(principal_id="agent:missing")))


def test_c0_rejects_lease_expired_at_execution_time():
    engine = base_engine()
    engine.state.leases["lease:executor"].expires_at = NOW - timedelta(seconds=1)
    assert_error("AIE-AUTH-002", lambda: engine.admit(request()))


def test_c0_rejects_revoked_lease():
    engine = base_engine()
    engine.state.leases["lease:executor"].revoked = True
    assert_error("AIE-AUTH-003", lambda: engine.admit(request()))


def test_c0_rejects_scope_outside_lease():
    engine = base_engine()
    assert_error("AIE-AUTH-004", lambda: engine.admit(request(resource="repo://other/service")))


def test_c0_replay_returns_prior_committed_outcome_without_second_budget_charge():
    engine = base_engine()
    first = engine.admit(request())
    second = engine.admit(request())
    assert first.status == "admitted"
    assert second.status == "prior-outcome"
    assert second.error_code == "AIE-REPLAY-001"
    assert engine.state.leases["lease:executor"].budget_remaining == 9


def test_c0_policy_explicit_deny():
    engine = base_engine(policy=lambda _: False)
    assert_error("AIE-POLICY-001", lambda: engine.admit(request()))


def test_c0_policy_error_fails_closed_without_degraded_mode():
    def broken(_):
        raise RuntimeError("policy unavailable")

    engine = base_engine(policy=broken)
    assert_error("AIE-POLICY-002", lambda: engine.admit(request()))


def test_c0_budget_is_reserved_before_commit_and_released_on_policy_deny():
    engine = base_engine(policy=lambda _: False)
    before = engine.state.leases["lease:executor"].budget_remaining
    assert_error("AIE-POLICY-001", lambda: engine.admit(request(budget_cost=3)))
    assert engine.state.leases["lease:executor"].budget_remaining == before


def test_c0_rejects_unsupported_critical_extension():
    engine = base_engine()
    assert_error(
        "AIE-EXT-001",
        lambda: engine.admit(request(extensions=({"namespace": "org.unknown", "critical": True},))),
    )
