# Governance

AIE is currently an **experimental, maintainer-led standards project**. Governance becomes progressively stricter as maturity increases.

## Decision classes

1. **Reference implementation changes** may merge when tests and relevant conformance vectors are green.
2. **Normative Draft changes** require an issue describing interoperability impact, an updated spec artifact, machine-testable vectors when applicable, and explicit maintainer approval.
3. **Registry additions** must preserve backward compatibility or document a versioned breaking change.
4. **Promotion claims** require external evidence. Local tests cannot promote an interoperability profile.

## Evidence hierarchy

`external reproducible evidence > independent implementation evidence > conformance vectors > unit/integration tests > prose claims`.

## Versioning

- `Draft 0.x` may change incompatibly, but breaking changes must be documented.
- A profile such as `v0.4-S1.1` is an interoperability workstream, not the core specification version.
- No `Candidate Standard` or `1.0` claim may be made until the published promotion gates are satisfied.

## Conflict and appeals

Technical disagreements should be recorded in issues with competing evidence and explicit trade-offs. The maintainer decides during the experimental phase. A multi-maintainer governance model is a prerequisite before Candidate Standard maturity.

## Prior-art and novelty posture

AIE's novelty is deliberately narrow. Broad mechanisms such as scoped permissions, external authorization, revocation, least privilege, durable agent control, and human approvals are known/existing mechanism classes and are not promoted as AIE research claims. AIE's preserved research boundary is narrower and portable. After Meta's September 2026 Muse release, Muse is treated as external architectural convergence for scoped permissions and external control, not as empirical reproduction of AIE results. See `evidence/s1.1/registry/prior_art_source_ledger.md` and `spec/AIE_Draft_0.3_Prior_Art_Novalty_Boundary.md`. No AIE text implies Meta independently validated AIE results.
