# Agentic Institution Engineering (AIE)

**AIE is an experimental standards and reference-implementation project for portable authority, delegation, lifecycle, budget, revocation, and evidence semantics across agent systems.**

The project explores the layer above coordination topology and runtime control:

> **Graph defines coordination. Control enforces execution. Institution resolves legitimate authority.**

Current maturity: **Draft 0.3 / v0.4 interoperability workstream**. This repository is intentionally conservative about claims: local tests are not treated as external interoperability evidence.

The repository contains the AIE Draft 0.3 specification artifacts, two reference runtimes, an admission gateway for MCP/A2A traffic, SPIFFE/X.509-SVID trust integration, conformance suites, and the v0.4-S1.1 external MCP interoperability lab.

## Current promotion target

`v0.4-S1.1` must prove on an external Linux runner:

- live SPIRE Server + Agent
- X.509-SVID and trust-bundle rotation without gateway restart
- official MCP `2026-07-28` conformance on three paths: direct, SPIFFE bridge, and SPIFFE + AIE
- identical official check IDs across all three paths
- revocation/replay enforcement without upstream execution
- privacy-minimized evidence by default

Until those gates run externally, promotion remains `BLOCKED_EXTERNAL_RUNTIME`.

## Repository structure

The full source tree, specs, tests, workflows, design notes, and reproducible interop lab are imported in the next bootstrap commit.

## Status

Research thesis → Draft specification → two runtimes → conformance → durable gateway → real trust/forwarding → **external interoperability closure (current)**.

## License

License and standards-governance policy are established in the repository bootstrap workstream before any 1.0 claim.
