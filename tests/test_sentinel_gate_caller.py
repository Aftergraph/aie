"""Regression coverage for the thin Sentinel reusable-workflow caller."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CALLER = ROOT / ".github" / "workflows" / "sentinel-gate.yml"
CENTRAL_WORKFLOW_SHA = "5ea9a7409b09092fda28f1fac3a59719b5cd51f4"


def test_sentinel_caller_pins_path_fixed_central_workflow() -> None:
    workflow = CALLER.read_text(encoding="utf-8")
    match = re.search(
        r"uses:\s*Aftergraph/\.github/\.github/workflows/agent-review\.yml@([0-9a-f]{40})\b",
        workflow,
    )
    assert match is not None
    assert match.group(1) == CENTRAL_WORKFLOW_SHA


def test_sentinel_caller_keeps_least_privilege_without_secret_inheritance() -> None:
    workflow = CALLER.read_text(encoding="utf-8")
    assert "secrets: inherit" not in workflow
    assert "contents: read" in workflow
    assert "checks: read" in workflow
    assert "pull-requests: read" in workflow
    assert not re.search(r"(?m)^\s+(contents|checks|pull-requests)\s*:\s*write\b", workflow)
