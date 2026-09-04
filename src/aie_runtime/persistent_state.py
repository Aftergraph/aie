from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .engine import ActionRequest, AuthorityLease, Mission, Principal


class PersistentCollection:
    """A dict-like collection that persists changes to SQLite."""
    def __init__(self, conn: sqlite3.Connection, table: str, cls: type | None = None, secret_key: bytes | None = None):
        self._conn = conn
        self._table = table
        self._cls = cls
        self._secret_key = secret_key
        self._cache: dict[str, Any] = {}
        self._cache_dirty = False

    def _load(self) -> None:
        if self._cache_dirty:
            return
        self._cache.clear()
        if self._cls is not None:
            for row in self._conn.execute(f"SELECT id, data FROM {self._table}"):
                self._cache[row[0]] = self._deserialize(row[1], self._cls)
        elif self._secret_key is not None:
            for row in self._conn.execute(f"SELECT id, data FROM {self._table}"):
                d = json.loads(row[1])
                self._cache[row[0]] = d
        else:
            for row in self._conn.execute(f"SELECT id, data FROM {self._table}"):
                self._cache[row[0]] = json.loads(row[1])
        self._cache_dirty = True

    def _save(self) -> None:
        if not self._cache_dirty:
            return
        self._conn.execute(f"DELETE FROM {self._table}")
        for key, obj in self._cache.items():
            if hasattr(obj, "__dict__"):
                # Convert sets to lists for JSON serialization
                d = {}
                for k, v in obj.__dict__.items():
                    if isinstance(v, set):
                        d[k] = list(v)
                    else:
                        d[k] = v
                serialized = json.dumps(d, default=str)
            else:
                serialized = json.dumps(obj, default=str)
            if self._table == "leases":
                hmac_val = hmac.new(self._secret_key, serialized.encode("utf-8"), hashlib.sha256).hexdigest()
                self._conn.execute(
                    f"INSERT INTO {self._table} (id, data, hmac) VALUES (?, ?, ?)",
                    (key, serialized, hmac_val),
                )
            else:
                self._conn.execute(
                    f"INSERT INTO {self._table} (id, data) VALUES (?, ?)",
                    (key, serialized),
                )
        self._conn.commit()
        self._cache_dirty = False

    def _deserialize(self, data: str, cls: type | None = None) -> Any:
        """Deserialize JSON string back to object."""
        d = json.loads(data)
        if cls is not None and hasattr(cls, "__dataclass_fields__"):
            # Convert ISO format datetime strings back to datetime objects
            if "expires_at" in d and isinstance(d["expires_at"], str):
                d["expires_at"] = datetime.fromisoformat(d["expires_at"])
            # Convert lists back to sets for capabilities
            if "capabilities" in d and isinstance(d["capabilities"], list):
                d["capabilities"] = set(d["capabilities"])
            # Convert lists back to tuples for extensions
            if "extensions" in d and isinstance(d["extensions"], list):
                d["extensions"] = tuple(d["extensions"])
            return cls(**d)
        return d

    def __getitem__(self, key: str) -> Any:
        self._load()
        return self._cache[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._load()
        self._cache[key] = value
        self._cache_dirty = True
        self._save()

    def __delitem__(self, key: str) -> None:
        self._load()
        del self._cache[key]
        self._cache_dirty = True

    def get(self, key: str, default: Any = None) -> Any:
        self._load()
        return self._cache.get(key, default)

    def items(self):
        self._load()
        return self._cache.items()

    def values(self):
        self._load()
        return self._cache.values()

    def keys(self):
        self._load()
        return self._cache.keys()

    def __iter__(self):
        self._load()
        return iter(self._cache)

    def __len__(self):
        self._load()
        return len(self._cache)

    def __contains__(self, key):
        self._load()
        return key in self._cache

    def update(self, *args, **kwargs):
        self._load()
        self._cache.update(*args, **kwargs)
        self._cache_dirty = True


class EvidenceCollection:
    """Evidence list with HMAC chain for tamper-evidence."""
    def __init__(self, conn: sqlite3.Connection, secret_key: bytes):
        self._conn = conn
        self._secret_key = secret_key
        self._cache: list[Any] = []
        self._cache_dirty = False

    def _load(self) -> None:
        if self._cache_dirty:
            return
        self._cache.clear()
        for row in self._conn.execute("SELECT data, hmac FROM evidence"):
            if hmac.compare_digest(
                hmac.new(self._secret_key, row[0].encode("utf-8"), hashlib.sha256).hexdigest(),
                row[1],
            ):
                self._cache.append(json.loads(row[0]))
        self._cache_dirty = True

    def _save(self) -> None:
        if not self._cache_dirty:
            return
        self._conn.execute("DELETE FROM evidence")
        for item in self._cache:
            serialized = json.dumps(item.__dict__ if hasattr(item, "__dict__") else item, default=str)
            hmac_val = hmac.new(self._secret_key, serialized.encode("utf-8"), hashlib.sha256).hexdigest()
            self._conn.execute("INSERT INTO evidence (data, hmac) VALUES (?, ?)", (serialized, hmac_val))
        self._conn.commit()
        self._cache_dirty = False

    def append(self, item: Any) -> None:
        self._load()
        self._cache.append(item)
        self._cache_dirty = True

    def __iter__(self):
        self._load()
        return iter(self._cache)

    def __len__(self):
        self._load()
        return len(self._cache)


@dataclass
class PersistentState:
    """State backed by SQLite with WAL mode and HMAC chain for tamper-evidence.

    Provides the same interface as InMemoryState but persists across restarts.
    """
    db_path: str = ":memory:"
    _conn: sqlite3.Connection | None = field(default=None, init=False, repr=False)
    _secret_key: bytes = field(default_factory=lambda: b"aie-persistent-state-key", init=False, repr=False)
    _principals: PersistentCollection = field(default=None, init=False, repr=False)
    _missions: PersistentCollection = field(default=None, init=False, repr=False)
    _leases: PersistentCollection = field(default=None, init=False, repr=False)
    _outcomes: PersistentCollection = field(default=None, init=False, repr=False)
    _admissions: PersistentCollection = field(default=None, init=False, repr=False)
    _evidence: EvidenceCollection = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._init_schema()
            self._init_collections()

    def _init_schema(self) -> None:
        conn = self._conn
        if conn is None:
            return
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS principals (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS missions (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS leases (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                hmac TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS outcomes (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS admissions (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS evidence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data TEXT NOT NULL,
                hmac TEXT NOT NULL
            );
        """)

    def _init_collections(self) -> None:
        conn = self._conn
        if conn is None:
            return
        self._principals = PersistentCollection(conn, "principals", Principal)
        self._missions = PersistentCollection(conn, "missions", Mission)
        self._leases = PersistentCollection(conn, "leases", AuthorityLease, self._secret_key)
        self._outcomes = PersistentCollection(conn, "outcomes")
        self._admissions = PersistentCollection(conn, "admissions", ActionRequest)
        self._evidence = EvidenceCollection(conn, self._secret_key)

    @property
    def principals(self) -> PersistentCollection:
        return self._principals

    @property
    def missions(self) -> PersistentCollection:
        return self._missions

    @property
    def leases(self) -> PersistentCollection:
        return self._leases

    @property
    def outcomes(self) -> PersistentCollection:
        return self._outcomes

    @property
    def admissions(self) -> PersistentCollection:
        return self._admissions

    @property
    def evidence(self) -> EvidenceCollection:
        return self._evidence

    def save_all(self) -> None:
        """Explicitly save all collections to database."""
        if self._principals:
            self._principals._save()
        if self._missions:
            self._missions._save()
        if self._leases:
            self._leases._save()
        if self._outcomes:
            self._outcomes._save()
        if self._admissions:
            self._admissions._save()
        if self._evidence:
            self._evidence._save()
