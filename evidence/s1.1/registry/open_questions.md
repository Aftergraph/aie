# Open Questions

Unresolved questions from the S1.1 promotion effort.

## OQ-001: What is the exact root cause of the SEP-2575 aie/bridge leg conformance failure?

**Context:** The relay chain is confirmed to stream correctly (E-004). The conformance test reports 0 frames within 800ms. The direct leg (2 hops) works; the aie leg (3 hops) fails.

**Hypotheses:**
1. The AIE gateway's `http.client`-based upstream connection buffers the response before the first chunk reaches the client-bridge.
2. The AIE gateway's response is being consumed by the client-bridge's `http.client` library in a way that blocks before the first frame reaches the conformance client.
3. End-to-end latency in the 3-hop relay chain exceeds the 800ms timeout.

**Status:** OPEN. Requires more detailed debug logging to pinpoint.

## OQ-002: Should the lab ca_ttl workaround be replaced with gateway-side bundle filtering?

**Context:** D-001 uses `ca_ttl = "90s"` as a lab workaround. The underlying architectural gap (gateway doesn't enforce CRLs) remains.

**Options:**
1. Accept the lab workaround (bounded test environment).
2. Implement gateway-side bundle filtering after revoke (estimated 4-6 hours, production-correct).
3. Use a different lab setup (e.g., a shorter rotation window that doesn't require ca_ttl changes).

**Status:** OPEN. Decision deferred to Jonas.

## OQ-003: Is the conformance test's 800ms timeout correct for the 3-hop relay chain?

**Context:** The conformance test's `c` function aborts the fetch after 800ms if no frames are received. This timeout is hardcoded in the conformance test source.

**Options:**
1. Accept the 800ms timeout and fix the relay chain to stream within it.
2. Modify the conformance test (but it's a third-party npm package).
3. Use a different conformance test that has a longer timeout.

**Status:** OPEN. If the root cause (OQ-001) is end-to-end latency, this may need to be revisited.

## OQ-004: Should the debug logging be removed from start_components.sh?

**Context:** D-004 added `AIE_BRIDGE_DEBUG=1` and `AIE_GATEWAY_DEBUG=1` to `start_components.sh`. This is fine for diagnostics but should be documented and the env vars should be off by default for clean runs.

**Options:**
1. Keep the env vars set (current state) — useful for ongoing diagnostics.
2. Remove the env vars and require them to be set explicitly when needed.
3. Keep the env vars but add a comment explaining when to use them.

**Status:** OPEN. Decision deferred to Jonas.

## OQ-005: When should the evidence/s1.1/AIE_S1_1_PROMOTION.json be refreshed?

**Context:** The current file on `main` is from a pre-fix run. It should be refreshed with the current run's evidence once `promotion: PASS` is achieved.

**Options:**
1. Refresh after the aie/bridge leg is fixed (when `promotion: PASS` is achieved).
2. Refresh after each cycle with the current run's evidence.
3. Keep the current file and add new evidence files for each run.

**Status:** OPEN. Current decision: refresh after `promotion: PASS` is achieved.
