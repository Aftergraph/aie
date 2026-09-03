# Changelog

## v0.4-S2 A2A TCK preparation — 2026-09-03

- pin official `a2aproject/a2a-tck` package `1.0.0` to commit `263b9cfaf16a554bdfb166a7ba5b67716e946349`
- record official A2A Protocol `1.0` and Python SDK `1.0.2` reference provenance without claiming the SUT implementation language
- add deterministic TCK checkout/venv preparation with official-origin verification, exact commit verification, upstream `uv.lock` via `uv sync --frozen --no-dev`, and package-version verification
- add three-leg MUST-level official TCK runner for direct, SPIFFE-proxied, and SPIFFE+AIE endpoints across all TCK transports
- add fail-closed comparator for requirement IDs, official test IDs, per-transport status maps, transport coverage, and Agent Card semantic capability parity
- emit `AIE_S2_A2A_INTEROP.json` with `BLOCKED_BY_S1` until the canonical S1 promotion attestation passes profile/revision, live SPIRE, external gate, leg parity, semantic-delta, and GitHub Actions provenance validation
- add regression coverage for empty MUST sets, missing transports, false capability advertisement, and parity mismatch

## v0.3.0 distribution metadata hardening — 2026-09-03

- raise the setuptools build-backend floor to `>=77.0.3` for PEP 639/SPDX license metadata
- declare `Apache-2.0` via `License-Expression` and include the top-level `LICENSE` in built wheels
- use the repository README as the Markdown package long description
- add author, keywords, and canonical Repository/Issues/Changelog/Documentation URLs to wheel metadata
- add executable regression coverage for the PEP 621/PEP 639 project metadata contract

## v0.4-S1.2 runner provisioning — 2026-09-03

- pin GitHub Actions Runner `v2.337.0` with the official Linux x64 SHA-256
- add checksum-verified bootstrap for a dedicated non-root `aie-runner` service
- require explicit dedicated-host opt-in before granting the S1 lab passwordless sudo boundary
- consume registration/removal tokens only as short-lived environment input and never persist them in repo evidence
- disable runner automatic updates so the externally tested execution runtime remains pinned and auditable
- restrict the root-capable self-hosted proof to `main` and pin checkout/artifact Actions by immutable commit SHA
- roll back the sudoers grant on incomplete bootstrap and revoke it even when deregistration fails
- add controlled service deregistration while preserving runner files for diagnostics/audit
- add regression coverage for pinning, checksum verification, token redaction, labels, system service lifecycle and removal

## v0.4-S1.2 runner portability — 2026-09-03

- add read-only manual self-hosted Linux workflow with dedicated `aie-interop` runner label
- add fail-fast external-host preflight for privilege, network, tools, disk, workspace access and fixed lab ports
- add runner-neutral wrapper that reuses the canonical S1.1 promotion contract and evidence paths
- create a fresh per-run Python venv so persistent runners are not mutated globally and PEP 668 hosts remain compatible
- disable checkout credential persistence and explicitly clean the persistent runner workspace before execution
- make the known-blocked GitHub-hosted external probe manual-only to avoid false-red `main` pushes
- add regression coverage for runner routing, permission boundaries, preflight requirements and promotion-contract reuse

## v0.4-S1.1 interop harness — 2026-09-03

- add read-only GitHub Actions external interoperability workflow
- add pinned SPIRE 1.15.2 download and SHA-256 verification
- add official MCP three-leg conformance harness using frozen 2026-07-28 requirements
- add live local X.509 authority prepare → activate → revoke gate
- add SVID/bundle change observation and old-trust rejection evidence
- add absolute tool-path handling across sudo/runuser boundaries
- isolate writable SQLite and evidence paths for distinct Unix workload identities
- add canonical S1.1 promotion report with GitHub run provenance
- keep external promotion blocked unless live SPIRE, rotation gates and all official MCP legs pass with zero semantic delta

## 0.3.0 — 2026-09-03

- add mutual-TLS inbound identity and strict X.509-SVID leaf validation
- add SPIFFE Workload API `FetchX509SVID` client and TLS-context materialization from SVID snapshots
- add expected-peer SPIFFE identity pinning for outbound HTTPS
- add transparent admitted MCP 2026-07-28 and A2A 1.0 forwarding
- distinguish deterministic upstream trust failures from terminal uncertain dispatch outcomes
- add OpenTelemetry decision spans with W3C trace-context inheritance
- add mutual-TLS gateway federation and durable revocation propagation
- add v0.3 error registry, conformance vectors, real-trust example configuration, and promotion documentation

## 0.2.0

- add HTTP admission gateway, protocol normalization, durable SQLite state, OPA adapter, metadata-only evidence and black-box reference conformance

## 0.1.0

- add two independent AIE Draft 0.3 runtime implementations and cross-runtime authority handoff proof
