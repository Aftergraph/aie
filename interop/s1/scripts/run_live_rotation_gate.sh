#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
source "$HERE/versions.env"
: "${SPIRE_ROOT:?Set SPIRE_ROOT}"
: "${AIE_S1_PYTHON:?Set AIE_S1_PYTHON}"
export AIE_S1_STATE=${AIE_S1_STATE:-/tmp/aie-v04-s1}
RESULT_ROOT=${AIE_S1_RESULTS:-$HERE/results}
ROT="$RESULT_ROOT/rotation"
mkdir -p "$ROT"
chown aie-s1-client "$ROT"
rm -f "$ROT"/{probe-ready,probe-rotated,revoke.signal,rotation-probe.json,rotation-gates.json}
SERVER="$SPIRE_ROOT/bin/spire-server"
SOCKET="$AIE_S1_STATE/spire-server/private/api.sock"

run_as_client() {
  if [[ $(id -un) == "aie-s1-client" ]]; then "$@"; else runuser -u aie-s1-client -- "$@"; fi
}

# Capture the authority that signs the currently issued workload SVIDs.
"$SERVER" localauthority x509 show -socketPath "$SOCKET" -output json > "$ROT/authority-before.json"
OLD_AUTH=$("$AIE_S1_PYTHON" "$HERE/tools/authority_id.py" --mode active < "$ROT/authority-before.json")
[[ -n "$OLD_AUTH" ]]

run_as_client "$AIE_S1_PYTHON" "$HERE/rotation_probe.py" \
  --endpoint "unix://$AIE_S1_STATE/spire-agent/public/api.sock" \
  --target "https://127.0.0.1:18444/healthz" \
  --expected-peer "spiffe://$TRUST_DOMAIN/gateway/s1" \
  --ready-file "$ROT/probe-ready" \
  --rotated-file "$ROT/probe-rotated" \
  --revoke-signal "$ROT/revoke.signal" \
  --output "$ROT/rotation-probe.json" \
  --timeout 150 >"$AIE_S1_STATE/logs/rotation-probe.log" 2>&1 &
PROBE_PID=$!

for _ in $(seq 1 200); do [[ -f "$ROT/probe-ready" ]] && break; sleep .1; done
[[ -f "$ROT/probe-ready" ]]

"$SERVER" localauthority x509 prepare -socketPath "$SOCKET" -output json > "$ROT/authority-prepared.json"
NEW_AUTH=$("$AIE_S1_PYTHON" "$HERE/tools/authority_id.py" --mode first < "$ROT/authority-prepared.json")
[[ -n "$NEW_AUTH" && "$NEW_AUTH" != "$OLD_AUTH" ]]
"$SERVER" localauthority x509 activate -socketPath "$SOCKET" -authorityID "$NEW_AUTH" -output json > "$ROT/authority-activated.json"

# SVID TTLs are 60 seconds in this lab. Allow the Workload API stream to
# deliver the reissued SVID and expanded bundle after activating the new CA.
for _ in $(seq 1 900); do [[ -f "$ROT/probe-rotated" ]] && break; sleep .1; done
[[ -f "$ROT/probe-rotated" ]]

"$SERVER" localauthority x509 taint -socketPath "$SOCKET" -authorityID "$OLD_AUTH" -output json > "$ROT/authority-tainted.json" 2>/dev/null || true
"$SERVER" localauthority x509 revoke -socketPath "$SOCKET" -authorityID "$OLD_AUTH" -output json > "$ROT/authority-revoked.json" 2>/dev/null || true
touch "$ROT/revoke.signal"
wait "$PROBE_PID"

"$AIE_S1_PYTHON" - "$ROT/rotation-probe.json" "$ROT/rotation-gates.json" <<'PY'
import json, sys
src, dst = sys.argv[1:]
probe = json.load(open(src, encoding='utf-8'))
keys = ('svid_rotation_live','trust_bundle_rotation_live','old_trust_rejected','new_trust_works')
gates = {key: probe.get(key, 'FAIL') for key in keys}
gates['live_spire'] = 'PASS'
json.dump({'external_gates': gates, 'probe': probe}, open(dst,'w',encoding='utf-8'), indent=2, sort_keys=True)
open(dst,'a',encoding='utf-8').write('\n')
if not all(gates[key] == 'PASS' for key in keys):
    raise SystemExit(1)
PY

echo "live rotation gates: PASS"
