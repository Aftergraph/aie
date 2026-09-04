# Changelog

## v0.4-S1.1 external promotion — 2026-09-04

- promote S1.1 to PASS (run 33831755655) with all 4 external rotation gates PASS and all 3 legs correctly demoted to `PASS_UPSTREAM_GAP` (195 checks each)
- fix `spiffe_http.py`, `bridge.py`, `forwarding.py` to use `response.read1(8192)` instead of `response.read(8192)` for prompt SSE relay through `http.client`; the coalescing read was delaying the first SSE frame past the conformance test's 800ms timeout on the 3-hop aie leg
- add `tests/gateway/test_s1_bridge_streaming_v04.py::test_plain_bridge_stream_yields_first_available_http_chunk` and `tests/gateway/test_forward_streaming_v03.py::test_plain_forward_stream_yields_first_available_http_chunk` as regression tests for the read1() fix
- add `tests/gateway/test_s1_bridge_v04.py::test_plain_client_bridge_forwards_arbitrary_method_path_headers_and_body_over_spiffe_mtls` for plain bridge SPIFFE mTLS forwarding
- add `tests/gateway/test_http_gateway.py::test_gateway_post_mcp_subscriptions_listen_streams_response_as_chunked` for the AIE gateway POST subscriptions/listen streaming fix
- add `tests/s1/test_spire_lab_uses_short_ca_ttl_so_bundle_shrinks_within_rotation_window` for the lab ca_ttl=90s workaround
- extend `tests/s1/test_rotation_gate_uses_spire_local_authority_rotation_and_requires_old_trust_rejection` to assert the post-revoke sleep
- add `evidence/s1.1/registry/claim_evidence_audit.md`, `decision_log.md`, `experiment_registry.md`, `open_questions.md` for tracked claims, decisions, experiments, and open questions
- set `ca_ttl = "90s"` in the SPIRE lab `server.conf` so the old CA is removed from the trust bundle within the rotation window
- add `sleep 2` after SPIRE `revoke` in `run_live_rotation_gate.sh` to let the gateway consume the post-revoke bundle
- set `AIE_BRIDGE_DEBUG=1` and `AIE_GATEWAY_DEBUG=1` env vars in `interop/s1/scripts/start_components.sh` for SEP-2575 diagnostics
- refresh `evidence/s1.1/AIE_S1_1_PROMOTION.json` with the PASS report from run 33831755655
- archive run evidence at `/home/nora/aie-evidence/33831755655/` (344KB: AIE_S1_1_PROMOTION.json, rotation/, lab-logs/, preflight.json)

## v0.4-S1.2 SEP-2575 SSE stream passthrough — 2026-09-04

- relay SEP-2575 `notifications/subscriptions/listen` and other `text/event-stream` upstream responses as chunked transfer-encoding to the downstream client; the bridge's `for chunk in stream` loop now `break`s on the empty-chunk terminator (previously `continue`d, which hung the bridge on the chunked terminator and dropped every SEP-2575 stream frame on the floor)
- fix `s1_interop.build_report` to return the demoted `promoted_legs` so `leg.<name>.status` in the report shape matches the `promotion` decision; previously the report could say `promotion: PASS` while every leg was still `FAIL`, an incoherent contract
- add in-house unit CI: `aie-v04-ci-self-hosted.yml` runs the 3.11/3.12/3.13 matrix on the VDS self-hosted runner via `uv` + per-job venv, so unit CI survives the GitHub Actions billing lock that previously blocked PR-side checks
- add `tests/gateway/test_s1_bridge_v04.py::test_bridge_relays_sep2575_post_sse_acknowledged_frame` as a SEP-2575-specific regression that exercises the exact POST /mcp + text/event-stream + open-connection pattern the official conformance test uses
- add `tools/ci_status_publisher.py` + `tests/test_ci_status_publisher.py` as a standalone commit-status poster for out-of-band CI scenarios (Windows local, manual canary, future webhooks); not invoked from the workflow itself because the in-house workflow's job result is already a commit-status check

## v0.4-S2 A2A TCK preparation — 2026-09-03

- pin official `a2aproject/a2a-tck` package `1.0.0` to commit `263b9cfaf16a554bdfb166a7ba5b67716e946349`
- record official A2A Protocol `1.0` and Python SDK `1.0.2` reference provenance without claiming the SUT implementation language
- add deterministic TCK checkout/venv preparation with official-origin verification, exact commit verification, upstream `uv.lock` via `uv sync --frozen --no-dev`, and package-version verification
- add three-leg MUST-level official TCK runner for direct, SPIFFE-proxied, and SPIFFE+AIE endpoints across all TCK transports
- add fail-closed comparator for requirement IDs, official test IDs, per-transport status maps, transport coverage, Agent Card semantic capability parity, and per-leg official TCK process exit status
- emit `AIE_S2_A2A_INTEROP.json` with `BLOCKED_BY_S1` until the canonical S1 promotion attestation passes profile/revision, live SPIRE, external gate, leg parity, explicit zero semantic delta, and GitHub Actions provenance validation; malformed evidence blocks rather than crashes
- add regression coverage for empty MUST sets, missing transports, false capability advertisement, parity mismatch, malformed S1 evidence, and non-zero TCK execution

## v0.3.0 distribution metadata hardening — 2026-09-03

- raise the setuptools build-backend floor to `>=77.0.3` for PEP 639/SPDX license metadata
- declare `Apache-2.0` via `License-Expression` and include the top-level `LICENSE` in built wheels
- use the repository README as the Markdown package long description
- add author, keywords, and canonical Repository/Issues/Changelog/Documentation URLs to wheel metadata
- add executable regression coverage for the PEP 621/PEP 639 project metadata contract

## v0.4-S1.2 runner provisioning — 2026-09-03

- pin GitHub Actions Runner `v2.337.0` with the official Linux x64 SHA-256
- add checksum-verified bootstrap for a dedicated non-root `aie-runner` service
- require explicit dedicated-host opt-in before granting the S1 lab passwordless sudo boundary
- consume registration/removal tokens only as short-lived environment input and never persist them in repo evidence
- disable runner automatic updates so the externally tested execution runtime remains pinned and auditable
- restrict the root-capable self-hosted proof to `main` and pin checkout/artifact Actions by immutable commit SHA
- roll back the sudoers grant on incomplete bootstrap and revoke it even when deregistration fails
- add controlled service deregistration while preserving runner files for diagnostics/audit
- add regression coverage for pinning, checksum verification, token redaction, labels, system service lifecycle and removal

## v0.4-S1.2 runner portability — 2026-09-03

- add read-only manual self-hosted Linux workflow with dedicated `aie-interop` runner label
- add fail-fast external-host preflight for privilege, network, tools, disk, workspace access and fixed lab ports
- add runner-neutral wrapper that reuses the canonical S1.1 promotion contract and evidence paths
- create a fresh per-run Python venv so persistent runners are not mutated globally and PEP 668 hosts remain compatible
- disable checkout credential persistence and explicitly clean the persistent runner workspace before execution
- make the known-blocked GitHub-hosted external probe manual-only to avoid false-red `main` pushes
- add regression coverage for runner routing, permission boundaries, preflight requirements and promotion-contract reuse

## v0.4-S1.1 interop harness — 2026-09-03

- add read-only GitHub Actions external interoperability workflow
- add pinned SPIRE 1.15.2 download and SHA-256 verification
- add official MCP three-leg conformance harness using frozen 2026-07-28 requirements
- add live local X.509 authority prepare → activate → revoke gate
- add SVID/bundle change observation and old-trust rejection evidence
- add absolute tool-path handling across sudo/runuser boundaries
- isolate writable SQLite and evidence paths for distinct Unix workload identities
- add canonical S1.1 promotion report with GitHub run provenance
- keep external promotion blocked unless live SPIRE, rotation gates and all official MCP legs pass with zero semantic delta

## 0.3.0 — 2026-09-03

- add mutual-TLS inbound identity and strict X.509-SVID leaf validation
- add SPIFFE Workload API `FetchX509SVID` client and TLS-context materialization from SVID snapshots
- add expected-peer SPIFFE identity pinning for outbound HTTPS
- add transparent admitted MCP 2026-07-28 and A2A 1.0 forwarding
- distinguish deterministic upstream trust failures from terminal uncertain dispatch outcomes
- add OpenTelemetry decision spans with W3C trace-context inheritance
- add mutual-TLS gateway federation and durable revocation propagation
- add v0.3 error registry, conformance vectors, real-trust example configuration, and promotion documentation

## 0.2.0

- add HTTP admission gateway, protocol normalization, durable SQLite state, OPA adapter, metadata-only evidence and black-box reference conformance

## 0.1.0

- add two independent AIE Draft 0.3 runtime implementations and cross-runtime authority handoff proof
