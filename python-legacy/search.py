"""The search layer.

Enumerates the search space implied by a manifest, runs trials per
(stack × task × seed), aggregates metrics, computes a Pareto front over
(quality, cost, latency), and selects the winner per the objective.

Strategies are pure Python behind the ``Strategy`` protocol so they can be
used without knowing Flyte.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from hlock.errors import content_hash


@dataclass
class Stack:
    """One concrete agent configuration (an axis of the search space)."""

    llm: dict[str, str] = field(default_factory=dict)  # role -> pinned model id
    harness: str = "reference"
    pattern: str = "single-agent"
    policy: dict[str, Any] = field(default_factory=dict)
    decision: str = "none"
    tools: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)

    def hash(self) -> str:
        return content_hash(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "llm": self.llm,
            "harness": self.harness,
            "pattern": self.pattern,
            "policy": self.policy,
            "decision": self.decision,
            "tools": sorted(self.tools),
            "skills": sorted(self.skills),
            "instructions": sorted(self.instructions),
        }

    def label(self) -> str:
        llm = "+".join(self.llm.values()) or "?"
        return f"{self.harness}/{llm}/d={self.decision}"


@dataclass
class TrialResult:
    stack_hash: str
    task_id: str
    seed: int
    success: bool
    score: float
    cost_usd: float
    latency_s: float
    steps: int
    trace: dict[str, Any] | None = None
    stall: bool = False  # infra failure, excluded from aggregates


@dataclass
class StackScore:
    stack: Stack
    trials: list[TrialResult]
    success_rate: float
    cost_usd: float
    latency_s: float
    n: int

    def mean(self, key: str) -> float:
        vals = [getattr(t, key) for t in self.trials if not t.stall]
        if not vals:
            return 0.0
        return sum(vals) / len(vals)

    def p95(self, key: str) -> float:
        vals = sorted(getattr(t, key) for t in self.trials if not t.stall)
        if not vals:
            return 0.0
        idx = min(len(vals) - 1, math.ceil(0.95 * len(vals)) - 1)
        return vals[idx]


class Strategy(Protocol):
    def propose(self, history: list[StackScore], budget: Any, stacks: list[Stack]) -> list[Stack]: ...


# --------------------------------------------------------------------------- #
# Selection / Pareto
# --------------------------------------------------------------------------- #
def dominates(a: tuple[float, float], b: tuple[float, float]) -> bool:
    """a dominates b on (quality-asc, cost): a.quality > b.quality and a.cost <= b.cost, or equal qual & lower cost."""
    aq, ac = a
    bq, bc = b
    return (aq >= bq and ac <= bc) and (aq > bq or ac < bc)


def pareto_front(scores: list[StackScore]) -> list[StackScore]:
    """Non-dominated stacks on (quality, cost). Quality is higher-is-better."""
    pts = [(round(s.success_rate, 6), round(s.cost_usd, 8), s) for s in scores]
    front = []
    for i, (q, c, s) in enumerate(pts):
        dominated = any(dominates((oq, oc), (q, c)) for j, (oq, oc, _) in enumerate(pts) if j != i)
        if not dominated:
            front.append(s)
    # sort front by quality desc, then cost asc
    front.sort(key=lambda s: (-s.success_rate, s.cost_usd))
    return front


def select_winner(scores: list[StackScore], objective: Any) -> StackScore | None:
    """Pick the winner from the Pareto front honoring objective constraints and select rule."""
    front = pareto_front(scores)
    if not front:
        return None

    def ok(s: StackScore) -> bool:
        for metric, expr in (objective.constraints or {}).items():
            val = {"success-rate": s.success_rate, "cost-usd-per-task": s.cost_usd}.get(metric)
            if val is None:
                continue
            if expr.startswith(">="):
                if not val >= float(expr[2:]):
                    return False
            elif expr.startswith("<="):
                if not val <= float(expr[2:]):
                    return False
            elif expr.startswith(">"):
                if not val > float(expr[1:]):
                    return False
            elif expr.startswith("<") and not val < float(expr[1:]):
                return False
        return True

    eligible = [s for s in front if ok(s)]
    pool = eligible or front
    if objective.select == "min-cost":
        return min(pool, key=lambda s: s.cost_usd)
    return max(pool, key=lambda s: s.success_rate)


# --------------------------------------------------------------------------- #
# Strategies
# --------------------------------------------------------------------------- #
class GridStrategy:
    """Try every candidate stack (used for small spaces)."""

    def propose(self, history: list[StackScore], budget: Any, stacks: list[Stack]) -> list[Stack]:
        return stacks


class RandomStrategy:
    def __init__(self, seed: int = 0) -> None:
        self.seed = seed

    def propose(self, history: list[StackScore], budget: Any, stacks: list[Stack]) -> list[Stack]:
        import random

        random.Random(self.seed)
        done = {h.stack.hash() for h in history}
        return [s for s in stacks if s.hash() not in done]


STRATEGIES: dict[str, Callable[..., Strategy]] = {
    "grid": GridStrategy,
    "random": RandomStrategy,
}
