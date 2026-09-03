#!/usr/bin/env bash
set -euo pipefail
umask 027

RUNNER_USER=${AIE_RUNNER_USER:-aie-runner}
RUNNER_HOME=${AIE_RUNNER_HOME:-/opt/actions-runner}
SUDOERS_FILE=/etc/sudoers.d/aie-interop-runner

fail() { printf 'AIE runner removal: %s\n' "$1" >&2; exit 2; }
[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "run as root"
cleanup_privilege() {
  unset AIE_RUNNER_REMOVAL_TOKEN || true
  rm -f "$SUDOERS_FILE" || true
}
trap cleanup_privilege EXIT
: "${AIE_RUNNER_REMOVAL_TOKEN:?Set a fresh GitHub runner removal token}"
[[ -d "$RUNNER_HOME" ]] || fail "$RUNNER_HOME does not exist"

cd "$RUNNER_HOME"
if [[ -x ./svc.sh ]]; then
  ./svc.sh stop || true
  ./svc.sh uninstall || true
fi
if [[ -x ./config.sh && -e .runner ]]; then
  runuser -u "$RUNNER_USER" -- ./config.sh remove --token "$AIE_RUNNER_REMOVAL_TOKEN"
fi
# The EXIT trap revokes the dedicated lab privilege and clears token state even on errors.
printf 'AIE self-hosted runner deregistered. Files preserved at %s.\n' "$RUNNER_HOME"
