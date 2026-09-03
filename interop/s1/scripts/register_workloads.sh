#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
source "$HERE/versions.env"
: "${SPIRE_ROOT:?Set SPIRE_ROOT}"
export AIE_S1_STATE=${AIE_S1_STATE:-/tmp/aie-v04-s1}
SERVER="$SPIRE_ROOT/bin/spire-server"
SOCKET="$AIE_S1_STATE/spire-server/private/api.sock"
ensure_user() {
  local user=$1
  if ! id "$user" >/dev/null 2>&1; then
    [[ ${EUID:-$(id -u)} -eq 0 ]] || { echo "Missing $user; rerun as root once to create lab users" >&2; exit 1; }
    useradd --system --no-create-home --shell /usr/sbin/nologin "$user"
  fi
}
for user in aie-s1-client aie-s1-gateway aie-s1-server; do ensure_user "$user"; done
create_entry() {
  local user=$1 sid=$2 uid
  uid=$(id -u "$user")
  "$SERVER" entry create -socketPath "$SOCKET" \
    -parentID "spiffe://$TRUST_DOMAIN/agent/lab" \
    -spiffeID "spiffe://$TRUST_DOMAIN/$sid" \
    -selector "unix:uid:$uid" -x509SVIDTTL 60
}
create_entry aie-s1-client  interop/mcp-client-bridge
create_entry aie-s1-gateway gateway/s1
create_entry aie-s1-server  interop/mcp-server-bridge
