#!/usr/bin/env bash
set -uo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
source "$HERE/versions.env"
RESULT_ROOT=${AIE_S1_RESULTS:-$HERE/results}
mkdir -p "$RESULT_ROOT"
NPX=${AIE_S1_NPX:-$(command -v npx)}
run_leg() {
  local name=$1 url=$2 dir="$RESULT_ROOT/$name"
  rm -rf "$dir"; mkdir -p "$dir"; cd "$dir"
  printf '%q ' "$NPX" --yes "@modelcontextprotocol/conformance@$MCP_CONFORMANCE_VERSION" server --url "$url" --requirements "$MCP_PROTOCOL_REVISION" > command.txt
  printf '\n' >> command.txt
  "$NPX" --yes "@modelcontextprotocol/conformance@$MCP_CONFORMANCE_VERSION" server --url "$url" --requirements "$MCP_PROTOCOL_REVISION" >stdout.log 2>stderr.log
  local ec=$?
  printf '%s\n' "$ec" > exit_code.txt
  return 0
}
run_leg direct "http://127.0.0.1:3000/mcp"
run_leg bridge "http://127.0.0.1:19080/mcp"
run_leg aie "http://127.0.0.1:19081/mcp"
