#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
cd "$ROOT"

export AIE_S1_RESULTS=${AIE_S1_RESULTS:-$HERE/results}
export AIE_S1_STATE=${AIE_S1_STATE:-/tmp/aie-v04-s1}
export AIE_S1_DEPS=${AIE_S1_DEPS:-/tmp/aie-v04-s1-deps}
mkdir -p "$AIE_S1_RESULTS"

"$HERE/scripts/preflight_external_host.sh"

PYTHON=${AIE_S1_BOOTSTRAP_PYTHON:-python3}
# Canonical install shape: python -m pip install -e '.[dev,otel]'
"$PYTHON" -m pip install --upgrade pip
"$PYTHON" -m pip install -e '.[dev,otel]'
"$PYTHON" -m pip install 'uv==0.8.17'

export AIE_S1_PYTHON=$(command -v "$PYTHON")
export AIE_S1_UV=$(command -v uv)
export AIE_S1_NPX=$(command -v npx)

sudo --preserve-env=AIE_S1_PYTHON,AIE_S1_UV,AIE_S1_NPX,AIE_S1_STATE,AIE_S1_RESULTS,AIE_S1_DEPS,GITHUB_ACTIONS,GITHUB_RUN_ID,GITHUB_RUN_ATTEMPT,GITHUB_SHA,GITHUB_WORKFLOW_REF \
  bash "$HERE/scripts/ci_external_s1.sh"

REPORT="$AIE_S1_RESULTS/AIE_S1_1_PROMOTION.json"
"$AIE_S1_PYTHON" - "$REPORT" <<'PY'
import json, sys
report = json.load(open(sys.argv[1], encoding='utf-8'))
print(json.dumps({'promotion': report.get('promotion'), 'report': sys.argv[1]}))
if report.get('promotion') != 'PASS':
    raise SystemExit('external host did not satisfy the canonical S1.1 promotion contract')
PY
