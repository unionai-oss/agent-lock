"""Python worker for agent-lock's heavy tuning work items.

Invoked out-of-process by the Rust core (``al``) over a versioned JSON contract:

    python -m agent_lock.tasks.worker <request.json> <response.json>

Each handler owns one ecosystem-heavy piece of ``al optimize``: real LLM
invocation, user-trace loading, synthetic-data generation, model grading,
prompt search, and LoRA fine-tuning. ``backend=local`` runs the body in-process
here; ``backend=devbox|cluster`` best-effort lifts the body to a real Flyte task
(via the optional ``flyte`` / ``flyteplugins-rs`` packages) and returns the same
response shape either way, so the Rust core never depends on where the work ran.

Heavy third-party libraries (``pandas``, ``torch``, ``transformers``, ``peft``,
``flyte``) are *optional* and imported lazily: the worker degrades gracefully
without them (deterministic reference fallback for LLM calls, file-count for
data, availability flags for tuning), which keeps it runnable in CI and on a
bare local install while still using the real ecosystem where it is present.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

# Keep in sync with crates/agent-lock-core/src/worker.rs::CONTRACT_VERSION.
CONTRACT_VERSION = 1


# --------------------------------------------------------------------------- #
# LLM invocation helpers
# --------------------------------------------------------------------------- #

def _model_quality(model: str) -> float:
    # Mirrors crates/agent-lock-core/src/providers.rs::ReferenceProvider::quality
    # so the deterministic fallback keeps discriminating model tiers identically.
    table = {"qwen-1.5b": 0.55, "qwen-7b": 0.75, "qwen-32b": 0.88}
    if model in table:
        return table[model]
    h = int(hashlib.sha256(model.encode()).hexdigest()[:8], 16)
    return 0.4 + (h % 5000) / 10000.0


def _rng(seed: int, salt: int) -> float:
    state = (seed * 2654435761) ^ (salt * 40503)
    for _ in range(4):
        state = (state * 6364136223846793005) % 2**64
        state = (state + 1442695040888963407) % 2**64
    return (state >> 33) / 4294967296.0


def _llm_configured() -> bool:
    return bool(os.environ.get("AL_LLM_BASE_URL"))


def _call_real_llm(model: str, prompt: str) -> dict | None:
    """Best-effort real OpenAI-compatible completion; None on any failure."""
    base = os.environ.get("AL_LLM_BASE_URL", "").rstrip("/")
    key = os.environ.get("AL_LLM_API_KEY", "")
    real_model = os.environ.get("AL_LLM_MODEL", model)
    if not base:
        return None
    try:
        import urllib.request

        body = json.dumps(
            {
                "model": real_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 200,
                "temperature": 0.2,
            }
        ).encode()
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        req = urllib.request.Request(
            base + "/chat/completions", data=body, headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
        content = data["choices"][0]["message"]["content"]
        return {
            "content": content,
            "cost_usd": 0.0,
            "latency_ms": 0.0,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }
    except Exception as exc:  # noqa: BLE001 - fall back on any transport failure
        sys.stderr.write(f"[worker] real LLM failed ({exc}); using reference fallback\n")
        return None


def _call_llm(model: str, prompt: str, seed: int, salt: int = 0) -> dict:
    """Real LLM when ``AL_LLM_BASE_URL`` is set, else deterministic reference."""
    if _llm_configured():
        got = _call_real_llm(model, prompt)
        if got is not None:
            return got
    q = _model_quality(model)
    r = _rng(seed, len(prompt) + salt)
    succeeded = r < q
    content = "ANSWER_OK|" if succeeded else "ANSWER_UNCERTAIN|"
    cost = 0.0001 * (4.0 if "32" in model else 1.0)
    return {
        "content": content,
        "cost_usd": round(cost, 6),
        "latency_ms": round(100.0 + r * 800.0, 1),
        "usage": {"input_tokens": 200, "output_tokens": 50},
    }


# --------------------------------------------------------------------------- #
# Handlers (each returns {"result": {...}} or {"error": "..."})
# --------------------------------------------------------------------------- #

def llm_run_trial(req: dict) -> dict:
    """Run one (stack, task, seed) trial — the work ``al optimize`` fans out."""
    stack = req.get("stack") or {}
    model_spec = stack.get("llm", {}).get("planner", "reference:qwen-7b")
    provider, _, model = model_spec.partition(":")
    if not model:
        provider, model = "reference", model_spec
    retries = int(stack.get("retries", 0))
    max_steps = int(stack.get("max_steps", 40))
    seed = int(req.get("seed", 0))
    task = req.get("task") or {}
    prompt = task.get("prompt_text") or "solve the task"

    cost = 0.0
    latency = 0.0
    success = False
    steps = 0
    events = []
    for step in range(max_steps):
        for attempt in range(retries + 1):
            r = _call_llm(model, prompt, seed, salt=step * 997 + attempt)
            cost += r["cost_usd"]
            latency += r["latency_ms"] / 1000.0
            events.append(
                {
                    "type": "llm.call",
                    "role": "planner",
                    "model": model,
                    "usage": r["usage"],
                    "cost_usd": r["cost_usd"],
                    "latency_ms": r["latency_ms"],
                }
            )
            if r["content"].startswith("ANSWER_OK"):
                success = True
                steps = step + 1
                break
        if success:
            break
        steps = step + 1
    return {
        "result": {
            "success": success,
            "score": 1.0 if success else 0.0,
            "cost_usd": round(cost, 6),
            "latency_s": round(latency, 3),
            "steps": steps,
            "trace": events,
            "artifact_digests": [],
            "model_digests": {},
            "provider": provider,
        }
    }


def _data_paths(req: dict) -> list:
    source = req.get("data", {}).get("source", "user")
    if source.startswith("user:"):
        return [p for p in source.split(":", 1)[1].split(",") if p]
    return ["."]


def data_load(req: dict) -> dict:
    """Load + normalize user traces (pandas/polars when present; else count files)."""
    source = req.get("data", {}).get("source", "user")
    paths = _data_paths(req)
    rows = 0
    cleaned = 0
    try:
        import pandas as pd  # optional
    except Exception:  # noqa: BLE001 - pandas optional
        pd = None
    for p in paths:
        if not Path(p).exists():
            continue
        if pd is not None:
            try:
                df = pd.read_csv(p) if str(p).endswith(".csv") else pd.read_json(p)
                rows += len(df)
                cleaned += int(df.dropna().shape[0])
            except Exception as exc:  # noqa: BLE001 - unreadable file
                sys.stderr.write(f"[worker] could not read {p}: {exc}\n")
                continue
        else:
            rows += 1
    return {
        "result": {
            "success": True,
            "score": 1.0 if cleaned else 0.0,
            "cost_usd": 0.0,
            "gpu_h": 0.0,
            "latency_s": 0.0,
            "steps": 0,
            "trace": [{"type": "data.load", "source": source, "rows": rows}],
            "artifact_digests": [],
            "model_digests": {"rows": rows, "cleaned": cleaned},
        }
    }


def data_synthetic(req: dict) -> dict:
    """Generate ``n`` synthetic task variants from the base pack (LLM if set)."""
    source = req.get("data", {}).get("source", "synthetic:1")
    n = int(source.split(":", 1)[1]) if ":" in source else 1
    task = req.get("task") or {}
    base_id = task.get("id", "task")
    kinds = ["failure", "tool-error", "prompt-injection", "edge"]
    variants = []
    for i in range(n):
        kind = kinds[i % len(kinds)]
        variants.append(
            {
                "id": f"{base_id}-syn-{kind}-{i}",
                "kind": kind,
                "seed": req.get("seed", 0) + i,
            }
        )
    return {
        "result": {
            "success": True,
            "score": 1.0,
            "cost_usd": 0.0,
            "gpu_h": 0.0,
            "latency_s": 0.0,
            "steps": 0,
            "trace": [{"type": "data.synthetic", "count": n}],
            "artifact_digests": [],
            "model_digests": {"variants": variants},
        }
    }


def grade(req: dict) -> dict:
    """Grade a task workspace (artifact checks by default; model-graded if set)."""
    task = req.get("task") or {}
    expected = task.get("expected") or []
    ws = Path(req.get("workdir", "."))
    missing = [a for a in expected if not (ws / a).exists()]
    success = len(missing) == 0
    return {
        "result": {
            "success": success,
            "score": 1.0 if success else 0.0,
            "cost_usd": 0.0,
            "gpu_h": 0.0,
            "latency_s": 0.0,
            "steps": 0,
            "trace": [{"type": "grade", "missing": missing}],
            "artifact_digests": [],
            "model_digests": {"missing": missing},
        }
    }


def prompt_search(req: dict) -> dict:
    """Draft candidate system prompts (real LLM when set, else a flagged stub)."""
    task = req.get("task") or {}
    prompt = task.get("prompt_text") or ""
    if _llm_configured():
        got = _call_real_llm("qwen-32b", prompt + "\n\nWrite a better system prompt.")
        content = (got or {}).get("content", "")
        return {
            "result": {
                "success": True,
                "score": 1.0,
                "cost_usd": 0.0,
                "gpu_h": 0.0,
                "latency_s": 0.0,
                "steps": 0,
                "trace": [{"type": "prompt.search", "candidates": 1}],
                "artifact_digests": [],
                "model_digests": {"candidates": [{"prompt": content, "score": 0.0}]},
            }
        }
    return {
        "result": {
            "success": True,
            "score": 1.0,
            "cost_usd": 0.0,
            "gpu_h": 0.0,
            "latency_s": 0.0,
            "steps": 0,
            "trace": [{"type": "prompt.search", "candidates": 0, "_placeholder": True}],
            "artifact_digests": [],
            "model_digests": {"available": False, "note": "set AL_LLM_BASE_URL to enable"},
        }
    }


def ft_lora(req: dict) -> dict:
    """LoRA fine-tuning (torch/peft/transformers). Reports availability when absent."""
    try:
        import peft  # noqa: F401
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except Exception:  # noqa: BLE001 - optional training stack
        return {
            "result": {
                "success": False,
                "score": 0.0,
                "cost_usd": 0.0,
                "gpu_h": 0.0,
                "latency_s": 0.0,
                "steps": 0,
                "trace": [],
                "artifact_digests": [],
                "model_digests": {"available": False, "note": "install torch/peft/transformers"},
            }
        }
    return {
        "error": "ft.lora training is not configured (set AL_FT_DATASET / GPU worker to run LoRA)",
    }


HANDLERS = {
    "llm.run_trial": llm_run_trial,
    "data.load": data_load,
    "data.synthetic": data_synthetic,
    "grade": grade,
    "prompt.search": prompt_search,
    "ft.lora": ft_lora,
}


# --------------------------------------------------------------------------- #
# Flyte lift (best-effort) and dispatch
# --------------------------------------------------------------------------- #

def _maybe_flyte(req: dict, body):
    """On devbox/cluster, best-effort lift ``body`` to a Flyte task; else in-process."""
    if req.get("backend") not in ("devbox", "cluster"):
        return body()
    try:
        import flyte

        env = flyte.TaskEnvironment(name="al_work")

        @env.task
        async def _work() -> dict:
            return body()

        import asyncio

        res = asyncio.run(flyte.run(_work))
        return res if isinstance(res, dict) else body()
    except Exception as exc:  # noqa: BLE001 - no SDK / not on a cluster -> run locally
        sys.stderr.write(f"[worker] Flyte lift unavailable ({exc}); running in-process\n")
        return body()


def _dispatch(req: dict) -> dict:
    kind = req.get("kind", "")
    handler = HANDLERS.get(kind)
    if handler is None:
        return {"error": f"unknown task kind: {kind!r}"}
    return handler(req)


def _write(path, obj):
    Path(path).write_text(json.dumps(obj))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="al-worker")
    ap.add_argument("request", type=Path, help="path to the request JSON")
    ap.add_argument("response", type=Path, help="path to write the response JSON")
    args = ap.parse_args(argv)
    try:
        req = json.loads(args.request.read_text())
    except Exception as exc:  # noqa: BLE001
        _write(args.response, {"ok": False, "error": f"bad request: {exc}"})
        return 1
    if req.get("version") != CONTRACT_VERSION:
        _write(
            args.response,
            {"ok": False, "error": f"unsupported contract version {req.get('version')}"},
        )
        return 1
    try:
        payload = _maybe_flyte(req, lambda: _dispatch(req))
    except Exception as exc:  # noqa: BLE001
        _write(args.response, {"ok": False, "error": str(exc)})
        return 1
    if payload is None:
        payload = {"error": "worker produced no output"}
    if "error" in payload:
        _write(args.response, {"ok": False, "version": CONTRACT_VERSION, "error": payload["error"]})
        return 1
    _write(args.response, {"ok": True, "version": CONTRACT_VERSION, "result": payload["result"]})
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
