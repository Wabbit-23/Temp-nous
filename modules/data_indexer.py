"""Knowledge index and search utilities for Nous AI Assistant."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from collections import defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import humanize

from modules.path_policies import (
    default_allowed_roots,
    default_excluded_paths,
    is_allowed,
    normalise_paths,
)
from modules.telemetry import log_event

ALLOWED_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".rst",
    ".py",
    ".json",
    ".cfg",
    ".ini",
    ".yaml",
    ".yml",
    ".csv",
    ".toml",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".html",
    ".css",
    ".scss",
    ".less",
    ".pdf",
    ".docx",
    ".log",
    ".ipynb",
}

TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".rst",
    ".json",
    ".cfg",
    ".ini",
    ".yaml",
    ".yml",
    ".csv",
    ".toml",
    ".log",
    ".html",
    ".css",
    ".scss",
    ".less",
}

CODE_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx"}

MAX_SNIPPET_CHARS = 6000


class DataIndexer:
    """SQLite-backed index that tracks local files and supports ranked search."""

    def __init__(
        self,
        base_path: Path | None = None,
        db_path: Path | None = None,
        allowed_roots: Sequence[str | Path] | None = None,
        excluded_paths: Sequence[str | Path] | None = None,
        max_file_size_mb: float = 8.0,
    ) -> None:
        project_root = Path(__file__).parent.parent
        self.base_path = Path(base_path or (project_root / "data")).expanduser().resolve()
        default_db = project_root / "data" / "knowledge_index.db"
        self.db_path = Path(db_path or default_db).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.allowed_extensions = {ext.lower() for ext in ALLOWED_EXTENSIONS}

        self.allowed_roots = normalise_paths(allowed_roots) or default_allowed_roots()
        self.excluded_paths = normalise_paths(excluded_paths) or default_excluded_paths()
        self.max_file_size_mb = max(1.0, float(max_file_size_mb))
        self.max_file_size_bytes = int(self.max_file_size_mb * 1024 * 1024)

        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._fts_available = True
        self._cancel_event = threading.Event()
        self._last_skipped: List[Dict[str, str]] = []
        self._last_errors: List[Dict[str, str]] = []

        self._connect()
        self._prepare_schema()

    # ------------------------------------------------------------------ #
    # Configuration helpers
    def update_policy(
        self,
        allowed_roots: Sequence[str | Path] | None = None,
        excluded_paths: Sequence[str | Path] | None = None,
        max_file_size_mb: Optional[float] = None,
    ) -> None:
        if allowed_roots is not None:
            self.allowed_roots = normalise_paths(allowed_roots) or default_allowed_roots()
        if excluded_paths is not None:
            base = default_excluded_paths()
            extras = normalise_paths(excluded_paths)
            merged = base + [path for path in extras if path not in base]
            self.excluded_paths = merged
        if max_file_size_mb is not None:
            self.max_file_size_mb = max(1.0, float(max_file_size_mb))
            self.max_file_size_bytes = int(self.max_file_size_mb * 1024 * 1024)

    def cancel_indexing(self) -> None:
        self._cancel_event.set()

    # ------------------------------------------------------------------ #
    # Database setup
    def _connect(self) -> None:
        if self._conn:
            return
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")

    def _prepare_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS files (
                    id          INTEGER PRIMARY KEY,
                    path        TEXT UNIQUE,
                    mtime       REAL,
                    size        INTEGER,
                    indexed_at  TEXT
                )
                """
            )
            try:
                cur.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS file_content
                    USING fts5(path UNINDEXED, content, tokenize = 'porter');
                    """
                )
            except sqlite3.OperationalError:
                self._fts_available = False
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS file_content (
                        file_id INTEGER PRIMARY KEY,
                        content TEXT,
                        FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
                    )
                    """
                )
            self._conn.commit()

    def _update_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                (key, value),
            )
            self._conn.commit()

    def _get_meta(self, key: str, default=None):
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM metadata WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row else default

    # ------------------------------------------------------------------ #
    # Public API
    def set_base_path(self, path: Path) -> None:
        resolved = Path(path).expanduser().resolve()
        ok, reason = self._check_allowed(resolved)
        if not ok:
            raise PermissionError(f"Cannot index '{resolved}': {reason}")
        if not resolved.exists():
            raise FileNotFoundError(f"Base path '{resolved}' does not exist")
        self.base_path = resolved
        self._update_meta("base_path", str(resolved))

    def get_base_path(self) -> Path:
        saved = self._get_meta("base_path", None)
        return Path(saved).expanduser().resolve() if saved else self.base_path

    def rebuild_index(
        self,
        on_progress: Callable[[int, int, str], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Dict[str, int | str | bool]:
        """Incrementally rebuild the knowledge index."""
        base = self.get_base_path()
        if not base.exists():
            return {"documents": 0, "total_scanned": 0, "skipped": 0, "errors": 0, "cancelled": False}

        event = cancel_event or threading.Event()
        self._cancel_event = event
        event.clear()

        self._last_skipped = []
        self._last_errors = []

        candidates = self._collect_candidates(base, event)
        total = len(candidates)
        log_event("index.rebuild_start", base=str(base), candidates=total)

        with self._lock:
            existing_rows = self._conn.execute(
                "SELECT path, mtime, size FROM files"
            ).fetchall()
        existing = {Path(row["path"]): (row["mtime"], row["size"]) for row in existing_rows}

        updated = 0
        processed = 0
        seen_paths: set[Path] = set()
        cancelled = False

        for idx, path in enumerate(candidates, start=1):
            if event.is_set():
                cancelled = True
                break

            seen_paths.add(path)
            processed += 1
            try:
                stat = path.stat()
            except OSError as exc:
                self._record_error(path, f"Stat failed: {exc}")
                continue

            previous = existing.get(path)
            if previous and previous[0] == stat.st_mtime and previous[1] == stat.st_size:
                if on_progress:
                    on_progress(idx, total, str(path))
                continue

            snippet, note = self._read_text_snippet(path, stat.st_size)
            if snippet is None:
                # fall back to filename when no readable content
                snippet = f"{path.name} (no readable text found)"

            with self._lock:
                self._upsert_file(path, stat, snippet)
            updated += 1

            if note:
                self._record_skip(path, note)

            if on_progress:
                on_progress(idx, total, str(path))

        stale_paths = set(existing.keys()) - seen_paths
        if stale_paths:
            with self._lock:
                for stale in stale_paths:
                    self._delete_file(stale)

        documents = self._count_files()
        self._update_meta("last_indexed", datetime.utcnow().isoformat())
        self._update_meta("document_count", str(documents))

        log_event(
            "index.rebuild_complete",
            base=str(base),
            documents=documents,
            total_scanned=total,
            updated=updated,
            processed=processed,
            skipped=len(self._last_skipped),
            errors=len(self._last_errors),
            cancelled=cancelled,
        )
        return {
            "documents": documents,
            "total_scanned": total,
            "updated": updated,
            "processed": processed,
            "skipped": len(self._last_skipped),
            "errors": len(self._last_errors),
            "cancelled": cancelled,
        }

    def stats(self) -> Dict[str, str | int]:
        base = self.get_base_path()
        with self._lock:
            doc_count_row = self._conn.execute("SELECT COUNT(*) FROM files").fetchone()
        count = doc_count_row[0] if doc_count_row else 0
        return {
            "documents": count,
            "last_indexed": self._get_meta("last_indexed", "Never"),
            "base_path": str(base),
            "skipped": len(self._last_skipped),
            "errors": len(self._last_errors),
        }

    def last_run_details(self) -> Dict[str, List[Dict[str, str]]]:
        return {
            "skipped": list(self._last_skipped),
            "errors": list(self._last_errors),
        }

    def search(self, query: str, limit: int = 20) -> List[Dict[str, str]]:
        query = (query or "").strip()
        if not query:
            return []

        limit = max(1, int(limit))
        lower_query = query.lower()
        tokens = [tok for tok in re.findall(r"[\\w]+", lower_query) if tok]

        with self._lock:
            file_rows = self._conn.execute(
                "SELECT path, mtime, size FROM files"
            ).fetchall()

        name_scores: Dict[Path, float] = defaultdict(float)
        now = time.time()
        for row in file_rows:
            path = Path(row["path"])
            filename = path.name.lower()
            score = 0.0
            if filename == lower_query:
                score += 150
            elif filename.startswith(lower_query):
                score += 110
            elif lower_query in filename:
                score += 90

            if score == 0 and len(lower_query) >= 3:
                ratio = SequenceMatcher(None, lower_query, filename).ratio()
                if ratio >= 0.6:
                    score += ratio * 70

            # Token bonus
            for token in tokens:
                if token and token in filename:
                    score += 15

            if score > 0:
                age_days = max(0.0, (now - row["mtime"]) / 86400.0)
                recency_bonus = max(5.0, 35.0 - age_days)
                depth_penalty = max(0.0, len(path.parts) * 1.5)
                name_scores[path] += score + recency_bonus - depth_penalty

        content_scores: Dict[Path, Tuple[float, str]] = {}
        if tokens:
            if self._fts_available:
                match_query = " OR ".join(f"{token}*" for token in tokens)
                sql = f"""
                    SELECT files.path,
                           snippet(file_content, 1, '[', ']', ' ... ', 16) AS preview,
                           bm25(file_content) AS rank
                    FROM file_content
                    JOIN files ON files.id = file_content.rowid
                    WHERE file_content MATCH ?
                    ORDER BY rank
                    LIMIT {limit * 2}
                """
                with self._lock:
                    rows = self._conn.execute(sql, (match_query,)).fetchall()
                for row in rows:
                    path = Path(row["path"])
                    rank = row["rank"] or 0.0
                    score = max(0.0, 120.0 - float(rank))
                    content_scores[path] = (score, row["preview"])
            else:
                like_term = f"%{lower_query}%"
                sql = f"""
                    SELECT files.path,
                           substr(file_content.content, 1, 400) AS preview,
                           files.mtime
                    FROM file_content
                    JOIN files ON files.id = file_content.file_id
                    WHERE lower(file_content.content) LIKE ?
                    LIMIT {limit * 2}
                """
                with self._lock:
                    rows = self._conn.execute(sql, (like_term,)).fetchall()
                for row in rows:
                    path = Path(row["path"])
                    score = 60.0
                    content_scores[path] = (score, row["preview"])

        merged: Dict[Path, Dict[str, str | float]] = {}
        for row in file_rows:
            path = Path(row["path"])
            entry = {
                "path": str(path),
                "name": path.name,
                "score": 0.0,
                "snippet": "",
                "modified": datetime.fromtimestamp(row["mtime"]).isoformat(),
                "modified_human": humanize.naturaltime(datetime.fromtimestamp(row["mtime"])),
                "size_bytes": row["size"],
                "size_human": humanize.naturalsize(row["size"], binary=True),
            }
            merged[path] = entry

        for path, score in name_scores.items():
            if path in merged:
                merged[path]["score"] = merged[path].get("score", 0.0) + score
                if not merged[path]["snippet"]:
                    merged[path]["snippet"] = f"Filename match for '{query}'"

        for path, (score, snippet) in content_scores.items():
            if path in merged:
                merged[path]["score"] = merged[path].get("score", 0.0) + score
                snippet_text = (snippet or "").strip()
                if snippet_text:
                    merged[path]["snippet"] = snippet_text
                elif not merged[path]["snippet"]:
                    merged[path]["snippet"] = "Content match"

        # final ranking
        ranked = sorted(
            merged.values(),
            key=lambda item: (-float(item["score"]), item["name"], item["path"]),
        )
        final = ranked[:limit]
        log_event("index.search", query=query, limit=limit, results=len(final))
        return final

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # ------------------------------------------------------------------ #
    # Internal helpers
    def _check_allowed(self, path: Path) -> Tuple[bool, Optional[str]]:
        return is_allowed(path, self.allowed_roots, self.excluded_paths)

    def _collect_candidates(self, root: Path, cancel_event: threading.Event) -> List[Path]:
        candidates: List[Path] = []
        visited: set[Path] = set()

        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            if cancel_event.is_set():
                break

            current_dir = Path(dirpath)
            try:
                resolved = current_dir.resolve()
            except OSError:
                resolved = current_dir

            if resolved in visited:
                dirnames[:] = []
                continue
            visited.add(resolved)

            allowed, reason = self._check_allowed(current_dir)
            if not allowed:
                dirnames[:] = []
                self._record_skip(current_dir, reason or "Excluded path")
                continue

            pruned = []
            for dirname in dirnames:
                subdir = current_dir / dirname
                ok, reason = self._check_allowed(subdir)
                if ok:
                    pruned.append(dirname)
                else:
                    self._record_skip(subdir, reason or "Excluded path")
            dirnames[:] = pruned

            for filename in filenames:
                path = current_dir / filename
                if path.suffix.lower() not in self.allowed_extensions:
                    continue
                ok, reason = self._check_allowed(path)
                if ok:
                    candidates.append(path)
                else:
                    self._record_skip(path, reason or "Excluded path")

        return candidates

    def _upsert_file(self, path: Path, stat: os.stat_result, content: str) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO files(path, mtime, size, indexed_at)
            VALUES (?, ?, ?, ?)
            """,
            (str(path), stat.st_mtime, stat.st_size, datetime.utcnow().isoformat()),
        )
        if self._fts_available:
            self._conn.execute(
                "INSERT OR REPLACE INTO file_content(rowid, path, content) VALUES ((SELECT id FROM files WHERE path = ?), ?, ?)",
                (str(path), str(path), content),
            )
        else:
            file_id = self._conn.execute(
                "SELECT id FROM files WHERE path = ?", (str(path),)
            ).fetchone()[0]
            self._conn.execute(
                "INSERT OR REPLACE INTO file_content(file_id, content) VALUES (?, ?)",
                (file_id, content),
            )
        self._conn.commit()

    def _delete_file(self, path: Path) -> None:
        self._conn.execute("DELETE FROM files WHERE path = ?", (str(path),))
        if self._fts_available:
            self._conn.execute("DELETE FROM file_content WHERE path = ?", (str(path),))
        else:
            self._conn.execute(
                "DELETE FROM file_content WHERE file_id NOT IN (SELECT id FROM files)"
            )
        self._conn.commit()

    def _count_files(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS total FROM files").fetchone()
        return row["total"] if row else 0

    def _read_text_snippet(self, path: Path, size: int) -> Tuple[Optional[str], Optional[str]]:
        """Return (snippet, note) tuple for a file."""
        note = None
        suffix = path.suffix.lower()

        if size > self.max_file_size_bytes:
            note = f"Skipped content (>{self.max_file_size_mb:.1f} MB)"
            return (path.name, note)

        try:
            if suffix in TEXT_EXTENSIONS or suffix in CODE_EXTENSIONS:
                text = path.read_text(encoding="utf-8", errors="ignore")
                return (text[:MAX_SNIPPET_CHARS], note)

            if suffix == ".pdf":
                try:
                    import fitz  # type: ignore
                except Exception:
                    note = "PDF text extraction unavailable"
                    return (path.name, note)
                doc = fitz.open(path)
                text = "\n".join(page.get_text("text") for page in doc)
                doc.close()
                return (text[:MAX_SNIPPET_CHARS], note)

            if suffix == ".docx":
                try:
                    from docx import Document  # type: ignore
                except Exception:
                    note = "DOCX text extraction unavailable"
                    return (path.name, note)
                document = Document(str(path))
                text = "\n".join(paragraph.text for paragraph in document.paragraphs)
                return (text[:MAX_SNIPPET_CHARS], note)

            if suffix == ".ipynb":
                data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
                cells = []
                for cell in data.get("cells", []):
                    if cell.get("cell_type") == "markdown":
                        cells.extend(cell.get("source", []))
                text = "\n".join(cells)
                return (text[:MAX_SNIPPET_CHARS], note)

        except Exception as exc:
            note = f"Read error: {exc}"
            return (None, note)

        return (None, "Unsupported format")

    def _record_skip(self, path: Path, reason: str) -> None:
        self._last_skipped.append({"path": str(path), "reason": reason})
        log_event("index.skip_path", path=str(path), reason=reason)

    def _record_error(self, path: Path, reason: str) -> None:
        self._last_errors.append({"path": str(path), "reason": reason})
        log_event("index.error", path=str(path), reason=reason)


__all__ = ["DataIndexer", "ALLOWED_EXTENSIONS"]
