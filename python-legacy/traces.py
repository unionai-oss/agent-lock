"""Trace schema, recorder, and replay.

Built on top of the OTel GenAI conventions with agent-lock extensions. Payloads are
content-addressed so traces stay small, shareable, and redactable. The trace layer
stands alone: it is usable without the tuner.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from al.errors import canon_json, sha256_text


@dataclass
class TraceEvent:
    type: str  # llm.call | decision | tool.call | skill.activate | approval | ...
    ts_ms: float = 0.0
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "ts_ms": self.ts_ms, **self.data}


@dataclass
class Trace:
    trace_id: str
    trial: dict[str, Any]
    events: list[TraceEvent] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    grades: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def new(cls, stack_hash: str, task_id: str, seed: int) -> Trace:
        return cls(trace_id=uuid.uuid4().hex, trial={"stack": stack_hash, "task": task_id, "seed": seed})

    def emit(self, type_: str, **data: Any) -> None:
        self.events.append(TraceEvent(type=type_, data=data))

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "trial": self.trial,
            "events": [e.to_dict() for e in self.events],
            "result": self.result,
            "grades": self.grades,
            "metrics": self.metrics,
        }

    def to_json(self) -> str:
        return canon_json(self.to_dict())

    def hash(self) -> str:
        return sha256_text(self.to_json())

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Trace:
        return cls(
            trace_id=d["trace_id"],
            trial=d["trial"],
            events=[TraceEvent(type=e["type"], ts_ms=e.get("ts_ms", 0.0), data=e) for e in d.get("events", [])],
            result=d.get("result", {}),
            grades=d.get("grades", []),
            metrics=d.get("metrics", {}),
        )


class TraceRecorder:
    """Collects trace events for one trial and hands back the finished Trace."""

    def __init__(self, stack_hash: str, task_id: str, seed: int) -> None:
        self.trace = Trace.new(stack_hash, task_id, seed)
        self._start = 0.0

    def llm_call(self, role: str, model: str, usage: dict, cost_usd: float, latency_ms: float, **extra: Any) -> None:
        self.trace.emit(
            "llm.call",
            role=role,
            model=model,
            usage=usage,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            **extra,
        )

    def decision(self, kind: str, model: str, choice: str, confidence: float | None = None) -> None:
        self.trace.emit("decision", kind=kind, model=model, choice=choice, confidence=confidence)

    def tool_call(self, tool: str, status: str, latency_ms: float, **extra: Any) -> None:
        self.trace.emit("tool.call", tool=tool, status=status, latency_ms=latency_ms, **extra)

    def skill_activate(self, skill: str, digest: str | None = None) -> None:
        self.trace.emit("skill.activate", skill=skill, digest=digest)

    def approval(self, action: str, outcome: str, by: str = "simulated") -> None:
        self.trace.emit("approval", action=action, outcome=outcome, by=by)

    def finish(self, result: dict[str, Any], metrics: dict[str, Any], grades: list[dict[str, Any]]) -> Trace:
        self.trace.result = result
        self.trace.metrics = metrics
        self.trace.grades = grades
        return self.trace
