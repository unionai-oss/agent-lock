"""Harness adapters.

An adapter teaches harness-package-manager how to configure, run, trace, and (later) enforce a
specific harness. v0.1 ships the ``reference`` adapter, which acts as a baseline and
test harness that works with the deterministic reference provider.

Each adapter declares which decision hooks it supports, its portable install
targets, and which config roots to isolate or scan.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from hpm.providers import PROVIDERS
from hpm.search import Stack
from hpm.traces import Trace, TraceRecorder


@dataclass
class RunResult:
    success: bool
    metrics: dict[str, Any] = field(default_factory=dict)
    trace: Trace | None = None


@runtime_checkable
class HarnessAdapter(Protocol):
    name: str
    supported_decisions: set[str]
    portable_kinds: dict[str, str]
    native_kinds: list[str]

    def materialize(self, stack: Stack, workdir: Path) -> Path:
        """Render config/prompts/tool wiring into workdir; return config path."""
        ...

    async def run(self, stack: Stack, task: Any, workspace: Path, recorder: TraceRecorder) -> RunResult:
        """Execute one task in workspace, recording trace events through `recorder`."""
        ...


class ReferenceAdapter:
    """Baseline harness.

    Uses the stack's planner LLM through the provider layer, emits trace events for
    every step, writes expected artifacts on success, and returns run metrics. Good
    enough to exercise the full tuner loop offline and as a comparison baseline.
    """

    name = "reference"
    supported_decisions = {"none", "retry", "stop"}
    portable_kinds: dict[str, str] = {"skill": ".harness-package-manager/skills/"}
    native_kinds: list[str] = []

    def __init__(self) -> None:
        self.provider = PROVIDERS.get("reference")

    def materialize(self, stack: Stack, workdir: Path) -> Path:
        cfg = workdir / "agent.yaml"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(f"harness: reference\nmodel: {stack.llm.get('planner', 'qwen-7b')}\n")
        return cfg

    async def run(self, stack: Stack, task: Any, workspace: Path, recorder: TraceRecorder) -> RunResult:
        model_spec = stack.llm.get("planner", "reference:qwen-7b")
        model = self.provider.resolve_alias(model_spec)[1]
        # Copy fixtures into the workspace (the "agent's scratch dir").
        if task.fixtures is not None and task.pack_dir is not None:
            src = task.pack_dir / task.fixtures
            if src.exists():
                shutil.copytree(src, workspace / "fixtures", dirs_exist_ok=True)

        expected = (task.expected or {}).get("artifacts", [])
        policy = stack.policy or {}
        steps = int(policy.get("max_steps", 20))
        success = False
        total_cost = 0.0
        total_latency = 0.0
        recorder.trace.trial["_expected"] = dict(task.expected or {})

        for step in range(steps):
            r = self.provider.complete(model, [{"role": "user", "content": task.prompt_text}])
            total_cost += r.cost_usd
            total_latency += r.latency_ms / 1000.0
            recorder.llm_call(
                role="planner",
                model=model,
                usage={"input_tokens": r.usage.input_tokens, "output_tokens": r.usage.output_tokens},
                cost_usd=r.cost_usd,
                latency_ms=r.latency_ms,
            )
            recorder.decision("retry", "rules:default", "continue", confidence=0.9)
            recorder.tool_call("filesystem", status="ok", latency_ms=5.0, detail="write")

            # Simulated agent writes the expected artifacts when "successful".
            if r.content.startswith("ANSWER_OK"):
                for art in expected:
                    (workspace / art).parent.mkdir(parents=True, exist_ok=True)
                    (workspace / art).write_text(f"artifact for {task.id}")
                success = True
                break

            # budget / steps guards stop runaway trials
            max_cost = policy.get("max_cost_usd_per_task")
            if max_cost is not None and total_cost > max_cost:
                break

        metrics = {
            "steps": step + 1,
            "cost_usd": round(total_cost, 6),
            "latency_s": round(total_latency, 3),
            "retries": step,
            "human_interventions": 0,
        }
        return RunResult(success=success, metrics=metrics)


@runtime_checkable
class AdapterRegistry(Protocol):
    def get(self, name: str) -> HarnessAdapter: ...


class _Registry:
    def __init__(self) -> None:
        self._adapters: dict[str, HarnessAdapter] = {"reference": ReferenceAdapter()}
        self._load_entry_points()

    def _load_entry_points(self) -> None:
        import importlib.metadata as _md

        try:
            eps = _md.entry_points(group="hpm.adapters")
        except Exception:
            return
        for ep in eps:
            try:
                adapter = ep.load()
            except Exception:
                continue
            if isinstance(adapter, type):
                adapter = adapter()
            self.register(adapter)

    def register(self, adapter: HarnessAdapter) -> None:
        self._adapters[adapter.name] = adapter

    def get(self, name: str) -> HarnessAdapter:
        if name not in self._adapters:
            from hpm.errors import UnsupportedComponent

            raise UnsupportedComponent(f"unknown harness adapter: {name!r}")
        return self._adapters[name]

    def names(self) -> list[str]:
        return sorted(self._adapters)

    def supports_decision(self, name: str, decision: str) -> bool:
        a = self.get(name)
        return decision in getattr(a, "supported_decisions", {"none"})


ADAPTERS = _Registry()
