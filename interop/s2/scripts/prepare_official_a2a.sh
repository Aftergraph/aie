#!/usr/bin/env bash
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
source "$HERE/versions.env"

AIE_S2_STATE=${AIE_S2_STATE:-/tmp/aie-v04-s2}
AIE_S2_TCK_DIR=${AIE_S2_TCK_DIR:-$AIE_S2_STATE/a2a-tck}
mkdir -p "$AIE_S2_STATE"

command -v uv >/dev/null 2>&1 || {
  echo "AIE S2: uv is required to reproduce the official TCK lockfile" >&2
  exit 2
}

if [[ ! -d "$AIE_S2_TCK_DIR/.git" ]]; then
  git clone "$A2A_TCK_REPO" "$AIE_S2_TCK_DIR"
fi

ORIGIN=$(git -C "$AIE_S2_TCK_DIR" remote get-url origin)
[[ "$ORIGIN" == "$A2A_TCK_REPO" ]] || {
  echo "AIE S2: TCK origin $ORIGIN != pinned official repository $A2A_TCK_REPO" >&2
  exit 2
}

git -C "$AIE_S2_TCK_DIR" fetch origin "$A2A_TCK_COMMIT"
(
  cd "$AIE_S2_TCK_DIR"
  git checkout --detach "$A2A_TCK_COMMIT"
  [[ "$(git rev-parse HEAD)" == "$A2A_TCK_COMMIT" ]]
  [[ -f uv.lock ]] || { echo "AIE S2: pinned TCK checkout is missing uv.lock" >&2; exit 2; }
  rm -rf .venv
  uv sync --frozen --no-dev
  .venv/bin/python - <<PY
import tomllib
from pathlib import Path
version = tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))['project']['version']
expected = '$A2A_TCK_VERSION'
if version != expected:
    raise SystemExit(f'a2a-tck version {version!r} != pinned {expected!r}')
print(f'a2a-tck prepared: version={version} commit=$A2A_TCK_COMMIT')
PY
)

printf 'AIE_S2_TCK_DIR=%s\n' "$AIE_S2_TCK_DIR"
