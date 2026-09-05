#!/usr/bin/env python3
"""AIE authority read bridge — CLI for the TG /v2/authority proxy.

Usage:
  python aie_authority_bridge.py --state <sqlite-db> [--kind leases|missions|admissions|outcomes|evidence]

Reads authority state from the real PersistentState (W0.4) and prints
machine-readable JSON. Read-only: opens SQLite in read-only URI mode,
never writes, never mutates state.

Output shapes:
  --kind leases      {"kind": "leases", "items": [...], "count": N}
  --kind missions    {"kind": "missions", "items": [...], "count": N}
  --kind admissions  {"kind": "admissions", "items": [...], "count": N}
  --kind outcomes    {"kind": "outcomes", "items": [...], "count": N}
  --kind evidence    {"kind": "evidence", "items": [...], "count": N}
  (no --kind)        {"kinds": ["leases", ...], "counts": {...}}

Exit codes: 0 = ok, 1 = error (fail-closed, no internals leaked).
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

REQUIRED_TABLES = {"principals", "missions", "leases", "outcomes", "admissions", "evidence"}
KINDS = ("leases", "missions", "admissions", "outcomes", "evidence")


def _open_readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise ValueError("state file is not an existing regular file")
    from urllib.parse import quote
    encoded = quote(path.resolve().as_posix(), safe="/:\\")
    conn = sqlite3.connect(f"file:{encoded}?mode=ro", uri=True)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if not REQUIRED_TABLES.issubset(tables):
        raise ValueError("state file has an invalid schema")
    return conn


def _read_table(conn: sqlite3.Connection, table: str, limit: int) -> list:
    rows = conn.execute(
        f"SELECT id, data FROM {table} ORDER BY rowid DESC LIMIT ?", (limit,)
    ).fetchall()
    items = []
    for row_id, data in rows:
        try:
            items.append({"id": row_id, **json.loads(data)})
        except (json.JSONDecodeError, TypeError):
            items.append({"id": row_id, "parse_error": True})
    return items


def main() -> int:
    ap = argparse.ArgumentParser(description="AIE authority read bridge for TG")
    ap.add_argument("--state", required=True, help="PersistentState sqlite db path")
    ap.add_argument("--kind", choices=KINDS, help="which collection to read")
    ap.add_argument("--limit", type=int, default=100)
    args = ap.parse_args()

    conn = None
    try:
        state_path = Path(args.state)
        conn = _open_readonly(state_path)
        if args.kind:
            items = _read_table(conn, args.kind, min(args.limit, 500))
            print(json.dumps({"kind": args.kind, "items": items, "count": len(items)}))
        else:
            counts = {}
            for kind in KINDS:
                counts[kind] = conn.execute(f"SELECT COUNT(*) FROM {kind}").fetchone()[0]
            print(json.dumps({"kinds": list(KINDS), "counts": counts}))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__}))
        return 1
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
