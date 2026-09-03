#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
source "$HERE/versions.env"
: "${SPIRE_ROOT:?Set SPIRE_ROOT to extracted spire-${SPIRE_VERSION} directory}"
export AIE_S1_STATE=${AIE_S1_STATE:-/tmp/aie-v04-s1}
mkdir -p "$AIE_S1_STATE"/{spire-server/{private,data},spire-agent/{public,data,keys},logs}
SERVER="$SPIRE_ROOT/bin/spire-server"
AGENT="$SPIRE_ROOT/bin/spire-agent"
"$SERVER" validate -config "$HERE/spire/server.conf" -expandEnv
"$AGENT" validate -config "$HERE/spire/agent.conf" -expandEnv
"$SERVER" run -config "$HERE/spire/server.conf" -expandEnv >"$AIE_S1_STATE/logs/spire-server.log" 2>&1 &
echo $! > "$AIE_S1_STATE/spire-server.pid"
for _ in $(seq 1 100); do [[ -S "$AIE_S1_STATE/spire-server/private/api.sock" ]] && break; sleep .1; done
[[ -S "$AIE_S1_STATE/spire-server/private/api.sock" ]]
"$SERVER" bundle show -socketPath "$AIE_S1_STATE/spire-server/private/api.sock" -format pem > "$AIE_S1_STATE/bundle.pem"
TOKEN_OUT=$("$SERVER" token generate -socketPath "$AIE_S1_STATE/spire-server/private/api.sock" -spiffeID "spiffe://$TRUST_DOMAIN/agent/lab")
TOKEN=$(printf '%s\n' "$TOKEN_OUT" | awk -F'Token: ' '/Token:/{print $2; exit}')
[[ -n "$TOKEN" ]]
"$AGENT" run -config "$HERE/spire/agent.conf" -expandEnv -joinToken "$TOKEN" >"$AIE_S1_STATE/logs/spire-agent.log" 2>&1 &
echo $! > "$AIE_S1_STATE/spire-agent.pid"
for _ in $(seq 1 100); do [[ -S "$AIE_S1_STATE/spire-agent/public/api.sock" ]] && break; sleep .1; done
[[ -S "$AIE_S1_STATE/spire-agent/public/api.sock" ]]
echo "SPIRE live: spiffe://$TRUST_DOMAIN/agent/lab"
