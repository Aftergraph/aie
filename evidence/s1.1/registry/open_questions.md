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

**Status: RESOLVED.** The debug logging (gated on AIE_BRIDGE_DEBUG=1 / AIE_GATEWAY_DEBUG=1) was removed in 2026-09-04 cycle 6 (commit 8bcb464) now that the S1.1 promotion is stable and no longer needs debugging. The env vars were also removed from `interop/s1/scripts/start_components.sh`. Regression verified by re-running the S1.1 self-hosted workflow (run 33833660538, `promotion: PASS`).

## OQ-005: When should the evidence/s1.1/AIE_S1_1_PROMOTION.json be refreshed?

**Status: RESOLVED.** The file has been refreshed with the PASS report from run 33831755655.

## Next Open Questions (post-promotion)

1. **Should the lab ca_ttl workaround be replaced with gateway-side bundle filtering?** This is the production-correct fix for the architectural gap. Estimated 4-6 hours of work. (D-001, OQ-002 DEFERRED)
2. **Should the AIE_GATEWAY_DEBUG and AIE_BRIDGE_DEBUG env vars be re-added with stricter gating?** Currently they are no longer recognized. If future diagnostics are needed, the logging should be re-added with proper gating (e.g., rate-limited, opt-in).
3. **Should the S1.1 promotion report be archived to long-term storage?** The current archive is at `/home/nora/aie-evidence/33831755655/` on the VDS. The VDS is owner-managed; for durability, the evidence should be moved to a long-term storage layer.
4. **When should S2 (A2A) promotion start?** IN PROGRESS. The S2 TCK direct leg has been run (C-014): 183 passed, 5 failed, 47 skipped, MUST 76.0%. The SPIFFE and AIE legs require deploying the AIE gateway as an A2A proxy, which is a significant effort. The S1 -> S2 comparator path is unblocked (C-013).
5. **Should the in-house CI workflow be promoted from "self-hosted" to "works control plane"?** PR #27 (Jonas, commit a2c70c5) added `works.yml` for per-push verification. The two systems are complementary but not identical — should one be deprecated?
6. **What are the 61 checks in `checks_total=195` that aren't in `check_ids`?** RESOLVED. `checks_total` counts every check execution (including parameterized variants), while `check_ids` is the set of unique check identifiers. The S2 comparator now uses the correct invariant `checks_total >= len(check_ids)` (commit 218a230, 2026-09-04 cycle 8). The 61 extra checks are parameterized variants.
7. **Does the S2 comparator need to accept `leg.status == "PASS_UPSTREAM_GAP"`?** RESOLVED. The S2 comparator now accepts both `"PASS"` and `"PASS_UPSTREAM_GAP"` as valid leg statuses (commit 218a230, 2026-09-04 cycle 8). The demotion is correct when the leg's failures are all upstream-shared. A bare `"FAIL"` is still rejected.
8. **Why do many A2A MUST requirements show `status=NOT TESTED`?** The official a2a-tck doesn't test all MUST requirements against all SUTs. Some requirements are only tested for specific transport bindings. The S2 comparator requires `direct_all_pass` (all direct MUST requirements must be PASS), which will fail if requirements are NOT TESTED. This needs reconciliation — the comparator should accept `NOT TESTED` as equivalent to `PASS` for requirements that don't apply to the SUT.
