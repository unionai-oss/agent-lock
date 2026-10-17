"""Layer 1 — the Python API (scriptable, embeddable).

Everything here is pure Python with no Flyte imports. ``flyte`` appears only in
``hlock.flyte`` (Layer 3) and is imported lazily by the cluster/devbox backend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness_lock import backends
from harness.lockfile import Lockfile
from hlock.manifest import Backend, Budget, Manifest, Objective
from hlock.runtime import LockedAgent
from hlock.tasks import TaskPack
from hlock.tuner import Tuner


# --------------------------------------------------------------------------- #
# Search space (programmatic manifest)
# --------------------------------------------------------------------------- #
@dataclass
class LLMSpace:
    planner: list[str] = field(default_factory=lambda: ["reference:qwen-7b"])
    executor: list[str] = field(default_factory=list)


@dataclass
class SearchSpace:
    """Programmatic stand-in for an ``harness.toml`` manifest."""

    llm: dict[str, list[str]] = field(default_factory=dict)
    decision: list[str] = field(default_factory=list)
    harness: list[str] = field(default_factory=list)
    policy: dict[str, list[Any]] = field(default_factory=dict)
    tools: dict[str, Any] = field(default_factory=dict)
    skills: dict[str, Any] = field(default_factory=dict)

    def to_manifest(self, name: str = "agent") -> Manifest:
        candidates = {"llm": {}, "decision": self.decision, "harness": [], "policy": self.policy}
        for role, opts in self.llm.items():
            candidates["llm"][role] = {"any_of": opts}
        for h in self.harness:
            if isinstance(h, str):
                candidates["harness"].append({"name": h, "pattern": []})
            else:
                candidates["harness"].append(h)
        return Manifest(
            project={"name": name},
            candidates=candidates,
            tools=self.tools,
            skills=self.skills,
            backend=Backend(target="local"),
        )


# --------------------------------------------------------------------------- #
# Public functions
# --------------------------------------------------------------------------- #
def resolve(
    manifest: Manifest | str | Path | SearchSpace | None = None,
    tasks: TaskPack | list | None = None,
    objective: Objective | None = None,
    budget: Budget | None = None,
    backend: str | None = None,
    workdir: str | Path | None = None,
) -> Lockfile:
    """Tune and return (and write) the locked agent stack.

    Accepts a Manifest, a path to an ``harness.toml``, a programmatic
    ``SearchSpace``, or ``None`` (loads ``./harness.toml``).
    """
    if isinstance(manifest, SearchSpace):
        m = manifest.to_manifest()
    elif isinstance(manifest, (str, Path)):
        m = Manifest.load(manifest)
    elif isinstance(manifest, Manifest):
        m = manifest
    else:
        m = Manifest.load("harness.toml")

    if objective:
        m.objective = objective
    if budget:
        m.budget = budget
    if isinstance(backend, str):
        m.backend = Backend(target=backend)  # type: ignore[arg-type]
    bk_override: Any = backend if not isinstance(backend, str) else None

    tuner = Tuner(m, workdir=workdir)
    bk = bk_override or backends.make_backend(m.backend.target)
    return tuner.tune(backend=bk)


def load(path: str | Path = "harness.lock", mode: str = "strict") -> LockedAgent:
    """Load a lockfile into a runnable, guarded agent."""
    return LockedAgent.load(path, mode=mode)


# Re-exported for convenience (already public via __init__)
__all__ = ["load", "lock"]
