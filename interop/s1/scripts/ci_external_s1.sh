#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
source "$HERE/versions.env"
export AIE_S1_STATE=${AIE_S1_STATE:-/tmp/aie-v04-s1}
export AIE_S1_RESULTS=${AIE_S1_RESULTS:-$HERE/results}
export AIE_S1_DEPS=${AIE_S1_DEPS:-/tmp/aie-v04-s1-deps}
PROMOTION="$AIE_S1_RESULTS/AIE_S1_1_PROMOTION.json"
mkdir -p "$AIE_S1_RESULTS" "$AIE_S1_DEPS"
cleanup() {
  mkdir -p "$AIE_S1_RESULTS/lab-logs"
  if [[ -d "$AIE_S1_STATE/logs" ]]; then cp -a "$AIE_S1_STATE/logs/." "$AIE_S1_RESULTS/lab-logs/" 2>/dev/null || true; fi
  # Archive the gateway replay/audit store before the next run wipes state;
  # per-run JSON-RPC id reuse makes cross-run rows indistinguishable.
  if [[ -f "$AIE_S1_STATE/gateway-data/gateway.sqlite3" ]]; then cp -a "$AIE_S1_STATE/gateway-data/gateway.sqlite3" "$AIE_S1_RESULTS/lab-logs/" 2>/dev/null || true; fi
  # Proof runs as root via sudo(8) but the checkout is owned by the runner
  # user; root-owned result files, __pycache__ dirs, and egg-info break the
  # next run's `git clean -ffdx`.
  if [[ -n "${SUDO_USER:-}" ]]; then
    chown -R "$SUDO_USER" "$AIE_S1_RESULTS" 2>/dev/null || true
    find "$ROOT/src" -name __pycache__ -exec chown -R "$SUDO_USER" {} + 2>/dev/null || true
    chown -R "$SUDO_USER" "$ROOT/src/"*.egg-info 2>/dev/null || true
  fi
  "$HERE/scripts/stop_lab.sh" || true
}
trap cleanup EXIT

export SPIRE_ROOT=${SPIRE_ROOT:-$("$HERE/scripts/install_spire.sh" | tail -n1)}
export AIE_S1_PYTHON=${AIE_S1_PYTHON:-$(command -v python)}
UV=${AIE_S1_UV:-$(command -v uv)}
export AIE_S1_NPX=${AIE_S1_NPX:-$(command -v npx)}

# The official Python SDK v2 everything-server is the upstream implementation
# under test. A fresh exact tag checkout prevents local fixtures from leaking in.
MCP_SDK="$AIE_S1_DEPS/python-sdk"
rm -rf "$MCP_SDK"
git clone --depth 1 --branch "$MCP_PYTHON_SDK_TAG" https://github.com/modelcontextprotocol/python-sdk.git "$MCP_SDK"
(
  cd "$MCP_SDK"
  "$UV" sync --frozen --all-extras --package mcp-everything-server
  "$UV" sync --frozen --all-extras --package mcp --inexact
)
# AIE_S1_MCP_PORT overrides the official MCP everything-server listener port
# (default 3000). Useful when 3000 is occupied by another long-lived service
# on the dedicated host; the AIE protocol itself is port-agnostic.
export AIE_S1_MCP_PORT=${AIE_S1_MCP_PORT:-3000}
export AIE_S1_MCP_SERVER_CMD="cd '$MCP_SDK' && '$UV' run --frozen mcp-everything-server --port '$AIE_S1_MCP_PORT'"

rm -rf "$AIE_S1_STATE" "$AIE_S1_RESULTS/direct" "$AIE_S1_RESULTS/bridge" "$AIE_S1_RESULTS/aie" "$AIE_S1_RESULTS/rotation"
mkdir -p "$AIE_S1_STATE" "$AIE_S1_RESULTS"

# Self-healing start: previous runs leak servers (pidfiles capture runuser/bash
# wrappers and rm -rf above destroys the only handles, so plain kill orphans
# the real processes). Sweep strays NOW, before anything of this run starts:
# otherwise this run's components crash on EADDRINUSE while traffic is silently
# served by stale code. Placed here and not in start_components because that
# runs after start_spire, whose fresh processes must survive.
"$HERE/scripts/stop_lab.sh" || true

"$HERE/scripts/start_spire.sh"
"$HERE/scripts/register_workloads.sh"

# Wait for the agent to sync registrations before components fetch SVIDs.
# Entries are created server-side; the agent caches them asynchronously, and
# bridge/gateway startup fails closed ("no identity issued") if it races ahead.
AGENT_API_SOCK="$AIE_S1_STATE/spire-agent/public/api.sock"
ready=0
for _ in $(seq 1 150); do
  ready=0
  for user in aie-s1-client aie-s1-gateway aie-s1-server; do
    if runuser -u "$user" -- "$SPIRE_ROOT/bin/spire-agent" api fetch x509 -socketPath "$AGENT_API_SOCK" -timeout 2s >/dev/null 2>&1; then
      ready=$((ready+1))
    fi
  done
  [[ $ready -eq 3 ]] && break
  sleep .2
done
[[ $ready -eq 3 ]] || { echo "SPIRE workload SVIDs not issued for all lab users" >&2; exit 1; }
"$HERE/scripts/start_components.sh"

# Give listeners a bounded readiness window before mutating trust state.
"$AIE_S1_PYTHON" - "$AIE_S1_MCP_PORT" <<'PY'
import socket, sys, time
mcp_port = int(sys.argv[1])
ports = (mcp_port, 18443, 18444, 19080, 19081)
deadline=time.monotonic()+20
for port in ports:
    while True:
        try:
            with socket.create_connection(('127.0.0.1',port), timeout=.5): break
        except OSError:
            if time.monotonic()>deadline: raise SystemExit(f'port {port} not ready')
            time.sleep(.1)
PY

"$HERE/scripts/run_live_rotation_gate.sh"
"$HERE/scripts/run_official_mcp.sh"
"$AIE_S1_PYTHON" "$HERE/collect_report.py" \
  --results "$AIE_S1_RESULTS" \
  --rotation-evidence "$AIE_S1_RESULTS/rotation/rotation-gates.json" \
  --live-spire PASS \
  --output "$PROMOTION"

# The canonical JSON report, not shell log vibes, decides promotion.
"$AIE_S1_PYTHON" - "$PROMOTION" <<'PY'
import json, sys
report=json.load(open(sys.argv[1], encoding='utf-8'))
if report.get("promotion") != "PASS":
    print(json.dumps(report, indent=2, sort_keys=True))
    raise SystemExit("S1.1 promotion is not PASS")
print(json.dumps({"promotion": report["promotion"], "report": sys.argv[1]}))
PY
