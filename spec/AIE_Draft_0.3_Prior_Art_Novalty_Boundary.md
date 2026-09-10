# AIE Draft 0.3 — Prior-Art and Novelty Boundary (working draft)

> **Status:** NEEDS REWORK. This file was created by an automated task action at commit `a32cf23` and has not yet been reviewed by a human maintainer. It duplicates material already captured in `evidence/s1.1/registry/prior_art_source_ledger.md`. Before this file is exposed as a canonical spec artifact, the maintainer should either (a) retire it and point spec readers at the registry, or (b) reconcile the two so spec and registry agree on scope, evidence, and disposition.

**Evidence cut:** 2026-09-09  **Tracks:** Aftergraph/after-graph-governance#68

## Purpose (as drafted)

This registry records AIE's novelty boundary and the external prior art that bounds it. It is descriptive, not promotional. Recording an external system here does not imply AIE results are independently reproduced by it.

## AIE novelty boundary (as drafted)

AIE's novelty is deliberately narrow. The repository does not claim novelty for broad mechanism classes that are known/existing across vendor control planes, policy engines, and agent frameworks, including:

- scoped permissions;
- external authorization;
- revocation;
- least privilege;
- durable agent control;
- human approvals.

AIE's preserved research boundary is narrower and portable:

- portable authority/delegation semantics;
- monotonic attenuation/conservation;
- budget inheritance/conservation;
- governed topology mutation;
- cross-runtime conformance/interoperability;
- portable evidence/settlement semantics.

## External prior art (as drafted)

### Meta Muse / Muse Code / Muse Spark 1.3

- **Date:** 2026-09-08 (Muse consumer launch); 2026-09-02 (Muse Spark 1.3 release)
- **Evidence:** public consumer launch materials, developer pricing pages, and independent coverage of the Muse Secure VM, Sentinel approval component, and Muse Spark 1.3 Contributor SKU
- **Scope recorded:** consumer personal-agent product with per-user Secure VM isolation, a separate Sentinel component that adjudicates connector and network egress requests, and model SKUs including a Contributor data-sharing tier hosted on Meta's own API and Muse Code
- **Convergence:** vendor vertical control of agent actions through scoped, session/task/time-bounded permission grants and a separate approval authority for consequential external calls
- **Not reproduced:** portable authority/delegation semantics across runtimes; monotonic attenuation/conservation as a portable invariant; budget inheritance/conservation as a portable institution primitive; governed topology mutation under the same admission/evidence pipeline as tool actions; cross-runtime conformance/interoperability against an external official suite; portable evidence/settlement semantics
- **Disposition:** external architectural convergence for scoped permissions and external control. Not empirical reproduction of AIE results. No AIE empirical claim is strengthened by Muse's existence.

## Comparison note — vendor vertical control vs portable institution semantics (as drafted)

Vendor vertical control systems can enforce scoped permissions and external approvals inside a single vendor runtime boundary. That is a legitimate and useful control posture. It is not the same claim as portable institution semantics. See `evidence/s1.1/registry/prior_art_source_ledger.md` for the full comparison and falsifier.

## Falsifier — "AIE is just vendor permissioning with new terminology" (as drafted)

See `evidence/s1.1/registry/prior_art_source_ledger.md` § Falsifier.

In brief: vocabulary is not the claim. The falsifiable AIE boundary is portable semantics and external conformance. External convergence on broad mechanism classes does not reproduce AIE's portable claims, and AIE does not assert it does. No novelty statement survives solely because a term differs.

## Evidence hierarchy reminder (as drafted)

`external reproducible evidence > independent implementation evidence > conformance vectors > unit/integration tests > prose claims`

This registry is a prose claim about the external landscape. It does not upgrade AIE empirical claims. It only keeps the novelty boundary honest.

## Maintainer action requested

- Confirm whether this file is intended as a canonical spec artifact or whether spec readers should be pointed at `evidence/s1.1/registry/prior_art_source_ledger.md` instead.
- If canonical: remove the duplication, keep one authoritative version, and add a cross-reference.
- If not canonical: replace the body above with a short pointer and delete the normative-sounding draft sections.
