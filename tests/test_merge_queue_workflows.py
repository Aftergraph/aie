"""Regression coverage for merge-queue verification triggers."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "workflow_path",
    [
        ".github/workflows/aie-v04-ci-self-hosted.yml",
        ".github/workflows/codeql.yml",
    ],
)
def test_required_verification_workflows_run_for_merge_group(workflow_path: str) -> None:
    workflow = yaml.load((ROOT / workflow_path).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    triggers = workflow["on"]
    assert isinstance(triggers, dict)
    assert "pull_request" in triggers
    assert "merge_group" in triggers
