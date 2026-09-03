# Changelog

## v0.4-S1.1 interop harness — 2026-09-03

- add read-only GitHub Actions external interoperability workflow
- add pinned SPIRE 1.15.2 download and SHA-256 verification
- add official MCP three-leg conformance harness using frozen 2026-07-28 requirements
- add live local X.509 authority prepare/activate/revoke rotation gate
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
