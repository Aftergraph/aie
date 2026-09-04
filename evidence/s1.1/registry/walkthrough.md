# S1.1 Promotion Walkthrough

End-to-end walkthrough of the S1.1 promotion effort, from initial state to PASS.

## Initial State (2026-09-03)

- Core semantics: AIE Draft 0.3
- Reference gateway: 0.3.x
- Current workstream: v0.4-S1.2 external MCP/SPIRE interoperability
- Promotion: BLOCKED_EXTERNAL_RUNTIME
- Local test baseline: 165/165
- External blockers: GitHub Actions billing lock, artifact storage quota

## Goal

Promote S1.1 to PASS by producing a canonical `AIE_S1_1_PROMOTION.json` with:
- All 4 external rotation gates PASS
- All 3 legs (direct, bridge, aie) either fully PASS or correctly demoted to `PASS_UPSTREAM_GAP`
- `live_spire: PASS`

## Approach

The S1.1 promotion is exercised by the `AIE v0.4 S1 Self-hosted External Interop` GitHub Actions workflow, which:
1. Checks out the repo on a dedicated/ephemeral Linux host with the `aie-interop` label
2. Runs the canonical S1 proof script
3. Shows the promotion report
4. Uploads external evidence (quota-blocked on JonasAbde)

The canonical S1 proof:
1. Starts a SPIRE 1.15.2 lab with the MCP Python SDK v2.0.0 everything-server
2. Starts three relay legs: direct (client-bridge-direct → server-bridge → mcp-server), bridge (client-bridge-bridge → server-bridge → mcp-server), aie (client-bridge-aie → AIE gateway → server-bridge → mcp-server)
3. Runs the official MCP conformance test against each leg
4. Runs the live SPIRE rotation gate (svid_rotation_live, trust_bundle_rotation_live, new_trust_works, old_trust_rejected)
5. Writes the promotion report

## What Was Fixed (5 cycles)

### Cycle 1: SEP-2575 SSE stream passthrough (commits f58dffe, a89fc53)

**Problem:** The bridge's `for chunk in stream` loop used `continue` on the empty-chunk terminator, which caused the bridge to hang on the chunked terminator and drop every SEP-2575 stream frame on the floor.

**Fix:** Change `continue` to `break` in the bridge's `_send_stream` and the AIE gateway's `_stream` methods.

**Evidence:** Local regression test `test_bridge_relays_sep2575_post_sse_acknowledged_frame` passes. `test_gateway_get_mcp_streams_text_event_stream_as_chunked_and_terminates` passes.

### Cycle 2: Report shape fix (commit f58dffe)

**Problem:** `s1_interop.build_report` returned raw `legs` instead of `promoted_legs`, so the report could say `promotion: PASS` while every leg was still `FAIL`.

**Fix:** Return `promoted_legs` (with `PASS_UPSTREAM_GAP` demotion applied) instead of raw `legs`.

**Evidence:** `test_s1_report_v04.py` updated to assert the new contract.

### Cycle 3: Rotation gate fixes (commits f90ce32, 58f0478)

**Problem 1:** The `old_trust_rejected` gate was tautological — it re-fetched the SVID for the old trust check, but after rotation the post-rotation SVID was returned, so the gate was checking the wrong context.

**Fix 1:** Use the original `old_client_ctx` (the snapshot from before rotation) for the `old_trust_rejected` gate.

**Problem 2:** The SPIRE lab's default `ca_ttl` (24h) meant the old CA stayed in the trust bundle for a day after `revoke`, so the gateway's trust store never shrank and the gate couldn't observe bundle propagation.

**Fix 2:** Set `ca_ttl = "90s"` in the lab's `server.conf` (just longer than the 60s SVID TTL so a natural CA rotation doesn't fire during the test).

**Problem 3:** The gateway's `RotatingTLSContextProvider` needs time to consume the post-revoke bundle. Without a wait, the probe races the gateway and the gate flakily passes/fails.

**Fix 3:** Add `sleep 2` after SPIRE `revoke` in `run_live_rotation_gate.sh`.

**Evidence:** run 33828142733, `old_trust_rejected: PASS` (was FAIL before).

### Cycle 4: AIE gateway POST subscriptions/listen (commit 4bdd811)

**Problem:** The AIE gateway's `do_POST` handler was calling `forward()` which buffers the upstream response into a single Content-Length body. SEP-2575 `subscriptions/listen` is a POST whose response IS the SSE stream (the ack is the first frame). The conformance test saw a buffered response and reported "Failed to open or receive frames".

**Fix:** In `do_POST`, detect `method: subscriptions/listen` and use `forward_stream` directly (bypass admission for transport-level relay). Same posture as the GET /mcp handler.

**Evidence:** Local test `test_gateway_post_mcp_subscriptions_listen_streams_response_as_chunked` passes.

### Cycle 5: read1() fix (commits dabd11c, 2430a42, f7840fc by Jonas)

**Problem:** `http.client.HTTPResponse.read(amt)` can wait for and coalesce multiple HTTP chunks on long-lived SSE responses. On the aie leg (3-hop relay chain), this caused the first SSE frame to be delayed past the conformance test's 800ms timeout. The direct leg (2-hop) worked because the delay was within tolerance.

**Fix:** Change `response.read(8192)` to `response.read1(8192)` in all three relay paths:
- `spiffe_http.py::request_stream_with_peer_identity._Stream.__next__` (SPIFFE TLS path)
- `bridge.py::_request_stream._Stream.__next__` (non-SPIFFE TLS path)
- `forwarding.py::HTTPUpstreamForwarder.forward_stream._Stream.__next__` (urllib path)

`read1()` returns the first available buffered bytes without waiting to fill a larger read, so event frames cross the relay promptly.

**Evidence:** run 33831755655, `promotion: PASS`.

## Final State (2026-09-04 cycle 5)

- Promotion: **PASS** (run 33831755655)
- All 4 external rotation gates PASS
- All 3 legs correctly demoted to `PASS_UPSTREAM_GAP` (195 checks each)
- `live_spire: PASS`
- Local test suite: 173/173 (+8 new regression tests)
- Evidence archived at `/home/nora/aie-evidence/33831755655/` (344KB)

## Lessons Learned

1. **Lab workarounds are acceptable for bounded test environments.** The `ca_ttl: 90s` workaround unblocks the rotation gate but doesn't fix the underlying architectural gap (gateway doesn't enforce CRLs). This is acceptable for a lab but should be addressed for production.

2. **http.client read coalescing is a real issue for SSE relay.** `read(amt)` can wait for and coalesce multiple HTTP chunks, which breaks prompt SSE delivery. `read1(amt)` is the correct API for streaming responses.

3. **Debug logging is essential for diagnosing relay issues.** The `AIE_BRIDGE_DEBUG` and `AIE_GATEWAY_DEBUG` env vars (since removed) were the only way to see what was happening in the live lab, since `BaseHTTPRequestHandler.log_message` writes to stderr which is killed by SIGKILL before the buffer flushes.

4. **3-hop relay chains are sensitive to end-to-end latency.** The direct leg (2-hop) worked because the delay was within tolerance. The aie leg (3-hop) failed because the extra hop added enough latency to exceed the conformance test's 800ms timeout.

## What Was NOT Fixed (Future Work)

1. **Gateway-side bundle filtering after revoke.** The lab `ca_ttl: 90s` workaround papers over the architectural gap. The production-correct fix is to poll SPIRE's `localauthority x509` for revoked CAs and filter the bundle.

2. **Debug logging was removed** but the env vars (`AIE_BRIDGE_DEBUG`, `AIE_GATEWAY_DEBUG`) are no longer recognized. If future diagnostics are needed, the logging should be re-added with proper gating.

3. **Runner housekeeping self-heal.** The `_work/aie/aie/` corruption pattern from earlier cycles should be addressed in the in-house workflow.

4. **GitHub Actions billing lock.** The GH-hosted CI continues to fail. The in-house CI on the VDS self-hosted runner is the workaround.
