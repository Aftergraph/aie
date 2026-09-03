#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
export AIE_S1_STATE=${AIE_S1_STATE:-/tmp/aie-v04-s1}
export AIE_S1_MCP_PORT=${AIE_S1_MCP_PORT:-3000}
: "${AIE_S1_PYTHON:?Set AIE_S1_PYTHON to Python with this wheel installed}"
: "${AIE_S1_MCP_SERVER_CMD:?Set to official MCP Python SDK v2.0.0 everything-server command}"
# Self-healing start: a previous run may have leaked servers (pidfiles capture
# runuser/bash wrappers, so plain kill orphans the real processes). Sweep
# strays before binding, otherwise this run dies on EADDRINUSE and silently
# tests against stale code.
"$HERE/scripts/stop_lab.sh" || true
mkdir -p "$AIE_S1_STATE/logs" "$AIE_S1_STATE/gateway-data" "$AIE_S1_STATE/config"
chown aie-s1-gateway "$AIE_S1_STATE/gateway-data"
run_as() {
  local user=$1; shift
  if [[ $(id -un) == "$user" ]]; then "$@"; else runuser -u "$user" -- "$@"; fi
}
# Materialize config with the configured MCP port. AIE_S1_MCP_PORT replaces
# ${AIE_S1_MCP_PORT} in the static configs; this keeps the upstream URL in
# server-bridge.json and the bridge listening on the same port as the
# everything-server without mutating the runtime gateway bridge code.
for cfg in server-bridge.json client-bridge-direct.json client-bridge-aie.json; do
  "$AIE_S1_PYTHON" - "$HERE/config/$cfg" "$AIE_S1_STATE/config/$cfg" "$AIE_S1_MCP_PORT" <<'PY'
import json, sys
src, dst, mcp_port = sys.argv[1], sys.argv[2], int(sys.argv[3])
data = json.loads(open(src, encoding='utf-8').read())
def walk(node):
    if isinstance(node, dict):
        return {k: walk(v) for k, v in node.items()}
    if isinstance(node, list):
        return [walk(v) for v in node]
    if isinstance(node, str):
        return node.replace('${AIE_S1_MCP_PORT}', str(mcp_port))
    return node
open(dst, 'w', encoding='utf-8').write(json.dumps(walk(data), indent=2) + '\n')
PY
done
SERVER_BRIDGE_CONFIG="$AIE_S1_STATE/config/server-bridge.json"
CLIENT_BRIDGE_DIRECT_CONFIG="$AIE_S1_STATE/config/client-bridge-direct.json"
CLIENT_BRIDGE_AIE_CONFIG="$AIE_S1_STATE/config/client-bridge-aie.json"
# Official server is intentionally protocol-only and does not receive a SPIFFE identity.
bash -lc "$AIE_S1_MCP_SERVER_CMD" >"$AIE_S1_STATE/logs/mcp-server.log" 2>&1 & echo $! >"$AIE_S1_STATE/mcp-server.pid"
run_as aie-s1-server "$AIE_S1_PYTHON" -m aie_runtime.gateway.bridge_cli --config "$SERVER_BRIDGE_CONFIG" >"$AIE_S1_STATE/logs/server-bridge.log" 2>&1 & echo $! >"$AIE_S1_STATE/server-bridge.pid"
AIE_GATEWAY_ADMIN_TOKEN=s1-admin run_as aie-s1-gateway env AIE_GATEWAY_ADMIN_TOKEN=s1-admin "$AIE_S1_PYTHON" -m aie_runtime.gateway.cli --config "$HERE/config/gateway.json" --host 127.0.0.1 --port 18444 >"$AIE_S1_STATE/logs/gateway.log" 2>&1 & echo $! >"$AIE_S1_STATE/gateway.pid"
run_as aie-s1-client "$AIE_S1_PYTHON" -m aie_runtime.gateway.bridge_cli --config "$CLIENT_BRIDGE_DIRECT_CONFIG" >"$AIE_S1_STATE/logs/client-bridge-direct.log" 2>&1 & echo $! >"$AIE_S1_STATE/client-bridge-direct.pid"
run_as aie-s1-client "$AIE_S1_PYTHON" -m aie_runtime.gateway.bridge_cli --config "$CLIENT_BRIDGE_AIE_CONFIG" >"$AIE_S1_STATE/logs/client-bridge-aie.log" 2>&1 & echo $! >"$AIE_S1_STATE/client-bridge-aie.pid"
echo "direct=http://127.0.0.1:$AIE_S1_MCP_PORT/mcp bridge=http://127.0.0.1:19080/mcp aie=http://127.0.0.1:19081/mcp"
