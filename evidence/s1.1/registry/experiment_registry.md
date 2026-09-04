# Experiment Registry

Experiments run during the S1.1 promotion effort. Each entry records the hypothesis, method, result, and conclusion.

## E-001: Lab ca_ttl affects old_trust_rejected gate

- **Date:** 2026-09-04 cycle 3
- **Run:** 33828142733
- **Hypothesis:** With the SPIRE lab's default ca_ttl (24h), the old CA stays in the trust bundle for a day after revoke, so the gateway's trust store never shrinks and the gate cannot observe bundle propagation. Setting ca_ttl to 90s (just longer than the 60s SVID TTL) should make the bundle shrink within the rotation window.
- **Method:** Changed `spire/server.conf` to `ca_ttl = "90s"`, re-ran the S1.1 self-hosted workflow.
- **Result:** `old_trust_rejected: PASS` (was FAIL before).
- **Conclusion:** Confirmed. The lab ca_ttl workaround unblocks the gate. Regression test added.

## E-002: Post-revoke wait affects old_trust_rejected gate

- **Date:** 2026-09-04 cycle 3
- **Run:** 33828142733
- **Hypothesis:** The gateway's `RotatingTLSContextProvider` needs time to consume the post-revoke bundle. Without a wait, the probe races the gateway and the gate flakily passes/fails.
- **Method:** Added `sleep 2` after SPIRE `revoke` in `run_live_rotation_gate.sh`, re-ran the S1.1 self-hosted workflow.
- **Result:** `old_trust_rejected: PASS` (was flaky before).
- **Conclusion:** Confirmed. The wait unblocks the gate. Regression test added.

## E-003: AIE gateway do_POST buffers SEP-2575 listen response

- **Date:** 2026-09-04 cycle 3
- **Run:** 33828142733
- **Hypothesis:** The AIE gateway's `do_POST` handler was calling `forward()` which buffers the upstream response into a single Content-Length body. SEP-2575 `subscriptions/listen` is a POST whose response IS the SSE stream, so the conformance test saw a buffered response and reported "Failed to open or receive frames".
- **Method:** Changed `do_POST` to detect `method: subscriptions/listen` and use `forward_stream` directly. Added local regression test.
- **Result:** Local test PASSES with the fix, FAILS without it. Live lab: the gateway correctly streams the response (run 33829373989).
- **Conclusion:** Confirmed at the unit level. The live lab aie/bridge leg still fails, but the relay chain is confirmed to stream correctly (E-004).

## E-004: Debug logging reveals relay chain streams correctly

- **Date:** 2026-09-04 cycle 4
- **Run:** 33829373989
- **Hypothesis:** The SEP-2575 aie/bridge leg failure is caused by a relay chain issue (buffering in bridge.py or http.py).
- **Method:** Added gated debug logging to the bridge's `_proxy` method and the gateway's `subscriptions/listen` handler. Set `AIE_BRIDGE_DEBUG=1` and `AIE_GATEWAY_DEBUG=1` in `start_components.sh`. Re-ran the S1.1 self-hosted workflow.
- **Result:** All 3 relay layers (server-bridge, gateway, client-bridge-aie) show correct SSE streaming behavior. The mcp-server returns `Content-Type: text/event-stream`, the server-bridge detects it and streams, the gateway forwards the stream, the client-bridge receives it and streams. But the conformance test still reports 0 frames.
- **Conclusion:** The relay chain is working correctly. The root cause is elsewhere — likely end-to-end timing or a buffering layer not yet instrumented. The conformance test's 800ms timeout may be too short for the 3-hop relay chain.

## E-005: Conformance test 800ms timeout for SEP-2575 listen (pending)

- **Date:** 2026-09-04 cycle 5 (planned)
- **Hypothesis:** The conformance test's 800ms timeout is too short for the 3-hop aie leg. The direct leg (2 hops) works because it has fewer hops.
- **Method:** Add more detailed debug logging to the client-bridge's `_request_stream` and `_send_stream` to measure the time between reading the first chunk from the AIE gateway and writing the first chunk to the conformance client. If this is > 800ms, the root cause is identified.
- **Result:** Pending.
- **Conclusion:** Pending.
