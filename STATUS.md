# Status

## Current maturity

- Core semantics: **AIE Draft 0.3**
- Reference gateway: **0.3.x**
- Current workstream: **v0.4-S1.1 external MCP/SPIRE interoperability**
- Promotion: **BLOCKED_EXTERNAL_RUNTIME** until official external gates pass

## Proven locally

- 114/114 tests on the canonical repository tree
- two independent runtime paths for C0/D1/T1/F1 semantics
- durable replay, budget, revocation, and evidence state
- strict X.509-SVID identity validation and Workload API consumption
- MCP/A2A forwarding behind the same admission semantics
- gateway federation and privacy-minimized evidence
- S1.1 harness generation and fail-closed promotion reporting

## External blockers

GitHub Actions events are accepted by the repository, but the initial GitHub-hosted jobs terminated before runner allocation (`runner_id: 0`, zero steps). This is tracked as an execution-environment blocker, not as passing interoperability evidence.

The next promotion proof remains live SPIRE + official MCP `2026-07-28` conformance parity across direct, bridge, and AIE legs.
