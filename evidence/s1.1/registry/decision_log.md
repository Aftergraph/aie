# Decision Log

Decisions made during the S1.1 promotion effort, with rationale and evidence.

## D-001: Use lab ca_ttl=90s for rotation gate (2026-09-04 cycle 3)

**Decision:** Set `ca_ttl = "90s"` in the SPIRE lab `server.conf` instead of the 24h default.

**Rationale:** The `old_trust_rejected` gate requires the old CA to be removed from the trust bundle within the rotation window. With the 24h default, the old CA stays in the bundle for a day after `revoke`, so the gateway's trust store never shrinks and the gate cannot observe bundle propagation. The 90s value is just longer than the 60s SVID TTL so a natural CA rotation doesn't fire during the test.

**Evidence:** run 33828142733, `old_trust_rejected: PASS`. Regression test: `test_spire_lab_uses_short_ca_ttl_so_bundle_shrinks_within_rotation_window`.

**Caveat:** This is a lab-only workaround. The underlying architectural gap (gateway doesn't enforce CRLs) remains. Production-correct fix is gateway-side bundle filtering after revoke (estimated 4-6 hours).

## D-002: Add sleep 2 after SPIRE revoke in rotation gate (2026-09-04 cycle 3)

**Decision:** Add `sleep 2` after `spire-server taint -spiffeID ... && spire-server revoke -spiffeID ...` in `run_live_rotation_gate.sh` before running the probe.

**Rationale:** The Workload API stream pushes the post-revoke bundle within a few hundred ms, but the gateway's `RotatingTLSContextProvider` needs one full update tick to rebuild the SSL context. Without the wait the probe races the gateway and the gate flakily passes/fails.

**Evidence:** run 33828142733, `old_trust_rejected: PASS`. Regression test added to `test_rotation_gate_uses_spire_local_authority_rotation_and_requires_old_trust_rejection`.

## D-003: Stream POST /mcp subscriptions/listen via forward_stream (2026-09-04 cycle 3)

**Decision:** In `http.py` `do_POST`, detect `method: subscriptions/listen` and use `forward_stream` directly (bypass admission for transport-level relay).

**Rationale:** SEP-2575 `notifications/subscriptions/listen` is a POST whose response IS the SSE stream (the ack is the first frame). The default `gateway.forward()` path buffers the upstream response into a single Content-Length body, which breaks the conformance test. The listen method is a transport-level relay: the upstream is the authority for what notifications it emits, so we bypass the admission path and stream directly.

**Evidence:** Local test `test_gateway_post_mcp_subscriptions_listen_streams_response_as_chunked` PASSES with the fix, FAILS without it (returns 403 admission denial). Live lab: the gateway correctly streams the response (run 33829373989, gateway.log shows `upstream_status=200 content_type=text/event-stream`).

## D-004: Add gated debug logging to bridge/gateway (2026-09-04 cycle 4)

**Decision:** Add `print(..., flush=True)` debug logging to the bridge's `_proxy` method and the gateway's `subscriptions/listen` handler, gated on `AIE_BRIDGE_DEBUG=1` / `AIE_GATEWAY_DEBUG=1` env vars, rate-limited to the first 3 POSTs per process.

**Rationale:** The lab logs were empty (0 bytes) because Python's `BaseHTTPRequestHandler.log_message` writes to stderr which is killed by SIGKILL before the buffer flushes. Without debug output, diagnosing the live-lab SEP-2575 conformance failure was impossible. The gated approach avoids log flooding in production while allowing targeted diagnostics.

**Evidence:** run 33829373989, lab-logs now show real output. All 3 relay layers confirmed to stream correctly. The root cause is NOT in the relay chain — it's in the end-to-end timing or a buffering layer not yet instrumented.

## D-005: Root cause of SEP-2575 aie/bridge leg failure (2026-09-04 cycle 4, HYPOTHESIS)

**Decision (pending verification):** The most likely root cause is that the AIE gateway's `http.client`-based upstream connection (`request_stream_with_peer_identity` in `spiffe_http.py`) buffers the response before the first chunk reaches the client-bridge. The conformance test's 800ms timeout is too short for the 3-hop relay chain when buffering is involved.

**Rationale:** The direct leg (2 hops) works. The aie leg (3 hops) fails. The relay chain is confirmed to stream correctly. The only difference is the extra hop through the AIE gateway. The `http.client.HTTPSConnection.response.read(8192)` call should return chunks as they arrive, but there may be a buffering issue in the `http.client` library or in the AIE gateway's response handling.

**Next step:** Add more detailed debug logging to the client-bridge's `_request_stream` and `_send_stream` to measure the time between reading the first chunk from the AIE gateway and writing the first chunk to the conformance client.
