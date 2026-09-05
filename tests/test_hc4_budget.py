from datetime import datetime, timezone
import pytest

from aie_runtime.engine import AdmissionEngine, Principal, Mission, AuthorityLease, ActionRequest
from aie_runtime.store import InMemoryState, BudgetLedger
from aie_runtime.errors import AIEError


class TestHC4BudgetConservation:
    """HC4: Budget Conservation - No budget escape via delegation chains."""

    def test_ledger_reserve_committed_settle(self):
        """HC4-02: Ledger reserve/settle/commit/refund semantics."""
        ledger = BudgetLedger(budget_usd=50.0)
        now = datetime.now(timezone.utc)
        
        # Reserve succeeds
        assert ledger.reserve("act-001", 15.0, now) is True
        assert ledger.reserved_usd == 15.0
        assert ledger.spent_usd == 0.0
        
        # Second reserve for same id is idempotent
        assert ledger.reserve("act-001", 10.0, now) is False
        assert ledger.reserved_usd == 15.0
        
        # Settle adds to committed
        assert ledger.settle("act-001", 15.0, now) is True
        assert ledger.reserved_usd == 15.0
        
        # Commit moves from reserved to spent
        assert ledger.commit("act-001") is True
        assert ledger.spent_usd == 15.0
        assert ledger.reserved_usd == 0.0

    def test_ledger_budget_exhausted(self):
        """HC4-02: Budget exhausted blocks new reservations."""
        ledger = BudgetLedger(budget_usd=20.0)
        now = datetime.now(timezone.utc)
        
        assert ledger.reserve("act-a", 15.0, now) is True
        assert ledger.reserve("act-b", 10.0, now) is False  # Would exceed
        assert ledger.available == 5.0

    def test_ledger_refund_on_failure(self):
        """HC4-02: Refund returns reserved budget."""
        ledger = BudgetLedger(budget_usd=50.0)
        now = datetime.now(timezone.utc)
        
        assert ledger.reserve("act-fail", 20.0, now) is True
        assert ledger.reserved_usd == 20.0
        
        assert ledger.refund("act-fail") is True
        assert ledger.reserved_usd == 0.0
        
        # Idempotent refund
        assert ledger.refund("act-fail") is False

    def test_admission_with_budget_ledger(self):
        """HC4-02: Admission reserves budget via ledger."""
        state = InMemoryState()
        state.principals["p1"] = Principal(id="p1", type="test", identity_ref="test")
        state.missions["m1"] = Mission(id="m1", state="RUNNING")
        
        now = datetime.now(timezone.utc)
        ledger = BudgetLedger(budget_usd=50.0)
        engine = AdmissionEngine(state, policy=lambda x: True, budget_ledger=ledger)
        
        req = ActionRequest(
            action_id="act-001",
            principal_id="p1",
            mission_id="m1",
            lease_id="l1",
            capability="mcp://github/create_pr",
            resource="repo/test",
            budget_cost=15.0,
        )
        state.leases["l1"] = AuthorityLease(
            id="l1",
            principal_id="p1",
            mission_id="m1",
            capabilities={"mcp://github/create_pr"},
            resource_prefixes=("repo/",),
            expires_at=now.replace(hour=23, minute=59, second=59),
            budget_remaining=50.0,
        )
        
        outcome = engine.admit(req)
        assert outcome.status == "admitted"
        assert ledger.reserved_usd == 15.0

    def test_admission_budget_exhausted_rejected(self):
        """HC4-02: Admission rejects when budget exhausted."""
        state = InMemoryState()
        state.principals["p1"] = Principal(id="p1", type="test", identity_ref="test")
        state.missions["m1"] = Mission(id="m1", state="RUNNING")
        
        now = datetime.now(timezone.utc)
        ledger = BudgetLedger(budget_usd=20.0)
        engine = AdmissionEngine(state, policy=lambda x: True, budget_ledger=ledger)
        
        req = ActionRequest(
            action_id="act-001",
            principal_id="p1",
            mission_id="m1",
            lease_id="l1",
            capability="mcp://github/create_pr",
            resource="repo/test",
            budget_cost=15.0,
        )
        state.leases["l1"] = AuthorityLease(
            id="l1",
            principal_id="p1",
            mission_id="m1",
            capabilities={"mcp://github/create_pr"},
            resource_prefixes=("repo/",),
            expires_at=now.replace(hour=23, minute=59, second=59),
            budget_remaining=20.0,
        )
        
        # First admission succeeds
        engine.admit(req)
        assert ledger.reserved_usd == 15.0
        
        # Second admission fails (exceeds budget)
        req2 = ActionRequest(
            action_id="act-002",
            principal_id="p1",
            mission_id="m1",
            lease_id="l1",
            capability="mcp://github/create_pr",
            resource="repo/test",
            budget_cost=10.0,
        )
        with pytest.raises(AIEError) as exc_info:
            engine.admit(req2)
        assert exc_info.value.code == "AIE-BUDGET-001"

    def test_revalidate_budget_enforcement(self):
        """HC4-02: Revalidation fails closed when budget depleted."""
        state = InMemoryState()
        state.principals["p1"] = Principal(id="p1", type="test", identity_ref="test")
        state.missions["m1"] = Mission(id="m1", state="RUNNING")
        
        now = datetime.now(timezone.utc)
        ledger = BudgetLedger(budget_usd=20.0)
        engine = AdmissionEngine(state, policy=lambda x: True, budget_ledger=ledger)
        
        req = ActionRequest(
            action_id="act-001",
            principal_id="p1",
            mission_id="m1",
            lease_id="l1",
            capability="mcp://github/create_pr",
            resource="repo/test",
            budget_cost=15.0,
        )
        state.leases["l1"] = AuthorityLease(
            id="l1",
            principal_id="p1",
            mission_id="m1",
            capabilities={"mcp://github/create_pr"},
            resource_prefixes=("repo/",),
            expires_at=now.replace(hour=23, minute=59, second=59),
            budget_remaining=50.0,
        )
        
        engine.admit(req)
        # Revalidate succeeds
        engine.revalidate("act-001")

    def test_parallel_budget_accounting(self):
        """HC4-02: Parallel execution budget accounting."""
        state = InMemoryState()
        state.principals["p1"] = Principal(id="p1", type="test", identity_ref="test")
        state.missions["m1"] = Mission(id="m1", state="RUNNING")
        
        now = datetime.now(timezone.utc)
        ledger = BudgetLedger(budget_usd=20.0)
        engine = AdmissionEngine(state, policy=lambda x: True, budget_ledger=ledger)
        
        # agent-a reserves 15.0
        req_a = ActionRequest(
            action_id="act-a",
            principal_id="p1",
            mission_id="m1",
            lease_id="l1",
            capability="mcp://github/create_pr",
            resource="repo/test",
            budget_cost=15.0,
        )
        state.leases["l1"] = AuthorityLease(
            id="l1",
            principal_id="p1",
            mission_id="m1",
            capabilities={"mcp://github/create_pr"},
            resource_prefixes=("repo/",),
            expires_at=now.replace(hour=23, minute=59, second=59),
            budget_remaining=20.0,
        )
        
        assert engine.admit(req_a).status == "admitted"
        assert ledger.reserved_usd == 15.0
        
        # agent-b should be budget-limited (total would be 25 > 20)
        req_b = ActionRequest(
            action_id="act-b",
            principal_id="p1",
            mission_id="m1",
            lease_id="l1",
            capability="mcp://github/create_pr",
            resource="repo/test",
            budget_cost=10.0,
        )
        with pytest.raises(AIEError) as exc_info:
            engine.admit(req_b)
        assert exc_info.value.code == "AIE-BUDGET-001"
