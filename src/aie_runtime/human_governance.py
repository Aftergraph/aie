"""Human-governance authority inside AIE (binding HUMAN-GOVERNANCE-V1).

AIE owns principal/authority semantics: delegation, mission envelopes,
budgets, authority lifecycle, and revocation. Human role labels (owner,
reviewer, auditor, operator) are convenience templates for assigning
grants; a label alone permits nothing. Only the issued AIE grant is the
authority truth: a principal may execute only what a live grant covers.

Seam notes (binding):
- Consent != Authority: ``authorize_use`` accepts an optional ``consent``
  flag for caller context but it never affects the decision. Consent is
  enforced by trust-gateway, not here.
- Revocation invalidates downstream effective use (cascade); audit
  retention is out of scope for this module.
- Fail closed on consequential ambiguity: unknown grants, expired or
  revoked grants, envelope/capability/resource drift, and budget overruns
  all deny with AIE-* codes, never permit.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Callable

from .capabilities import capability_set_allows, capability_set_attenuates
from .errors import AIEError

ROLE_LABELS: tuple[str, ...] = ("owner", "reviewer", "auditor", "operator")

# Convenience templates for assigning grants. Suggestions only: presenting a
# label (or its template) never authorizes anything.
ROLE_TEMPLATES: dict[str, dict[str, frozenset[str]]] = {
    "owner": {"capabilities": frozenset({"repo.read", "repo.write", "ci.run"})},
    "reviewer": {"capabilities": frozenset({"repo.read", "review.approve"})},
    "auditor": {"capabilities": frozenset({"repo.read", "audit.read"})},
    "operator": {"capabilities": frozenset({"repo.read", "ci.run"})},
}


def role_template(label: str) -> dict[str, frozenset[str]]:
    """Return the suggested capability set for a role label.

    The suggestion carries no authority; it only seeds grant issuance.
    """
    try:
        return ROLE_TEMPLATES[label]
    except KeyError as exc:
        raise ValueError(f"unknown role label: {label!r}") from exc


@dataclass(frozen=True)
class HumanPrincipalRecord:
    # Frozen: register_principal constructs a new record per call and the
    # registry stores it by reference while also handing it to the caller,
    # so a mutable record would let holder code rewrite identity_ref/labels
    # in place and silently change registry identity truth (defeating the
    # rebind-deny). Mutating a returned handle raises instead.
    principal_id: str
    identity_ref: str
    labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class HumanGrant:
    # Frozen: holders only ever see snapshots. All state transitions go
    # through dataclasses.replace + re-store in the registry, so mutating
    # a returned handle raises instead of corrupting live authority.
    grant_id: str
    principal_id: str
    mission_id: str
    tenant_id: str
    capabilities: frozenset[str]
    resource_prefixes: tuple[str, ...]
    budget_ceiling: float
    budget_remaining: float
    issuer: str
    issued_at: datetime
    expires_at: datetime
    revoked: bool = False
    parent_grant_id: str | None = None
    depth: int = 0
    max_delegation_depth: int = 0


class HumanGovernanceAuthority:
    """Registry and enforcement point for human-governance grants."""

    def __init__(
        self,
        clock: Callable[[], datetime] | None = None,
        authorized_issuers: set[str] | None = None,
    ) -> None:
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        # Bootstrap trust roots allowed to issue root grants. Principals can
        # never self-issue: issuance requires an authorized issuer distinct
        # from the subject, and chained issuance flows through delegate().
        # Immutable: a frozenset snapshot behind a read-only property, so no
        # holder can enroll a new trust root via .add().
        self._authorized_issuers: frozenset[str] = frozenset(
            authorized_issuers or frozenset()
        )
        self._principals: dict[str, HumanPrincipalRecord] = {}
        self._grants: dict[str, HumanGrant] = {}

    @property
    def authorized_issuers(self) -> frozenset[str]:
        """Trust roots allowed to issue root grants (immutable snapshot)."""
        return frozenset(self._authorized_issuers)

    def grant(self, grant_id: str) -> HumanGrant | None:
        """Return the live grant snapshot, or None when unknown.

        Safe to hand out: HumanGrant is frozen, so holders cannot mutate
        live authority through the returned handle.
        """
        return self._grants.get(grant_id)

    def principal(self, principal_id: str) -> HumanPrincipalRecord | None:
        """Return the principal record, or None when unknown.

        Safe to hand out: HumanPrincipalRecord is frozen.
        """
        return self._principals.get(principal_id)

    # -- principals ----------------------------------------------------

    def register_principal(
        self,
        principal_id: str,
        identity_ref: str,
        labels: tuple[str, ...] = (),
    ) -> HumanPrincipalRecord:
        if not principal_id or not identity_ref:
            raise ValueError("principal_id and identity_ref are required")
        existing = self._principals.get(principal_id)
        if existing is not None and existing.identity_ref != identity_ref:
            # No silent rebind: a principal_id is bound to its identity_ref.
            # Re-registration carries labels only for the same identity.
            raise AIEError("AIE-AUTH-001")
        record = HumanPrincipalRecord(
            principal_id=principal_id,
            identity_ref=identity_ref,
            labels=tuple(labels),
        )
        # Re-registration updates descriptive labels only; authority follows
        # the live grants, never the labels.
        self._principals[principal_id] = record
        return record

    # -- issuance ------------------------------------------------------

    def issue_grant(
        self,
        *,
        grant_id: str,
        principal_id: str,
        mission_id: str,
        tenant_id: str,
        capabilities: set[str] | frozenset[str],
        resource_prefixes: tuple[str, ...],
        budget: float,
        ttl: timedelta,
        issuer: str,
        max_delegation_depth: int = 0,
    ) -> HumanGrant:
        if not grant_id or grant_id in self._grants:
            raise ValueError("grant_id must be unique and non-empty")
        if issuer == principal_id:
            # Self-granted authority is never valid.
            raise AIEError("AIE-AUTH-001")
        if issuer not in self._authorized_issuers:
            raise AIEError("AIE-AUTH-001")
        if principal_id not in self._principals:
            raise AIEError("AIE-AUTH-001")
        caps = frozenset(capabilities)
        if (
            not mission_id
            or not tenant_id
            or not caps
            or not resource_prefixes
            or any(not p for p in resource_prefixes)
        ):
            raise ValueError("mission, tenant, capabilities, and resources are required")
        if (
            not math.isfinite(budget)
            or budget < 0
            or max_delegation_depth < 0
            or ttl <= timedelta(0)
        ):
            raise ValueError("budget, depth, and ttl must be non-degenerate")
        now = self.clock()
        grant = HumanGrant(
            grant_id=grant_id,
            principal_id=principal_id,
            mission_id=mission_id,
            tenant_id=tenant_id,
            capabilities=caps,
            resource_prefixes=tuple(resource_prefixes),
            budget_ceiling=budget,
            budget_remaining=budget,
            issuer=issuer,
            issued_at=now,
            expires_at=now + ttl,
            max_delegation_depth=max_delegation_depth,
        )
        self._grants[grant_id] = grant
        return grant

    # -- delegation ----------------------------------------------------

    def delegate(
        self,
        *,
        parent_grant_id: str,
        delegated_by: str,
        grant_id: str,
        principal_id: str,
        capabilities: set[str] | frozenset[str],
        resource_prefixes: tuple[str, ...],
        budget: float,
        ttl: timedelta,
    ) -> HumanGrant:
        parent = self._grants.get(parent_grant_id)
        if parent is None:
            raise AIEError("AIE-AUTH-001")
        if delegated_by != parent.principal_id:
            # Only the holder delegates their own authority: a stranger
            # cannot mint a child grant from another principal's live grant.
            raise AIEError("AIE-AUTH-001")
        if parent.revoked or self._ancestor_revoked(parent):
            raise AIEError("AIE-AUTH-003")
        if parent.expires_at <= self.clock():
            raise AIEError("AIE-AUTH-002")
        if not grant_id or grant_id in self._grants:
            raise ValueError("grant_id must be unique and non-empty")
        if parent.depth >= parent.max_delegation_depth:
            raise AIEError("AIE-DELEG-002")
        caps = frozenset(capabilities)
        if not caps or not resource_prefixes:
            raise AIEError("AIE-DELEG-001")
        if not capability_set_attenuates(parent.capabilities, caps):
            raise AIEError("AIE-DELEG-001")
        for child_prefix in resource_prefixes:
            if not child_prefix or not any(
                child_prefix.startswith(p) for p in parent.resource_prefixes
            ):
                raise AIEError("AIE-DELEG-001")
        if (
            not math.isfinite(budget)
            or budget < 0
            or budget > parent.budget_remaining
        ):
            raise AIEError("AIE-BUDGET-001")
        if principal_id not in self._principals:
            raise AIEError("AIE-AUTH-001")
        if ttl <= timedelta(0):
            raise ValueError("ttl must be positive")
        now = self.clock()
        self._grants[parent.grant_id] = replace(
            parent, budget_remaining=parent.budget_remaining - budget
        )
        child = HumanGrant(
            grant_id=grant_id,
            principal_id=principal_id,
            # Delegation never escapes the parent's mission/tenant envelope.
            mission_id=parent.mission_id,
            tenant_id=parent.tenant_id,
            capabilities=caps,
            resource_prefixes=tuple(resource_prefixes),
            budget_ceiling=budget,
            budget_remaining=budget,
            issuer=parent.principal_id,
            issued_at=now,
            expires_at=min(parent.expires_at, now + ttl),
            parent_grant_id=parent.grant_id,
            depth=parent.depth + 1,
            max_delegation_depth=parent.max_delegation_depth,
        )
        self._grants[grant_id] = child
        return child

    # -- enforcement ---------------------------------------------------

    def authorize_use(
        self,
        *,
        grant_id: str,
        principal_id: str,
        capability: str,
        resource: str,
        mission_id: str,
        tenant_id: str,
        cost: float = 0.0,
        consent: bool | None = None,
    ) -> bool:
        """Authorize one use against the live grant registry.

        ``consent`` is accepted for caller context and explicitly ignored:
        consent is not authority (enforced by trust-gateway, not AIE).
        Returns True on allow; raises AIEError on any deny. Successful
        calls deduct ``cost`` from the grant budget.
        """
        _ = consent
        grant = self._grants.get(grant_id)
        if grant is None or grant.principal_id != principal_id:
            raise AIEError("AIE-AUTH-001")
        if principal_id not in self._principals:
            raise AIEError("AIE-AUTH-001")
        now = self.clock()
        if grant.expires_at <= now or self._ancestor_expired(grant, now):
            raise AIEError("AIE-AUTH-002")
        if grant.revoked or self._ancestor_revoked(grant):
            raise AIEError("AIE-AUTH-003")
        if mission_id != grant.mission_id or tenant_id != grant.tenant_id:
            raise AIEError("AIE-AUTH-004")
        if (
            not capability
            or not resource
            or not capability_set_allows(grant.capabilities, capability)
            or not any(resource.startswith(p) for p in grant.resource_prefixes)
        ):
            raise AIEError("AIE-AUTH-004")
        if (
            not math.isfinite(cost)
            or cost < 0
            or cost > grant.budget_remaining
        ):
            raise AIEError("AIE-BUDGET-001")
        self._grants[grant_id] = replace(
            grant, budget_remaining=grant.budget_remaining - cost
        )
        return True

    def authorize_by_label(self, label: str, **kwargs) -> bool:
        """A role label alone permits nothing: always denies."""
        _ = kwargs
        if label not in ROLE_TEMPLATES:
            raise ValueError(f"unknown role label: {label!r}")
        raise AIEError("AIE-AUTH-004")

    # -- lifecycle -----------------------------------------------------

    def revoke(self, grant_id: str) -> None:
        if grant_id not in self._grants:
            raise AIEError("AIE-AUTH-001")
        stack = [grant_id]
        while stack:
            current = stack.pop()
            grant = self._grants.get(current)
            if grant is None or grant.revoked:
                continue
            self._grants[current] = replace(grant, revoked=True)
            stack.extend(
                g.grant_id for g in self._grants.values() if g.parent_grant_id == current
            )

    def is_live(self, grant_id: str) -> bool:
        grant = self._grants.get(grant_id)
        if grant is None or grant.revoked or self._ancestor_revoked(grant):
            return False
        return grant.expires_at > self.clock()

    # -- ancestry guards (defense in depth behind the revoke cascade) ---

    def _ancestor_revoked(self, grant: HumanGrant) -> bool:
        seen: set[str] = set()
        current = grant.parent_grant_id
        while current is not None and current not in seen:
            seen.add(current)
            parent = self._grants.get(current)
            if parent is None:
                return True  # dangling lineage fails closed
            if parent.revoked:
                return True
            current = parent.parent_grant_id
        return False

    def _ancestor_expired(self, grant: HumanGrant, now: datetime) -> bool:
        seen: set[str] = set()
        current = grant.parent_grant_id
        while current is not None and current not in seen:
            seen.add(current)
            parent = self._grants.get(current)
            if parent is None:
                return True  # dangling lineage fails closed
            if parent.expires_at <= now:
                return True
            current = parent.parent_grant_id
        return False
