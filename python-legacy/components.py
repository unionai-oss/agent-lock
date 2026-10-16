"""The component model.

Everything in a lock is a component of some *kind* (``tool``, ``mcp``, ``skill``,
``instructions``, … or a namespaced native kind such as ``pydantic-ai.capability``).
Kinds are a plugin point: each is a small class registered by an adapter or a
third-party package through the ``hlock.component_kinds`` entry point.

This module defines the ``ComponentKind`` protocol, the registry, pin strategies,
and the concrete portable kinds shipped with harness-lock.
"""

from __future__ import annotations

import importlib.metadata as _md
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from hlock.errors import UnsupportedComponent, content_hash

# --------------------------------------------------------------------------- #
# Pin strategies
# --------------------------------------------------------------------------- #
PIN_STRATEGIES = ("artifact", "version+integrity", "snapshot", "endpoint+fingerprint", "literal")


# --------------------------------------------------------------------------- #
# Kinds
# --------------------------------------------------------------------------- #
@runtime_checkable
class ComponentKind(Protocol):
    name: str
    harness: str | None  # None for portable kinds
    strategy: str
    entry: type[BaseModel]

    def resolve(self, spec: dict[str, Any], ctx: Any) -> dict[str, Any]: ...
    def check(self, locked: dict[str, Any], env: Any) -> list[str]: ...


class _Portable(BaseModel):
    name: str
    schema: dict[str, Any] = {}
    digest: str | None = None


class ToolEntry(_Portable):
    source: str | None = None
    permissions: list[str] = []


class MCPEntry(_Portable):
    source: str | None = None
    transport: str = "stdio"
    url: str | None = None


class SkillEntry(_Portable):
    origin: str = "third-party"
    source: str | None = None


class InstructionsEntry(_Portable):
    scope: str = "project"


class ToolKind:
    name = "tool"
    harness = None
    strategy = "artifact"
    entry = ToolEntry

    def resolve(self, spec: dict[str, Any], ctx: Any) -> dict[str, Any]:
        e = ToolEntry(**spec)
        d = e.model_dump(exclude_none=True)
        if e.source and (h := ctx and getattr(ctx, "sha256_of_source", None)):
            d["digest"] = h(e.source)
        d["schema"] = f"sha256:{content_hash(d.get('schema') or {})}"
        d["strategy"] = self.strategy
        return d

    def check(self, locked: dict[str, Any], env: Any) -> list[str]:
        return []


class MCPKind:
    name = "mcp"
    harness = None
    strategy = "version+integrity"
    entry = MCPEntry

    def resolve(self, spec: dict[str, Any], ctx: Any) -> dict[str, Any]:
        e = MCPEntry(**spec)
        return {**e.model_dump(exclude_none=True), "strategy": self.strategy}

    def check(self, locked: dict[str, Any], env: Any) -> list[str]:
        return []


class SkillKind:
    name = "skill"
    harness = None
    strategy = "artifact"
    entry = SkillEntry

    def resolve(self, spec: dict[str, Any], ctx: Any) -> dict[str, Any]:
        e = SkillEntry(**spec)
        return {**e.model_dump(exclude_none=True), "strategy": self.strategy}

    def check(self, locked: dict[str, Any], env: Any) -> list[str]:
        return []


class InstructionsKind:
    name = "instructions"
    harness = None
    strategy = "artifact"
    entry = InstructionsEntry

    def resolve(self, spec: dict[str, Any], ctx: Any) -> dict[str, Any]:
        e = InstructionsEntry(**spec)
        return {**e.model_dump(exclude_none=True), "strategy": self.strategy}

    def check(self, locked: dict[str, Any], env: Any) -> list[str]:
        return []


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
class KindRegistry:
    """Registry of component kinds, populated from built-ins + entry points."""

    def __init__(self) -> None:
        self._kinds: dict[str, ComponentKind] = {}
        self._register_builtins()
        self._load_entry_points()

    def _register_builtins(self) -> None:
        for k in (ToolKind(), MCPKind(), SkillKind(), InstructionsKind()):
            self._kinds[k.name] = k

    def _load_entry_points(self) -> None:
        try:
            eps = _md.entry_points(group="hlock.component_kinds")
        except Exception:  # pragma: no cover - packaging variants
            return
        for ep in eps:
            try:
                kind = ep.load()
            except Exception:  # pragma: no cover - a bad third-party kind must not break us
                continue
            if isinstance(kind, type):
                kind = kind()
            self.register(kind)

    def register(self, kind: ComponentKind) -> None:
        if not kind.name:
            return
        self._kinds[kind.name] = kind

    def get(self, name: str) -> ComponentKind:
        if name not in self._kinds:
            raise UnsupportedComponent(f"unknown component kind: {name!r}")
        return self._kinds[name]

    def names(self) -> list[str]:
        return sorted(self._kinds)


DEFAULT_KINDS = KindRegistry()
