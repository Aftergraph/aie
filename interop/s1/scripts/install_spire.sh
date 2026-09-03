#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
source "$HERE/versions.env"
DEPS=${AIE_S1_DEPS:-/tmp/aie-v04-s1-deps}
mkdir -p "$DEPS"
ARCHIVE="$DEPS/spire-${SPIRE_VERSION}-linux-amd64-musl.tar.gz"
URL="https://github.com/spiffe/spire/releases/download/v${SPIRE_VERSION}/spire-${SPIRE_VERSION}-linux-amd64-musl.tar.gz"
if [[ ! -f "$ARCHIVE" ]]; then curl --fail --location --retry 4 --retry-delay 2 "$URL" -o "$ARCHIVE"; fi
printf '%s  %s\n' "$SPIRE_LINUX_AMD64_MUSL_SHA256" "$ARCHIVE" | sha256sum --check --strict
rm -rf "$DEPS/spire-${SPIRE_VERSION}"
tar -xzf "$ARCHIVE" -C "$DEPS"
[[ -x "$DEPS/spire-${SPIRE_VERSION}/bin/spire-server" ]]
printf '%s\n' "$DEPS/spire-${SPIRE_VERSION}"
