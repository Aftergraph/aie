from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .errors import AIEError
from .capabilities import capability_set_allows, capability_set_attenuates


class FunctionalRuntime:
    """Second reference implementation using plain dictionaries only.

    It intentionally does not call AdmissionEngine so conformance can catch
    semantic drift between independent implementations.
    """

    def __init__(
        self,
        state: dict[str, Any],
        policy: Callable[[dict[str, Any]], bool],
        now: Callable[[], datetime] | None = None,
        trusted_issuers: set[str] | None = None,
        supported_extensions: set[str] | None = None,
    ):
        self.state = state
        self.policy = policy
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.trusted_issuers = trusted_issuers or set()
        self.supported_extensions = supported_extensions or set()

    def _event(self, event_type: str, **attrs: Any) -> None:
        self.state.setdefault("events", []).append({"event_type": event_type, "attributes": attrs})

    def admit(self, request: dict[str, Any]) -> dict[str, Any]:
        outcomes = self.state.setdefault("outcomes", {})
        action_id = request["action_id"]
        if action_id in outcomes:
            return {"status": "prior-outcome", "error_code": "AIE-REPLAY-001"}

        for ext in request.get("extensions", []):
            if ext.get("critical") and ext.get("namespace") not in self.supported_extensions:
                raise AIEError("AIE-EXT-001")

        principals = self.state.get("principals", {})
        missions = self.state.get("missions", {})
        leases = self.state.get("leases", {})
        principal = principals.get(request["principal_id"])
        mission = missions.get(request["mission_id"])
        lease = leases.get(request["lease_id"])
        if principal is None or mission is None or lease is None:
            raise AIEError("AIE-AUTH-001")
        if lease.get("principal_id") != request["principal_id"] or lease.get("mission_id") != request["mission_id"]:
            raise AIEError("AIE-AUTH-001")
        expires = datetime.fromisoformat(lease["expires_at"])
        if expires <= self.now():
            raise AIEError("AIE-AUTH-002")
        if lease.get("revoked", False):
            raise AIEError("AIE-AUTH-003")
        if not capability_set_allows(set(lease.get("capabilities", [])), request["capability"]):
            raise AIEError("AIE-AUTH-004")
        if not any(request["resource"].startswith(p) for p in lease.get("resource_prefixes", [])):
            raise AIEError("AIE-AUTH-004")

        cost = float(request.get("budget_cost", 0))
        remaining = float(lease.get("budget_remaining", 0))
        if cost < 0 or cost > remaining:
            raise AIEError("AIE-BUDGET-001")
        lease["budget_remaining"] = remaining - cost
        self._event("budget.reserved", actionId=action_id, amount=cost)
        try:
            try:
                allowed = bool(self.policy({
                    "principal": request["principal_id"],
                    "mission": request["mission_id"],
                    "capability": request["capability"],
                    "resource": request["resource"],
                    "actionId": action_id,
                }))
            except Exception as exc:
                raise AIEError("AIE-POLICY-002") from exc
            self._event("policy.decided", actionId=action_id, allow=allowed)
            if not allowed:
                raise AIEError("AIE-POLICY-001")
            result = {"status": "admitted", "error_code": None}
            self._event("action.admitted", actionId=action_id)
            self._event("action.committed", actionId=action_id)
            outcomes[action_id] = result
            return result
        except Exception:
            lease["budget_remaining"] = remaining
            raise

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
    ) -> dict[str, Any]:
        parent = self.state["leases"][parent_lease_id]
        if parent.get("revoked", False):
            raise AIEError("AIE-AUTH-003")
        if int(parent.get("depth", 0)) >= int(parent.get("max_delegation_depth", 0)):
            raise AIEError("AIE-DELEG-002")
        if not capability_set_attenuates(set(parent.get("capabilities", [])), capabilities):
            raise AIEError("AIE-DELEG-001")
        for prefix in resource_prefixes:
            if not any(prefix.startswith(parent_prefix) for parent_prefix in parent.get("resource_prefixes", [])):
                raise AIEError("AIE-DELEG-001")
        remaining = float(parent.get("budget_remaining", 0))
        if budget < 0 or budget > remaining:
            raise AIEError("AIE-BUDGET-001")
        if child_principal_id not in self.state.get("principals", {}):
            raise AIEError("AIE-AUTH-001")
        parent_expires = datetime.fromisoformat(parent["expires_at"])
        child = {
            "id": child_lease_id,
            "principal_id": child_principal_id,
            "mission_id": parent["mission_id"],
            "capabilities": sorted(capabilities),
            "resource_prefixes": list(resource_prefixes),
            "expires_at": min(parent_expires, self.now() + ttl).isoformat(),
            "budget_remaining": budget,
            "revoked": False,
            "parent_lease_id": parent_lease_id,
            "depth": int(parent.get("depth", 0)) + 1,
            "max_delegation_depth": int(parent.get("max_delegation_depth", 0)),
        }
        parent["budget_remaining"] = remaining - budget
        self.state["leases"][child_lease_id] = child
        self._event("delegation.created", parentLeaseId=parent_lease_id, childLeaseId=child_lease_id)
        return child

    def revoke(self, lease_id: str) -> None:
        pending = [lease_id]
        while pending:
            current = pending.pop()
            lease = self.state.get("leases", {}).get(current)
            if not lease or lease.get("revoked", False):
                continue
            lease["revoked"] = True
            self._event("authority.revoked", leaseId=current)
            for child in self.state.get("leases", {}).values():
                if child.get("parent_lease_id") == current:
                    pending.append(child["id"])

    def authorize_topology_mutation(self, *, actor: str, mutation: str, target: str) -> bool:
        try:
            allowed = bool(self.policy({"type": "topology", "actor": actor, "mutation": mutation, "target": target}))
        except Exception as exc:
            raise AIEError("AIE-TOPO-001") from exc
        if not allowed:
            raise AIEError("AIE-TOPO-001")
        self._event("topology.mutated", actor=actor, mutation=mutation, target=target)
        return True

    def verify_federated_identity(self, *, issuer: str, clock_skew: timedelta, max_clock_skew: timedelta, revocation_fresh: bool) -> bool:
        if issuer not in self.trusted_issuers:
            raise AIEError("AIE-FED-001")
        if abs(clock_skew) > max_clock_skew:
            raise AIEError("AIE-FED-002")
        if not revocation_fresh:
            raise AIEError("AIE-FRESH-001")
        return True
