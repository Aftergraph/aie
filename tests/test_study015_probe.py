from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_study015_probe_executes_real_authority_path():
    proc = subprocess.run(
        [sys.executable, "scripts/study015_probe.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    receipt = json.loads(proc.stdout.strip().splitlines()[-1])
    assert receipt["schema"] == "study015.probe/1.0"
    assert receipt["component"] == "aie"
    assert receipt["network_used"] is False
    assert len(receipt["source_head"]) == 40
    assert all(receipt["mechanisms"].values())
    assert receipt["observations"]["revocation_error_code"] == "AIE-AUTH-003"
    assert "action.revalidated" in receipt["observations"]["evidence_events"]
