# Claim Evidence Audit

Tracked claims and their evidence status. Updated each cycle.

## Claims

| ID | Claim | Evidence Type | Evidence Reference | Status | Last Verified |
|----|-------|---------------|--------------------|--------|---------------|
| C-001 | SEP-2575 SSE relay fix in bridge.py:122 (chunked terminator) | SIMULATED (unit test) | tests/gateway/test_s1_bridge_v04.py::test_bridge_relays_sep2575_post_sse_acknowledged_frame | PASS | 2026-09-04 cycle 2 |
| C-002 | SEP-2575 SSE relay fix in http.py:91 (chunked terminator) | SIMULATED (unit test) | tests/gateway/test_http_gateway.py::test_gateway_get_mcp_streams_text_event_stream_as_chunked_and_terminates | PASS | 2026-09-04 cycle 2 |
| C-003 | old_trust_rejected gate passes with lab ca_ttl=90s + sleep 2 | LIVE (self-hosted runner) | run 33828142733, AIE_S1_1_PROMOTION.json::external_gates.old_trust_rejected | PASS | 2026-09-04 cycle 3 |
| C-004 | Direct leg correctly demoted to PASS_UPSTREAM_GAP | LIVE (self-hosted runner) | run 33828142733, AIE_S1_1_PROMOTION.json::legs.direct.demoted | PASS | 2026-09-04 cycle 3 |
| C-005 | AIE gateway do_POST streams subscriptions/listen via forward_stream | SIMULATED (unit test) | tests/gateway/test_http_gateway.py::test_gateway_post_mcp_subscriptions_listen_streams_response_as_chunked | PASS | 2026-09-04 cycle 3 |
| C-006 | All 3 relay layers stream SSE correctly in live lab | LIVE (self-hosted runner, debug logs) | run 33829373989, lab-logs/{server-bridge,gateway,client-bridge-aie}.log | PASS | 2026-09-04 cycle 4 |
| C-007 | SEP-2575 aie/bridge legs pass conformance | LIVE (self-hosted runner) | run 33831755655, AIE_S1_1_PROMOTION.json::legs.aie.status=PASS_UPSTREAM_GAP, legs.bridge.status=PASS_UPSTREAM_GAP | PASS | 2026-09-04 cycle 5 |
| C-008 | S1.1 promotion: PASS | LIVE (self-hosted runner) | run 33831755655, AIE_S1_1_PROMOTION.json::promotion=PASS | PASS | 2026-09-04 cycle 5 |
| C-009 | read1() fix unblocks SSE relay through http.client | LIVE (self-hosted runner) | run 33831755655, commit dabd11c (Jonas), commit 2430a42 (Jonas), commit f7840fc (Jonas) | PASS | 2026-09-04 cycle 5 |
| C-010 | Debug logging cleanup doesn't break promotion | LIVE (self-hosted runner) | run 33833660538, "Run canonical S1 proof" step success, "Show canonical promotion report" step success | PASS | 2026-09-04 cycle 6 |
| C-011 | works.yml CI control plane covers per-push verification on avc-core pool | LIVE (works control plane on VDS) | PR #27, commit a2c70c5 (Jonas), pytest 171/171 verified | PASS | 2026-09-04 cycle 6 |
| C-012 | S2 official A2A TCK prepared on VDS at commit 263b9cfa | LIVE (VDS, 2026-09-04) | /tmp/aie-v04-s2/a2a-tck, uv 0.12.9, Python 3.12.3, TCK version 1.0.0 | PASS | 2026-09-04 cycle 6 |

## Evidence Types

- **SIMULATED/INTERNAL**: evidence from local unit tests or simulated lab runs
- **LIVE/EXTERNAL**: evidence from the self-hosted runner on the VDS against official MCP SDK v2.0.0 and SPIRE 1.15.2
- **LIVE/WORKS**: evidence from the works control plane (avc-core pool on VDS) running `uv venv` + `pytest` on per-push commits

## Promotion Criteria

The S1.1 promotion is PASS only when:
1. All 4 external rotation gates PASS (C-003, C-004 are PASS)
2. The direct leg is either fully PASS or correctly demoted to PASS_UPSTREAM_GAP (C-004 is PASS)
3. The aie and bridge legs are either fully PASS or correctly demoted to PASS_UPSTREAM_GAP (C-007 is PASS)
4. The promotion report is written to `evidence/s1.1/AIE_S1_1_PROMOTION.json` with `promotion: PASS`
