"""In-house CI status publisher.

Posts a commit status to GitHub via the `gh api` CLI from inside a
self-hosted CI job. Used by `aie-v04-ci-self-hosted.yml` to keep the
PR-side check suite populated even when GitHub Actions billing on the
account is locked.

Usage:
    python tools/ci_status_publisher.py <state> <context> <description> [target_url]

State is one of: success | failure | pending | error.
Context is the commit-status key, e.g. "ci/test (3.12)".
Description is truncated to 140 chars (GitHub's hard limit).

Required env:
    GITHUB_SHA       - the commit SHA being reported
    GITHUB_REPOSITORY - owner/repo slug (e.g. "JonasAbde/aie")

Optional env:
    CI_TARGET_URL    - URL the status should deep-link to (e.g. the
                       self-hosted workflow run on the VDS, or the
                       interop results dir). If unset, GitHub shows
                       the commit, which is fine for pending states.

The script exits 0 on success, non-zero on any failure. Callers
should `|| true` if a non-fatal status is fine.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.stderr.write(f"ci_status_publisher: missing required env {name}\n")
        sys.exit(2)
    return value


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        sys.stderr.write(
            "usage: ci_status_publisher.py <state> <context> <description> [target_url]\n"
        )
        return 2

    state, context, description = argv[1], argv[2], argv[3]
    target_url = argv[4] if len(argv) >= 5 else os.environ.get("CI_TARGET_URL", "")

    if state not in {"success", "failure", "pending", "error"}:
        sys.stderr.write(
            f"ci_status_publisher: invalid state {state!r} "
            "(must be success|failure|pending|error)\n"
        )
        return 2

    description = description[:140]

    sha = _required("GITHUB_SHA")
    repo = _required("GITHUB_REPOSITORY")

    # `gh api` builds the JSON body via -f flags. It is the runner's
    # registered identity that posts, so no extra token wiring is
    # needed beyond the runner registration (same as the existing
    # S1.1 self-hosted workflow).
    cmd = [
        "gh",
        "api",
        f"repos/{repo}/statuses/{sha}",
        "-X",
        "POST",
        "-f",
        f"state={state}",
        "-f",
        f"context={context}",
        "-f",
        f"description={description}",
    ]
    if target_url:
        cmd += ["-f", f"target_url={target_url}"]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(
            f"ci_status_publisher: gh api failed "
            f"(rc={proc.returncode})\n"
            f"cmd: {shlex.join(cmd)}\n"
            f"stdout: {proc.stdout}\n"
            f"stderr: {proc.stderr}\n"
        )
        return proc.returncode

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
