# AIE Public Release Gate

**Canonical maturity:** AIE Draft 0.3  
**Current workstream:** v0.4-S2 A2A interoperability  
**Authority:** `STATUS.md` and tracked evidence, not marketing copy

This file defines what may be called a public AIE milestone.

## Current public truth

- AIE is an experimental standards and reference-implementation project.
- Draft 0.3 core semantics are public.
- S1.1 external interoperability evidence exists for the recorded MCP/SPIFFE promotion path.
- S2 A2A work currently has local TCK evidence; external attestation remains the promotion boundary stated in `STATUS.md`.
- AIE is not represented as an established industry standard.

## Release classes

### Research Draft

Use when semantics/specification change without an external interoperability promotion.

Suggested title:

`AIE Draft 0.3 — <semantic milestone>`

### Interoperability Preview

Use when implementation/conformance work is useful publicly but a named external promotion gate is still open.

Suggested title:

`AIE Interoperability Preview — <scope>`

### Externally Attested Interop Milestone

Use only when the exact external promotion gate in `STATUS.md` is satisfied and the raw evidence/provenance is available.

Do not infer this class from local tests or a green internal CI run.

## Release checklist

- [ ] `STATUS.md` matches the release claim
- [ ] relevant conformance suite rerun on exact release head
- [ ] evidence/provenance location is public or explicitly documented
- [ ] local vs external evidence is labelled
- [ ] `CITATION.cff` version/date updated when appropriate
- [ ] changelog/release notes identify breaking semantic changes
- [ ] MCP/A2A/SPIFFE versions are pinned where material
- [ ] authority, revocation and budget semantics are not described more strongly than the tests prove
- [ ] canonical repository URL is `https://github.com/Aftergraph/aie`
- [ ] related Aftergraph research/evidence links are source-bound rather than claim-inherited

## Public call to action

For every meaningful AIE release, prefer one of:

- implement the semantics independently;
- run the conformance vectors;
- test MCP/A2A interoperability;
- attack authority attenuation or revocation boundaries;
- submit contradictory prior art or an overlapping standard.
- attack the novelty boundary directly: if AIE is merely renamed vendor permissioning, the portable-semantics and external-conformance claims should be empty; the falsifier and prior-art ledger in `evidence/s1.1/registry/prior_art_source_ledger.md` record how that objection is bounded.

The useful outcome is independent implementation and criticism, not merely a version number with ceremonial confetti.
