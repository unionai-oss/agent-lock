"""Trial cache.

Maps ``(stack hash, task id, seed)`` onto cached trial results so a crash / partial
update only pays for new trials. On cluster this would be a shared backend; locally
it is a small JSON file.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any


class TrialCache:
    """A thread-safe, append-friendly JSON trial cache persisted to disk."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text("utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            return self._data.get(key)

    def put(self, key: str, value: dict[str, Any]) -> None:
        with self._lock:
            self._data[key] = value
            self._flush()

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, sort_keys=True))
        tmp.replace(self.path)

    def __len__(self) -> int:
        return len(self._data)
