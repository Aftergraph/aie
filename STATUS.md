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

Latest run `33828142733` produced:

- `promotion: FAIL` (script exited 4)
- `aie` leg: 163/195 pass, 32 fail
- `bridge` leg: 163/195 pass, 32 fail
- `direct` leg: 168/195 pass, 27 fail → demoted `PASS_UPSTREAM_GAP`
- external gates: `svid_rotation_live=PASS`, `trust_bundle_rotation_live=PASS`, `new_trust_works=PASS`, **`old_trust_rejected=PASS`** ← fixed this cycle

The 32-vs-27 leg delta is the 5 SEP-2575 server-sends-subscription
checks (AIE-specific; should not be demoted). The `old_trust_rejected`
gate now passes (lab `ca_ttl: 90s` + `sleep 2` after revoke), so the
remaining block is the SEP-2575 conformance path, not the rotation
gate.

### SEP-2575 conformance: deeper root cause

The SEP-2575 `subscriptions/listen` is a POST whose response IS the
SSE stream. The mcp-everything-server sets
`Content-Type: text/event-stream` for this response (verified in the
Python SDK v2.0.0 source at `streamable_http.py:650`).

The `direct` leg works: conformance client → server-bridge → mcp-server.
The server-bridge's `_is_event_stream` detects the header and streams
via `_send_stream` (also fixed this cycle for the chunked terminator
hang).

The `aie` and `bridge` legs fail: the conformance client → client-bridge
→ AIE gateway → server-bridge → mcp-server. The AIE gateway's `do_POST`
handler was buffering the upstream response into a single
Content-Length body via `forward()`, so the conformance client saw a
buffered response and reported "Failed to open or receive frames from
the subscriptions/listen stream endpoint".

Fix applied this cycle: `do_POST` detects `method: subscriptions/listen`
and uses `forward_stream` directly (same transport-level relay posture
as the GET /mcp handler). Local regression test
`test_gateway_post_mcp_subscriptions_listen_streams_response_as_chunked`
passes. **But the live lab still shows the same failure** — the fix
may not be reaching the bridge's POST handler for some reason (possibly
the `Content-Type` header from the mcp-server is being stripped or
re-typed by an intermediate layer, or the server-bridge's
`_is_event_stream` is not matching the header in the live path).

### What was fixed this cycle (commits on `main`)

- `bridge.py:122` — `if not chunk: continue` → `break` (chunked
  terminator hang). Regression test:
  `test_bridge_relays_sep2575_post_sse_acknowledged_frame`.
- `http.py:91` — same bug in the AIE HTTP gateway. Regression test:
  `test_gateway_get_mcp_streams_text_event_stream_as_chunked_and_terminates`.
- `http.py:236` — new: stream POST /mcp `subscriptions/listen` via
  `forward_stream` (bypass admission for transport-level relay).
  Regression test:
  `test_gateway_post_mcp_subscriptions_listen_streams_response_as_chunked`.
- `s1_interop.py:135` — return `promoted_legs` (with
  `PASS_UPSTREAM_GAP` demotion applied) instead of raw `legs`.
  Tests in `test_s1_report_v04.py` updated to assert the new
  contract.
- `rotation_probe.py:87-93` — use the original `old_client_ctx`
  (the snapshot from before rotation) for the `old_trust_rejected`
  gate instead of a fresh fetch (which returned the post-rotation
  SVID and made the gate tautological). Regression test:
  `test_rotation_probe_uses_original_old_context_for_trust_rejection_check`.
- `spire/server.conf` — `ca_ttl = "90s"` so the lab's bundle shrinks
  within the rotation window. Regression test:
  `test_spire_lab_uses_short_ca_ttl_so_bundle_shrinks_within_rotation_window`.
- `run_live_rotation_gate.sh` — `sleep 2` after SPIRE `revoke` to
  let the gateway consume the post-revoke bundle. Regression test
  added to `test_rotation_gate_uses_spire_local_authority_rotation_and_requires_old_trust_rejection`.
- Local test suite: **170 passed** (was 165 at cycle start; +5
  regression tests).

### Why the live lab aie/bridge legs still fail

The AIE gateway's POST `subscriptions/listen` streaming fix is in
place (verified deployed to VDS at `http.py:248`) but the conformance
test still reports "Failed to open or receive frames". Possible
causes not yet diagnosed in this cycle:
1. The server-bridge's `_is_event_stream` may not be matching the
   `text/event-stream` header from the mcp-server in the live lab
   (header normalization or case sensitivity issue).
2. The AIE gateway's `forward_stream` may be returning a buffered
   response for some reason (e.g., the SPIFFE verification path
   returns a non-streaming error).
3. The mcp-server may be returning a different `Content-Type` for
   the POST response than expected (e.g., `application/json` with
   the SSE body embedded, not `text/event-stream`).

Lab logs are empty for the bridges and gateway (0 bytes) because
Python's `BaseHTTPRequestHandler.log_message` writes to stderr which
is killed by SIGKILL before the buffer flushes. Diagnosing the
live-lab failure requires either adding `print(..., flush=True)` to
the bridge/gateway or using a proper logging framework.
