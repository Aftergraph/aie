# Muse Prior Art and AIE Novelty Boundary — Comparison Note and Falsifier

Tracks Aftergraph/after-graph-governance#68, work item `aie#55`.

## Summary

After Meta's September 2026 Muse release, AIE's prior-art and claims posture is updated. Muse is treated as external architectural convergence for scoped permissions and external control, not as empirical reproduction of AIE results.

## What changed

- Added `evidence/s1.1/registry/prior_art_source_ledger.md` with dated Muse/Muse Code evidence and explicit scope.
- Marked broad claims around scoped permissions, external authorization, revocation, least privilege, durable agent control, and human approvals as known/existing mechanism classes where appropriate.
- Preserved the narrower AIE research boundary around portable authority/delegation semantics, monotonic attenuation/conservation, budget inheritance/conservation, governed topology mutation, cross-runtime conformance/interoperability, and portable evidence/settlement semantics.
- Added a comparison note distinguishing vendor vertical control systems from portable institution semantics.
- Added a falsifier for the objection "AIE is just vendor permissioning with new terminology."

## What did not change

- Conformance scope is unchanged unless evidence supports expansion.
- No novelty statement survives solely because a term differs.
- No text implies Meta independently validated AIE results.
- README, spec, and release-gate wording remain maturity-honest.

## Falsifier — "AIE is just vendor permissioning with new terminology"

See `evidence/s1.1/registry/prior_art_source_ledger.md` § Falsifier.

In brief: vocabulary is not the claim. The falsifiable AIE boundary is portable semantics and external conformance. External convergence on broad mechanism classes (Muse, comparable vendor control planes) does not reproduce AIE's portable claims, and AIE does not assert it does. If AIE's portable semantics were merely renamed vendor permissioning, then independent implementations and external parity would not be the right gates; the repository rejects that by preserving the evidence hierarchy and the narrower claim boundary.

## Comparison note — vendor vertical control vs portable institution semantics

| Dimension | Vendor vertical control (e.g. Muse Sentinel posture) | AIE portable institution semantics |
|---|---|---|
| Authority locus | vendor-run service adjudicates actions for its own agents | portable semantics for resolved authority across runtimes |
| Scope model | vendor-specific grant shapes | portable delegation with attenuation/conservation invariants across runtimes |
| Revocation | vendor-enforced within the vendor boundary | governed revocation with declared freshness objectives and cross-runtime propagation concerns |
| Budget | vendor billing/usage control | portable budget inheritance/conservation as an institution primitive |
| Topology | vendor orchestration model | governed topology mutation under the same admission/evidence pipeline as tool actions |
| Evidence | vendor-centric logging/monitoring | portable evidence and settlement semantics with privacy-minimized defaults |
| Interoperability claim | product integration within the vendor ecosystem | external conformance parity across independent legs and, eventually, independent implementations |

Convergence on the existence of scoped permissions and external approval is expected and healthy. It does not collapse AIE's narrower portable-semantics boundary.

## Acceptance checklist

- [x] prior-art/source ledger added with dated evidence and explicit scope
- [x] broad claims marked as known/existing mechanisms where appropriate
- [x] narrower AIE research boundary preserved
- [x] comparison note added: vendor vertical control vs portable institution semantics
- [x] falsifier added for "AIE is just vendor permissioning with new terminology"
- [x] no text implies Meta validated AIE results
- [x] conformance scope unchanged
- [x] no novelty statement survives solely because a term differs
