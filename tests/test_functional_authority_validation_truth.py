from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

from aie_runtime.errors import AIEError
from aie_runtime.functional import FunctionalRuntime


class FunctionalAuthorityValidationTruthTest(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 9, 20, tzinfo=timezone.utc)
        self.base_state = {
            "principals": {"p1": {"id": "p1"}},
            "missions": {"m1": {"id": "m1", "state": "RUNNING"}},
            "leases": {
                "lease-1": {
                    "id": "lease-1",
                    "principal_id": "p1",
                    "mission_id": "m1",
                    "capabilities": ["fs.read"],
                    "resource_prefixes": ["/data"],
                    "expires_at": (self.now + timedelta(hours=1)).isoformat(),
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
        self.request = {
            "action_id": "a1",
            "principal_id": "p1",
            "mission_id": "m1",
            "lease_id": "lease-1",
            "capability": "fs.read",
            "resource": "/data/file.txt",
            "budget_cost": 1,
        }

    def runtime(self, state: dict) -> FunctionalRuntime:
        return FunctionalRuntime(state, policy=lambda _: True, now=lambda: self.now)

    def test_admit_authority_failures_keep_exact_error_codes(self) -> None:
        cases = [
            ("missing principal", lambda s, r: s["principals"].clear(), "AIE-AUTH-001"),
            ("lease principal mismatch", lambda s, r: s["leases"]["lease-1"].update(principal_id="other"), "AIE-AUTH-001"),
            ("expired lease", lambda s, r: s["leases"]["lease-1"].update(expires_at=(self.now - timedelta(seconds=1)).isoformat()), "AIE-AUTH-002"),
            ("revoked lease", lambda s, r: s["leases"]["lease-1"].update(revoked=True), "AIE-AUTH-003"),
            ("capability denied", lambda s, r: r.update(capability="fs.write"), "AIE-AUTH-004"),
            ("resource denied", lambda s, r: r.update(resource="/other/file.txt"), "AIE-AUTH-004"),
        ]
        for name, mutate, expected in cases:
            with self.subTest(name=name):
                state = deepcopy(self.base_state)
                request = deepcopy(self.request)
                mutate(state, request)
                with self.assertRaises(AIEError) as ctx:
                    self.runtime(state).admit(request)
                self.assertEqual(ctx.exception.code, expected)

    def test_revalidate_rechecks_the_same_live_authority_contract(self) -> None:
        cases = [
            ("missing principal", lambda s: s["principals"].clear(), "AIE-AUTH-001"),
            ("lease principal mismatch", lambda s: s["leases"]["lease-1"].update(principal_id="other"), "AIE-AUTH-001"),
            ("expired lease", lambda s: s["leases"]["lease-1"].update(expires_at=(self.now - timedelta(seconds=1)).isoformat()), "AIE-AUTH-002"),
            ("revoked lease", lambda s: s["leases"]["lease-1"].update(revoked=True), "AIE-AUTH-003"),
            ("capability drift", lambda s: s["leases"]["lease-1"].update(capabilities=["fs.write"]), "AIE-AUTH-004"),
            ("resource drift", lambda s: s["leases"]["lease-1"].update(resource_prefixes=["/other"]), "AIE-AUTH-004"),
        ]
        for name, mutate, expected in cases:
            with self.subTest(name=name):
                state = deepcopy(self.base_state)
                runtime = self.runtime(state)
                runtime.admit(deepcopy(self.request))
                mutate(state)
                with self.assertRaises(AIEError) as ctx:
                    runtime.revalidate("a1")
                self.assertEqual(ctx.exception.code, expected)


if __name__ == "__main__":
    unittest.main()
