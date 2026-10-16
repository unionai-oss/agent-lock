"""Task packs: versioned sets of domain tasks + fixtures + graders.

A task pack is a directory (or Hub reference) with a ``pack.toml``. This module
loads local packs, runs deterministic graders, and splits tasks into search /
holdout sets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomllib

from hpm.errors import AgentLockError, sha256_file


class TaskError(AgentLockError):
    pass


@dataclass
class Task:
    id: str
    prompt: str
    fixtures: Path | None = None
    tools: list[str] = field(default_factory=list)
    expected: dict[str, Any] = field(default_factory=dict)
    graders: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    timeout_seconds: int = 600

    # resolved from relative prompt path at load time
    prompt_text: str = ""
    pack_dir: Path | None = None

    def load_prompt_text(self) -> str:
        if self.prompt_text:
            return self.prompt_text
        if self.pack_dir is not None and self.prompt:
            self.prompt_text = (self.pack_dir / self.prompt).read_text("utf-8")
        return self.prompt_text


@dataclass
class Grade:
    success: bool
    score: float = 0.0
    detail: str | None = None


class Grader:
    """A named grader that can score a trial's workspace/trace."""

    def __init__(self, spec: str, pack_dir: Path):
        self.spec = spec
        self.pack_dir = pack_dir

    def run(self, workspace: Path, trace: Any) -> Grade:
        if self.spec.startswith("tests:"):
            return self._run_test(self.spec[len("tests:"):], workspace, trace)
        if self.spec.startswith("artifact:"):
            return self._run_artifact(self.spec[len("artifact:"):], workspace, trace)
        if self.spec.startswith("judge:"):
            # Judge graders need a judge model; in local reference mode we grade
            # on the presence of expected artifacts as a stand-in.
            return self._run_judge(self.spec[len("judge:"):], workspace, trace)
        raise TaskError(f"unknown grader type in {self.spec!r}")

    def _run_test(self, module_path: str, workspace: Path, trace: Any) -> Grade:
        # module_path like "tests:tasks/014/check.py" -> strip the "tests/"
        rel = module_path
        check_file = self.pack_dir / rel
        if not check_file.exists():
            return Grade(success=False, detail=f"grader file missing: {check_file}")
        # Import the check module by path (a plain function `grade(workspace, trace)`).
        import importlib.util

        spec = importlib.util.spec_from_file_location(f"_al_check_{check_file.stem}", check_file)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        fn = getattr(mod, "grade", None)
        if fn is None:
            return Grade(success=False, detail=f"grader has no grade(workspace, trace): {check_file}")
        try:
            result = fn(workspace, trace)
        except Exception as e:  # a broken grader is a failed grade, not a crash
            return Grade(success=False, detail=f"grader raised {type(e).__name__}: {e}")
        if isinstance(result, Grade):
            return result
        if isinstance(result, bool):
            return Grade(success=result, score=1.0 if result else 0.0)
        if isinstance(result, dict):
            return Grade(success=bool(result.get("success")), score=float(result.get("score", 0.0)))
        return Grade(success=False, detail=f"grader returned unexpected type: {type(result)!r}")

    def _run_artifact(self, spec: str, workspace: Path, trace: Any) -> Grade:
        specs = [s.strip() for s in spec.split(",") if s.strip()]
        missing = [s for s in specs if not (workspace / s).exists()]
        if missing:
            return Grade(success=False, score=0.0, detail=f"missing artifacts: {missing}")
        return Grade(success=True, score=1.0)

    def _run_judge(self, spec: str, workspace: Path, trace: Any) -> Grade:
        # Reference stand-in: judge passes if expected artifacts exist.
        expected = trace.trial.get("_expected", {}).get("artifacts", [])
        return self._run_artifact(",".join(expected), workspace, trace)


@dataclass
class TaskPack:
    name: str
    version: str
    domain: str
    path: Path
    tasks: list[Task]
    license: str = "Apache-2.0"
    hash: str = ""

    @classmethod
    def load(cls, source: str, base: Path | None = None) -> TaskPack:
        """Load a pack from a directory path or an ``org/name[@version]`` hub ref.

        Hub refs are resolved against any installed pack for v0.1; local paths are
        loaded from disk.
        """
        p = Path(source)
        if not p.is_absolute() and base is not None:
            p = base / p
        if not p.exists():
            raise TaskError(f"task pack not found: {source} (resolved to {p})")
        pack_toml = p / "pack.toml"
        if not pack_toml.exists():
            raise TaskError(f"task pack missing pack.toml: {p}")
        raw = tomllib.loads(pack_toml.read_text("utf-8"))
        pack = raw["pack"]
        tasks = [
            Task(
                id=t["id"],
                prompt=t.get("prompt", ""),
                fixtures=Path(t["fixtures"]) if t.get("fixtures") else None,
                tools=t.get("tools", []),
                expected=t.get("expected", {}),
                graders=t.get("graders", []),
                tags=t.get("tags", []),
                timeout_seconds=t.get("timeout-seconds", 600),
                pack_dir=p,
            )
            for t in raw.get("task", [])
        ]
        # load prompt text eagerly
        for t in tasks:
            t.load_prompt_text()
        return cls(
            name=pack["name"],
            version=pack.get("version", "0.0.0"),
            domain=pack.get("domain", ""),
            license=pack.get("license", "Apache-2.0"),
            path=p,
            tasks=tasks,
            hash=sha256_file(pack_toml),
        )

    def split(self, search_frac: float = 0.7, seed: int = 0) -> tuple[list[Task], list[Task]]:
        """Deterministic search/holdout split over task ids."""
        import random

        rng = random.Random(seed)
        tasks = sorted(self.tasks, key=lambda t: t.id)
        n_search = max(1, round(len(tasks) * search_frac))
        order = list(range(len(tasks)))
        rng.shuffle(order)
        search_idx, holdout_idx = order[:n_search], order[n_search:]
        search = [tasks[i] for i in search_idx]
        holdout = [tasks[i] for i in holdout_idx]
        return search, holdout

    def grade(self, task: Task, workspace: Path, trace: Any) -> list[Grade]:
        if not task.graders:
            # Default: require expected artifacts.
            expected = task.expected.get("artifacts", [])
            return [Grader("artifact:" + ",".join(expected), self.path).run(workspace, trace)]
        return [Grader(g, self.path).run(workspace, trace) for g in task.graders]
