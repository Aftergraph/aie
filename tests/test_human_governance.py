"""Behavioral tests for AIE human-governance authority (V4 binding HUMAN-GOVERNANCE-V1).

AIE owns principal/authority semantics: delegation, mission envelopes,
budgets, authority lifecycle, revocation. Role labels (owner/reviewer/
auditor/operator) are convenience templates that permit nothing; only the
issued AIE grant is authority truth.

Run: .venv/bin/python -m pytest tests/test_human_governance.py -q
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aie_runtime.errors import AIEError
from aie_runtime.human_governance import (
    ROLE_LABELS,
    HumanGovernanceAuthority,
    role_template,
)

NOW = datetime(2026, 9, 9, tzinfo=timezone.utc)
ROOT_ISSUER = "system:governance"


def authority(now=NOW):
    return HumanGovernanceAuthority(
        clock=lambda: now, authorized_issuers={ROOT_ISSUER}
    )


def registered(gov, pid="human:alice", labels=()):
    gov.register_principal(pid, identity_ref="oidc:alice", labels=labels)
    return pid


def issued(gov, grant_id="grant:1", pid="human:alice", **kw):
    params = dict(
        grant_id=grant_id,
        principal_id=pid,
        mission_id="mission:release",
        tenant_id="tenant:acme",
        capabilities={"repo.write"},
        resource_prefixes=("repo://acme/",),
        budget=10.0,
        ttl=timedelta(minutes=30),
        issuer=ROOT_ISSUER,
    )
    params.update(kw)
    return gov.issue_grant(**params)


def use(gov, grant_id="grant:1", **kw):
    params = dict(
        grant_id=grant_id,
        principal_id="human:alice",
        capability="repo.write",
        resource="repo://acme/service-a",
        mission_id="mission:release",
        tenant_id="tenant:acme",
        cost=1.0,
    )
    params.update(kw)
    return gov.authorize_use(**params)


def test_grant_is_authority_truth_live_use_is_allowed():
    gov = authority()
    registered(gov)
    issued(gov)
    assert use(gov) is True


def test_unknown_grant_fails_closed():
    gov = authority()
    registered(gov)
    with pytest.raises(AIEError) as exc:
        use(gov, grant_id="grant:missing")
    assert exc.value.code == "AIE-AUTH-001"


def test_principal_mismatch_fails_closed():
    gov = authority()
    registered(gov)
    registered(gov, "human:bob")
    issued(gov)
    with pytest.raises(AIEError) as exc:
        use(gov, principal_id="human:bob")
    assert exc.value.code == "AIE-AUTH-001"


# --- Role labels permit nothing -------------------------------------------

def test_role_labels_cover_owner_reviewer_auditor_operator():
    assert set(ROLE_LABELS) == {"owner", "reviewer", "auditor", "operator"}


@pytest.mark.parametrize("label", ["owner", "reviewer", "auditor", "operator"])
def test_label_alone_permits_nothing(label):
    gov = authority()
    registered(gov, labels=(label,))
    with pytest.raises(AIEError) as exc:
        gov.authorize_by_label(
            label,
            principal_id="human:alice",
            capability="repo.write",
            resource="repo://acme/service-a",
            mission_id="mission:release",
            tenant_id="tenant:acme",
        )
    assert exc.value.code == "AIE-AUTH-004"


def test_role_template_suggests_but_never_authorizes():
    suggestion = role_template("owner")
    assert suggestion["capabilities"], "template must suggest something"
    gov = authority()
    registered(gov, labels=("owner",))
    # Even presenting the template's exact suggestion as a label still denies:
    # only a grant issued under it authorizes.
    with pytest.raises(AIEError) as exc:
        gov.authorize_by_label(
            "owner",
            principal_id="human:alice",
            capability=sorted(suggestion["capabilities"])[0],
            resource="repo://acme/service-a",
            mission_id="mission:release",
            tenant_id="tenant:acme",
        )
    assert exc.value.code == "AIE-AUTH-004"


def test_changing_label_never_changes_authority():
    gov = authority()
    registered(gov)
    issued(gov, capabilities={"repo.read"})
    # Granting the principal the 'owner' label does not widen the grant:
    # repo.write is still outside the live grant.
    gov.register_principal("human:alice", identity_ref="oidc:alice", labels=("owner",))
    with pytest.raises(AIEError) as exc:
        use(gov, capability="repo.write")
    assert exc.value.code == "AIE-AUTH-004"
    # And the granted capability still works: authority follows the grant.
    assert use(gov, capability="repo.read") is True


def test_unknown_role_label_fails_closed():
    with pytest.raises(ValueError, match="unknown role label"):
        role_template("superadmin")


# --- Self-granted authority ------------------------------------------------

def test_self_issued_grant_is_rejected():
    gov = authority()
    registered(gov)
    with pytest.raises(AIEError) as exc:
        issued(gov, issuer="human:alice")
    assert exc.value.code == "AIE-AUTH-001"


def test_unauthorized_issuer_is_rejected():
    gov = authority()
    registered(gov)
    with pytest.raises(AIEError) as exc:
        issued(gov, issuer="mallory:external")
    assert exc.value.code == "AIE-AUTH-001"


# --- Consent is not authority ----------------------------------------------

def test_consent_without_grant_permits_nothing():
    gov = authority()
    registered(gov)
    with pytest.raises(AIEError) as exc:
        gov.authorize_use(
            grant_id="grant:missing",
            principal_id="human:alice",
            capability="repo.write",
            resource="repo://acme/service-a",
            mission_id="mission:release",
            tenant_id="tenant:acme",
            consent=True,
        )
    assert exc.value.code == "AIE-AUTH-001"


def test_live_grant_decides_regardless_of_consent_flag():
    gov = authority()
    registered(gov)
    issued(gov)
    assert use(gov, consent=False) is True
    assert use(gov, grant_id="grant:1", cost=0.0, consent=True) is True


# --- Delegation -------------------------------------------------------------

def delegated(gov, grant_id="grant:child", pid="human:bob", **kw):
    gov.register_principal(pid, identity_ref="oidc:bob")
    params = dict(
        parent_grant_id="grant:1",
        delegated_by="human:alice",
        grant_id=grant_id,
        principal_id=pid,
        capabilities={"repo.write"},
        resource_prefixes=("repo://acme/service-a",),
        budget=4.0,
        ttl=timedelta(minutes=10),
    )
    params.update(kw)
    return gov.delegate(**params)


def test_narrowing_delegation_authorizes_child_use():
    gov = authority()
    registered(gov)
    issued(gov, max_delegation_depth=1)
    delegated(gov)
    assert use(gov, grant_id="grant:child", principal_id="human:bob",
               resource="repo://acme/service-a/x", cost=1.0) is True


def test_delegation_widening_capabilities_is_rejected():
    gov = authority()
    registered(gov)
    issued(gov, capabilities={"repo.read"}, max_delegation_depth=1)
    with pytest.raises(AIEError) as exc:
        delegated(gov, capabilities={"repo.write"})
    assert exc.value.code == "AIE-DELEG-001"


def test_delegation_widening_resources_is_rejected():
    gov = authority()
    registered(gov)
    issued(gov, max_delegation_depth=1)
    with pytest.raises(AIEError) as exc:
        delegated(gov, resource_prefixes=("repo://other/",))
    assert exc.value.code == "AIE-DELEG-001"


def test_delegation_over_budget_is_rejected():
    gov = authority()
    registered(gov)
    issued(gov, budget=10.0, max_delegation_depth=1)
    with pytest.raises(AIEError) as exc:
        delegated(gov, budget=11.0)
    assert exc.value.code == "AIE-BUDGET-001"


def test_delegation_conserves_parent_budget():
    gov = authority()
    registered(gov)
    issued(gov, budget=10.0, max_delegation_depth=1)
    delegated(gov, budget=4.0)
    assert gov.grant("grant:1").budget_remaining == 6.0
    assert gov.grant("grant:child").budget_remaining == 4.0


def test_delegation_depth_is_bounded():
    gov = authority()
    registered(gov)
    issued(gov, max_delegation_depth=0)
    with pytest.raises(AIEError) as exc:
        delegated(gov)
    assert exc.value.code == "AIE-DELEG-002"


def test_delegation_across_mission_partition_is_rejected():
    gov = authority()
    registered(gov)
    issued(gov, max_delegation_depth=1)
    child = delegated(gov)
    assert child.mission_id == "mission:release"
    # A delegated grant never escapes its parent's mission envelope.
    with pytest.raises(AIEError) as exc:
        use(gov, grant_id="grant:child", principal_id="human:bob",
            resource="repo://acme/service-a/x",
            mission_id="mission:other")
    assert exc.value.code == "AIE-AUTH-004"


def test_cannot_delegate_from_revoked_parent():
    gov = authority()
    registered(gov)
    issued(gov, max_delegation_depth=1)
    gov.revoke("grant:1")
    with pytest.raises(AIEError) as exc:
        delegated(gov, grant_id="grant:late")
    assert exc.value.code == "AIE-AUTH-003"


def test_child_expiry_is_capped_at_parent_expiry():
    gov = authority()
    registered(gov)
    issued(gov, ttl=timedelta(minutes=30), max_delegation_depth=1)
    child = delegated(gov, ttl=timedelta(hours=5))
    assert child.expires_at <= gov.grant("grant:1").expires_at


# --- Mission envelopes -------------------------------------------------------

def test_use_outside_mission_envelope_is_rejected():
    gov = authority()
    registered(gov)
    issued(gov)
    with pytest.raises(AIEError) as exc:
        use(gov, mission_id="mission:other")
    assert exc.value.code == "AIE-AUTH-004"


def test_use_outside_tenant_partition_is_rejected():
    gov = authority()
    registered(gov)
    issued(gov)
    with pytest.raises(AIEError) as exc:
        use(gov, tenant_id="tenant:other")
    assert exc.value.code == "AIE-AUTH-004"


def test_use_outside_capability_or_resource_is_rejected():
    gov = authority()
    registered(gov)
    issued(gov)
    with pytest.raises(AIEError) as exc:
        use(gov, capability="ci.run")
    assert exc.value.code == "AIE-AUTH-004"
    with pytest.raises(AIEError) as exc:
        use(gov, resource="repo://other/x")
    assert exc.value.code == "AIE-AUTH-004"


# --- Budgets ------------------------------------------------------------------

def test_budget_overrun_is_rejected():
    gov = authority()
    registered(gov)
    issued(gov, budget=2.0)
    with pytest.raises(AIEError) as exc:
        use(gov, cost=3.0)
    assert exc.value.code == "AIE-BUDGET-001"


def test_spend_is_deducted_and_second_overrun_fails():
    gov = authority()
    registered(gov)
    issued(gov, budget=2.0)
    assert use(gov, cost=2.0) is True
    with pytest.raises(AIEError) as exc:
        use(gov, grant_id="grant:1", cost=0.5)
    assert exc.value.code == "AIE-BUDGET-001"


def test_failed_authorization_does_not_charge_budget():
    gov = authority()
    registered(gov)
    issued(gov, budget=5.0)
    with pytest.raises(AIEError):
        use(gov, capability="ci.run", cost=2.0)
    assert gov.grant("grant:1").budget_remaining == 5.0


# --- Lifecycle / revocation / staleness ----------------------------------------

def test_expired_grant_is_rejected():
    gov = authority()
    registered(gov)
    issued(gov, ttl=timedelta(minutes=30))
    # Advance time on the same authority: the live registry entry is now past
    # expiry, so enforcement denies without any registry aliasing.
    gov.clock = lambda: NOW + timedelta(hours=1)
    with pytest.raises(AIEError) as exc:
        use(gov)
    assert exc.value.code == "AIE-AUTH-002"


def test_revoked_grant_is_rejected():
    gov = authority()
    registered(gov)
    issued(gov)
    gov.revoke("grant:1")
    with pytest.raises(AIEError) as exc:
        use(gov)
    assert exc.value.code == "AIE-AUTH-003"


def test_revocation_cascades_to_delegated_children():
    gov = authority()
    registered(gov)
    issued(gov, max_delegation_depth=1)
    delegated(gov)
    gov.revoke("grant:1")
    assert gov.grant("grant:child").revoked is True
    with pytest.raises(AIEError) as exc:
        use(gov, grant_id="grant:child", principal_id="human:bob",
            resource="repo://acme/service-a/x", cost=0.0)
    assert exc.value.code == "AIE-AUTH-003"


def test_revocation_bypass_via_stale_reference_is_rejected():
    gov = authority()
    registered(gov)
    grant = issued(gov)
    assert grant.revoked is False
    gov.revoke("grant:1")
    # The previously returned snapshot says nothing: live registry decides.
    with pytest.raises(AIEError) as exc:
        use(gov)
    assert exc.value.code == "AIE-AUTH-003"


def test_revoking_unknown_grant_fails_closed():
    gov = authority()
    with pytest.raises(AIEError) as exc:
        gov.revoke("grant:missing")
    assert exc.value.code == "AIE-AUTH-001"


def test_ambiguous_use_fails_closed():
    gov = authority()
    registered(gov)
    issued(gov)
    with pytest.raises(AIEError) as exc:
        use(gov, capability="")
    assert exc.value.code == "AIE-AUTH-004"
    with pytest.raises(AIEError) as exc:
        use(gov, resource="")
    assert exc.value.code == "AIE-AUTH-004"


# --- Stranger delegation (binding fix 1) -------------------------------------

def test_delegate_by_holder_authorizes_child_use():
    gov = authority()
    registered(gov)
    issued(gov, max_delegation_depth=1)
    gov.register_principal("human:bob", identity_ref="oidc:bob")
    child = gov.delegate(
        parent_grant_id="grant:1",
        delegated_by="human:alice",
        grant_id="grant:child",
        principal_id="human:bob",
        capabilities={"repo.write"},
        resource_prefixes=("repo://acme/service-a",),
        budget=4.0,
        ttl=timedelta(minutes=10),
    )
    assert child.parent_grant_id == "grant:1"
    assert use(gov, grant_id="grant:child", principal_id="human:bob",
               resource="repo://acme/service-a/x", cost=1.0) is True


def test_stranger_delegation_is_rejected():
    gov = authority()
    registered(gov)
    issued(gov, max_delegation_depth=1)
    gov.register_principal("human:bob", identity_ref="oidc:bob")
    gov.register_principal("human:mallory", identity_ref="oidc:mallory")
    with pytest.raises(AIEError) as exc:
        gov.delegate(
            parent_grant_id="grant:1",
            delegated_by="human:mallory",
            grant_id="grant:evil",
            principal_id="human:mallory",
            capabilities={"repo.write"},
            resource_prefixes=("repo://acme/service-a",),
            budget=4.0,
            ttl=timedelta(minutes=10),
        )
    assert exc.value.code == "AIE-AUTH-001"
    assert gov.grant("grant:evil") is None
    assert gov.grant("grant:1").budget_remaining == 10.0


# --- Non-finite budgets (binding fix 2) ---------------------------------------

def test_issue_grant_rejects_nonfinite_budget():
    import math

    gov = authority()
    registered(gov)
    for bad in (math.inf, -math.inf, math.nan):
        with pytest.raises(ValueError):
            issued(gov, grant_id=f"grant:bad-{bad}", budget=bad)


def test_delegate_rejects_nonfinite_budget():
    import math

    gov = authority()
    registered(gov)
    issued(gov, budget=10.0, max_delegation_depth=1)
    gov.register_principal("human:bob", identity_ref="oidc:bob")
    for bad in (math.inf, math.nan):
        with pytest.raises(AIEError) as exc:
            gov.delegate(
                parent_grant_id="grant:1",
                delegated_by="human:alice",
                grant_id=f"grant:bad-{bad}",
                principal_id="human:bob",
                capabilities={"repo.write"},
                resource_prefixes=("repo://acme/service-a",),
                budget=bad,
                ttl=timedelta(minutes=10),
            )
        assert exc.value.code == "AIE-BUDGET-001"
    assert gov.grant("grant:1").budget_remaining == 10.0


def test_authorize_use_rejects_nonfinite_cost():
    import math

    gov = authority()
    registered(gov)
    issued(gov, budget=10.0)
    for bad in (math.inf, math.nan):
        with pytest.raises(AIEError) as exc:
            use(gov, cost=bad)
        assert exc.value.code == "AIE-BUDGET-001"
    assert gov.grant("grant:1").budget_remaining == 10.0


# --- Identity rebind (binding fix 3) ------------------------------------------

def test_reregistration_with_changed_identity_ref_is_rejected():
    gov = authority()
    registered(gov)
    issued(gov)
    with pytest.raises(AIEError) as exc:
        gov.register_principal("human:alice", identity_ref="oidc:mallory")
    assert exc.value.code == "AIE-AUTH-001"
    # No silent rebind: original binding is preserved and still authorizes.
    assert gov.principal("human:alice").identity_ref == "oidc:alice"
    assert use(gov) is True


def test_reregistration_with_same_identity_ref_updates_labels():
    gov = authority()
    registered(gov)
    issued(gov, capabilities={"repo.read"})
    record = gov.register_principal(
        "human:alice", identity_ref="oidc:alice", labels=("owner",))
    assert record.labels == ("owner",)
    assert gov.principal("human:alice").identity_ref == "oidc:alice"
    assert use(gov, capability="repo.read") is True


# --- Mutable-grant aliasing (binding fix 4) -----------------------------------
#
# Grants were stored by reference AND handed to callers, so holder code
# could mutate the live registry entry directly. Grants must be frozen:
# every mutation attempt on a returned handle raises, and the registry
# is unaffected.

def test_held_grant_reference_cannot_restore_budget():
    import dataclasses
    import math

    gov = authority()
    registered(gov)
    grant = issued(gov, budget=10.0)
    assert use(gov, cost=4.0) is True
    assert gov.grant("grant:1").budget_remaining == 6.0
    with pytest.raises(dataclasses.FrozenInstanceError):
        grant.budget_remaining = math.inf
    with pytest.raises(dataclasses.FrozenInstanceError):
        grant.budget_remaining = float("nan")
    assert gov.grant("grant:1").budget_remaining == 6.0
    with pytest.raises(AIEError) as exc:
        use(gov, cost=7.0)
    assert exc.value.code == "AIE-BUDGET-001"


def test_held_grant_reference_cannot_unrevoke():
    import dataclasses

    gov = authority()
    registered(gov)
    grant = issued(gov)
    gov.revoke("grant:1")
    assert gov.grant("grant:1").revoked is True
    with pytest.raises(dataclasses.FrozenInstanceError):
        grant.revoked = False
    assert gov.grant("grant:1").revoked is True
    with pytest.raises(AIEError) as exc:
        use(gov)
    assert exc.value.code == "AIE-AUTH-003"


@pytest.mark.parametrize(
    "field,tampered",
    [
        ("capabilities", frozenset({"*"})),
        ("principal_id", "human:mallory"),
        ("resource_prefixes", ("repo://other/",)),
        ("expires_at", NOW + timedelta(days=365)),
    ],
)
def test_held_grant_reference_cannot_rebind_authority_fields(field, tampered):
    import dataclasses

    gov = authority()
    registered(gov)
    grant = issued(gov)
    before = gov.grant("grant:1")
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(grant, field, tampered)
    live = gov.grant("grant:1")
    assert getattr(live, field) == getattr(before, field)
    # Original envelope still enforced: tampered values authorize nothing.
    assert use(gov) is True
    with pytest.raises(AIEError):
        use(gov, capability="*")
    with pytest.raises(AIEError):
        use(gov, principal_id="human:mallory")
    with pytest.raises(AIEError):
        use(gov, resource="repo://other/x")


def test_authorize_use_deducts_live_grant_after_freeze():
    gov = authority()
    registered(gov)
    snapshot = issued(gov, budget=2.0)
    assert use(gov, cost=2.0) is True
    assert gov.grant("grant:1").budget_remaining == 0.0
    # The previously returned handle is a stale snapshot, not live state.
    assert snapshot.budget_remaining == 2.0
    with pytest.raises(AIEError) as exc:
        use(gov, grant_id="grant:1", cost=0.5)
    assert exc.value.code == "AIE-BUDGET-001"


def test_revoke_cascade_marks_live_grants_after_freeze():
    gov = authority()
    registered(gov)
    issued(gov, max_delegation_depth=1)
    delegated(gov)
    gov.revoke("grant:1")
    assert gov.grant("grant:1").revoked is True
    assert gov.grant("grant:child").revoked is True
    with pytest.raises(AIEError) as exc:
        use(gov, grant_id="grant:child", principal_id="human:bob",
            resource="repo://acme/service-a/x", cost=0.0)
    assert exc.value.code == "AIE-AUTH-003"


def test_delegate_conserves_parent_budget_after_freeze():
    gov = authority()
    registered(gov)
    issued(gov, budget=10.0, max_delegation_depth=1)
    delegated(gov, budget=4.0)
    assert gov.grant("grant:1").budget_remaining == 6.0
    assert gov.grant("grant:child").budget_remaining == 4.0


# --- Mutable issuer-set aliasing (binding fix 5) -----------------------------
#
# authorized_issuers was a plain mutable set attribute, so any holder could
# enroll a new trust root (auth.authorized_issuers.add('mallory')) and then
# issue arbitrary grants. Issuers must be immutable: a frozenset snapshot
# behind a read-only property.

def test_enroll_then_issue_is_rejected():
    gov = authority()
    gov.register_principal("human:mallory", identity_ref="oidc:mallory")
    with pytest.raises(AttributeError):
        gov.authorized_issuers.add("mallory")
    with pytest.raises(AIEError) as exc:
        gov.issue_grant(
            grant_id="grant:evil",
            principal_id="human:mallory",
            mission_id="mission:release",
            tenant_id="tenant:acme",
            capabilities={"repo.write"},
            resource_prefixes=("repo://acme/",),
            budget=10.0,
            ttl=timedelta(minutes=30),
            issuer="mallory",
        )
    assert exc.value.code == "AIE-AUTH-001"
    assert gov.grant("grant:evil") is None


def test_authorized_issuers_is_immutable_snapshot():
    gov = authority()
    assert isinstance(gov.authorized_issuers, frozenset)
    assert gov.authorized_issuers == frozenset({ROOT_ISSUER})
    with pytest.raises(AttributeError):
        gov.authorized_issuers = {"mallory"}


# --- Mutable-principal aliasing (binding fix 6) ---------------------------
#
# HumanPrincipalRecord was a mutable dataclass stored by reference AND handed
# to callers, so holder code could rewrite rec.identity_ref/rec.labels in
# place, silently changing registry identity truth and defeating the
# rebind-deny. Records must be frozen: every mutation attempt on a returned
# handle raises, and the registry is unaffected.

def test_held_principal_reference_cannot_rebind_identity():
    import dataclasses

    gov = authority()
    record = gov.register_principal("human:alice", identity_ref="oidc:alice")
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.identity_ref = "oidc:mallory"
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.labels = ("owner",)
    live = gov.principal("human:alice")
    assert live.identity_ref == "oidc:alice"
    assert live.labels == ()

# --- Public registry injection (binding fix 7) ------------------------------
#
# self.grants / self.principals were public mutable dicts, so any holder
# could inject forged entries (gov.grants['evil'] = ...) that enforcement
# then trusted. The registries must be private; reads go through the
# grant()/principal() accessors (safe: both record types are frozen).

def test_public_registry_names_do_not_back_enforcement():
    gov = authority()
    registered(gov)
    issued(gov)
    # No public mutable registry behind these names.
    for name in ("grants", "principals"):
        with pytest.raises(AttributeError):
            getattr(gov, name)
    # Even planting a same-named attribute must not affect enforcement:
    # the forged entry authorizes nothing and the live grant still works.
    gov.register_principal("human:mallory", identity_ref="oidc:mallory")
    gov.grants = {
        "grant:evil": gov.grant("grant:1"),
    }
    with pytest.raises(AIEError) as exc:
        use(gov, grant_id="grant:evil", principal_id="human:mallory")
    assert exc.value.code == "AIE-AUTH-001"
    assert use(gov) is True
