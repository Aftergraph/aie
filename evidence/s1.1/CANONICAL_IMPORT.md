# Canonical repository import

The AIE v0.4-S1.1 canonical source tree was promoted to `main` from commit `e8d7a926e9e766c16d577ad06d2b7747d9a9c42f` after byte-level Git blob fidelity checks against the locally verified baseline.

Protected baseline paths: `src/`, `spec/`, `tests/`, and `interop/s1/`.

Fresh local verification immediately before promotion:

```text
114 passed in 12.28s
compileall=PASS
shell_syntax=PASS
```

This is repository-integrity evidence only. External interoperability remains `BLOCKED_EXTERNAL_RUNTIME` until issue #5 produces live SPIRE + official MCP evidence.
