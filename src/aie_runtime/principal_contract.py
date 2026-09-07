"""Canonical principal/1.0 projection for Platform Convergence V2.1.

This module adapts the existing AIE runtime Principal without changing its
runtime semantics. Identity resolution does not grant capabilities, approval
rights, roles, or authority.
"""
from __future__ import annotations

import re
from typing import Any

_PRINCIPAL_ID = re.compile(r"^prn_[a-f0-9]{32}$")
_TENANT_ID = re.compile(r"^ten_[a-f0-9]{32}$")
_CANONICAL_TYPES = {
    "human": "human",
    "agent": "agent",
    "bot": "agent",
    "service": "service",
    "worker": "worker",
}
_STATUSES = {"active", "disabled"}


def canonical_principal_type(runtime_type: str) -> str:
    """Map runtime Principal types to principal/1.0 actor types."""
    try:
        return _CANONICAL_TYPES[runtime_type]
    except KeyError as exc:
        raise ValueError("unsupported principal type") from exc


def _require_match(value: str, pattern: re.Pattern[str], field: str) -> None:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValueError(f"invalid {field}")


def principal_to_contract(
    *,
    principal: Any,
    principal_id: str,
    tenant_id: str,
    status: str = "active",
) -> dict[str, str]:
    """Project an existing runtime Principal into canonical principal/1.0.

    The supplied canonical IDs are bindings created by the owning platform
    identity layer. The runtime Principal's legacy ``id`` is intentionally not
    promoted or reinterpreted as a canonical principal ID.
    """
    _require_match(principal_id, _PRINCIPAL_ID, "principal_id")
    _require_match(tenant_id, _TENANT_ID, "tenant_id")
    if status not in _STATUSES:
        raise ValueError("invalid principal status")

    identity_ref = getattr(principal, "identity_ref", None)
    if not isinstance(identity_ref, str) or not identity_ref:
        raise ValueError("invalid identity_ref")

    return {
        "schema": "principal/1.0",
        "principal_id": principal_id,
        "tenant_id": tenant_id,
        "type": canonical_principal_type(getattr(principal, "type", "")),
        "identity_ref": identity_ref,
        "status": status,
    }
