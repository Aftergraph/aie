# Team Contract — Draft 0.4 design note

> Status: **draft proposal**. Tracked in issue #90. Requires maintainer approval per
> `GOVERNANCE.md` decision class 2 (Normative Draft changes) before this becomes a
> normative artifact. Nothing here is a promotion claim.

## Problem

A cross-repo audit (2026-09-19) found no canonical Team / team-membership source
contract anywhere in the Aftergraph organization. Meanwhile:

- FIHIM's canonical registry assigns team semantics to AIE (`F-021 Team Topology`,
  `F-022 Dynamic Team Formation`, repo: `Aftergraph/aie`) and its route taxonomy
  maps `/teams/:teamId` to `U-30 Team Workspace` / `U-31 Team Topology`.
- Runtime's `ServiceOpsJobSummary.assignedTeamId` is a dangling UUID with no
  resolvable Team schema anywhere.
- Consumers (FIHIM) must not invent a parallel durable Team model to fill the gap.

## Proposal

A **declarative Team artifact** keyed to the Institution Manifest, shipped as a
frozen contract schema (`contracts/frozen/team.schema.json`, `$id: contract:team/0.4-draft`).

Shape:

- `teamId` — stable identifier, `^team_[a-z0-9][a-z0-9-]*$`
- `displayName`
- `status` — `active | suspended | dissolved`
- `institutionRef` — the owning Institution manifest
- `members[]` — `{ principalId, role, memberStatus, joinedAt?, revokedAt?, revokedBy? }`
  where `principalId` must resolve to a principal declared by the owning
  institution, `role` is a team-scoped label, and `memberStatus` is
  `active | suspended | revoked`
- `topology` — `hierarchical | peer | pipeline | council`; a **declared shape for
  display**, not a claim about live communication paths or authority
- `sourceRef` — `{ repository, ref, path }` provenance; consumers must surface it
  with any projection
- `authorityRefs[]` — optional references to delegation/lease/decision artifacts

## Invariants

1. **Membership ≠ authorization.** Authority is resolved exclusively through AIE
   authority resolution and Trust Gateway admission. The Team artifact never
   grants capability; `role` is a label.
2. **Projection-only consumption.** Consumers (e.g. FIHIM `/teams/:teamId`)
   display team, members, roles, status and provenance, and fail closed when the
   team is absent or its source is unreachable. They must not fabricate
   membership or derived authority.
3. **Declarative, not a service.** Team artifacts are files like the Institution
   Manifest. AIE remains the semantic owner. Runtime may orchestrate using teams;
   Trust Gateway remains the enforcement point.
4. **Topology is display shape.** It does not assert runtime communication paths.

## Relationship to existing artifacts

- Institution Manifest (`spec/AIE_Draft_0.3_Schema.json`): Team artifacts
  reference principals declared there via `institutionRef` + `principalId`. The
  manifest's free-form `topology` section may eventually be superseded by these
  artifacts; that is a maintainer decision, out of scope here.
- `contracts/frozen/identity.schema.json`: unchanged. Team membership is not an
  identity dimension.
- Runtime `org-delegation/0.1`: unchanged. Delegation gates continue to operate
  on principal refs and envelopes; a Team artifact gives those refs a resolvable
  group context without changing gate semantics.
- Runtime `identity-core` Organization/Membership: unchanged. Those model human
  org membership with human roles; Team artifacts model agent-team composition
  within an institution.

## Open questions for the maintainer

1. Declarative artifact keyed to the Institution Manifest (as proposed), or a
   first-class `spec.teams` section of the Institution Manifest itself?
2. Should team-scoped `role` stay a free string (as proposed, consistent with the
   manifest's free `roles` object) or become an enum?
3. Should conformance vectors live under `conformance/` next to the existing
   vector suites, and what is the minimum vector set for approval?

## Consumers

- FIHIM `/teams/:teamId` (U-30/U-31): read-only projection with provenance;
  blocked on approval of this contract.
- Runtime service-ops: may resolve `assignedTeamId` against the schema in the
  future; no change required now.
