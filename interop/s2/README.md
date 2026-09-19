# AIE S2 official A2A interoperability

S2 evaluates whether the AIE authority layer preserves official A2A 1.0 semantics across direct, SPIFFE-proxied, and SPIFFE+AIE paths.

**Current evidence boundary:** local three-leg official-TCK parity has produced a local S2 `PASS` with zero AIE semantic delta after shared upstream failures were classified separately. This is not an institutional/external S2 promotion claim. Issues #5/#6 remain the external-attestation gate.

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
4. an official TCK process result that is either `0` (tests pass) or `1` (test failures recorded in the compatibility report); process exits `>=2` fail the comparison;
5. a semantically identical Agent Card capability/skill surface, excluding the endpoint URL;
6. a passing direct baseline;
7. a structurally valid canonical S1 external attestation.

The S1 dependency is not satisfied by a bare `{"promotion":"PASS"}`. The attestation must carry the expected S1 profile/revision, live SPIRE result, all external rotation/trust gates, three passing legs with identical non-empty check IDs, an explicit empty semantic-delta list, and GitHub Actions run provenance. Malformed count fields are treated as validation failures rather than exceptions.

The output is `AIE_S2_A2A_INTEROP.json`.

- semantic mismatch, process crash (`exit >= 2`), leg-specific MUST failure, missing transport coverage, or Agent Card semantic mismatch -> `FAIL`
- a MUST failure shared identically by direct, SPIFFE, and AIE legs is recorded as an upstream gap rather than an AIE semantic delta
- perfect A2A parity but invalid/non-PASS S1 attestation -> `BLOCKED_BY_S1`
- perfect parity + validated S1 PASS -> `PASS`

## Current observed evidence

The recorded local three-leg official-TCK run produced the same result on direct, SPIFFE, and AIE legs: **183 passed, 5 failed, 47 skipped**. The comparator identified three MUST failures as shared upstream failures and produced local `promotion=PASS` with zero AIE semantic delta.

This evidence establishes local parity for the tested paths. It does **not** establish institutional/external S2 promotion while issues #5/#6 remain open. A synthetic comparator test alone is not interoperability evidence; raw official TCK reports, per-leg process status, and the required external attestation remain part of the promotion boundary.

## Preparing the official TCK

`interop/s2/scripts/prepare_official_a2a.sh` clones the official repository when absent and verifies an existing checkout still points at the pinned official origin. It checks out the pinned commit detached, requires the upstream `uv.lock`, creates a fresh environment with `uv sync --frozen --no-dev`, and verifies the TCK package version before any S2 run. Open-ended `pip install -e .` resolution is intentionally not used for the conformance environment.
