# Meta Muse Prior-Art Note — 2026-09-09

**Status:** Research/prior-art note for AIE Draft 0.3. This note does not modify the normative Draft 0.3 specification, expand conformance scope, or claim legal novelty.

## Purpose

Meta's 2026 Muse publications are now explicit prior art/comparator material for AIE. They demonstrate that production-oriented agent systems independently converge on mechanisms such as persistent execution, external authorization, scoped approvals, credential separation, network mediation, and human escalation.

That convergence strengthens the relevance of the systems problem while simultaneously narrowing what AIE may plausibly claim as a research contribution.

## Dated comparator sources

| Date | Source | Relevant scope |
|---|---|---|
| 2026-08-05 | Meta AI Research, *Introducing Muse Code and Muse Spark 1.2* | Persistent asynchronous background agents, long-horizon work, goals/plans, recovery/event-log patterns, multi-agent execution |
| 2026-09-02 | Meta AI Research, *Introducing Muse Spark 1.3* | Long-horizon agentic workflows, tool use, constraint retention, recovery and human escalation |
| 2026-09-08 | Meta AI Research, *Security and Safety for AI Agents: Our Approach with Muse* | Isolated agent execution, external permission authority, scoped approvals, credential separation/brokering, network-egress mediation, durable state |

Canonical URIs:

- https://research.meta.ai/blog/introducing-muse-code-and-muse-spark-1-2
- https://research.meta.ai/blog/introducing-muse-spark-1-3
- https://research.meta.ai/blog/security-and-safety-for-ai-agents-our-approach-with-muse

## Claims AIE must not present as novel by themselves

The following mechanisms are known/adjacent prior art and may be implemented by AIE-compatible systems without constituting an AIE novelty claim:

- external authorization separated from the reasoning agent;
- scoped, expiring, revocable permissions;
- least-privilege tool/connector access;
- human approval of consequential actions;
- persistent/background agent execution;
- durable state outside a conversational turn;
- credential isolation or brokered credential resolution;
- network-egress mediation;
- agent-authored skills/connectors as a general mechanism.

Terminology differences do not restore novelty. A claim does not become new merely because AIE calls a product-specific permission a lease, grant, capability, or institutional object.

## Narrower candidate AIE contribution boundary

AIE remains an experimental project for **portable institution semantics** across heterogeneous systems. Candidate contribution areas that remain subject to prior-art review and falsification include:

1. portable authority and delegation semantics that are independent of a specific vendor/runtime;
2. monotonic authority attenuation/conservation through delegation chains;
3. budget inheritance/conservation coupled to delegated authority;
4. governed topology mutation and lifecycle semantics;
5. cross-runtime conformance/interoperability for the same institutional semantics;
6. portable evidence/settlement semantics that can connect execution to independently verified outcomes.

These are candidate boundaries, not established novelty conclusions.

## Vertical control system vs portable institution semantics

A useful comparison is:

```text
vendor vertical control system
  owns product runtime + permission engine + connectors + execution environment
  can enforce product-specific scoped permissions very strongly

AIE target
  does not own the runtime or enforcement implementation
  defines portable authority/delegation/lifecycle/budget semantics
  requires independent implementations to preserve the same institutional meaning
```

AIE therefore must be falsifiable by interoperability, not by vocabulary.

## Objection: "AIE is just vendor permissioning with new terminology"

**Strongest form of objection:** If AIE's observable semantics reduce to ordinary scoped permissions/approvals already implemented by vertical products such as Muse, and no independent runtime can demonstrate additional portable delegation, conservation, lifecycle, budget, or conformance behavior, then AIE adds terminology rather than an engineering layer.

**Falsifier / rejection condition:** Reject or materially narrow the AIE layer if prior art or an independent implementation already provides the same portable semantics across heterogeneous runtimes with equivalent delegation conservation, budget inheritance, topology/lifecycle rules, evidence semantics, and conformance evidence.

**Evidence required to resist the objection:**

- at least two independent runtimes preserving the same normative AIE semantics;
- conformance tests that distinguish AIE behavior from ordinary product-specific permission checks;
- negative/adversarial tests showing conservation/attenuation failures are detected;
- no dependency on AIE's reference implementation to interpret the normative result.

## Research-boundary rule

Meta Muse is evidence of **external architectural convergence**. It is not:

- an external AIE implementation;
- AIE conformance evidence;
- independent reproduction of AIE experiments;
- evidence that Meta used or derived from AIE;
- evidence that AIE is legally novel or patentable.

AIE's existing external S1.1 interoperability evidence remains governed by its own exact artifacts and promotion records. This note does not upgrade or downgrade those results.

## Change-control rule

This note is additive prior-art analysis. Normative Draft 0.3 files under `spec/` remain unchanged unless a separately reviewed standards change has evidence sufficient to justify a versioned specification amendment.