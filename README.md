# Agentic Institution Engineering (AIE)

**AIE is an experimental standards and reference-implementation project for portable authority, delegation, lifecycle, budget, revocation, and evidence semantics across agent systems.**

The project explores the layer above coordination topology and runtime control:

> **Graph defines coordination. Control enforces execution. Institution resolves legitimate authority.**

Current maturity: **Draft 0.3 / v0.4-S1.1 external interoperability PASS** (run 33831755655, 2026-09-04). This repository is intentionally conservative about claims: local tests are not treated as external interoperability evidence.

## Repository boundaries

- `spec/` — normative draft artifacts and registries
- `src/` — reference implementation only
- `conformance/` — executable claim vectors
- `interop/` — external interoperability labs
- `evidence/` — release and promotion provenance
- `docs/` — research, standards basis, roadmap, and design notes

## Current promotion target

`v0.4-S1.1` has achieved external PASS (run 33831755655, 2026-09-04) with:

- live SPIRE Server + Agent
- X.509-SVID and trust-bundle rotation without gateway restart
- official MCP `2026-07-28` conformance on three paths: direct, SPIFFE bridge, and SPIFFE + AIE
- identical official check IDs across all three paths (195 checks each)
- revocation/replay enforcement without upstream execution
- privacy-minimized evidence by default
- all 4 external rotation gates PASS (svid_rotation_live, trust_bundle_rotation_live, new_trust_works, old_trust_rejected)

Evidence: `evidence/s1.1/AIE_S1_1_PROMOTION.json`, archived at `/home/nora/aie-evidence/33831755655/`.

The next promotion target is `v0.4-S1.2` (S2 — A2A official TCK over supported transports and task lifecycle semantics) and then `v0.4-S2`.

The repository carries two manual execution providers for the same proof contract: the original GitHub-hosted diagnostic and a dedicated self-hosted Linux workflow using labels `[self-hosted, linux, x64, aie-interop]`. See `docs/s1-self-hosted-runner.md`.

## Local verification

```bash
python -m pip install -e '.[dev,otel]'
pytest -q
```

The **173-test repository baseline** includes the S2 A2A-preparation targeted suite (16/16 tests passing). S2 remains preparation-only and does not satisfy the external interoperability gate.

## Status

Research thesis → Draft specification → two runtimes → conformance → durable gateway → real trust/forwarding → external interoperability closure (S1.1 PASS, 2026-09-04) → **A2A interop (next)**.

See `evidence/s1.1/registry/walkthrough.md` for the end-to-end S1.1 promotion walkthrough.

## License

Apache-2.0.
