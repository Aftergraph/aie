from datetime import datetime, timedelta, timezone

import pytest

from aie_runtime.engine import AuthorityLease
from aie_runtime.errors import AIEError
from aie_runtime.interop import export_authority_envelope, import_authority_envelope

NOW = datetime(2026, 9, 3, tzinfo=timezone.utc)


def lease():
    return AuthorityLease(
        id="lease:x",
        principal_id="agent:a",
        mission_id="mission:m",
        capabilities={"repo.read"},
        resource_prefixes=("repo://acme/",),
        expires_at=NOW + timedelta(minutes=5),
        budget_remaining=3,
        depth=1,
        max_delegation_depth=2,
    )


def test_authority_envelope_round_trips_between_runtimes():
    env = export_authority_envelope(lease(), issuer="spiffe://issuer.example", secret=b"shared-secret")
    imported = import_authority_envelope(
        env,
        keyring={"spiffe://issuer.example": b"shared-secret"},
        trusted_issuers={"spiffe://issuer.example"},
        now=NOW,
    )
    assert imported.id == "lease:x"
    assert imported.capabilities == {"repo.read"}
    assert imported.resource_prefixes == ("repo://acme/",)


def test_authority_envelope_rejects_tampering():
    env = export_authority_envelope(lease(), issuer="spiffe://issuer.example", secret=b"shared-secret")
    env["authority"]["budget_remaining"] = 300
    with pytest.raises(AIEError) as exc:
        import_authority_envelope(
            env,
            keyring={"spiffe://issuer.example": b"shared-secret"},
            trusted_issuers={"spiffe://issuer.example"},
            now=NOW,
        )
    assert exc.value.code == "AIE-FED-001"


def test_authority_envelope_rejects_untrusted_issuer():
    env = export_authority_envelope(lease(), issuer="spiffe://issuer.example", secret=b"shared-secret")
    with pytest.raises(AIEError) as exc:
        import_authority_envelope(
            env,
            keyring={"spiffe://issuer.example": b"shared-secret"},
            trusted_issuers={"spiffe://other.example"},
            now=NOW,
        )
    assert exc.value.code == "AIE-FED-001"


def test_signed_object_authority_can_execute_in_independent_functional_runtime():
    from aie_runtime.functional import FunctionalRuntime

    env = export_authority_envelope(lease(), issuer="spiffe://issuer.example", secret=b"shared-secret")
    imported = import_authority_envelope(
        env,
        keyring={"spiffe://issuer.example": b"shared-secret"},
        trusted_issuers={"spiffe://issuer.example"},
        now=NOW,
    )
    state = {
        "principals": {"agent:a": {"id": "agent:a"}},
        "missions": {"mission:m": {"id": "mission:m", "state": "RUNNING"}},
        "leases": {
            imported.id: {
                "id": imported.id,
                "principal_id": imported.principal_id,
                "mission_id": imported.mission_id,
                "capabilities": sorted(imported.capabilities),
                "resource_prefixes": list(imported.resource_prefixes),
                "expires_at": imported.expires_at.isoformat(),
                "budget_remaining": imported.budget_remaining,
                "revoked": imported.revoked,
                "parent_lease_id": imported.parent_lease_id,
                "depth": imported.depth,
                "max_delegation_depth": imported.max_delegation_depth,
            }
        },
        "outcomes": {},
        "events": [],
    }
    rt = FunctionalRuntime(state, policy=lambda _: True, now=lambda: NOW)
    result = rt.admit({
        "action_id": "remote-1",
        "principal_id": "agent:a",
        "mission_id": "mission:m",
        "lease_id": "lease:x",
        "capability": "repo.read",
        "resource": "repo://acme/service-a",
        "budget_cost": 1,
    })
    assert result["status"] == "admitted"
