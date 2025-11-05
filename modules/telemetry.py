"""Simple structured telemetry for Nous AI Assistant."""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

_LOCK = threading.Lock()
_LOG_PATH = Path(__file__).parent.parent / "data" / "activity.log"


def _ensure_log_path() -> Path:
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    return _LOG_PATH


def log_event(event: str, **payload: Any) -> None:
    entry: Dict[str, Any] = {
        "timestamp": datetime.utcnow().isoformat(),
        "event": event,
        "data": payload,
    }
    record = json.dumps(entry, ensure_ascii=True)
    path = _ensure_log_path()
    with _LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(record + "\n")


__all__ = ["log_event"]

