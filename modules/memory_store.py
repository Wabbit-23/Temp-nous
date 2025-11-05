"""Persistent key-value memory store for Nous AI Assistant."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional


class MemoryStore:
    """SQLite-backed memory store supporting simple key/value recall."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None

        self._connect_with_recovery()

    # ------------------------------------------------------------------ #
    # Internal helpers
    def _connect_with_recovery(self) -> None:
        """Open the database, recovering from corruption when necessary."""
        try:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._initialise_schema()
        except sqlite3.DatabaseError:
            self._handle_corruption()
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._initialise_schema()

    def _handle_corruption(self) -> None:
        """Rename the corrupted database and start fresh."""
        try:
            if self._conn:
                self._conn.close()
        except Exception:
            pass
        finally:
            self._conn = None

        backup = self.db_path.with_suffix(self.db_path.suffix + ".bak")
        try:
            if backup.exists():
                backup.unlink()
            if self.db_path.exists():
                self.db_path.rename(backup)
        except OSError:
            # If we cannot rename, attempt to remove the broken file.
            try:
                if self.db_path.exists():
                    self.db_path.unlink()
            except OSError:
                pass

    def _initialise_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS profile (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fact TEXT UNIQUE NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.commit()

    def _timestamp(self) -> str:
        return datetime.utcnow().isoformat()

    # ------------------------------------------------------------------ #
    # Public API
    def save_memory(self, key: str, value: str) -> Dict[str, str]:
        """Insert or update a memory value."""
        key = key.strip()
        value = value.strip()
        if not key:
            raise ValueError("Memory key cannot be empty.")
        if not value:
            raise ValueError("Memory value cannot be empty.")

        created = updated = self._timestamp()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO memories (key, value, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE
                SET value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, created, updated),
            )
            self._conn.commit()
        return {"key": key, "value": value, "updated_at": updated}

    def get_memory(self, key: str) -> Optional[str]:
        """Fetch a memory by key."""
        key = key.strip()
        if not key:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM memories WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def search_memory(self, query: str, limit: int = 5) -> List[Dict[str, str]]:
        """Search memories for a query substring."""
        query = (query or "").strip()
        if not query:
            return []
        pattern = f"%{query.lower()}%"
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT key, value, updated_at
                FROM memories
                WHERE lower(key) LIKE ? OR lower(value) LIKE ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (pattern, pattern, int(limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    def all_memories(self) -> Iterable[Dict[str, str]]:
        """Return all memories ordered by most recent."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT key, value, updated_at FROM memories ORDER BY updated_at DESC"
            ).fetchall()
        for row in rows:
            yield dict(row)

    def stats(self) -> Dict[str, int]:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS total FROM memories").fetchone()
        total = row["total"] if row else 0
        return {"count": total}

    def delete_memory(self, key: str) -> None:
        key = key.strip()
        if not key:
            return
        with self._lock:
            self._conn.execute("DELETE FROM memories WHERE key = ?", (key,))
            self._conn.commit()

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM memories")
            self._conn.commit()

    def seed_from_file(self, file_path: Path, key: str = "base_policy") -> None:
        """Seed the store with a file's contents if the key is absent."""
        path = Path(file_path)
        if not path.exists():
            return
        existing = self.get_memory(key)
        if existing:
            return
        try:
            text = path.read_text(encoding="utf-8").strip()
        except UnicodeDecodeError:
            text = path.read_text(encoding="utf-8", errors="ignore").strip()
        if text:
            self.save_memory(key, text)

    def export(self) -> List[Dict[str, str]]:
        return list(self.all_memories())

    # ------------------------------------------------------------------ #
    # Profile helpers
    def add_profile_fact(self, fact: str) -> Optional[Dict[str, str]]:
        fact = (fact or "").strip()
        if not fact:
            return None
        timestamp = self._timestamp()
        with self._lock:
            try:
                self._conn.execute(
                    """
                    INSERT INTO profile (fact, created_at, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(fact) DO UPDATE
                    SET updated_at = excluded.updated_at
                    """,
                    (fact, timestamp, timestamp),
                )
                self._conn.commit()
            except sqlite3.Error:
                return None
        return {"fact": fact, "updated_at": timestamp}

    def list_profile_facts(self, limit: int = 10) -> List[str]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT fact
                FROM profile
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return [row["fact"] for row in rows]

    def clear_profile(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM profile")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# ---------------------------------------------------------------------- #
# Module-level helpers
_DEFAULT_STORE: Optional[MemoryStore] = None


def set_default_store(store: MemoryStore) -> None:
    """Register a shared default store used by helper functions."""
    global _DEFAULT_STORE
    _DEFAULT_STORE = store


def _require_store() -> MemoryStore:
    if _DEFAULT_STORE is None:
        raise RuntimeError("Memory store has not been initialised.")
    return _DEFAULT_STORE


def save_memory(key: str, value: str) -> Dict[str, str]:
    return _require_store().save_memory(key, value)


def get_memory(key: str) -> Optional[str]:
    return _require_store().get_memory(key)


def search_memory(query: str, limit: int = 5) -> List[Dict[str, str]]:
    return _require_store().search_memory(query, limit=limit)

def add_profile_fact(fact: str) -> Optional[Dict[str, str]]:
    return _require_store().add_profile_fact(fact)

def list_profile_facts(limit: int = 10) -> List[str]:
    return _require_store().list_profile_facts(limit=limit)


__all__ = [
    "MemoryStore",
    "set_default_store",
    "save_memory",
    "get_memory",
    "search_memory",
    "add_profile_fact",
    "list_profile_facts",
]
