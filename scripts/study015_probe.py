#!/usr/bin/env python3
"""STUDY-015 black-box capability probe for AIE.

Runs local-only against the real AdmissionEngine implementation. No network,
no provider credentials, no synthetic "pass" constants.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aie_runtime.engine import (  # noqa: E402
    ActionRequest,
    AdmissionEngine,
    AuthorityLease,
    Mission,
    Principal,
)
from aie_runtime.errors import AIEError  # noqa: E402
from aie_runtime.store import InMemoryState  # noqa: E402


def git_head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def run_probe() -> dict:
    now = datetime(2026, 9, 25, tzinfo=timezone.utc)
    state = InMemoryState()
    state.principals["agent:parent"] = Principal(
        "agent:parent", "agent", "spiffe://aftergraph.dev/agents/parent"
    )
    state.principals["agent:child"] = Principal(
        "agent:child", "agent", "spiffe://aftergraph.dev/agents/child"
    )
    state.missions["mission:study015"] = Mission("mission:study015", "RUNNING")
    state.leases["lease:parent"] = AuthorityLease(
        id="lease:parent",
        principal_id="agent:parent",
        mission_id="mission:study015",
        capabilities={"repo.read", "repo.write"},
        resource_prefixes=("repo://aftergraph/",),
        expires_at=now + timedelta(hours=1),
        budget_remaining=10,
        depth=0,
        max_delegation_depth=2,
    )
    engine = AdmissionEngine(state, policy=lambda _: True, clock=lambda: now)

    request = ActionRequest(
        action_id="action:study015",
        principal_id="agent:parent",
        mission_id="mission:study015",
        lease_id="lease:parent",
        capability="repo.read",
        resource="repo://aftergraph/runtime",
        budget_cost=1,
    )
    admitted = engine.admit(request)
    if admitted.status != "admitted":
        raise RuntimeError(f"unexpected admission outcome: {admitted}")
    engine.revalidate(request.action_id)

    child = engine.delegate(
        parent_lease_id="lease:parent",
        child_lease_id="lease:child",
        child_principal_id="agent:child",
        capabilities={"repo.read"},
        resource_prefixes=("repo://aftergraph/runtime",),
        budget=4,
        ttl=timedelta(minutes=10),
    )
    if child.capabilities != {"repo.read"}:
        raise RuntimeError("delegation did not attenuate capabilities")
    if child.budget_remaining != 4 or state.leases["lease:parent"].budget_remaining != 5:
        raise RuntimeError("delegated budget was not conserved")

    engine.revoke("lease:parent")
    if not state.leases["lease:parent"].revoked or not state.leases["lease:child"].revoked:
        raise RuntimeError("revocation did not cascade")

    revalidation_error = None
    try:
        engine.revalidate(request.action_id)
    except AIEError as exc:
        revalidation_error = exc.code
    if revalidation_error != "AIE-AUTH-003":
        raise RuntimeError(
            f"revoked execution did not fail closed with AIE-AUTH-003: {revalidation_error}"
        )

    event_types = [record.event_type for record in state.evidence]
    required_events = {
        "action.admitted",
        "action.revalidated",
        "delegation.created",
        "authority.revoked",
    }
    if not required_events.issubset(event_types):
        raise RuntimeError(f"missing AIE evidence events: {sorted(required_events - set(event_types))}")

    return {
        "schema": "study015.probe/1.0",
        "component": "aie",
        "source_head": git_head(),
        "execution_class": "LOCAL_IMPLEMENTATION_PROBE",
        "network_used": False,
        "mechanisms": {
            "authority_admission": True,
            "execution_time_revalidation": True,
            "delegation_attenuation": True,
            "budget_conservation": True,
            "cascading_revocation": True,
            "revoked_execution_fails_closed": True,
        },
        "observations": {
            "admission_status": admitted.status,
            "revocation_error_code": revalidation_error,
            "parent_budget_remaining": state.leases["lease:parent"].budget_remaining,
            "child_budget_remaining": child.budget_remaining,
            "evidence_events": event_types,
        },
    }


def main() -> int:
    print(json.dumps(run_probe(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
