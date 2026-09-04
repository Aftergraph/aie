#!/usr/bin/env python3
"""
End-to-end ABDE mission demo v2 — extended chain with failure paths.

Scenarios (mapped to STUDY-013 hard cases):
  S1: happy path (admit → revalidate → execute → evidence → quittance)  [HC5]
  S2: revocation between admit and revalidate → fail-closed, NO execution [HC1]
  S3: stale authority (expired lease) → fail-closed, no execution        [HC6]
  S4: takeover continuity — new lease after takeover, old action denied  [HC8]

No real providers. Pure AIE runtime. Each scenario asserts VERIFIED semantics.
"""
from datetime import datetime, timedelta, timezone
import uuid, sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from aie_runtime.engine import (
    AdmissionEngine, ActionRequest, InMemoryState, Principal, Mission, AuthorityLease,
)


def make_state(budget=1000.0, ttl_minutes=60):
    state = InMemoryState()
    pid = f"principal_{uuid.uuid4().hex[:8]}"
    state.principals[pid] = Principal(id=pid, type="bot", identity_ref="tg-bot-001")
    mid = f"mission_{uuid.uuid4().hex[:8]}"
    state.missions[mid] = Mission(id=mid, state="active")
    lid = f"lease_{uuid.uuid4().hex[:8]}"
    state.leases[lid] = AuthorityLease(
        id=lid, principal_id=pid, mission_id=mid,
        capabilities={"read", "write", "execute"},
        resource_prefixes=("tools:", "harness:"),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes),
        budget_remaining=budget, revoked=False,
    )
    return state, pid, mid, lid


def allow(_):
    return True


def _request(pid, mid, lid, cost=10.0):
    return ActionRequest(
        action_id=f"action_{uuid.uuid4().hex[:12]}",
        principal_id=pid, mission_id=mid, lease_id=lid,
        capability="execute", resource="tools:file_read",
        budget_cost=cost,
    )


def s1_happy_path():
    """admit → revalidate → execute → evidence complete → quittance."""
    state, pid, mid, lid = make_state()
    engine = AdmissionEngine(state=state, policy=allow, clock=lambda: datetime.now(timezone.utc))
    req = _request(pid, mid, lid)
    assert engine.admit(req).status == "admitted"
    engine.revalidate(req.action_id)  # no raise
    events = {e.event_type for e in state.evidence}
    need = {"budget.reserved", "policy.decided", "action.admitted", "action.committed", "action.revalidated"}
    missing = need - events
    assert not missing, f"missing evidence: {missing}"
    quittance = {
        "action_id": req.action_id, "status": "VERIFIED_COMPLETE",
        "evidence_count": len(state.evidence),
    }
    print(f"  S1 PASS: quittance={quittance['status']} evidence={quittance['evidence_count']}")
    return True


def s2_revocation_fail_closed():
    """Revoke lease between admit and revalidate → revalidate MUST raise, no execution."""
    state, pid, mid, lid = make_state()
    engine = AdmissionEngine(state=state, policy=allow, clock=lambda: datetime.now(timezone.utc))
    req = _request(pid, mid, lid)
    assert engine.admit(req).status == "admitted"
    state.leases[lid].revoked = True  # revocation propagates
    try:
        engine.revalidate(req.action_id)
        print("  S2 FAIL: revalidate passed on revoked lease")
        return False
    except Exception as e:
        print(f"  S1→S2 PASS: fail-closed on revocation ({type(e).__name__})")
        return True


def s3_stale_authority_fail_closed():
    """Expired lease → admit or revalidate fails closed."""
    state, pid, mid, lid = make_state(ttl_minutes=0)
    # force already-expired
    state.leases[lid].expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    engine = AdmissionEngine(state=state, policy=allow, clock=lambda: datetime.now(timezone.utc))
    req = _request(pid, mid, lid)
    try:
        outcome = engine.admit(req)
        if outcome.status != "admitted":
            print(f"  S3 PASS: admit rejected stale lease ({outcome.error_code})")
            return True
        engine.revalidate(req.action_id)
        print("  S3 FAIL: expired lease admitted+revalidated")
        return False
    except Exception as e:
        print(f"  S3 PASS: fail-closed on stale authority ({type(e).__name__})")
        return True


def s4_takeover_continuity():
    """After takeover: old lease revoked, new lease issued; old action fails closed,
    new action succeeds — no authority leak across takeover."""
    state, pid, mid, lid = make_state()
    engine = AdmissionEngine(state=state, policy=allow, clock=lambda: datetime.now(timezone.utc))
    old_req = _request(pid, mid, lid)
    assert engine.admit(old_req).status == "admitted"
    # Human takeover: revoke old lease, issue fresh one
    state.leases[lid].revoked = True
    new_lid = f"lease_{uuid.uuid4().hex[:8]}"
    state.leases[new_lid] = AuthorityLease(
        id=new_lid, principal_id=pid, mission_id=mid,
        capabilities={"read", "execute"},  # subset — no escalation
        resource_prefixes=("tools:",),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        budget_remaining=500.0, revoked=False,
    )
    # old action must fail closed at revalidate
    leaked = False
    try:
        engine.revalidate(old_req.action_id)
        leaked = True
    except Exception:
        pass
    assert not leaked, "AUTHORITY LEAK: revoked pre-takeover action survived revalidation"
    # new action under new lease succeeds
    new_req = _request(pid, mid, new_lid, cost=5.0)
    assert engine.admit(new_req).status == "admitted"
    engine.revalidate(new_req.action_id)
    print("  S4 PASS: takeover continuity, subset capabilities, zero authority leak")
    return True


def main():
    print("=" * 60)
    print("ABDE Mission Demo v2: failure paths + takeover (HC1/HC6/HC8)")
    print("=" * 60)
    results = [
        ("S1 happy path (HC5)", s1_happy_path()),
        ("S2 revocation fail-closed (HC1)", s2_revocation_fail_closed()),
        ("S3 stale authority (HC6)", s3_stale_authority_fail_closed()),
        ("S4 takeover continuity (HC8)", s4_takeover_continuity()),
    ]
    ok = all(r for _, r in results)
    print("\n" + "=" * 60)
    print("ALL SCENARIOS PASS" if ok else "SCENARIO FAILURE")
    print("=" * 60)
    return ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
