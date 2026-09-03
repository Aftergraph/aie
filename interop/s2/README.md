# AIE S2 official A2A interoperability preparation

S2 proves that the AIE authority layer preserves official A2A 1.0 semantics across direct, SPIFFE-proxied, and SPIFFE+AIE paths. This directory is **preparation only** until S1.2 issue #5 has an external PASS attestation.

## Pinned upstream provenance

- A2A Protocol: `1.0`
- official `a2aproject/a2a-tck`: package version `1.0.0`
- pinned TCK commit: `263b9cfaf16a554bdfb166a7ba5b67716e946349`
- official Python SDK reference provenance: `1.0.2` (not a claim about the SUT implementation language)

The official TCK runs gRPC, JSON-RPC and HTTP+JSON when no transport filter is supplied. S2 runs only the TCK's MUST-level requirements for the promotion comparison.

## Promotion contract

`collect_report.py` compares:

1. identical official MUST requirement-ID sets across all three legs;
2. identical per-requirement status and per-transport result maps;
3. a semantically identical Agent Card capability/skill surface, excluding the endpoint URL;
4. a passing direct baseline;
5. the canonical S1 promotion dependency.

The output is `AIE_S2_A2A_INTEROP.json`.

- semantic mismatch or failing direct MUST -> `FAIL`
- perfect A2A parity but S1 not PASS -> `BLOCKED_BY_S1`
- perfect parity + S1 PASS -> `PASS`

A local synthetic test of the comparator is not A2A interoperability evidence. Raw official TCK reports remain required.

## Preparing the official TCK

`interop/s2/scripts/prepare_official_a2a.sh` clones the official repository, checks out the pinned commit detached, creates a fresh `.venv`, installs that checkout, and verifies its declared package version before any S2 run.
