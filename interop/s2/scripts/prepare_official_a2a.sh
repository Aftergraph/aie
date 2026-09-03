#!/usr/bin/env bash
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
source "$HERE/versions.env"

AIE_S2_STATE=${AIE_S2_STATE:-/tmp/aie-v04-s2}
AIE_S2_TCK_DIR=${AIE_S2_TCK_DIR:-$AIE_S2_STATE/a2a-tck}
mkdir -p "$AIE_S2_STATE"

if [[ ! -d "$AIE_S2_TCK_DIR/.git" ]]; then
  git clone "$A2A_TCK_REPO" "$AIE_S2_TCK_DIR"
fi

git -C "$AIE_S2_TCK_DIR" fetch origin "$A2A_TCK_COMMIT"
(
  cd "$AIE_S2_TCK_DIR"
  git checkout --detach "$A2A_TCK_COMMIT"
  [[ "$(git rev-parse HEAD)" == "$A2A_TCK_COMMIT" ]]
  rm -rf .venv
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -e .
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
