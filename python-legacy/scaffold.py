"""Scaffolding: render a starter ``hpm.toml`` (``al init``)."""

from __future__ import annotations

import tomli_w


def render_default_manifest(name: str = "agent", pack: str = "./tasks") -> str:
    data = {
        "project": {"name": name},
        "tasks": {"packs": [pack], "seeds": 2},
        "candidates": {
            "llm": {
                "planner": {"any_of": ["reference:qwen-7b", "reference:qwen-32b"]},
            },
            "decision": ["none", "rules:default"],
            "harness": ["reference"],
            "policy": {"retries": [0, 1]},
        },
        "objective": {
            "primary": "success-rate",
            "constraints": {"success-rate": ">=0.5"},
            "select": "min-cost",
        },
        "budget": {"max_trials": 200, "strategy": "grid", "random_seed": 0},
        "enforce": {"mode": "strict"},
        "backend": {"target": "local"},
    }
    body = tomli_w.dumps(data)
    return "# agent-lock manifest\n# Declare what the tuner may try and what 'best' means.\n" + body
