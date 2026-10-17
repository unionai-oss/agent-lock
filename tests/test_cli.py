"""Tests for the `hlock` CLI: the init -> resolve -> check -> run loop, errors, --json."""

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from harness_lock.cli import main

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def project(tmp_path, monkeypatch):
    shutil.copytree(REPO / "tasks", tmp_path / "tasks")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NO_COLOR", "1")
    return tmp_path


def invoke(*args):
    return CliRunner().invoke(main, list(args))


def test_lock_loop(project):
    r = invoke("init", "--name", "demo", "--pack", "./tasks")
    assert r.exit_code == 0, r.output
    assert "wrote harness.toml" in r.output
    assert "next" in r.output and "hlock resolve" in r.output

    r = invoke("resolve")
    assert r.exit_code == 0, r.output
    assert (project / "harness.lock").exists()
    assert "Evidence" in r.output and "success rate" in r.output

    r = invoke("check")
    assert r.exit_code == 0, r.output
    assert "matches" in r.output

    r = invoke("show", "--json")
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["lock-version"] == 1

    r = invoke("tree")
    assert r.exit_code == 0 and "planner" in r.output

    r = invoke("run", "--json", "clean ./data/orders.csv")
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["success"] is True


def test_check_detects_drift(project):
    invoke("init", "--pack", "./tasks")
    invoke("resolve")
    manifest = project / "harness.toml"
    manifest.write_text(manifest.read_text().replace("max_trials = 200", "max_trials = 10"))

    r = invoke("check")
    assert r.exit_code == 1
    assert "drift" in r.output and "hlock resolve" in r.output


def test_errors_are_friendly(project):
    r = invoke("show")
    assert r.exit_code == 1
    assert "Traceback" not in r.output
    assert "hint" in r.output and "hlock resolve" in r.output

    invoke("init")
    r = invoke("init")
    assert r.exit_code == 1 and "--force" in r.output


def test_upgrade_plan(project):
    invoke("init", "--pack", "./tasks")
    invoke("resolve")
    r = invoke("upgrade", "--all")
    assert r.exit_code == 0, r.output
    assert "qwen-32b" in r.output
    assert "hlock upgrade --all --apply" in r.output
