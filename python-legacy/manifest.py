"""The manifest: ``hpm.toml``.

Declares what the tuner is allowed to try (candidates), what must be present
(peripherals), and what "best" means (objective / budget). Parsed into typed
Pydantic models so failures are caught before any tuning starts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import tomllib
from pydantic import BaseModel, Field, field_validator

from hpm.errors import ManifestError, canon_json, sha256_file, sha256_text


# --------------------------------------------------------------------------- #
# Objective
# --------------------------------------------------------------------------- #
class Objective(BaseModel):
    """How the winner is chosen from the Pareto front of (quality, cost, latency)."""

    primary: str = "success-rate"
    constraints: dict[str, str] = Field(default_factory=dict)  # e.g. {"success-rate": ">=0.8"}
    select: Literal["min-cost", "max-quality"] = "min-cost"


class Budget(BaseModel):
    max_spend_usd: float | None = None
    max_trials: int | None = None
    strategy: Literal["grid", "random", "successive-halving", "bayesian", "auto"] = "auto"
    random_seed: int = 0


class Enforce(BaseModel):
    mode: Literal["strict", "warn", "off"] = "strict"


class Backend(BaseModel):
    target: Literal["local", "devbox", "cluster"] = "local"
    # Marshal from the spec's `[backend] target = ...` plus optional config file path.

    @classmethod
    def from_toml(cls, d: dict[str, Any]) -> Backend:
        return cls(target=d.get("target", "local"))


# --------------------------------------------------------------------------- #
# Candidates / search space
# --------------------------------------------------------------------------- #
class LLMCandidate(BaseModel):
    """Candidate assignment for one LLM role."""

    any_of: list[str] = Field(default_factory=list)
    constraint: dict[str, Any] | None = None  # resolved version ranges, etc.


class HarnessCandidate(BaseModel):
    name: str
    pattern: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)


class Candidates(BaseModel):
    llm: dict[str, LLMCandidate] = Field(default_factory=dict)  # role -> candidates
    decision: list[str] = Field(default_factory=list)
    harness: list[HarnessCandidate] = Field(default_factory=list)
    policy: dict[str, list[Any]] = Field(default_factory=dict)

    @field_validator("harness", mode="before")
    @classmethod
    def coerce_harness(cls, v: Any) -> Any:
        if isinstance(v, list):
            out = []
            for item in v:
                if isinstance(item, str):
                    out.append({"name": item, "pattern": []})
                else:
                    out.append(item)
            return out
        if isinstance(v, dict):
            return [
                ({"name": n, **cfg} if isinstance(cfg, dict) else {"name": n})
                for n, cfg in v.items()
            ]
        return v

    @field_validator("decision", mode="before")
    @classmethod
    def coerce_decision(cls, v: Any) -> Any:
        return _as_list(v)


class Manifest(BaseModel):
    """Parsed ``hpm.toml``."""

    project: dict[str, Any] = Field(default_factory=dict)
    tasks: dict[str, Any] = Field(default_factory=dict)
    candidates: Candidates = Field(default_factory=Candidates)
    tools: dict[str, Any] = Field(default_factory=dict)
    skills: dict[str, Any] = Field(default_factory=dict)
    instructions: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    objective: Objective = Field(default_factory=Objective)
    budget: Budget = Field(default_factory=Budget)
    enforce: Enforce = Field(default_factory=Enforce)
    backend: Backend = Field(default_factory=Backend)

    source_path: Path | None = None

    # ------------------------------------------------------------------ #
    @classmethod
    def load(cls, path: str | Path) -> Manifest:
        p = Path(path)
        if not p.exists():
            raise ManifestError(f"manifest not found: {p}")
        try:
            raw = tomllib.loads(p.read_text("utf-8"))
        except tomllib.TOMLDecodeError as e:
            raise ManifestError(f"invalid hpm.toml: {e}") from e
        m = cls.from_dict(raw)
        m.source_path = p
        return m

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Manifest:
        try:
            manifest = cls(
                project=raw.get("project", {}),
                tasks=raw.get("tasks", {}),
                candidates=Candidates(
                    llm={
                        k: LLMCandidate(**v) if isinstance(v, dict) else LLMCandidate(any_of=[v])
                        for k, v in raw.get("candidates", {}).get("llm", {}).items()
                    },
                    decision=_as_list(raw.get("candidates", {}).get("decision", [])),
                    harness=[
                        HarnessCandidate(name=name, **cfg)
                        for name, cfg in _harness_candidates(raw.get("candidates", {}).get("harness", {}))
                    ],
                    policy=_as_dict(raw.get("candidates", {}).get("policy", {})),
                ),
                tools=raw.get("tools", {}),
                skills=raw.get("skills", {}),
                instructions=raw.get("instructions", {}),
                context=raw.get("context", {}),
                objective=Objective(**raw.get("objective", {})),
                budget=Budget(**raw.get("budget", {})),
                enforce=Enforce(**raw.get("enforce", {})),
                backend=Backend.from_toml(raw.get("backend", {}) or {}),
            )
        except (TypeError, ValueError) as e:
            raise ManifestError(f"invalid hpm.toml: {e}") from e
        return manifest

    @property
    def name(self) -> str:
        return (self.project or {}).get("name", "agent")

    def manifest_hash(self) -> str:
        if self.source_path is not None and self.source_path.exists():
            return sha256_file(self.source_path)
        return self._fallback_hash()

    def _fallback_hash(self) -> str:
        return sha256_text(canon_json(self.model_dump()))

    def task_packs(self) -> list[str]:
        return list(self.tasks.get("packs", []))

    def seeds(self) -> int:
        return int(self.tasks.get("seeds", 3))

    def save(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self._render_toml())
        self.source_path = p
        return p

    def _render_toml(self) -> str:
        d = self.model_dump(exclude_none=True)
        return _toml_dumps(d)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"Manifest(name={self.name!r}, backend={self.backend.target})"


def _as_list(v: Any) -> list:
    """Return v if it's a list; an empty dict (empty TOML table) or None -> []"""
    if isinstance(v, list):
        return v
    if v in (None, {}):
        return []
    return [v]


def _as_dict(v: Any) -> dict:
    return v if isinstance(v, dict) else {}


def _harness_candidates(raw: Any) -> list[tuple[str, dict]]:
    """Normalize the harness candidate table:
    - ``harness = ["opencode", "pi"]``
    - ``[candidates.harness.opencode] version = ...``
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        return [(item, {}) for item in raw if isinstance(item, str)]
    if isinstance(raw, dict):
        out = []
        for name, cfg in raw.items():
            if isinstance(cfg, bool):
                cfg = {}
            if isinstance(cfg, str):
                cfg = {"pattern": [cfg]}
            out.append((name, dict(cfg) if isinstance(cfg, dict) else {}))
        return out
    return []


def _toml_dumps(d: dict) -> str:
    """Minimal deterministic TOML renderer for the manifest save path."""
    import tomli_w  # type: ignore

    return tomli_w.dumps(d)
