"""TDD contract tests for Platform Convergence V2.1 principal/1.0."""
from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "spec" / "contracts" / "principal" / "1.0.json"
MODULE = "aie_runtime.principal_contract"


def _adapter():
    spec = importlib.util.find_spec(MODULE)
    assert spec is not None, "principal/1.0 adapter module is not implemented"
    return importlib.import_module(MODULE)


def _schema():
    assert SCHEMA.is_file(), "principal/1.0 schema is not implemented"
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def test_schema_is_strict_and_has_only_canonical_actor_fields():
    schema = _schema()
    assert schema["additionalProperties"] is False
    assert schema["required"] == [
        "schema", "principal_id", "tenant_id", "type", "identity_ref", "status"
    ]
    assert schema["properties"]["type"]["enum"] == ["human", "agent", "service", "worker"]


def test_runtime_types_map_to_canonical_principal_types():
    adapter = _adapter()
    expected = {
        "human": "human",
        "agent": "agent",
        "bot": "agent",
        "service": "service",
        "worker": "worker",
    }
    assert {k: adapter.canonical_principal_type(k) for k in expected} == expected


def test_unknown_runtime_type_fails_closed():
    adapter = _adapter()
    with pytest.raises(ValueError, match="unsupported principal type"):
        adapter.canonical_principal_type("admin-superbot")


def test_principal_projection_preserves_identity_without_authority_fields():
    from aie_runtime.engine import Principal

    adapter = _adapter()
    principal = Principal(id="legacy-bot-1", type="bot", identity_ref="tg:worker-1")
    result = adapter.principal_to_contract(
        principal=principal,
        principal_id="prn_0123456789abcdef0123456789abcdef",
        tenant_id="ten_fedcba9876543210fedcba9876543210",
    )
    assert result == {
        "schema": "principal/1.0",
        "principal_id": "prn_0123456789abcdef0123456789abcdef",
        "tenant_id": "ten_fedcba9876543210fedcba9876543210",
        "type": "agent",
        "identity_ref": "tg:worker-1",
        "status": "active",
    }
    forbidden = {"capabilities", "roles", "approvals", "authority", "authority_lease_id"}
    assert forbidden.isdisjoint(result)


@pytest.mark.parametrize(
    "principal_id,tenant_id",
    [
        ("prn_short", "ten_fedcba9876543210fedcba9876543210"),
        ("prn_0123456789ABCDEF0123456789ABCDEF", "ten_fedcba9876543210fedcba9876543210"),
        ("prn_0123456789abcdef0123456789abcdef", "tenant_fedcba9876543210fedcba9876543210"),
        ("prn_0123456789abcdef0123456789abcdef", "ten_xyz"),
    ],
)
def test_projection_rejects_noncanonical_platform_ids(principal_id, tenant_id):
    from aie_runtime.engine import Principal

    adapter = _adapter()
    principal = Principal(id="p1", type="human", identity_ref="oidc:subject:1")
    with pytest.raises(ValueError):
        adapter.principal_to_contract(
            principal=principal,
            principal_id=principal_id,
            tenant_id=tenant_id,
        )
