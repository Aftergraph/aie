from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class BudgetLedger:
    """Frozen-semantic budget ledger with reservation semantics.
    
    Tracks budget_usd, spent_usd, reserved_usd with commit()/settle()/refund().
    Monotonic spending; replay-safe via action_id idempotency.
    """
    budget_usd: float
    spent_usd: float = 0.0
    reserved_usd: float = 0.0
    _committed: dict[str, float] = field(default_factory=dict)  # action_id -> cost
    _action_history: list[dict] = field(default_factory=list)  # replay-safe audit trail

    def reserve(self, action_id: str, cost: float, now: datetime) -> bool:
        """Reserve budget for action; returns True if successful."""
        if action_id in self._committed:
            return False  # idempotent: already committed/reserved
        if self.spent_usd + self.reserved_usd + cost > self.budget_usd:
            return False
        self.reserved_usd += cost
        self._committed[action_id] = cost
        self._action_history.append({"action_id": action_id, "cost": cost, "type": "reserve", "ts": now.isoformat()})
        return True

    def commit(self, action_id: str) -> bool:
        """Commit reserved budget to spent; returns True if successful."""
        if action_id not in self._committed:
            return False  # idempotent: never reserved
        cost = self._committed.pop(action_id)
        self.reserved_usd -= cost
        self.spent_usd += cost
        self._action_history.append({"action_id": action_id, "cost": cost, "type": "commit", "ts": datetime.now().isoformat()})
        return True

    def settle(self, action_id: str, cost: float, now: datetime) -> bool:
        """Settle final cost after execution; returns True if successful."""
        if action_id not in self._committed:
            return False  # idempotent: never reserved
        actual_cost = self._committed.pop(action_id)
        self.reserved_usd -= actual_cost
        self.reserved_usd += cost
        self._committed[action_id] = cost
        self._action_history.append({"action_id": action_id, "cost": cost, "type": "settle", "ts": now.isoformat()})
        return True

    def refund(self, action_id: str) -> bool:
        """Refund budget if action failed; returns True if successful."""
        if action_id not in self._committed:
            return False  # idempotent: never reserved
        cost = self._committed.pop(action_id)
        self.reserved_usd -= cost
        self._action_history.append({"action_id": action_id, "cost": cost, "type": "refund", "ts": datetime.now().isoformat()})
        return True

    @property
    def available(self) -> float:
        return max(0.0, self.budget_usd - self.spent_usd - self.reserved_usd)


@dataclass
class InMemoryState:
    principals: dict[str, Any] = field(default_factory=dict)
    missions: dict[str, Any] = field(default_factory=dict)
    leases: dict[str, Any] = field(default_factory=dict)
    outcomes: dict[str, Any] = field(default_factory=dict)
    # ponytail: admissions tracks action_id -> ActionRequest so the executor can
    # call engine.revalidate(action_id) immediately before executing (TH-12 variant:
    # revocation/expiry between admission and execution must fail closed).
    admissions: dict[str, Any] = field(default_factory=dict)
    evidence: list[Any] = field(default_factory=list)
