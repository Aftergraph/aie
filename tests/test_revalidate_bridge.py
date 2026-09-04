import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from aie_runtime.engine import (
    ActionRequest, AdmissionEngine, AuthorityLease, EvidenceRecord, Mission, Principal,
)
from aie_runtime.persistent_state import PersistentState


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "scripts" / "aie_revalidate_bridge.py"
NOW = datetime.now(timezone.utc)


BOUNDING = "a" * 64


def _state_with_admitted_action(path: Path, extensions=()) -> None:
    state = PersistentState(db_path=str(path))
    state.principals["p1"] = Principal("p1", "agent", "ref:p1")
    state.missions["m1"] = Mission("m1", "active")
    state.leases["l1"] = AuthorityLease(
        id="l1", principal_id="p1", mission_id="m1", capabilities={"fs.read"},
        resource_prefixes=("/data/",), expires_at=NOW + timedelta(hours=1),
        budget_remaining=10,
    )
    state.leases["unrelated"] = AuthorityLease(
        id="unrelated", principal_id="p1", mission_id="m1", capabilities={"fs.read"},
        resource_prefixes=("/other/",), expires_at=NOW + timedelta(hours=1),
        budget_remaining=20,
    )
    state.evidence.append(EvidenceRecord("preexisting", NOW, {"keep": True}))
    engine = AdmissionEngine(state, policy=lambda _: True, clock=lambda: NOW)
    engine.admit(ActionRequest(
        "a1", "p1", "m1", "l1", "fs.read", "/data/file.txt", 1,
        extensions=tuple(extensions),
    ))
    state.save_all()
    state._conn.close()


def _run(state: Path, action_id: str = "a1", expected: str | None = None) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(BRIDGE), "--state", str(state), "--action-id", action_id]
    if expected is not None:
        command.extend(["--expected-binding", expected])
    return subprocess.run(
        command,
        cwd=str(ROOT), text=True, capture_output=True, check=False,
    )


def test_bridge_flushes_revalidated_evidence(tmp_path):
    db = tmp_path / "state.db"
    _state_with_admitted_action(db)
    result = _run(db)
    assert result.returncode == 0
    assert json.loads(result.stdout) == {"ok": True}
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute("SELECT data FROM evidence").fetchall()
    finally:
        conn.close()
    assert any("action.revalidated" in row[0] for row in rows)
    assert any("preexisting" in row[0] for row in rows)

    reopened = PersistentState(db_path=str(db))
    try:
        assert reopened.leases["unrelated"].budget_remaining == 20
    finally:
        reopened._conn.close()


def test_bridge_rejects_missing_state_without_creating_it(tmp_path):
    db = tmp_path / "missing.db"
    result = _run(db)
    assert result.returncode == 2
    assert json.loads(result.stdout) == {"ok": False, "code": "AIE_UNREACHABLE"}
    assert not db.exists()


def test_bridge_rejects_corrupt_state_without_sensitive_detail(tmp_path):
    db = tmp_path / "corrupt.db"
    db.write_bytes(b"secret-corrupt-state")
    result = _run(db)
    assert result.returncode == 2
    assert json.loads(result.stdout) == {"ok": False, "code": "AIE_UNREACHABLE"}
    assert "secret-corrupt-state" not in result.stdout


def test_bridge_rejects_existing_empty_state_without_changing_it(tmp_path):
    db = tmp_path / "empty.db"
    db.write_bytes(b"")
    result = _run(db)
    assert result.returncode == 2
    assert json.loads(result.stdout) == {"ok": False, "code": "AIE_UNREACHABLE"}
    assert db.read_bytes() == b""


def test_bridge_accepts_exact_tg_binding(tmp_path):
    db = tmp_path / "bound.db"
    _state_with_admitted_action(db, [{"namespace": "urn:aftergraph:tg-action:v1", "sha256": BOUNDING}])
    result = _run(db, expected=BOUNDING)
    assert result.returncode == 0
    assert json.loads(result.stdout) == {"ok": True}


@pytest.mark.parametrize("extensions, expected", [
    ((), BOUNDING),
    ([{"namespace": "urn:aftergraph:tg-action:v1", "sha256": "b" * 64}], BOUNDING),
    ([
        {"namespace": "urn:aftergraph:tg-action:v1", "sha256": BOUNDING},
        {"namespace": "urn:aftergraph:tg-action:v1", "sha256": BOUNDING},
    ], BOUNDING),
    ([{"namespace": "urn:aftergraph:tg-action:v1", "sha256": BOUNDING}], "A" * 64),
    ([{"namespace": "urn:aftergraph:tg-action:v1", "sha256": BOUNDING}], "not-a-digest"),
])
def test_bridge_rejects_invalid_tg_binding(tmp_path, extensions, expected):
    db = tmp_path / "invalid-bound.db"
    _state_with_admitted_action(db, extensions)
    result = _run(db, expected=expected)
    assert result.returncode == 1
    assert json.loads(result.stdout) == {"ok": False, "code": "AIE-AUTH-004"}
