#!/usr/bin/env bash
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
source "$HERE/versions.env"

: "${AIE_S2_TCK_DIR:?Set AIE_S2_TCK_DIR to the pinned official a2a-tck checkout}"
: "${AIE_S2_DIRECT_URL:?Set direct A2A SUT URL}"
: "${AIE_S2_SPIFFE_URL:?Set SPIFFE-proxied A2A SUT URL}"
: "${AIE_S2_AIE_URL:?Set SPIFFE+AIE A2A SUT URL}"
: "${AIE_S2_S1_PROMOTION:?Set path to canonical S1 promotion JSON}"

AIE_S2_RESULTS=${AIE_S2_RESULTS:-$HERE/results}
AIE_S2_PYTHON=${AIE_S2_PYTHON:-$AIE_S2_TCK_DIR/.venv/bin/python}
mkdir -p "$AIE_S2_RESULTS"

[[ -x "$AIE_S2_PYTHON" ]] || { echo "AIE S2: TCK python not executable: $AIE_S2_PYTHON" >&2; exit 2; }
HEAD=$(cd "$AIE_S2_TCK_DIR" && git rev-parse HEAD)
[[ "$HEAD" == "$A2A_TCK_COMMIT" ]] || {
  echo "AIE S2: a2a-tck HEAD $HEAD != pinned $A2A_TCK_COMMIT" >&2
  exit 2
}

run_leg() {
  local leg=$1
  local url=$2
  local out="$AIE_S2_RESULTS/$leg"
  mkdir -p "$out"
  rm -rf "$AIE_S2_TCK_DIR/reports"
  set +e
  (
    cd "$AIE_S2_TCK_DIR"
    "$AIE_S2_PYTHON" run_tck.py --sut-host "$url" --level must
  ) >"$out/stdout.log" 2>"$out/stderr.log"
  local rc=$?
  set -e
  printf '%s\n' "$rc" > "$out/exit_code.txt"
  if [[ -f "$AIE_S2_TCK_DIR/reports/compatibility.json" ]]; then
    cp "$AIE_S2_TCK_DIR/reports/compatibility.json" "$out/compatibility.json"
  else
    echo "AIE S2: official TCK did not emit compatibility.json for $leg" >&2
    return 3
  fi
}

run_leg direct "$AIE_S2_DIRECT_URL"
run_leg spiffe "$AIE_S2_SPIFFE_URL"
run_leg aie "$AIE_S2_AIE_URL"

python3 "$HERE/collect_report.py" \
  --direct "$AIE_S2_RESULTS/direct/compatibility.json" \
  --spiffe "$AIE_S2_RESULTS/spiffe/compatibility.json" \
  --aie "$AIE_S2_RESULTS/aie/compatibility.json" \
  --direct-exit-code "$AIE_S2_RESULTS/direct/exit_code.txt" \
  --spiffe-exit-code "$AIE_S2_RESULTS/spiffe/exit_code.txt" \
  --aie-exit-code "$AIE_S2_RESULTS/aie/exit_code.txt" \
  --s1-promotion "$AIE_S2_S1_PROMOTION" \
  --output "$AIE_S2_RESULTS/AIE_S2_A2A_INTEROP.json"
