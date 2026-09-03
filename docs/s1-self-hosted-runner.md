# S1.2 self-hosted interoperability runner

This runner exists to change the **execution provider**, not the AIE promotion contract. A self-hosted run is valid only when it produces the same canonical `interop/s1/results/AIE_S1_1_PROMOTION.json` used by the hosted workflow and that report says `PASS`.

## Security boundary

The workflow is `workflow_dispatch` only, refuses to execute unless `github.ref == refs/heads/main`, and grants `GITHUB_TOKEN` only `contents: read`. Use a dedicated or ephemeral Linux runner for this public repository. Do not place unrelated long-lived secrets on the host. Checkout explicitly sets `persist-credentials: false` and `clean: true` so the ephemeral job token is not retained in the persistent workspace and stale untracked files are removed before execution. The root-capable workflow pins `actions/checkout` and `actions/upload-artifact` by immutable commit SHA rather than mutable major tags.

The S1 lab needs root privileges to create isolated Unix workload users and operate the SPIRE lab. The bootstrap script refuses to grant that privilege unless `AIE_RUNNER_ENABLE_LAB_SUDO=1` is explicitly set. That opt-in is appropriate only on a dedicated or ephemeral host because trusted manual workflow code can then execute as root.

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
- Python 3 with working `venv` support (`python3-venv` on distributions that package it separately)
- Git, curl, OpenSSL, Node/npm/npx, `runuser`, `useradd`, and `visudo`
- outbound HTTPS to GitHub, npm registry, and PyPI
- at least 3 GiB free under `/tmp`
- checkout readability for isolated lab users
- free loopback ports `18081`, `18443`, `18444`, `19080`, `19081`, and `3000`

The proof wrapper creates a fresh virtual environment under `$AIE_S1_DEPS/venv` for each run. It does not install project dependencies into the host's system Python.

## Pinned GitHub Actions Runner

The bootstrap pins GitHub Actions Runner **v2.337.0** for Linux x64 and verifies the official SHA-256 before extraction:

```text
70920811a4f8ad4328818682bca5c6469c1c942fab52448868071d0063816613
```

The values live in `interop/s1/versions.env` so the tested pin and installer use the same source of truth.

The runner is registered with `--disableupdate`, so GitHub automatic updates cannot silently change the externally tested runtime. Runner upgrades are a manual maintenance action: update the pinned version and official checksum in `versions.env`, rerun the tests, then reprovision the dedicated runner.

## Registration

Generate a fresh repository self-hosted runner registration token in GitHub immediately before installation. GitHub registration tokens expire after **one hour**. Do not paste the token into source files, issues, Actions variables, or shell history.

From a trusted checkout on the dedicated host:

```bash
export AIE_RUNNER_REGISTRATION_TOKEN='<fresh-token>'
export AIE_RUNNER_ENABLE_LAB_SUDO=1
sudo -E bash interop/s1/scripts/bootstrap_actions_runner.sh
```

The script:

1. creates or reuses non-root user `aie-runner`;
2. downloads pinned runner v2.337.0 and verifies its checksum;
3. installs GitHub runner OS dependencies;
4. enables the explicit dedicated-host lab sudo boundary;
5. registers `https://github.com/JonasAbde/aie` with custom label `aie-interop`;
6. disables runner auto-update so the pinned runtime remains reproducible;
7. installs and starts the runner as a system service under `aie-runner`;
8. runs `preflight_external_host.sh` as the runner identity.

The registration token is consumed from `AIE_RUNNER_REGISTRATION_TOKEN`, is never printed by the script, and is unset after registration.

## External proof execution

When the runner shows online in GitHub, manually dispatch **AIE v0.4 S1 Self-hosted External Interop**. Preserve the uploaded evidence artifact and attach the canonical promotion JSON to issue #5. Keep S1.2 blocked unless `promotion == PASS` and all direct/bridge/AIE official MCP check-ID sets are identical with zero semantic delta.

The GitHub-hosted probe remains available as a manual diagnostic, but its known pre-runner failure must not be treated as protocol evidence.

## Deregistration

Generate a fresh GitHub removal token, then run:

```bash
export AIE_RUNNER_REMOVAL_TOKEN='<fresh-removal-token>'
sudo -E bash interop/s1/scripts/remove_actions_runner.sh
```

The removal script stops/uninstalls the service, deregisters the runner, removes the dedicated sudoers grant, unsets `AIE_RUNNER_REMOVAL_TOKEN`, and deliberately preserves `/opt/actions-runner` for audit/recovery. Delete that directory separately only after evidence and diagnostics have been retained.
