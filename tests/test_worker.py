"""Tests for the Rust <-> Python worker bridge (agent_lock.tasks.worker).

These prove the seam ``al optimize --backend devbox|cluster`` uses: the Rust core
shells a trial out to the Python worker over a versioned JSON contract and
consumes the response. They run entirely offline — the worker's LLM call falls
back to the deterministic reference RNG when no ``AL_LLM_BASE_URL`` is set, and
the Flyte lift degrades to in-process when the ``flyte`` SDK is absent.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def run_worker(req: dict) -> dict:
    """Invoke the worker exactly as the Rust core does."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        rq_path = td / "_al_request.json"
        rs_path = td / "_al_response.json"
        rq_path.write_text(json.dumps(req))
        proc = subprocess.run(
            [sys.executable, "-m", "agent_lock.tasks.worker", str(rq_path), str(rs_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if rs_path.exists():
            return json.loads(rs_path.read_text())
        assert proc.returncode == 0, proc.stderr
        raise AssertionError("worker wrote no response file")


def test_worker_contract_llm_trial():
    resp = run_worker(
        {
            "version": 1,
            "kind": "llm.run_trial",
            "backend": "local",
            "stack": {"llm": {"planner": "reference:qwen-7b"}, "retries": 0, "max_steps": 4},
            "task": {"id": "t1", "prompt_text": "Do the thing"},
            "seed": 0,
            "workdir": ".",
            "plan": {},
        }
    )
    assert resp["ok"] is True, resp
    r = resp["result"]
    assert "success" in r and "score" in r
    assert isinstance(r["success"], bool)
    assert isinstance(r["cost_usd"], float)
    assert isinstance(r["steps"], int)
    assert r["trace"]  # at least one llm.call event


def test_worker_contract_unknown_kind():
    resp = run_worker({"version": 1, "kind": "nope", "backend": "local"})
    assert resp["ok"] is False
    assert "unknown task kind" in resp["error"]


def test_worker_contract_bad_version():
    resp = run_worker({"version": 99, "kind": "llm.run_trial", "backend": "local"})
    assert resp["ok"] is False


@pytest.mark.parametrize(
    "kind,key",
    [
        ("data.load", "rows"),
        ("data.synthetic", "variants"),
        ("grade", "missing"),
        ("prompt.search", "available"),
        ("ft.lora", "available"),
    ],
)
def test_worker_contract_handlers(kind, key):
    resp = run_worker(
        {
            "version": 1,
            "kind": kind,
            "backend": "local",
            "data": {"source": "synthetic:3"},
            "task": {"id": "t", "expected": []},
            "stack": {"llm": {"planner": "reference:qwen-7b"}},
            "seed": 0,
            "workdir": str(REPO / "tasks"),
            "plan": {},
        }
    )
    assert resp["ok"] is True, resp
    assert key in resp["result"]["model_digests"]


def test_optimize_backend_devbox(tmp_path, monkeypatch):
    """End-to-end: Rust core -> Python worker -> harness.opt.lock, offline."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AL_PYTHON", sys.executable)  # pin the interpreter the worker runs under

    manifest = f"""[project]
name = "worker-e2e"

[tasks]
packs = ["{REPO / 'tasks'}"]
seeds = 1

[candidates.llm.planner]
any_of = ["reference:qwen-7b"]

[candidates]
decision = ["none"]
harness = ["reference"]

[objective]
primary = "success-rate"
select = "min-cost"

[budget]
strategy = "grid"
max_trials = 1
"""
    (tmp_path / "hpm.toml").write_text(manifest)

    import agent_lock as al

    out = json.loads(al.optimize(backend="devbox", depth="probe", data="synthetic:1", max_trials=1))
    report = out["report"]
    assert report["backend"] == "devbox"
    assert (tmp_path / "harness.opt.lock").exists()
    assert report["best"]["trials"] == 1  # evidence.trials follows the winner's real trial count

    lf = al.Lockfile.load(str(tmp_path / "harness.opt.lock"))
    assert json.loads(lf.to_json())["kind"] == "optimized"
