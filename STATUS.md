# Status

## Current maturity

- Core semantics: **AIE Draft 0.3**
- Reference gateway: **0.3.x**
- Current workstream: **v0.4-S1.2 external MCP/SPIRE interoperability**
- Promotion: **BLOCKED_EXTERNAL_RUNTIME** until official external gates pass

## Proven locally

- repository baseline: 165/165 tests passing after SEP-2575 SSE relay fix + report shape fix (post-#25)
- current S2 A2A-preparation targeted suite: 16/16 tests passing after provenance, S1-attestation, malformed-evidence, and TCK-process-status hardening
- an earlier integrated S2 review tree reached 144/144; after scratch recovery the current PR head is reported conservatively as baseline + targeted evidence rather than claiming a fresh full-suite rerun
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
- SEP-2575 SSE stream relay (post-#25): bridge no longer hangs on the chunked terminator; upstream `text/event-stream` responses are forwarded as chunked transfer-encoding to the downstream client
- in-house unit CI on the VDS self-hosted runner: 3.11/3.12/3.13 matrix runs `pip install -e .[dev,otel]` + `pytest -q` + `compileall` and posts the `ci/test (<py>)` check on the PR, so unit CI survives a GitHub Actions billing lock on the account

## External blockers

GitHub Actions events are accepted by the repository, but repeated GitHub-hosted jobs terminated before runner execution with zero steps/logs. This remains an execution-environment blocker, not interoperability evidence.

The hosted external probe is therefore manual-only while the blocker is unresolved. A second manual workflow targets a dedicated Linux x64 self-hosted runner carrying the `aie-interop` label and preserves the same canonical `AIE_S1_1_PROMOTION.json` contract.

The repository now contains a pinned self-hosted runner installer, but registration itself still requires a fresh short-lived GitHub repository runner token and a dedicated/ephemeral Linux host. The connected GitHub integration available in this session cannot issue runner registration/removal tokens or register the host directly.

The next promotion proof remains live SPIRE + official MCP `2026-07-28` conformance parity across direct, bridge, and AIE legs. No provider may mark S1.2 green without that report and its raw evidence.

GitHub Actions artifact storage quota is also exhausted on the `JonasAbde` account, so the S1.1 self-hosted workflow's `actions/upload-artifact` step fails after the promotion report is written. The in-house evidence is still on the VDS under `/home/nora/aie-evidence/<run_id>/`, mirrored to the runner's `_work/aie/aie/interop/s1/results/`. No live evidence is lost; only GH-side artifact retention is.

## S1.1 promotion block (post-#25)

Latest run `33826496344` produced:

- `promotion: FAIL` (script exited 4)
- `aie` leg: 163/195 pass, 32 fail
- `bridge` leg: 163/195 pass, 32 fail
- `direct` leg: 168/195 pass, 27 fail → demoted `PASS_UPSTREAM_GAP`
- external gates: `svid_rotation_live=PASS`, `trust_bundle_rotation_live=PASS`, `new_trust_works=PASS`, `old_trust_rejected=FAIL`

The 32-vs-27 leg delta is the 5 SEP-2575 server-sends-subscription
checks (AIE-specific; should not be demoted). If `old_trust_rejected`
were PASS, the AIE/bridge leg demotion logic in `s1_interop.py:119`
would demote them to `PASS_UPSTREAM_GAP` and `promotion` would
reach PASS.

### `old_trust_rejected` is a real architectural gap, not a probe bug

The AIE gateway uses Python's `ssl.SSLContext` which only validates
trust chains, not CRLs. SPIRE's `taint`+`revoke` operations add the
old CA to the bundle's revocation list, but the bundle continues to
include the old CA cert itself, so the gateway's trust store
continues to accept SVIDs signed by the revoked CA.

To enforce revocation, the gateway must:
1. Poll SPIRE's `localauthority x509` for revoked CAs
2. Filter the bundle to exclude revoked CAs
3. Build the SSL context with the filtered CA file

This is a feature, not a one-line fix, so it is out of scope for
the current cycle.

### What was fixed this cycle (commits on `main`)

- `bridge.py:122` — `if not chunk: continue` → `break` (chunked
  terminator hang). Regression test:
  `test_bridge_relays_sep2575_post_sse_acknowledged_frame`.
- `http.py:91` — same bug in the AIE HTTP gateway. Regression test:
  `test_gateway_get_mcp_streams_text_event_stream_as_chunked_and_terminates`.
- `s1_interop.py:135` — return `promoted_legs` (with
  `PASS_UPSTREAM_GAP` demotion applied) instead of raw `legs`.
  Tests in `test_s1_report_v04.py` updated to assert the new
  contract.
- `rotation_probe.py:87-93` — use the original `old_client_ctx`
  (the snapshot from before rotation) for the `old_trust_rejected`
  gate instead of a fresh fetch (which returned the post-rotation
  SVID and made the gate tautological). Regression test:
  `test_rotation_probe_uses_original_old_context_for_trust_rejection_check`.
- Local test suite: **168 passed** (was 165, +3 regression tests).
