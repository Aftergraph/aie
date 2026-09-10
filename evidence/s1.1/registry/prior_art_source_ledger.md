# Prior-Art and Source Ledger

Tracked external architectural convergence, comparable systems, and source-of-truth references that bound AIE's novelty claims. Updated each cycle. This ledger is descriptive, not promotional: listing a system here does not imply AIE results are independently reproduced by it, nor that the external system validates AIE.

## Why this ledger exists

AIE's novelty is deliberately narrow. Broad capabilities such as scoped permissions, external authorization, revocation, least privilege, durable agent control, and human approvals are known/existing mechanisms across vendor control planes, policy engines, and agent frameworks. They are not, by themselves, AIE research claims.

This ledger records where external convergence exists so the repository can distinguish:
- **external architectural convergence** — another system also addresses a problem space AIE addresses;
- **empirical reproduction** — an external system independently validates AIE's specific portable-semantics claims.

Only the second category would strengthen AIE empirical claims. The first category does not.

## Source ledger

### P-001: Meta Muse / Muse Code / Muse Spark 1.3

- **Date:** 2026-09-08 (Muse consumer launch); 2026-09-02 (Muse Spark 1.3 release)
- **Evidence:** public consumer launch materials, developer pricing pages, and independent coverage of the Muse Secure VM, Sentinel approval component, and Muse Spark 1.3 Contributor SKU
- **Scope recorded:** consumer personal-agent product with per-user Secure VM isolation, a separate Sentinel component that adjudicates connector and network egress requests, and model SKUs (including a Contributor data-sharing tier) hosted on Meta's own API and Muse Code
- **What it converges on:** vendor vertical control of agent actions through scoped, session/task/time-bounded permission grants and a separate approval authority for consequential external calls
- **What it does NOT reproduce:** portable authority/delegation semantics across runtimes; monotonic attenuation/conservation as a portable invariant; budget inheritance/conservation as a portable institution primitive; governed topology mutation under the same admission/evidence pipeline as tool actions; cross-runtime conformance/interoperability against an external official suite; portable evidence/settlement semantics
- **Disposition:** external architectural convergence for scoped permissions and external control. Not empirical reproduction of AIE results. No AIE empirical claim is strengthened by Muse's existence.

### P-002: General vendor permissioning and policy-control planes

- **Date:** ongoing
- **Evidence type:** category observation, not a single dated source
- **Scope recorded:** vendor control planes, policy engines, and agent frameworks commonly provide scoped permissions, external authorization, revocation, least-privilege enforcement, durable agent control, and human approvals in vendor-specific vertical architectures
- **Disposition:** these are known/existing mechanism classes. AIE does not claim novelty for their existence. AIE claims are bounded to the portable semantics defined in `spec/` and the narrower research boundary below.

## AIE novelty boundary (preserved)

The following are the narrower AIE research claims preserved by this ledger. They are not displaced by external convergence on broad mechanism classes:

- portable authority/delegation semantics;
- monotonic attenuation/conservation;
- budget inheritance/conservation;
- governed topology mutation;
- cross-runtime conformance/interoperability;
- portable evidence/settlement semantics.

## Comparison note: vendor vertical control vs portable institution semantics

Vendor vertical control systems (including Muse's Secure VM + Sentinel model) can enforce scoped permissions and external approvals inside a single vendor runtime boundary. That is a legitimate and useful control posture. It is not the same claim as portable institution semantics.

| Dimension | Vendor vertical control (e.g. Muse Sentinel posture) | AIE portable institution semantics |
|---|---|---|
| Authority locus | vendor-run service adjudicates actions for its own agents | portable semantics for resolved authority across runtimes |
| Scope model | vendor-specific grant shapes (one-time, session, task, time-bounded, perpetual) | portable delegation with attenuation/conservation invariants across runtimes |
| Revocation | vendor-enforced within the vendor boundary | governed revocation with declared freshness objectives and cross-runtime propagation concerns |
| Budget | vendor billing/usage control | portable budget inheritance/conservation as an institution primitive |
| Topology | vendor orchestration model | governed topology mutation under the same admission/evidence pipeline as tool actions |
| Evidence | vendor-centric logging/monitoring | portable evidence and settlement semantics with privacy-minimized defaults |
| Interoperability claim | product integration within the vendor ecosystem | external conformance parity across independent legs and, eventually, independent implementations |

Convergence on the existence of scoped permissions and external approval is expected and healthy. It does not collapse AIE's narrower portable-semantics boundary.

## Falsifier: "AIE is just vendor permissioning with new terminology"

**Objection:** AIE merely renames existing vendor permissioning, scope, revocation, and approval concepts and presents them as a new institution layer.

**Response:** If that were true, the testable difference would be empty. The falsifiable AIE boundary is portable semantics and external conformance, not vocabulary.

1. **Vocabulary is not the claim.** Scoped permissions, external authorization, revocation, least privilege, durable agent control, and human approvals are known/existing mechanism classes (see P-001, P-002). AIE does not claim these as novel. The prior-art ledger explicitly marks them as such.
2. **The narrower claim is portable and testable.** AIE's preserved boundary is portable authority/delegation semantics, monotonic attenuation/conservation, budget inheritance/conservation, governed topology mutation, cross-runtime conformance/interoperability, and portable evidence/settlement semantics. These are specified in `spec/` and exercised by conformance vectors and external interop legs, not asserted by terminology.
3. **External convergence is not reproduction.** Muse and comparable vendor control planes converge on the broad mechanism class of vendor-scoped permissioning and external approval. That is architectural convergence, not empirical reproduction of AIE's portable claims. A system can share a problem space with AIE without reproducing AIE's portable-semantics results.
4. **Novelty survives only if the testable difference survives.** If AIE's portable semantics were merely renamed vendor permissioning, then independent implementations, cross-runtime conformance, and external parity evidence would not be the right gates — vocabulary would be enough. The repository rejects that: promotion gates remain external reproducible evidence, independent implementation evidence, conformance vectors, unit/integration tests, and prose claims, in that order. No novelty statement survives solely because a term differs.

**Practical falsification path:** an independent implementation that reproduces AIE's portable semantics across runtimes, or an external conformance result that shows parity on the narrower claim surface, would be the kind of evidence that strengthens AIE. A vendor control plane that shares the broad mechanism class but does not reproduce the portable semantics does not falsify or validate the narrower claim — it only bounds the novelty statement.

## Evidence hierarchy reminder

`external reproducible evidence > independent implementation evidence > conformance vectors > unit/integration tests > prose claims`

Listing prior art in this ledger is a prose claim about the external landscape. It does not upgrade AIE empirical claims. It only keeps the novelty boundary honest.
