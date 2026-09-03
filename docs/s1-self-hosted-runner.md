# S1.2 self-hosted interoperability runner

This runner exists to change the **execution provider**, not the AIE promotion contract. A self-hosted run is valid only when it produces the same canonical `interop/s1/results/AIE_S1_1_PROMOTION.json` used by the hosted workflow and that report says `PASS`.

## Security boundary

The workflow is `workflow_dispatch` only and grants `GITHUB_TOKEN` only `contents: read`. Use a dedicated or ephemeral Linux runner for this public repository. Do not place unrelated long-lived secrets on the host.

Required runner labels:

```text
self-hosted
linux
x64
aie-interop
```

GitHub routes the job only to a runner matching every label.

## Host prerequisites

`interop/s1/scripts/preflight_external_host.sh` checks the executable environment before any promotion work begins. The host must provide:

- Linux x86-64
- passwordless `sudo` for the isolated SPIRE/workload-user lab
- Python 3, Git, curl, OpenSSL, Node/npm/npx, `runuser`, and `useradd`
- outbound HTTPS to GitHub, npm registry, and PyPI
- at least 3 GiB free under `/tmp`
- checkout readability for isolated lab users
- free loopback ports `18081`, `18443`, `18444`, `19080`, `19081`, and `3000`

## Execution

1. Register a dedicated GitHub Actions self-hosted runner for `JonasAbde/aie` and add custom label `aie-interop`; retain the default `self-hosted`, `linux`, and `x64` labels.
2. On the host, run `bash interop/s1/scripts/preflight_external_host.sh` from a checkout if you want to validate prerequisites before attaching it to Actions.
3. In GitHub Actions, manually dispatch **AIE v0.4 S1 Self-hosted External Interop**.
4. Preserve the uploaded evidence artifact and attach the canonical promotion JSON to issue #5.
5. Keep S1.2 blocked unless `promotion == PASS` and all direct/bridge/AIE official MCP check-ID sets are identical with zero semantic delta.

The GitHub-hosted probe remains available as a manual diagnostic, but its known pre-runner failure must not be treated as protocol evidence.
