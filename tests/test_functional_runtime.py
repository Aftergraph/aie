from datetime import datetime, timedelta, timezone

import pytest

from aie_runtime.errors import AIEError
from aie_runtime.functional import FunctionalRuntime

NOW = datetime(2026, 9, 3, tzinfo=timezone.utc)


def state():
    return {
        "principals": {"agent:a": {"id": "agent:a"}},
        "missions": {"mission:m": {"id": "mission:m", "state": "active"}},
        "leases": {
            "lease:l": {
                "id": "lease:l",
                "principal_id": "agent:a",
                "mission_id": "mission:m",
                "capabilities": ["repo.write"],
                "resource_prefixes": ["repo://acme/"],
                "expires_at": (NOW + timedelta(minutes=5)).isoformat(),
                "budget_remaining": 2,
                "revoked": False,
            }
        },
        "outcomes": {},
        "events": [],
    }


def request(**updates):
    r = {
        "action_id": "a1",
        "principal_id": "agent:a",
        "mission_id": "mission:m",
        "lease_id": "lease:l",
        "capability": "repo.write",
        "resource": "repo://acme/x",
        "budget_cost": 1,
    }
    r.update(updates)
    return r


def test_functional_runtime_matches_core_admit_and_replay_semantics():
    rt = FunctionalRuntime(state(), policy=lambda _: True, now=lambda: NOW)
    assert rt.admit(request()) == {"status": "admitted", "error_code": None}
    assert rt.admit(request()) == {"status": "prior-outcome", "error_code": "AIE-REPLAY-001"}
    assert rt.state["leases"]["lease:l"]["budget_remaining"] == 1


def test_functional_runtime_fails_closed_on_expired_authority():
    s = state()
    s["leases"]["lease:l"]["expires_at"] = (NOW - timedelta(seconds=1)).isoformat()
    rt = FunctionalRuntime(s, policy=lambda _: True, now=lambda: NOW)
    with pytest.raises(AIEError) as exc:
        rt.admit(request())
    assert exc.value.code == "AIE-AUTH-002"
