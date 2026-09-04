#!/usr/bin/env python3
"""AIE revalidation bridge — CLI for the TG aie-client (W0.4 live posture).

Usage:
  python aie_revalidate_bridge.py --state <sqlite-db> --action-id <id>

Hydrates the real AdmissionEngine with PersistentState (leases survive restarts)
and runs execution-time revalidation (TH-12). Prints machine-readable JSON:

  {"ok": true}
  {"ok": false, "code": "AIE-AUTH-004"}

Exit codes: 0 = ok, 1 = fail-closed rejection, 2 = usage/environment error.

This is the production path for TG → AIE execution-time revalidation: the
AdmissionEngine revalidates against LIVE persistent leases, not a fresh
InMemoryState (W0.4 DoD).
"""
import argparse
import hashlib
import hmac
import json
import re
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from aie_runtime.engine import AdmissionEngine  # noqa: E402
from aie_runtime.errors import AIEError  # noqa: E402
from aie_runtime.persistent_state import PersistentState  # noqa: E402

ALLOW_POLICY = lambda decision_input: True  # policy is TG-owned; AIE posture allows here  # noqa: E731
REQUIRED_TABLES = {"principals", "missions", "leases", "outcomes", "admissions", "evidence"}
TG_BINDING_NAMESPACE = "urn:aftergraph:tg-action:v1"


def _validate_existing_state(path: Path) -> None:
    """Reject absent, non-file, empty, or malformed state without creating it."""
    if not path.is_file():
        raise ValueError("state file is not an existing regular file")
    try:
        # Read-only URI mode prevents a race from turning a missing path into a
        # newly-created SQLite database between the is_file check and open.
        encoded_path = quote(path.resolve().as_posix(), safe="/:\\")
        state_uri = f"file:{encoded_path}?mode=ro"
        conn = sqlite3.connect(
            state_uri, uri=True
        )
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise ValueError("state file is not a readable SQLite database") from exc
    if not REQUIRED_TABLES.issubset(tables):
        raise ValueError("state file has an invalid schema")


def _append_new_evidence(state: PersistentState, previous_count: int) -> None:
    """Persist only evidence emitted by this invocation.

    PersistentState.save_all() rewrites every loaded collection from process-local
    caches. The bridge must not use it after reading authority state because a
    concurrent writer could otherwise be overwritten. Insert the new evidence
    rows under one SQLite write transaction instead.
    """
    evidence = list(state.evidence)
    new_items = evidence[previous_count:]
    if not new_items:
        raise RuntimeError("revalidation emitted no evidence")
    conn = state._conn
    if conn is None:
        raise RuntimeError("state connection is unavailable")
    try:
        conn.execute("BEGIN IMMEDIATE")
        for item in new_items:
            serialized = json.dumps(
                item.__dict__ if hasattr(item, "__dict__") else item, default=str
            )
            signature = hmac.new(
                state._secret_key, serialized.encode("utf-8"), hashlib.sha256
            ).hexdigest()
            conn.execute(
                "INSERT INTO evidence (data, hmac) VALUES (?, ?)",
                (serialized, signature),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _check_expected_binding(state: PersistentState, action_id: str, expected: str | None) -> None:
    """Bind the caller's TG payload digest to the persisted admission."""
    if expected is None:
        return
    if re.fullmatch(r"[0-9a-f]{64}", expected) is None:
        raise AIEError("AIE-AUTH-004")
    request = state.admissions.get(action_id)
    if request is None:
        raise AIEError("AIE-AUTH-004")
    bindings = [
        extension
        for extension in request.extensions
        if isinstance(extension, dict) and extension.get("namespace") == TG_BINDING_NAMESPACE
    ]
    if len(bindings) != 1:
        raise AIEError("AIE-AUTH-004")
    digest = bindings[0].get("sha256")
    if not isinstance(digest, str) or not hmac.compare_digest(digest, expected):
        raise AIEError("AIE-AUTH-004")


def main() -> int:
    ap = argparse.ArgumentParser(description="AIE revalidation bridge for TG aie-client")
    ap.add_argument("--state", required=True, help="PersistentState sqlite db path")
    ap.add_argument("--action-id", required=True)
    ap.add_argument("--expected-binding", help="lowercase SHA-256 digest of the TG action payload")
    args = ap.parse_args()

    state = None
    try:
        state_path = Path(args.state)
        _validate_existing_state(state_path)
        state = PersistentState(db_path=str(state_path))
        previous_evidence_count = len(state.evidence)
        _check_expected_binding(state, args.action_id, args.expected_binding)
        engine = AdmissionEngine(state=state, policy=ALLOW_POLICY)
        engine.revalidate(args.action_id)
        _append_new_evidence(state, previous_evidence_count)
        print(json.dumps({"ok": True}))
        return 0
    except AIEError as e:
        print(json.dumps({"ok": False, "code": str(e)}))
        return 1
    except Exception:  # unreachable/corrupt state -> fail closed, no internals
        print(json.dumps({"ok": False, "code": "AIE_UNREACHABLE"}))
        return 2
    finally:
        if state is not None and state._conn is not None:
            state._conn.close()


if __name__ == "__main__":
    sys.exit(main())
