"""Shared exceptions and small helpers for harness-package-manager."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any


class AgentLockError(Exception):
    """Base class for all harness-package-manager errors."""


class ManifestError(AgentLockError):
    """A manifest is malformed or refers to something we cannot resolve."""


class LockfileError(AgentLockError):
    """An agent.lock is malformed, stale, or out of schema."""


class CheckFailed(AgentLockError):
    """Static verification (``hpm check``) found violations."""


class VerifyFailed(AgentLockError):
    """Dynamic verification (``hpm verify``) found drift."""


class UnsupportedComponent(AgentLockError):
    """A component kind / adapter / backend is not registered."""


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def content_hash(obj: Any) -> str:
    """Stable content hash for a JSON-serializable object."""
    return sha256_bytes(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def canon_json(obj: Any) -> str:
    """Deterministic JSON for hashing and store addressing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def iter_unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out
