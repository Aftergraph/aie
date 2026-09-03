# AIE v0.4-S1 External Interoperability Lab

This lab measures whether AIE remains semantically transparent to an allowed MCP 2026-07-28 interaction while adding workload identity and authority admission.

## Pinned upstreams

- SPIRE: `1.15.2`; Linux amd64 musl SHA-256 `3874d07ffeb6640bafb9fe6a538de06151f155d5ed2f8e8a51f138d2f51b8105`
- MCP Python SDK: `v2.0.0`
- MCP conformance runner: `0.2.0-alpha.11`
- MCP requirements: `2026-07-28`

## Three legs

1. `direct`: official conformance runner -> official MCP everything server.
2. `bridge`: runner -> plain localhost -> SPIFFE client bridge -> mTLS -> SPIFFE server bridge -> MCP server.
3. `aie`: runner -> plain localhost -> SPIFFE client bridge -> mTLS -> AIE Gateway -> mTLS -> SPIFFE server bridge -> MCP server.

The local plain listener exists only so the upstream conformance runner stays unmodified. Identity is established at the first cryptographic bridge boundary, not by trusted headers.

## Promotion rule

S1 is `PASS` only when live SPIRE is used, all three official conformance legs exit successfully, and their official `checks.json` ID sets are identical. Otherwise the machine report remains `FAIL` or `BLOCKED_EXTERNAL_RUNTIME`.

`protocol_passthrough_on_parse_error` is enabled only in the S1 lab. It authorizes such requests under `mcp.transport.forward`, preserves the raw JSON object, and leaves strict fail-closed parsing as the default product behavior.

## External prerequisites

An external Linux host needs SPIRE 1.15.2 binaries, `uv`, Git, Node/npm, and the official MCP Python SDK v2.0.0 source/dependencies. Configure `SPIRE_ROOT`, install the AIE wheel into a Python environment, set `AIE_S1_PYTHON`, and set `AIE_S1_MCP_SERVER_CMD` to the official everything-server command.

Example official server setup from the MCP SDK repository:

```bash
git checkout v2.0.0
uv sync --frozen --all-extras --package mcp-everything-server
uv sync --frozen --all-extras --package mcp --inexact
export AIE_S1_MCP_SERVER_CMD='uv run --frozen mcp-everything-server --port 3000'
```

Then run `start_spire.sh`, `register_workloads.sh`, `start_components.sh`, and `run_official_mcp.sh`, followed by `collect_report.py --live-spire PASS`.

## Known unpromoted edge

The v0.3 forwarder buffers upstream bodies. Long-lived SSE behavior therefore remains an external interoperability risk until the official 2026-07-28 suite is executed through the AIE leg. S1 is deliberately not promoted on local synthetic tests alone.

## S1.1 external CI closure

`.github/workflows/aie-v04-s1-external-interop.yml` is the canonical external runner. It is intentionally read-only and performs four independent gates before promotion:

1. full local regression suite;
2. live SPIRE deployment with workload attestation;
3. forced local X.509 authority prepare -> activate -> revoke with observed Workload API SVID/bundle updates and rejection of the old trust snapshot;
4. official MCP `--requirements 2026-07-28` server conformance over `direct`, `bridge`, and `aie` legs.

The job may promote only when `interop/s1/results/AIE_S1_1_PROMOTION.json` says `PASS`. The JSON report records the SPIRE, MCP SDK, MCP conformance, MCP requirement versions, GitHub run provenance, live trust-rotation gates, and official check-ID parity. A successful unit-test run is not accepted as a substitute for any external gate.
