"""Execution-time revalidation tests (TH-12 variant).

The window between admission and execution must fail closed:
revocation, expiry, and unknown actions after admit() must be caught
by engine.revalidate() before the executor runs the action.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from aie_runtime.engine import (
    ActionRequest,
    AdmissionEngine,
    AuthorityLease,
    Mission,
    Principal,
)
from aie_runtime.errors import AIEError
from aie_runtime.store import InMemoryState


class ExecutionTimeRevalidationTest(unittest.TestCase):
    def setUp(self):
        self.state = InMemoryState()
        self.state.principals["p1"] = Principal("p1", "human", "ref:p1")
        self.state.missions["m1"] = Mission("m1", "active")
        self.engine = AdmissionEngine(self.state, policy=lambda d: True)
        self.lease = AuthorityLease(
            id="lease-1",
            principal_id="p1",
            mission_id="m1",
            capabilities={"fs.read"},
            resource_prefixes=("/data",),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            budget_remaining=100.0,
        )
        self.state.leases["lease-1"] = self.lease
        self.request = ActionRequest(
            action_id="a1",
            principal_id="p1",
            mission_id="m1",
            lease_id="lease-1",
            capability="fs.read",
            resource="/data/file.txt",
            budget_cost=1,
        )

    def test_admit_then_revalidate_passes_when_unchanged(self):
        self.engine.admit(self.request)
        self.engine.revalidate("a1")  # must not raise

    def test_revoke_between_admit_and_execution_fails_closed(self):
        self.engine.admit(self.request)
        self.engine.revoke("lease-1")
        with self.assertRaises(AIEError):
            self.engine.revalidate("a1")

    def test_expiry_between_admit_and_execution_fails_closed(self):
        self.engine.admit(self.request)
        self.engine.state.leases["lease-1"].expires_at = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        )
        with self.assertRaises(AIEError):
            self.engine.revalidate("a1")

    def test_unknown_action_fails_closed(self):
        with self.assertRaises(AIEError) as ctx:
            self.engine.revalidate("nope")
        self.assertEqual(ctx.exception.code, "AIE-AUTH-004")

    def test_revalidate_emits_event(self):
        self.engine.admit(self.request)
        self.engine.revalidate("a1")
        self.assertTrue(
            any(e.event_type == "action.revalidated" for e in self.state.evidence)
        )

    def test_revoked_parent_lease_cascades_to_child(self):
        # child lease delegated from parent; parent revocation must kill the child
        child = AuthorityLease(
            id="lease-child",
            principal_id="p1",
            mission_id="m1",
            capabilities={"fs.read"},
            resource_prefixes=("/data",),
            expires_at=self.lease.expires_at,
            budget_remaining=50.0,
            parent_lease_id="lease-1",
        )
        self.state.leases["lease-child"] = child
        req2 = ActionRequest(
            action_id="a2",
            principal_id="p1",
            mission_id="m1",
            lease_id="lease-child",
            capability="fs.read",
            resource="/data/file.txt",
            budget_cost=1,
        )
        self.engine.admit(req2)
        self.engine.revoke("lease-1")  # cascade
        with self.assertRaises(AIEError):
            self.engine.revalidate("a1")


if __name__ == "__main__":
    unittest.main()
