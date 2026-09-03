#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

ID_KEYS = ("authority_id", "authorityID", "authorityId", "id")
ACTIVE_KEYS = ("active", "is_active", "isActive")
STATUS_KEYS = ("status", "state")


def walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def record_id(record: dict[str, Any]) -> str | None:
    for key in ID_KEYS:
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def is_active(record: dict[str, Any]) -> bool:
    for key in ACTIVE_KEYS:
        if record.get(key) is True:
            return True
    for key in STATUS_KEYS:
        value = record.get(key)
        if isinstance(value, str) and value.upper() == "ACTIVE":
            return True
    return False


def select(value: Any, mode: str) -> str:
    records = list(walk(value))
    if mode == "active":
        for record in records:
            authority_id = record_id(record)
            if authority_id and is_active(record):
                return authority_id
    for record in records:
        authority_id = record_id(record)
        if authority_id:
            return authority_id
    raise ValueError(f"no authority ID found for mode={mode}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("active", "first"), default="first")
    args = parser.parse_args()
    value = json.load(sys.stdin)
    print(select(value, args.mode))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
