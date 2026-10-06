from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Mapping

from aie_runtime.engine import AuthorityLease, Mission, Principal
from aie_runtime.errors import AIEError
from aie_runtime.human_governance import HumanGovernanceAuthority
from aie_runtime.persistent_state import PersistentState

PRINCIPAL_RE = re.compile(r"^prn_[a-f0-9]{32}$")
TENANT_RE = re.compile(r"^ten_[a-f0-9]{32}$")
AUTHORITY_RE = re.compile(r"^auth_[a-f0-9]{32}$")
IDENTITY_RE = re.compile(r"^lume:access-sub-sha256:[a-f0-9]{64}$")


class PlatformAuthorityError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PlatformAuthorityProfile:
    issuer: str
    mission_id: str
    capabilities: frozenset[str]
    resource_prefixes: tuple[str, ...]
    budget: float
    ttl_seconds: int

    @classmethod
    def parse(cls, value: Mapping[str, Any] | None) -> "PlatformAuthorityProfile":
        if not isinstance(value, Mapping):
            raise PlatformAuthorityError("profile_unconfigured", "platform authority profile is not configured")
        issuer = str(value.get("issuer", "")).strip()
        mission_id = str(value.get("mission_id", "")).strip()
        capabilities_raw = value.get("capabilities")
        resources_raw = value.get("resource_prefixes")
        budget = value.get("budget")
        ttl = value.get("ttl_seconds")
        if (
            not issuer
            or not mission_id
            or not isinstance(capabilities_raw, list)
            or not capabilities_raw
            or any(not isinstance(item, str) or not item.strip() for item in capabilities_raw)
            or not isinstance(resources_raw, list)
            or not resources_raw
            or any(not isinstance(item, str) or not item.strip() for item in resources_raw)
            or not isinstance(budget, (int, float))
            or isinstance(budget, bool)
            or not math.isfinite(float(budget))
            or float(budget) < 0
            or not isinstance(ttl, int)
            or isinstance(ttl, bool)
            or ttl <= 0
        ):
            raise PlatformAuthorityError("profile_invalid", "platform authority profile is invalid")
        return cls(
            issuer=issuer,
            mission_id=mission_id,
            capabilities=frozenset(item.strip() for item in capabilities_raw),
            resource_prefixes=tuple(item.strip() for item in resources_raw),
            budget=float(budget),
            ttl_seconds=ttl,
        )


def _lease_id(profile: PlatformAuthorityProfile, principal_id: str, tenant_id: str, idempotency_key: str) -> str:
    payload = "\0".join(
        [
            "aie-platform-authority/1",
            profile.issuer,
            profile.mission_id,
            principal_id,
            tenant_id,
            idempotency_key,
            ",".join(sorted(profile.capabilities)),
            ",".join(profile.resource_prefixes),
        ]
    ).encode("utf-8")
    return "auth_" + hashlib.sha256(payload).hexdigest()[:32]


class PlatformAuthorityProvisioner:
    def __init__(self, gateway: Any) -> None:
        self.gateway = gateway

    def ensure(
        self,
        *,
        principal_id: str,
        tenant_id: str,
        identity_ref: str,
        idempotency_key: str,
    ) -> AuthorityLease:
        if not isinstance(self.gateway.state, PersistentState):
            raise PlatformAuthorityError("durable_state_required", "platform authority provisioning requires PersistentState")
        if PRINCIPAL_RE.fullmatch(principal_id) is None:
            raise PlatformAuthorityError("invalid_principal", "principal_id is invalid")
        if TENANT_RE.fullmatch(tenant_id) is None:
            raise PlatformAuthorityError("invalid_tenant", "tenant_id is invalid")
        if IDENTITY_RE.fullmatch(identity_ref) is None:
            raise PlatformAuthorityError("invalid_identity", "identity_ref is invalid")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 256:
            raise PlatformAuthorityError("invalid_idempotency_key", "idempotency_key is invalid")

        profile = PlatformAuthorityProfile.parse(self.gateway.platform_authority_profile)
        lease_id = _lease_id(profile, principal_id, tenant_id, idempotency_key.strip())
        if AUTHORITY_RE.fullmatch(lease_id) is None:
            raise PlatformAuthorityError("internal_id_error", "authority id generation failed")

        state = self.gateway.state
        existing_principal = state.principals.get(principal_id)
        if existing_principal is not None and existing_principal.identity_ref != identity_ref:
            raise PlatformAuthorityError("principal_rebind", "principal identity rebind denied")

        existing = state.leases.get(lease_id)
        if existing is not None:
            exact = (
                existing.principal_id == principal_id
                and existing.mission_id == profile.mission_id
                and set(existing.capabilities) == set(profile.capabilities)
                and tuple(existing.resource_prefixes) == profile.resource_prefixes
            )
            if not exact:
                raise PlatformAuthorityError("idempotency_conflict", "authority idempotency conflict")
            if existing.revoked or self.gateway.store.is_revoked(existing.id):
                raise PlatformAuthorityError("authority_revoked", "authority is revoked; use a new idempotency key")
            if existing.expires_at <= self.gateway.clock():
                raise PlatformAuthorityError("authority_expired", "authority is expired; use a new idempotency key")
            return existing

        governance = HumanGovernanceAuthority(
            clock=self.gateway.clock,
            authorized_issuers={profile.issuer},
        )
        governance.register_principal(principal_id, identity_ref=identity_ref)
        grant = governance.issue_grant(
            grant_id=lease_id,
            principal_id=principal_id,
            mission_id=profile.mission_id,
            tenant_id=tenant_id,
            capabilities=profile.capabilities,
            resource_prefixes=profile.resource_prefixes,
            budget=profile.budget,
            ttl=timedelta(seconds=profile.ttl_seconds),
            issuer=profile.issuer,
        )

        mission = state.missions.get(profile.mission_id)
        if mission is not None and mission.state not in {"READY", "AUTHORIZED", "RUNNING"}:
            raise PlatformAuthorityError("mission_not_active", "platform authority mission is not active")

        state.principals[principal_id] = Principal(principal_id, "human", identity_ref)
        if mission is None:
            state.missions[profile.mission_id] = Mission(profile.mission_id, "RUNNING")
        lease = AuthorityLease(
            id=grant.grant_id,
            principal_id=grant.principal_id,
            mission_id=grant.mission_id,
            capabilities=set(grant.capabilities),
            resource_prefixes=grant.resource_prefixes,
            expires_at=grant.expires_at,
            budget_remaining=grant.budget_remaining,
            revoked=grant.revoked,
            parent_lease_id=None,
            depth=0,
            max_delegation_depth=grant.max_delegation_depth,
        )
        state.leases[lease.id] = lease
        self.gateway.store.initialize_budget(lease.id, lease.budget_remaining)
        return lease
