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
2. identical official test-ID, status, and per-transport result maps;
3. non-empty coverage of gRPC, JSON-RPC, and HTTP+JSON on every leg;
4. a semantically identical Agent Card capability/skill surface, excluding the endpoint URL;
5. a passing direct baseline;
6. a structurally valid canonical S1 external attestation.

The S1 dependency is not satisfied by a bare `{"promotion":"PASS"}`. The attestation must carry the expected S1 profile/revision, live SPIRE result, all external rotation/trust gates, three passing legs with identical non-empty check IDs, zero semantic delta, and GitHub Actions run provenance.

The output is `AIE_S2_A2A_INTEROP.json`.

- semantic mismatch or failing direct MUST -> `FAIL`
- perfect A2A parity but invalid/non-PASS S1 attestation -> `BLOCKED_BY_S1`
- perfect parity + validated S1 PASS -> `PASS`

A local synthetic test of the comparator is not A2A interoperability evidence. Raw official TCK reports remain required.

## Preparing the official TCK

`interop/s2/scripts/prepare_official_a2a.sh` clones the official repository when absent and verifies an existing checkout still points at the pinned official origin. It checks out the pinned commit detached, requires the upstream `uv.lock`, creates a fresh environment with `uv sync --frozen --no-dev`, and verifies the TCK package version before any S2 run. Open-ended `pip install -e .` resolution is intentionally not used for the conformance environment.
