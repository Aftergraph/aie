#!/usr/bin/env bash
set -euo pipefail
STATE=${AIE_S1_STATE:-/tmp/aie-v04-s1}
for name in client-bridge-aie client-bridge-direct gateway server-bridge mcp-server spire-agent spire-server; do
  f="$STATE/$name.pid"
  if [[ -f "$f" ]]; then kill "$(cat "$f")" 2>/dev/null || true; rm -f "$f"; fi
done
