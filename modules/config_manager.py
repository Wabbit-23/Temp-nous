"""Simple JSON-backed configuration manager for Nous AI Assistant."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, Optional


class ConfigManager:
    def __init__(self, path: Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._data: Dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        with self._lock:
            if self.path.exists():
                try:
                    self._data = json.loads(self.path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    self._data = {}
            else:
                self._data = {}

    def save(self) -> None:
        with self._lock:
            self.path.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value
        self.save()

    def update(self, values: Dict[str, Any]) -> None:
        with self._lock:
            self._data.update(values)
        self.save()

