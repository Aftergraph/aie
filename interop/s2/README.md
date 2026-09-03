# AIE S2 official A2A interoperability preparation

S2 proves that the AIE authority layer preserves official A2A 1.0 semantics across direct, SPIFFE-proxied, and SPIFFE+AIE paths. This directory is **preparation only** until S1.2 issue #5 has an external PASS attestation.

## Pinned upstream provenance

- A2A Protocol: `1.0`
- official `a2aproject/a2a-tck`: package version `1.0.0`
- pinned TCK commit: `263b9cfaf16a554bdfb166a7ba5b67716e946349`
- official Python SDK reference provenance: `1.0.2` (not a claim about the SUT implementation language)

The official TCK runs gRPC, JSON-RPC and HTTP+JSON when no transport filter is supplied. S2 runs only the TCK's MUST-level requirements for the promotion comparison.

## Runtime transport coverage

The reference gateway currently has two distinct A2A binding surfaces:

| Binding | Current implementation status | External TCK proof |
|---|---|---|
| JSON-RPC 1.0 | existing admission + forwarding | not yet promoted |
| HTTP+JSON 1.0 non-streaming | `POST /message:send`, `GET /tasks`, `GET /tasks/{id}`, `POST /tasks/{id}:cancel`; original method/path/query/body preserved upstream | not yet run externally |
| HTTP+JSON streaming/SSE | not implemented in this slice (`/message:stream`, `/tasks/{id}:subscribe`) | not claimed |
| HTTP+JSON push-notification resources | not implemented in this slice | not claimed |
| gRPC 1.0 | not implemented | not claimed |

HTTP+JSON tenant routing is treated as an authority boundary. When a tenant-prefixed REST route is used, the tenant is canonicalized into the AIE resource (`a2a://tenant/<tenant>/...`). For body-carrying operations, path and request-body tenant values must agree. A non-tenant lease cannot authorize a tenant-scoped request.

Repeatable HTTP+JSON reads receive per-request action identifiers so ordinary GETs do not collide with replay/budget ledgers. Mutating send/cancel operations use deterministic identities and remain replay-protected.

This runtime implementation is **implementer evidence**, not official A2A interoperability evidence. S2 promotion still requires the raw official TCK reports across all required transports and all three direct/SPIFFE/AIE legs.

## Promotion contract

`collect_report.py` compares:

1. identical official MUST requirement-ID sets across all three legs;
2. identical official test-ID, status, and per-transport result maps;
3. non-empty coverage of gRPC, JSON-RPC, and HTTP+JSON on every leg;
4. a zero official TCK process exit code on every leg;
5. a semantically identical Agent Card capability/skill surface, excluding the endpoint URL;
6. a passing direct baseline;
7. a structurally valid canonical S1 external attestation.

The S1 dependency is not satisfied by a bare `{"promotion":"PASS"}`. The attestation must carry the expected S1 profile/revision, live SPIRE result, all external rotation/trust gates, three passing legs with identical non-empty check IDs, an explicit empty semantic-delta list, and GitHub Actions run provenance. Malformed count fields are treated as validation failures rather than exceptions.

The output is `AIE_S2_A2A_INTEROP.json`.

- semantic mismatch, non-zero TCK process status, or failing direct MUST -> `FAIL`
- perfect A2A parity but invalid/non-PASS S1 attestation -> `BLOCKED_BY_S1`
- perfect parity + validated S1 PASS -> `PASS`

A local synthetic test of the comparator is not A2A interoperability evidence. Raw official TCK reports and per-leg process status remain required.

## Preparing the official TCK

`interop/s2/scripts/prepare_official_a2a.sh` clones the official repository when absent and verifies an existing checkout still points at the pinned official origin. It checks out the pinned commit detached, requires the upstream `uv.lock`, creates a fresh environment with `uv sync --frozen --no-dev`, and verifies the TCK package version before any S2 run. Open-ended `pip install -e .` resolution is intentionally not used for the conformance environment.
