# AIE Local Gate

A developer-only gate that runs the same baseline that
[`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) runs on a hosted
runner, but without depending on GitHub Actions at all. It is meant for the
case where hosted runners are unavailable (for example when the account is
billing-locked) and the maintainer needs to verify locally that a change does
not break the repository baseline.

## What it is

- Runs `pip install -e '.[dev,otel]'` (idempotent — skips if already installed)
- Runs `python -m compileall -q src interop/s1`
- Runs `pytest -q --json-report`
- Emits `results/AIE_S1_1_PROMOTION.local.json` shaped exactly like the
  canonical S1.1 external report, with:
  - `local_gates` populated from real pytest results
  - `external_gates` and `legs` set to `BLOCKED_EXTERNAL_RUNTIME`
  - `promotion` = `BLOCKED_EXTERNAL_RUNTIME` when local gates pass, `FAIL`
    when they do not (never `PASS`)

## What it is NOT

- **Not external interoperability evidence.** It runs only the local baseline.
  The AIE promotion contract requires a self-hosted Linux runner with live
  SPIRE and the official MCP conformance suite; see
  [`docs/s1-self-hosted-runner.md`](../../docs/s1-self-hosted-runner.md).
- **Not a substitute for CI on pull requests.** When GitHub-hosted runners
  work normally, this script is redundant. Use it when they do not.
- **Not a green light to merge S1.1 / S1.2 promotion.** The S1 promotion
  remains `BLOCKED_EXTERNAL_RUNTIME` until an actual external runner produces
  the canonical `AIE_S1_1_PROMOTION.json` with `promotion == PASS`.

## Usage

```bash
# from anywhere — script locates the repo root itself
bash tools/aie_local_gate/run.sh

# or with a specific python
AIE_GATE_PYTHON=python3.12 bash tools/aie_local_gate/run.sh
```

Exit codes:

| Code | Meaning |
|------|---------|
| 0    | Local gates all PASS (compileall + pytest) |
| 2    | Local gate failed (compileall or pytest reported errors) |
| 3    | Internal error (python missing, repo not found, ...) |

The script writes its result to
`tools/aie_local_gate/results/AIE_S1_1_PROMOTION.local.json` and prints a
short JSON summary to stdout.

## Why a separate file name

The canonical external artifact is `interop/s1/results/AIE_S1_1_PROMOTION.json`
and must be produced by the S1 lab. This gate produces
`AIE_S1_1_PROMOTION.local.json` in a `tools/`-scoped path, so it can never be
mistaken for external evidence. The promotion field is also forced to
`BLOCKED_EXTERNAL_RUNTIME` on success, mirroring the convention in
[`interop/s1/S1_1_EXTERNAL_CI_STATUS.md`](../../interop/s1/S1_1_EXTERNAL_CI_STATUS.md).
