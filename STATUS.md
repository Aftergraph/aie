# Status

## Current maturity

- Core semantics: **AIE Draft 0.3**
- Reference gateway: **0.3.x**
- Current workstream: **v0.4-S1.2 external MCP/SPIRE interoperability**
- Promotion: **BLOCKED_EXTERNAL_RUNTIME** until official external gates pass

## Proven locally

- repository baseline: 131/131 tests passing before the S2 preparation slice
- current S2 A2A-preparation targeted suite: 16/16 tests passing after provenance, S1-attestation, malformed-evidence, and TCK-process-status hardening
- an earlier integrated S2 review tree reached 144/144; after scratch recovery the current PR head is reported conservatively as baseline + targeted evidence rather than claiming a fresh full-suite rerun
- A2A HTTP+JSON SSE/rotation slice: 11/11 targeted tests and 93/93 clean-room gateway regression tests passing locally; this is scoped implementation evidence, not official external TCK evidence
- two independent runtime paths for C0/D1/T1/F1 semantics
- durable replay, budget, revocation, and evidence state
- strict X.509-SVID identity validation and Workload API consumption
- MCP/A2A forwarding behind the same admission semantics
- gateway federation and privacy-minimized evidence
- S1.1/S1.2 harness generation and fail-closed promotion reporting
- provider-neutral self-hosted runner preflight and canonical promotion wrapper
- isolated per-run Python environment on persistent self-hosted runners
- pinned/checksum-verified GitHub Actions Runner bootstrap with non-root service identity and controlled deregistration
- main-only root-capable workflow with immutable checkout/upload Action pins
- fail-safe rollback/revocation of the dedicated runner sudoers grant
- weekly Dependabot coverage for Python and GitHub Actions dependencies
- wheel metadata emits SPDX `Apache-2.0`, bundled `LICENSE`, Markdown README, author, keywords, and canonical project URLs
- official A2A TCK 1.0.0 preparation harness pinned to commit `263b9cfa…`, using the upstream frozen `uv.lock`, official-origin verification, exact TCK exit-status evidence, and direct/SPIFFE/AIE MUST parity hard-gated on a validated canonical S1 attestation

## External blockers

GitHub Actions events are accepted by the repository, but repeated GitHub-hosted jobs terminated before runner execution with zero steps/logs. This remains an execution-environment blocker, not interoperability evidence.

The hosted external probe is therefore manual-only while the blocker is unresolved. A second manual workflow targets a dedicated Linux x64 self-hosted runner carrying the `aie-interop` label and preserves the same canonical `AIE_S1_1_PROMOTION.json` contract.

The repository now contains a pinned self-hosted runner installer, but registration itself still requires a fresh short-lived GitHub repository runner token and a dedicated/ephemeral Linux host. The connected GitHub integration available in this session cannot issue runner registration/removal tokens or register the host directly.

The next promotion proof remains live SPIRE + official MCP `2026-07-28` conformance parity across direct, bridge, and AIE legs. No provider may mark S1.2 green without that report and its raw evidence.
