from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from typing import Any

from .engine import AuthorityLease
from .errors import AIEError


def _canonical_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def export_authority_envelope(lease: AuthorityLease, *, issuer: str, secret: bytes) -> dict[str, Any]:
    authority = {
        "id": lease.id,
        "principal_id": lease.principal_id,
        "mission_id": lease.mission_id,
        "capabilities": sorted(lease.capabilities),
        "resource_prefixes": list(lease.resource_prefixes),
        "expires_at": lease.expires_at.isoformat(),
        "budget_remaining": lease.budget_remaining,
        "revoked": lease.revoked,
        "parent_lease_id": lease.parent_lease_id,
        "depth": lease.depth,
        "max_delegation_depth": lease.max_delegation_depth,
    }
    unsigned = {"version": "aie-authority-envelope/0.1", "issuer": issuer, "authority": authority}
    signature = hmac.new(secret, _canonical_bytes(unsigned), hashlib.sha256).hexdigest()
    return {**unsigned, "signature": {"alg": "HS256-demo", "value": signature}}


def import_authority_envelope(
    envelope: dict[str, Any],
    *,
    keyring: dict[str, bytes],
    trusted_issuers: set[str],
    now: datetime,
) -> AuthorityLease:
    issuer = envelope.get("issuer")
    if issuer not in trusted_issuers or issuer not in keyring:
        raise AIEError("AIE-FED-001")
    signature = envelope.get("signature", {}).get("value", "")
    unsigned = {k: v for k, v in envelope.items() if k != "signature"}
    expected = hmac.new(keyring[issuer], _canonical_bytes(unsigned), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise AIEError("AIE-FED-001")
    a = envelope["authority"]
    expires = datetime.fromisoformat(a["expires_at"])
    if expires <= now:
        raise AIEError("AIE-AUTH-002")
    if a.get("revoked", False):
        raise AIEError("AIE-AUTH-003")
    return AuthorityLease(
        id=a["id"],
        principal_id=a["principal_id"],
        mission_id=a["mission_id"],
        capabilities=set(a["capabilities"]),
        resource_prefixes=tuple(a["resource_prefixes"]),
        expires_at=expires,
        budget_remaining=float(a["budget_remaining"]),
        revoked=bool(a.get("revoked", False)),
        parent_lease_id=a.get("parent_lease_id"),
        depth=int(a.get("depth", 0)),
        max_delegation_depth=int(a.get("max_delegation_depth", 0)),
    )
