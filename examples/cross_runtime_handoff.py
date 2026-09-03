from datetime import datetime, timedelta, timezone

from aie_runtime.engine import AuthorityLease
from aie_runtime.functional import FunctionalRuntime
from aie_runtime.interop import export_authority_envelope, import_authority_envelope

now = datetime.now(timezone.utc)
lease = AuthorityLease(
    id="lease:demo",
    principal_id="agent:remote",
    mission_id="mission:release",
    capabilities={"repo.read"},
    resource_prefixes=("repo://acme/",),
    expires_at=now + timedelta(minutes=5),
    budget_remaining=2,
)

envelope = export_authority_envelope(
    lease,
    issuer="spiffe://issuer.example",
    secret=b"demo-secret",
)

imported = import_authority_envelope(
    envelope,
    keyring={"spiffe://issuer.example": b"demo-secret"},
    trusted_issuers={"spiffe://issuer.example"},
    now=now,
)

state = {
    "principals": {"agent:remote": {"id": "agent:remote"}},
    "missions": {"mission:release": {"id": "mission:release", "state": "active"}},
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
        }
    },
    "outcomes": {},
    "events": [],
}

runtime_b = FunctionalRuntime(state, policy=lambda _: True, now=lambda: now)
result = runtime_b.admit({
    "action_id": "demo-action-1",
    "principal_id": "agent:remote",
    "mission_id": "mission:release",
    "lease_id": "lease:demo",
    "capability": "repo.read",
    "resource": "repo://acme/service-a",
    "budget_cost": 1,
})

print(result)
