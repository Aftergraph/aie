#!/usr/bin/env bash
# AIE Local Gate — runnable locally (Linux/macOS/Windows git-bash) without GitHub.
#
# Scope: developer/CI-bypass gate only. Runs the same baseline that
# .github/workflows/ci.yml runs on a hosted runner, and emits a promotion
# report shaped like the canonical S1.1 external report.
#
# This gate NEVER claims external interoperability. All external_* fields
# remain BLOCKED_EXTERNAL_RUNTIME. Local-only evidence lives under
# local_gates; the script's purpose is to confirm "the change does not
# break the repository baseline on this host" without depending on GitHub
# Actions (e.g. when the account is billing-locked or hosted runners are
# unavailable).
#
# Exit codes:
#   0 — every local gate PASS (compileall + pytest)
#   2 — compileall or pytest failed
#   3 — internal error (missing python, repo not found, ...)

set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
OUT_DIR="$HERE/results"
mkdir -p "$OUT_DIR"

PYTHON=${AIE_GATE_PYTHON:-python3}
REPORT="$OUT_DIR/AIE_S1_1_PROMOTION.local.json"
JUNIT_XML="$OUT_DIR/pytest-junit.xml"
# git -C does not translate MSYS paths to Windows-native paths on git-bash;
# use a subshell cd instead so git sees the directory it already understands.
GIT_SHA=$(cd "$ROOT" && git rev-parse HEAD 2>/dev/null || echo unknown)

fail() { printf 'aie-local-gate: %s\n' "$1" >&2; exit 3; }

command -v "$PYTHON" >/dev/null 2>&1 || fail "python3 not found (set AIE_GATE_PYTHON)"

printf '== install (idempotent) ==\n' >&2
"$PYTHON" -c "import aie_reference_runtime" >/dev/null 2>&1 || {
  printf '  package not installed; running: pip install -e .[dev,otel]\n' >&2
  (cd "$ROOT" && "$PYTHON" -m pip install -e '.[dev,otel]') 1>&2 || fail "pip install failed"
}

printf '== compileall ==\n' >&2
"$PYTHON" -m compileall -q "$ROOT/src" "$ROOT/interop/s1" 1>&2 \
  || fail "compileall failed"

# junit-xml is a builtin pytest option; do not depend on pytest-json-report
# because its entry_points are not reliably registered on Windows after an
# editable install, which would silently drop the JSON evidence file.
# Convert MSYS path to Windows native path on Windows because pytest's
# junit-xml option silently prints the destination and writes nothing when
# given an MSYS-style absolute path under git-bash.
JUNIT_XML="$OUT_DIR/pytest-junit.xml"
case "$(uname -s 2>/dev/null)" in
  MINGW*|MSYS*|CYGWIN*)
    JUNIT_XML_ARG=$(cygpath -w "$JUNIT_XML")
    REPORT_ARG=$(cygpath -w "$REPORT")
    JUNIT_XML_PY=$(cygpath -w "$JUNIT_XML")
    ;;
  *)
    JUNIT_XML_ARG="$JUNIT_XML"
    REPORT_ARG="$REPORT"
    JUNIT_XML_PY="$JUNIT_XML"
    ;;
esac
printf '== pytest ==\n' >&2
(cd "$ROOT" && "$PYTHON" -m pytest -q --tb=short \
   --junit-xml="$JUNIT_XML_ARG") 1>&2 \
  || fail "pytest failed"

python_summary=$(AIE_GATE_ROOT="$ROOT" "$PYTHON" - "$GIT_SHA" "$REPORT_ARG" <<PY
import json, sys, platform, xml.etree.ElementTree as ET, os
from datetime import datetime, timezone
JUNIT_XML = r"""$JUNIT_XML_PY"""
GIT_SHA = r"""$GIT_SHA"""
REPORT_PATH = r"""$REPORT_ARG"""
# pytest may emit <testsuites><testsuite .../></testsuites> (newer) or a
# flat <testsuite> root (older). Walk the tree and aggregate.
def _walk(elem):
    yield elem
    for child in elem:
        yield from _walk(child)
suites = [e for e in _walk(ET.parse(JUNIT_XML).getroot())
          if e.tag == 'testsuite']
def _sum(attr, default=0):
    return sum(int(s.attrib.get(attr, default)) for s in suites)
total = _sum('tests')
failed = _sum('failures')
errored = _sum('errors')
skipped = _sum('skipped')
passed = total - failed - errored - skipped
local_pass = (failed == 0 and errored == 0)
report = {
    'profile': 'AIE v0.4-S1.1 local-only gate',
    'promotion': 'BLOCKED_EXTERNAL_RUNTIME' if local_pass else 'FAIL',
    'live_spire': 'BLOCKED_EXTERNAL_RUNTIME',
    'external_gates': {
        'new_trust_works': 'BLOCKED_EXTERNAL_RUNTIME',
        'old_trust_rejected': 'BLOCKED_EXTERNAL_RUNTIME',
        'svid_rotation_live': 'BLOCKED_EXTERNAL_RUNTIME',
        'trust_bundle_rotation_live': 'BLOCKED_EXTERNAL_RUNTIME',
    },
    'legs': {
        'direct': {'name': 'direct', 'status': 'BLOCKED_EXTERNAL_RUNTIME', 'check_ids': [], 'checks_total': 0},
        'bridge': {'name': 'bridge', 'status': 'BLOCKED_EXTERNAL_RUNTIME', 'check_ids': [], 'checks_total': 0},
        'aie':    {'name': 'aie',    'status': 'BLOCKED_EXTERNAL_RUNTIME', 'check_ids': [], 'checks_total': 0},
    },
    'semantic_delta': [],
    'local_gates': {
        'compileall': 'PASS' if local_pass else 'FAIL',
        'pytest': 'PASS' if local_pass else 'FAIL',
        'pytest_total': total,
        'pytest_passed': passed,
        'pytest_failed': failed,
        'pytest_error': errored,
        'pytest_skipped': skipped,
    },
    'mcp_revision': '2026-07-28',
    'versions': {
        'spire': '1.15.2',
        'mcp_python_sdk': 'v2.0.0',
        'mcp_conformance': '0.2.0-alpha.11',
        'mcp_requirements': '2026-07-28',
    },
    'provenance': {
        'git_sha': GIT_SHA,
        'provider': 'local',
        'run_id': '',
        'run_attempt': '',
        'workflow_ref': '',
        'runner': platform.platform(),
        'python': platform.python_version(),
        'timestamp': datetime.now(timezone.utc).isoformat(timespec='seconds'),
    },
}
open(REPORT_PATH, 'w', encoding='utf-8').write(
    json.dumps(report, indent=2, sort_keys=True) + '\n'
)
print(json.dumps({
    'report': REPORT_PATH,
    'promotion': report['promotion'],
    'pytest': {'total': total, 'passed': passed, 'failed': failed, 'errored': errored, 'skipped': skipped},
}, indent=2))
sys.exit(0 if local_pass else 2)
PY
)
printf '%s\n' "$python_summary"
