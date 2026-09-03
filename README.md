# Agentic Institution Engineering (AIE)

**AIE is an experimental standards and reference-implementation project for portable authority, delegation, lifecycle, budget, revocation, and evidence semantics across agent systems.**

The project explores the layer above coordination topology and runtime control:

> **Graph defines coordination. Control enforces execution. Institution resolves legitimate authority.**

Current maturity: **Draft 0.3 / v0.4 interoperability workstream**. This repository is intentionally conservative about claims: local tests are not treated as external interoperability evidence.

## Repository boundaries

- `spec/` — normative draft artifacts and registries
- `src/` — reference implementation only
- `conformance/` — executable claim vectors
- `interop/` — external interoperability labs
- `evidence/` — release and promotion provenance
- `docs/` — research, standards basis, roadmap, and design notes

## Current promotion target

`v0.4-S1.1` must prove on an external Linux runner:

- live SPIRE Server + Agent
- X.509-SVID and trust-bundle rotation without gateway restart
- official MCP `2026-07-28` conformance on three paths: direct, SPIFFE bridge, and SPIFFE + AIE
- identical official check IDs across all three paths
- revocation/replay enforcement without upstream execution
- privacy-minimized evidence by default

Until those gates run externally, promotion remains `BLOCKED_EXTERNAL_RUNTIME`.

## Local verification

```bash
python -m pip install -e '.[dev,otel]'
pytest -q
```

The canonical repository tree was locally verified at **114/114 tests passing** before publication.

## Status

Research thesis → Draft specification → two runtimes → conformance → durable gateway → real trust/forwarding → **external interoperability closure (current)**.

## License

Apache-2.0.
