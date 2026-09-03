#!/usr/bin/env bash
set -euo pipefail
STATE=${AIE_S1_STATE:-/tmp/aie-v04-s1}
# ponytail: pidfiles capture runuser/bash wrappers, not the real servers, so
# killing by pid orphans the children and every later run dies on bind. The
# marker sweep below is the backstop: it kills whatever actually runs the lab.
for name in client-bridge-aie client-bridge-direct gateway server-bridge mcp-server spire-agent spire-server; do
  f="$STATE/$name.pid"
  if [[ -f "$f" ]]; then kill "$(cat "$f")" 2>/dev/null || true; rm -f "$f"; fi
done
# Marker sweep: lab python processes (gateway/bridges run under runuser, whose
# cmdline also carries the marker; everything-server leaks its bash wrapper).
# Never matches spire, the harness shell, or Roro (port 3000, node/docker).
if command -v pkill >/dev/null 2>&1; then
  pkill -f -TERM 'aie_runtime\.gateway|mcp-everything-server|everything-server' 2>/dev/null || true
  for _ in $(seq 1 10); do
    pgrep -f 'aie_runtime\.gateway|mcp-everything-server|everything-server' >/dev/null 2>&1 || break
    sleep 1
  done
  pkill -f -KILL 'aie_runtime\.gateway|mcp-everything-server|everything-server' 2>/dev/null || true
  sleep 1
fi
