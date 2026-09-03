#!/usr/bin/env bash
set -euo pipefail
umask 027

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
source "$HERE/versions.env"

RUNNER_USER=${AIE_RUNNER_USER:-aie-runner}
RUNNER_HOME=${AIE_RUNNER_HOME:-/opt/actions-runner}
RUNNER_NAME=${AIE_RUNNER_NAME:-aie-interop-$(hostname -s)}
RUNNER_LABELS=${AIE_RUNNER_LABELS:-aie-interop}
REPO_URL=${AIE_RUNNER_REPO_URL:-https://github.com/JonasAbde/aie}
SUDOERS_FILE=/etc/sudoers.d/aie-interop-runner
ARCHIVE_NAME="actions-runner-linux-x64-${GITHUB_ACTIONS_RUNNER_VERSION}.tar.gz"
DOWNLOAD_URL="https://github.com/actions/runner/releases/download/v${GITHUB_ACTIONS_RUNNER_VERSION}/${ARCHIVE_NAME}"

fail() { printf 'AIE runner bootstrap: %s\n' "$1" >&2; exit 2; }

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "run as root (for example: sudo -E bash $0)"
[[ $(uname -s) == Linux ]] || fail "Linux is required"
case "$(uname -m)" in x86_64|amd64) ;; *) fail "Linux x86-64 is required" ;; esac
: "${AIE_RUNNER_REGISTRATION_TOKEN:?Set a fresh GitHub runner registration token; it expires after one hour}"
[[ ${AIE_RUNNER_ENABLE_LAB_SUDO:-0} == 1 ]] || fail "set AIE_RUNNER_ENABLE_LAB_SUDO=1 only on a dedicated or ephemeral AIE interop host"
command -v curl >/dev/null || fail "curl is required"
command -v sha256sum >/dev/null || fail "sha256sum is required"
command -v useradd >/dev/null || fail "useradd is required"
command -v runuser >/dev/null || fail "runuser is required"
command -v visudo >/dev/null || fail "visudo is required"

if ! id "$RUNNER_USER" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash "$RUNNER_USER"
fi
install -d -m 0750 -o "$RUNNER_USER" -g "$RUNNER_USER" "$RUNNER_HOME"
[[ ! -e "$RUNNER_HOME/.runner" ]] || fail "$RUNNER_HOME is already configured; remove/deregister it first"

TMP_DIR=$(mktemp -d)
cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT
ARCHIVE="$TMP_DIR/$ARCHIVE_NAME"
curl --fail --location --silent --show-error "$DOWNLOAD_URL" -o "$ARCHIVE"
printf '%s  %s\n' "$GITHUB_ACTIONS_RUNNER_LINUX_X64_SHA256" "$ARCHIVE" | sha256sum -c -
tar -xzf "$ARCHIVE" -C "$RUNNER_HOME"
chown -R "$RUNNER_USER:$RUNNER_USER" "$RUNNER_HOME"

# GitHub's dependency helper is root-oriented and installs OS packages when needed.
"$RUNNER_HOME/bin/installdependencies.sh"

# The S1 lab intentionally executes root-required trust/user isolation code. This is
# equivalent to granting trusted manual workflow code root on this dedicated host.
TMP_SUDOERS="$TMP_DIR/aie-interop-runner"
printf '%s ALL=(ALL) NOPASSWD: ALL\n' "$RUNNER_USER" > "$TMP_SUDOERS"
chmod 0440 "$TMP_SUDOERS"
visudo -cf "$TMP_SUDOERS" >/dev/null
install -o root -g root -m 0440 "$TMP_SUDOERS" "$SUDOERS_FILE"
chmod 0440 "$SUDOERS_FILE"
visudo -cf "$SUDOERS_FILE" >/dev/null

cd "$RUNNER_HOME"
runuser -u "$RUNNER_USER" -- ./config.sh \
  --unattended \
  --url "$REPO_URL" \
  --token "$AIE_RUNNER_REGISTRATION_TOKEN" \
  --name "$RUNNER_NAME" \
  --labels "$RUNNER_LABELS" \
  --work _work \
  --disableupdate \
  --replace
unset AIE_RUNNER_REGISTRATION_TOKEN

./svc.sh install "$RUNNER_USER"
./svc.sh start

# Verify the exact execution prerequisites from the runner identity before declaring
# the host ready. Results stay outside the repository checkout.
PREFLIGHT_OUT=/tmp/aie-runner-preflight
rm -rf "$PREFLIGHT_OUT"
runuser -u "$RUNNER_USER" -- env AIE_S1_RESULTS="$PREFLIGHT_OUT" \
  bash "$ROOT/interop/s1/scripts/preflight_external_host.sh"

printf 'AIE self-hosted runner configured: name=%s labels=%s repo=%s\n' \
  "$RUNNER_NAME" "$RUNNER_LABELS" "$REPO_URL"
