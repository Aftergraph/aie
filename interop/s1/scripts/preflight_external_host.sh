#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
RESULT_ROOT=${AIE_S1_RESULTS:-$HERE/results}
OUT="$RESULT_ROOT/preflight.json"
FAILURES=$(mktemp)
trap 'rm -f "$FAILURES"' EXIT
mkdir -p "$RESULT_ROOT"
: > "$FAILURES"

# AIE_S1_MCP_PORT overrides the official MCP everything-server port (default 3000).
# The AIE protocol itself is port-agnostic; 3000 is only the upstream MCP reference
# server's default. All other ports are AIE-internal and fixed.
AIE_S1_MCP_PORT=${AIE_S1_MCP_PORT:-3000}
# AIE_S1_FIXED_PORTS preserves the historical preflight port set: 18081 was
# reserved for an internal preflight probe and is part of the published
# contract (see tests/interop/test_self_hosted_runner_v04.py). It is included
# here so callers that need to free it can override the whole list at once
# with a single env var instead of editing the script.
AIE_S1_FIXED_PORTS=${AIE_S1_FIXED_PORTS:-"18081 18443 18444 19080 19081"}
# shellcheck disable=SC2206  # intentional word-splitting of the override above
AIE_S1_FIXED_PORTS_ARR=($AIE_S1_FIXED_PORTS)
AIE_S1_ALL_PORTS=("$AIE_S1_MCP_PORT" "${AIE_S1_FIXED_PORTS_ARR[@]}")

fail() { printf '%s\n' "$1" >> "$FAILURES"; }
check_cmd() { command -v "$1" >/dev/null 2>&1 || fail "missing_command:$1"; }

[[ $(uname -s) == Linux ]] || fail "platform:not-linux"
case "$(uname -m)" in x86_64|amd64) ;; *) fail "arch:not-x86_64" ;; esac

for cmd in bash curl git sha256sum tar python3 openssl node npm npx runuser useradd; do
  check_cmd "$cmd"
done

# Persistent runners must support an isolated Python environment; do not mutate system Python.
VENV_PROBE=$(mktemp -d)
if python3 -m venv "$VENV_PROBE/venv" >/dev/null 2>&1; then :; else
  fail "python:venv-unavailable"
fi
rm -rf "$VENV_PROBE"

# Lab scripts create isolated Unix workload users and manipulate SPIRE state.
if ! sudo -n true 2>/dev/null; then
  fail "privilege:passwordless-sudo-required"
fi

# The canonical external proof downloads pinned SPIRE/MCP assets and npm packages.
curl --fail --silent --show-error --head --max-time 10 https://github.com >/dev/null 2>&1 || fail "network:github.com"
curl --fail --silent --show-error --head --max-time 10 https://registry.npmjs.org/ >/dev/null 2>&1 || fail "network:registry.npmjs.org"
curl --fail --silent --show-error --head --max-time 10 https://pypi.org/simple/ >/dev/null 2>&1 || fail "network:pypi.org"

# Require at least 3 GiB free under /tmp for SPIRE, SDK checkouts and result artifacts.
FREE_KB=$(df -Pk /tmp | awk 'NR==2 {print $4}')
[[ ${FREE_KB:-0} -ge 3145728 ]] || fail "disk:/tmp-less-than-3GiB"

# Lab users must be able to traverse/read the checkout when runuser switches UID.
if sudo -n -u nobody test -r "$ROOT/interop/s1/config/gateway.json" 2>/dev/null; then :; else
  fail "workspace:not-readable-by-lab-users"
fi

# Every fixed lab port must be free before the proof begins.
if command -v python3 >/dev/null 2>&1; then
  python3 - "$AIE_S1_ALL_PORTS" <<'PY' || fail "ports:one-or-more-in-use"
import socket, sys
ports = tuple(int(p) for p in sys.argv[1:])
sockets = []
try:
    for port in ports:
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('127.0.0.1', port))
        sockets.append(s)
finally:
    for s in sockets:
        s.close()
PY
fi

python3 - "$FAILURES" "$OUT" <<'PY'
import json, platform, shutil, sys
from pathlib import Path
failures = [line.strip() for line in Path(sys.argv[1]).read_text().splitlines() if line.strip()]
commands = ['bash','curl','git','sha256sum','tar','python3','openssl','node','npm','npx','runuser','useradd']
report = {
    'profile': 'AIE v0.4-S1 external-host preflight',
    'status': 'PASS' if not failures else 'FAIL',
    'platform': platform.platform(),
    'machine': platform.machine(),
    'commands': {name: shutil.which(name) for name in commands},
    'ports': list(ports),
    'failures': failures,
}
Path(sys.argv[2]).write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
print(json.dumps({'preflight': report['status'], 'output': sys.argv[2]}))
raise SystemExit(0 if not failures else 2)
PY
