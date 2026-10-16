"""End-to-end tests: init -> lock -> show/check/tree/run, plus the Python API."""

import asyncio

from hpm.api import load
from hpm.manifest import Manifest
from hpm.runtime import RuntimeGuard

MANIFEST_TOML = """\
[project]
name = "demo"

[tasks]
packs = ["./tasks"]
seeds = 2

[candidates]
decision = ["none", "rules:default"]
harness = ["reference"]

[candidates.llm.planner]
any_of = ["reference:qwen-7b", "reference:qwen-32b"]

[objective]
primary = "success-rate"
select = "min-cost"

[objective.constraints]
success-rate = ">=0.5"

[budget]
max_trials = 200
strategy = "grid"

[backend]
target = "local"
"""


def test_manifest_load_from_string(tmp_path):
    (tmp_path / "agentlock.toml").write_text(MANIFEST_TOML)
    m = Manifest.load(tmp_path / "agentlock.toml")
    assert m.name == "demo"
    assert m.budget.strategy == "grid"
    assert [h.name for h in m.candidates.harness] == ["reference"]


def test_full_local_loop(tmp_path, tasks_pack, monkeypatch):
    """hpm init/lock/show/check/tree/run end to end against a local pack."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "agentlock.toml").write_text(MANIFEST_TOML)

    from hpm.tuner import Tuner

    m = Manifest.load(tmp_path / "agentlock.toml")
    m.tasks = {"packs": [str(tasks_pack)], "seeds": 2}
    tuner = Tuner(m, workdir=tmp_path / ".agentlock")
    rf = tuner.tune()
    assert rf.manifest_hash is not None
    lock_path = tmp_path / "agent.lock"
    assert lock_path.exists()

    # reload as lockfile
    from hpm.lockfile import Lockfile

    lf = Lockfile.load(lock_path)
    assert lf.harness.name == "reference"
    assert lf.evidence.trials >= 1
    assert lf.check_manifest(m.manifest_hash()) == []

    # tree / show info available
    assert lf.llms
    assert lf.provenance.backend == "local"


def test_runtime_guard():
    from hpm.lockfile import Lockfile

    lf = Lockfile(stack={"name": "g"}, harness={"name": "reference"})
    guard = RuntimeGuard(lf, mode="strict")
    guard.check_model("planner", "reference:qwen-7b")  # no lock -> no violation
    guard.check_tool("python")  # no allowlist -> no violation


def test_locked_agent_run(tmp_path, tasks_pack, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "agentlock.toml").write_text(MANIFEST_TOML)
    m = Manifest.load(tmp_path / "agentlock.toml")
    m.tasks = {"packs": [str(tasks_pack)], "seeds": 2}
    from hpm.tuner import Tuner

    Tuner(m, workdir=tmp_path / ".agentlock").tune()

    agent = load(tmp_path / "agent.lock", mode="off")
    outcome = asyncio.run(agent.run("solve the demo task"))
    assert outcome.metrics.get("steps", 0) >= 0
    assert outcome.trace is not None
