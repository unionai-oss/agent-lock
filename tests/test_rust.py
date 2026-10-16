"""Tests for the `hpm` Python bindings (Rust-backed)."""

import json
from pathlib import Path

import pytest

import hpm

REPO = Path(__file__).resolve().parent.parent
TASKS = REPO / "tasks"

PACK_TOML = """\
[pack]
name = "test/pack"
version = "0.1.0"
license = "Apache-2.0"
domain = "demo"

[[task]]
id = "summarize"
prompt = "t1/prompt.md"
expected = { artifacts = ["summary.md"] }
"""


@pytest.fixture
def workspace(tmp_path):
    d = tmp_path / "ws"
    taskdir = d / "t1"
    taskdir.mkdir(parents=True)
    (taskdir / "prompt.md").write_text("Write an executive summary to summary.md")
    (d / "pack.toml").write_text(PACK_TOML)
    return d, tmp_path


def test_module_surface():
    assert hpm.LOCK_VERSION == 1
    assert isinstance(hpm.__version__, str)
    for name in ("Manifest", "Objective", "Budget", "SearchSpace", "Lockfile", "LockedAgent"):
        assert hasattr(hpm, name)
    assert callable(hpm.lock)
    assert callable(hpm.load)


def test_search_space_tune(workspace, monkeypatch):
    ws, base = workspace
    monkeypatch.chdir(base)
    space = hpm.SearchSpace(
        llm={"planner": ["reference:qwen-7b", "reference:qwen-32b"]},
        decision=["none", "rules:default"],
        harness=["reference"],
        tasks=json.dumps({"packs": [str(ws)], "seeds": 2}),
    )
    lf = hpm.lock(space, backend="local", workdir=str(base / ".agentlock"))
    assert lf.harness == "reference"
    ev = json.loads(lf.evidence)
    assert ev["trials"] >= 1
    # hpm.lock written at cwd
    assert (base / "hpm.lock").exists()

    # load + run
    agent = hpm.load(str(base / "hpm.lock"))
    assert agent.summary() != ""
    outcome = json.loads(agent.run("do the demo task"))
    assert "success" in outcome


def test_manifest_load_write(tmp_path):
    m = hpm.Manifest.from_str(
        "[project]\nname='m'\n[candidates.llm.planner]\nany_of=['reference:qwen-7b']\n"
        "[candidates]\nharness=['reference']\n[budget]\nstrategy='grid'\n"
    )
    assert m.name == "m"
    assert m.backend == "local"
    assert "sha256:" in m.manifest_hash()
