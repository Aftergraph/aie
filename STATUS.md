# Status

## Current maturity

- Core semantics: **AIE Draft 0.3**
- Reference gateway: **0.3.x**
- Current workstream: **v0.4-S1.2 external MCP/SPIRE interoperability**
- Promotion: **BLOCKED_EXTERNAL_RUNTIME** until official external gates pass

## Proven locally

- 118/118 tests on the S1.2 runner-portability tree
- two independent runtime paths for C0/D1/T1/F1 semantics
- durable replay, budget, revocation, and evidence state
- strict X.509-SVID identity validation and Workload API consumption
- MCP/A2A forwarding behind the same admission semantics
- gateway federation and privacy-minimized evidence
- S1.1/S1.2 harness generation and fail-closed promotion reporting
- provider-neutral self-hosted runner preflight and canonical promotion wrapper

## External blockers

GitHub Actions events are accepted by the repository, but repeated GitHub-hosted jobs terminated before runner execution with zero steps/logs. This remains an execution-environment blocker, not interoperability evidence.

The hosted external probe is therefore manual-only while the blocker is unresolved. A second manual workflow targets a dedicated Linux x64 self-hosted runner carrying the `aie-interop` label and preserves the same canonical `AIE_S1_1_PROMOTION.json` contract.

The next promotion proof remains live SPIRE + official MCP `2026-07-28` conformance parity across direct, bridge, and AIE legs. No provider may mark S1.2 green without that report and its raw evidence.
