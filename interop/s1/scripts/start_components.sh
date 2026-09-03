#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
export AIE_S1_STATE=${AIE_S1_STATE:-/tmp/aie-v04-s1}
: "${AIE_S1_PYTHON:?Set AIE_S1_PYTHON to Python with this wheel installed}"
: "${AIE_S1_MCP_SERVER_CMD:?Set to official MCP Python SDK v2.0.0 everything-server command}"
mkdir -p "$AIE_S1_STATE/logs" "$AIE_S1_STATE/gateway-data"
chown aie-s1-gateway "$AIE_S1_STATE/gateway-data"
run_as() {
  local user=$1; shift
  if [[ $(id -un) == "$user" ]]; then "$@"; else runuser -u "$user" -- "$@"; fi
}
# Official server is intentionally protocol-only and does not receive a SPIFFE identity.
bash -lc "$AIE_S1_MCP_SERVER_CMD" >"$AIE_S1_STATE/logs/mcp-server.log" 2>&1 & echo $! >"$AIE_S1_STATE/mcp-server.pid"
run_as aie-s1-server "$AIE_S1_PYTHON" -m aie_runtime.gateway.bridge_cli --config "$HERE/config/server-bridge.json" >"$AIE_S1_STATE/logs/server-bridge.log" 2>&1 & echo $! >"$AIE_S1_STATE/server-bridge.pid"
AIE_GATEWAY_ADMIN_TOKEN=s1-admin run_as aie-s1-gateway env AIE_GATEWAY_ADMIN_TOKEN=s1-admin "$AIE_S1_PYTHON" -m aie_runtime.gateway.cli --config "$HERE/config/gateway.json" --host 127.0.0.1 --port 18444 >"$AIE_S1_STATE/logs/gateway.log" 2>&1 & echo $! >"$AIE_S1_STATE/gateway.pid"
run_as aie-s1-client "$AIE_S1_PYTHON" -m aie_runtime.gateway.bridge_cli --config "$HERE/config/client-bridge-direct.json" >"$AIE_S1_STATE/logs/client-bridge-direct.log" 2>&1 & echo $! >"$AIE_S1_STATE/client-bridge-direct.pid"
run_as aie-s1-client "$AIE_S1_PYTHON" -m aie_runtime.gateway.bridge_cli --config "$HERE/config/client-bridge-aie.json" >"$AIE_S1_STATE/logs/client-bridge-aie.log" 2>&1 & echo $! >"$AIE_S1_STATE/client-bridge-aie.pid"
echo "direct=http://127.0.0.1:3000/mcp bridge=http://127.0.0.1:19080/mcp aie=http://127.0.0.1:19081/mcp"
