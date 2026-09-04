"""FunctionalRuntime execution-time revalidation tests (TH-12 variant).

The window between admission and execution must fail closed:
revocation, expiry, and unknown actions after admit() must be caught
by runtime.revalidate() before the executor runs the action.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from aie_runtime.errors import AIEError
from aie_runtime.functional import FunctionalRuntime


class FunctionalRuntimeRevalidationTest(unittest.TestCase):
    def setUp(self):
        now = datetime.now(timezone.utc)
        self.state = {
            "principals": {"p1": {"id": "p1"}},
            "missions": {"m1": {"id": "m1", "state": "active"}},
            "leases": {
                "lease-1": {
                    "id": "lease-1",
                    "principal_id": "p1",
                    "mission_id": "m1",
                    "capabilities": ["fs.read"],
                    "resource_prefixes": ["/data"],
                    "expires_at": (now + timedelta(hours=1)).isoformat(),
                    "budget_remaining": 100.0,
                    "revoked": False,
                    "depth": 0,
                    "max_delegation_depth": 2,
                }
            },
            "outcomes": {},
            "admissions": {},
            "events": [],
        }
        self.runtime = FunctionalRuntime(self.state, policy=lambda d: True, now=lambda: now)
        self.request = {
            "action_id": "a1",
            "principal_id": "p1",
            "mission_id": "m1",
            "lease_id": "lease-1",
            "capability": "fs.read",
            "resource": "/data/file.txt",
            "budget_cost": 1,
        }

    def test_admit_then_revalidate_passes_when_unchanged(self):
        self.runtime.admit(self.request)
        self.runtime.revalidate("a1")  # must not raise

    def test_revoke_between_admit_and_execution_fails_closed(self):
        self.runtime.admit(self.request)
        self.runtime.revoke("lease-1")
        with self.assertRaises(AIEError):
            self.runtime.revalidate("a1")

    def test_expiry_between_admit_and_execution_fails_closed(self):
        self.runtime.admit(self.request)
        self.state["leases"]["lease-1"]["expires_at"] = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
        with self.assertRaises(AIEError):
            self.runtime.revalidate("a1")

    def test_unknown_action_fails_closed(self):
        with self.assertRaises(AIEError) as ctx:
            self.runtime.revalidate("nope")
        self.assertEqual(ctx.exception.code, "AIE-AUTH-004")

    def test_revalidate_emits_event(self):
        self.runtime.admit(self.request)
        self.runtime.revalidate("a1")
        self.assertTrue(
            any(e["event_type"] == "action.revalidated" for e in self.state["events"])
        )

    def test_revoked_parent_lease_cascades_to_child(self):
        # child lease delegated from parent; parent revocation must kill the child
        self.runtime.delegate(
            parent_lease_id="lease-1",
            child_lease_id="lease-child",
            child_principal_id="p1",
            capabilities={"fs.read"},
            resource_prefixes=("/data",),
            budget=50.0,
            ttl=timedelta(hours=1),
        )
        req2 = {
            "action_id": "a2",
            "principal_id": "p1",
            "mission_id": "m1",
            "lease_id": "lease-child",
            "capability": "fs.read",
            "resource": "/data/file.txt",
            "budget_cost": 1,
        }
        self.runtime.admit(req2)
        self.runtime.revoke("lease-1")  # cascade
        with self.assertRaises(AIEError):
            self.runtime.revalidate("a2")


if __name__ == "__main__":
    unittest.main()
