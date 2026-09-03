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
# cmdline also carries the marker; everything-server leaks its bash wrapper)
# plus stale spire-server/agent (rm -rf of $STATE destroys their pidfiles, so
# the pidfile loop above can never reach them).
# Never matches the harness shell, or Roro (port 3000, node/docker).
if command -v pkill >/dev/null 2>&1; then
  for marker in 'aie_runtime\.gateway|mcp-everything-server|everything-server' 'bin/spire-server|bin/spire-agent'; do
    # ponytail: pkill -f matches full cmdlines; keep markers narrow so the
    # harness shell and unrelated services can never match.
    pkill -f -TERM "$marker" 2>/dev/null || true
    for _ in $(seq 1 10); do
      pgrep -f "$marker" >/dev/null 2>&1 || break
      sleep 1
    done
    pkill -f -KILL "$marker" 2>/dev/null || true
  done
  sleep 1
fi
