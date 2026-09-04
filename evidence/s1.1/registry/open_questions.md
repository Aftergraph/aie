# Open Questions — RESOLVED

All open questions from the S1.1 promotion effort have been resolved as of 2026-09-04 cycle 5 (run 33831755655, `promotion: PASS`).

## OQ-001: What is the exact root cause of the SEP-2575 aie/bridge leg conformance failure?

**Status: RESOLVED.**

**Root cause:** `http.client.HTTPResponse.read(amt)` can wait for and coalesce multiple HTTP chunks on long-lived SSE responses. On the aie leg (3-hop relay chain), this caused the first SSE frame to be delayed past the conformance test's 800ms timeout.

**Fix:** Change `response.read(8192)` to `response.read1(8192)` in all three relay paths (spiffe_http.py, bridge.py, forwarding.py).

**Evidence:** run 33831755655, `promotion: PASS`.

## OQ-002: Should the lab ca_ttl workaround be replaced with gateway-side bundle filtering?

**Status: DEFERRED.** The lab workaround is acceptable for the bounded test environment. The production-correct fix (gateway-side bundle filtering after revoke) remains a future improvement.

## OQ-003: Is the conformance test's 800ms timeout correct for the 3-hop relay chain?

**Status: RESOLVED.** With the read1() fix, the 800ms timeout is sufficient for the 3-hop relay chain.

## OQ-004: Should the debug logging be removed from start_components.sh?

**Status: DEFERRED.** The debug logging (gated on AIE_BRIDGE_DEBUG=1 / AIE_GATEWAY_DEBUG=1) is still useful for future diagnostics. It can be removed when the promotion is stable and no longer needs debugging.

## OQ-005: When should the evidence/s1.1/AIE_S1_1_PROMOTION.json be refreshed?

**Status: RESOLVED.** The file has been refreshed with the PASS report from run 33831755655.

## Next Open Questions (post-promotion)

1. **Should the debug logging in bridge.py and http.py be removed?** The timing logs (added in cycle 4-5) are useful for diagnostics but add overhead. Consider gating them more strictly or removing them once the promotion is stable.
2. **Should the lab ca_ttl workaround be replaced with gateway-side bundle filtering?** This is the production-correct fix for the architectural gap. Estimated 4-6 hours of work.
3. **Should the AIE_GATEWAY_DEBUG and AIE_BRIDGE_DEBUG env vars be set in production?** Currently they're set in the lab's start_components.sh but not in production configs.
