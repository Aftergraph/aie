from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

from .errors import AIEError
from .capabilities import capability_set_allows, capability_set_attenuates
from .store import InMemoryState, BudgetLedger


@dataclass(frozen=True)
class Principal:
    id: str
    type: str
    identity_ref: str


# Canonical mission lifecycle states — must match
# after-graph-governance/docs/contracts/mission-state/1.0.json enum (H9 alignment).
MISSION_STATES = frozenset({
    "DRAFT", "READY", "AUTHORIZED", "RUNNING", "PAUSED", "VERIFYING",
    "VERIFIED", "RECOVERING", "NEEDS_INPUT", "FAILED", "CANCELLED", "REVOKED",
})


@dataclass(frozen=True)
class Mission:
    id: str
    state: str


@dataclass
class AuthorityLease:
    id: str
    principal_id: str
    mission_id: str
    capabilities: set[str]
    resource_prefixes: tuple[str, ...]
    expires_at: datetime
    budget_remaining: float
    revoked: bool = False
    parent_lease_id: str | None = None
    depth: int = 0
    max_delegation_depth: int = 0


@dataclass(frozen=True)
class ActionRequest:
    action_id: str
    principal_id: str
    mission_id: str
    lease_id: str
    capability: str
    resource: str
    budget_cost: float = 0
    extensions: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class AdmissionOutcome:
    status: str
    error_code: str | None = None


@dataclass(frozen=True)
class EvidenceRecord:
    event_type: str
    timestamp: datetime
    attributes: dict[str, Any] = field(default_factory=dict)


PolicyFn = Callable[[dict[str, Any]], bool]


class AdmissionEngine:
    def __init__(
        self,
        state: InMemoryState,
        policy: PolicyFn,
        clock: Callable[[], datetime] | None = None,
        trusted_issuers: set[str] | None = None,
        supported_extensions: set[str] | None = None,
        budget_ledger: BudgetLedger | None = None,
    ):
        self.state = state
        self.policy = policy
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.trusted_issuers = trusted_issuers or set()
        self.supported_extensions = supported_extensions or set()
        self.budget_ledger = budget_ledger

    def _emit(self, event_type: str, **attributes: Any) -> None:
        self.state.evidence.append(EvidenceRecord(event_type, self.clock(), attributes))

    def _check_extensions(self, request: ActionRequest) -> None:
        for ext in request.extensions:
            if ext.get("critical") and ext.get("namespace") not in self.supported_extensions:
                raise AIEError("AIE-EXT-001")

    def _resolve(self, request: ActionRequest) -> AuthorityLease:
        principal = self.state.principals.get(request.principal_id)
        mission = self.state.missions.get(request.mission_id)
        if principal is None or mission is None:
            raise AIEError("AIE-AUTH-001")
        lease = self.state.leases.get(request.lease_id)
        if lease is None or lease.principal_id != principal.id or lease.mission_id != mission.id:
            raise AIEError("AIE-AUTH-001")
        if lease.expires_at <= self.clock():
            raise AIEError("AIE-AUTH-002")
        if lease.revoked:
            raise AIEError("AIE-AUTH-003")
        if not capability_set_allows(lease.capabilities, request.capability) or not any(
            request.resource.startswith(prefix) for prefix in lease.resource_prefixes
        ):
            raise AIEError("AIE-AUTH-004")
        return lease

    def admit(self, request: ActionRequest) -> AdmissionOutcome:
        prior = self.state.outcomes.get(request.action_id)
        if prior is not None:
            return AdmissionOutcome("prior-outcome", "AIE-REPLAY-001")

        self._check_extensions(request)
        lease = self._resolve(request)

        if request.budget_cost < 0 or request.budget_cost > lease.budget_remaining:
            raise AIEError("AIE-BUDGET-001")

        # HC4: Budget ledger enforcement - reserve on admission.
        # Frozen evidence contract: budget.reserved is emitted here (first in the
        # ordered evidence sequence) whether or not a ledger is attached; the
        # ledger enforces the reservation ceiling, the lease keeps its
        # budget_remaining mirror for conformance.
        if self.budget_ledger and not self.budget_ledger.reserve(
            request.action_id, request.budget_cost, self.clock()
        ):
            raise AIEError("AIE-BUDGET-001")
        self._emit("budget.reserved", actionId=request.action_id, amount=request.budget_cost)
        if not self.budget_ledger:
            lease.budget_remaining -= request.budget_cost

        try:
            decision_input = {
                "principal": request.principal_id,
                "mission": request.mission_id,
                "capability": request.capability,
                "resource": request.resource,
                "actionId": request.action_id,
            }
            try:
                allowed = bool(self.policy(decision_input))
            except Exception as exc:
                raise AIEError("AIE-POLICY-002") from exc
            self._emit("policy.decided", actionId=request.action_id, allow=allowed)
            if not allowed:
                raise AIEError("AIE-POLICY-001")

            outcome = AdmissionOutcome("admitted")
            self.state.admissions[request.action_id] = request
            self._emit("action.admitted", actionId=request.action_id)
            self._emit("action.committed", actionId=request.action_id)
            self.state.outcomes[request.action_id] = outcome
            return outcome
        except Exception:
            # Refund reservation on failure
            if self.budget_ledger:
                self.budget_ledger.refund(request.action_id)
            if not self.budget_ledger:
                lease.budget_remaining += request.budget_cost
            raise

    def revalidate(self, action_id: str) -> None:
        """Execution-time revalidation (TH-12 fix).

        The executor MUST call this immediately before running an admitted action.
        Closes the window between admission and execution: revocation (including
        parent-lease cascades), lease expiry, and capability/resource drift fail
        closed here. AIE-AUTH-004 marks execution-time rejection.
        """
        request = self.state.admissions.get(action_id)
        if request is None:
            raise AIEError("AIE-AUTH-004")
        # Re-resolve against live state: _raise_on drift/expiry/revocation.
        try:
            self._resolve(request)
        except AIEError:
            raise

        # HC4: Budget floor - must still be coverable at execution time
        if self.budget_ledger:
            # reserved_usd already includes this action's cost from admission
            if self.budget_ledger.spent_usd + self.budget_ledger.reserved_usd > self.budget_ledger.budget_usd:
                raise AIEError("AIE-BUDGET-002")
        else:
            lease = self.state.leases[request.lease_id]
            if request.budget_cost > lease.budget_remaining:
                raise AIEError("AIE-BUDGET-002")
        self._emit("action.revalidated", actionId=action_id, leaseId=request.lease_id)

    def delegate(
        self,
        *,
        parent_lease_id: str,
        child_lease_id: str,
        child_principal_id: str,
        capabilities: set[str],
        resource_prefixes: tuple[str, ...],
        budget: float,
        ttl: timedelta,
    ) -> AuthorityLease:
        parent = self.state.leases[parent_lease_id]
        if parent.revoked:
            raise AIEError("AIE-AUTH-003")
        if parent.depth >= parent.max_delegation_depth:
            raise AIEError("AIE-DELEG-002")
        if not capability_set_attenuates(parent.capabilities, capabilities):
            raise AIEError("AIE-DELEG-001")
        for child_prefix in resource_prefixes:
            if not any(child_prefix.startswith(parent_prefix) for parent_prefix in parent.resource_prefixes):
                raise AIEError("AIE-DELEG-001")
        # HC4: Budget ledger enforcement for delegation chains
        if self.budget_ledger:
            if budget > self.budget_ledger.available:
                raise AIEError("AIE-BUDGET-001")
        else:
            if budget < 0 or budget > parent.budget_remaining:
                raise AIEError("AIE-BUDGET-001")
        if child_principal_id not in self.state.principals:
            raise AIEError("AIE-AUTH-001")
        parent.budget_remaining -= budget
        child = AuthorityLease(
            id=child_lease_id,
            principal_id=child_principal_id,
            mission_id=parent.mission_id,
            capabilities=set(capabilities),
            resource_prefixes=tuple(resource_prefixes),
            expires_at=min(parent.expires_at, self.clock() + ttl),
            budget_remaining=budget,
            parent_lease_id=parent.id,
            depth=parent.depth + 1,
            max_delegation_depth=parent.max_delegation_depth,
        )
        self.state.leases[child.id] = child
        self._emit("delegation.created", parentLeaseId=parent.id, childLeaseId=child.id)
        return child

    def revoke(self, lease_id: str) -> None:
        stack = [lease_id]
        while stack:
            current = stack.pop()
            lease = self.state.leases.get(current)
            if lease is None or lease.revoked:
                continue
            lease.revoked = True
            self._emit("authority.revoked", leaseId=current)
            stack.extend(
                child.id for child in self.state.leases.values() if child.parent_lease_id == current
            )

    def authorize_topology_mutation(self, *, actor: str, mutation: str, target: str) -> bool:
        try:
            allowed = bool(self.policy({"type": "topology", "actor": actor, "mutation": mutation, "target": target}))
        except Exception as exc:
            raise AIEError("AIE-TOPO-001") from exc
        if not allowed:
            raise AIEError("AIE-TOPO-001")
        self._emit("topology.mutated", actor=actor, mutation=mutation, target=target)
        return True

    def verify_federated_identity(
        self,
        *,
        issuer: str,
        clock_skew: timedelta,
        max_clock_skew: timedelta,
        revocation_fresh: bool,
    ) -> bool:
        if issuer not in self.trusted_issuers:
            raise AIEError("AIE-FED-001")
        if abs(clock_skew) > max_clock_skew:
            raise AIEError("AIE-FED-002")
        if not revocation_fresh:
            raise AIEError("AIE-FRESH-001")
        return True
