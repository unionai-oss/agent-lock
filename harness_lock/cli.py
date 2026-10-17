"""The `hlock` command line interface.

Thin Python layer over the compiled Rust bindings (`hlock`), so the CLI story stays
consistent with the Python API. Install the wheel (pip / uv / uvx) and run `hlock`.
"""

from __future__ import annotations

import sys

import click

from harness_lock import LOCK_VERSION, Lockfile, Manifest, __version__, load
from harness_lock import optimize as al_optimize
from harness_lock import resolve as _resolve
from harness_lock import upgrade as al_upgrade


@click.group()
@click.version_option(__version__, prog_name="hlock")
def main() -> None:
    """hlock — harness-lock: lock your agent into place."""


@main.command()
@click.option("--name", default="demo", show_default=True)
@click.option("--pack", default="./tasks", show_default=True)
@click.option("--force", is_flag=True)
def init(name: str, pack: str, force: bool) -> None:
    """Write a starter harness.toml manifest."""
    from pathlib import Path

    p = Path("harness.toml")
    if p.exists() and not force:
        click.echo("harness.toml already exists (use --force to overwrite)")
        sys.exit(1)
    p.write_text(_default_manifest(name, pack))
    click.echo(f"wrote {p}")


@main.command()
@click.option("--backend", default=None, help="local | devbox | cluster")
@click.option("--workdir", default=None, help="Where to put .harnesslock artifacts")
def resolve(backend: str | None, workdir: str | None) -> None:
    """Tune the search space and write harness.lock."""
    lf = _resolve("harness.toml", backend=backend, workdir=workdir or ".harnesslock")
    click.echo("wrote harness.lock")
    click.echo(lf.summary())


@main.command()
def show() -> None:
    """Pretty-print the locked stack and evidence."""
    lf = Lockfile.load("harness.lock")
    click.echo(_render(lf))


@main.command()
def check() -> None:
    """Static verification (CI-friendly exit code)."""
    m = Manifest.load("harness.toml")
    lf = Lockfile.load("harness.lock")
    if lf.manifest_hash is None:
        click.echo("FAIL: lock has no manifest-hash")
        sys.exit(1)
    live = m.manifest_hash()
    if lf.manifest_hash.split(":", 1)[-1] != live.split(":", 1)[-1]:
        click.echo(f"FAIL: manifest drift (lock {lf.manifest_hash}, live {live})")
        sys.exit(1)
    click.echo("check passed: manifest matches lock")
    sys.exit(0)


@main.command()
def tree() -> None:
    """Print the locked component dependency graph."""
    import json as _json

    lf = Lockfile.load("harness.lock")
    click.echo(f"[stack] {lf.harness}")
    for role, spec in _json.loads(lf.llm):
        click.echo(f"  ├─ [llm:{role}] {spec}")
    click.echo(f"  ├─ [harness] {lf.harness}")
    click.echo(f"  └─ backend={lf.provenance}")


@main.command()
@click.argument("prompt")
def run(prompt: str) -> None:
    """Run the locked agent on a prompt (with the Rust runtime guard)."""
    import json

    agent = load("harness.lock")
    outcome = json.loads(agent.run(prompt))
    ok = bool(outcome.get("success"))
    click.echo(f"success={ok} model={outcome.get('model')} cost=${outcome.get('cost_usd', 0):.4f}")
    sys.exit(0 if ok else 1)


@main.command()
@click.option("--to", default=None, help="target model/version to upgrade to")
@click.option("--all", is_flag=True, help="upgrade every upgradeable component")
@click.option("--apply", is_flag=True, help="perform the upgrade (default is plan-only)")
@click.option("--rollback", is_flag=True, help="restore harness.lock from harness.lock.prev")
@click.option("--force", is_flag=True, help="apply even if success-rate regresses")
@click.option("--workdir", default=None)
def upgrade(to: str | None, all: bool, apply: bool, rollback: bool, force: bool, workdir: str | None) -> None:
    """Upgrade all or a subset of locked components; plan -> apply -> rollback (§5.8)."""
    import json as _json

    result = _json.loads(
        al_upgrade(to=to, all=all, apply=apply, rollback=rollback, force=force, workdir=workdir)
    )
    for item in result.get("plan", {}).get("upgradeable", []):
        click.echo(f"  {item['role']}: {item['from']} -> {item['to']}")
    click.echo(result.get("message", ""))
    if result.get("applied"):
        click.echo(f"  after success-rate: {result.get('after'):.2f} (prev kept at harness.lock.prev)")


@main.command()
@click.option("--depth", default="auto",
              type=click.Choice(["probe", "prompt", "hpo", "ft", "full", "auto"]), help="how deep to optimize")
@click.option("--data", default="user", help="user | user:<paths> | synthetic[:n] | hub:<pack>")
@click.option("--harness", default=None)
@click.option("--out", default="harness.opt.lock", help="output opt-lock filename (user-renamable)")
@click.option("--strict", is_flag=True, help="fail unless the opt lock beats the base")
@click.option("--apply", is_flag=True, help="also adopt the result into harness.lock")
@click.option("--max-trials", default=None, type=int)
@click.option("--backend", default=None, type=click.Choice(["local", "devbox", "cluster"]), help="override the manifest's [backend] target")
@click.option("--workdir", default=None)
def optimize(depth: str, data: str, harness: str | None, out: str, strict: bool, apply: bool, max_trials: int | None, backend: str | None, workdir: str | None) -> None:
    """Optimize the harness -> harness.opt.lock (§5.9, §8.5)."""
    import json as _json

    result = _json.loads(
        al_optimize(depth=depth, data=data, harness=harness, out=out, strict=strict, apply=apply, max_trials=max_trials, backend=backend, workdir=workdir)
    )
    r = result.get("report", {})
    click.echo(f"wrote {result.get('path')}")
    click.echo(f"  depth={r.get('depth')} backend={r.get('backend')} grid={r.get('grid')} best={r.get('best')}")
    click.echo(f"  baseline success={r.get('baseline_success_rate'):.2f} -> "
               f"optimized={r.get('best', {}).get('success_rate'):.2f} (gain {r.get('gain_success_rate'):+.2f})")
    if result.get("summary"):
        click.echo(f"  summary: {result['summary']}")
    if apply:
        click.echo("  adopted into harness.lock")


@main.group()
def backend() -> None:
    """Inspect the tuning backend."""


@backend.command("status")
def backend_status() -> None:
    """Report the active backend."""
    try:
        m = Manifest.load("harness.toml")
        click.echo(f"configured backend (manifest): {m.backend}")
    except Exception:  # noqa: BLE001 - manifest may be absent
        click.echo("configured backend (manifest): local (no harness.toml)")


def _default_manifest(name: str, pack: str) -> str:
    return f"""# hlock manifest — declare what the tuner may try and what 'best' means.
[project]
name = "{name}"

[tasks]
packs = ["{pack}"]
seeds = 2

[candidates.llm.planner]
any_of = ["reference:qwen-7b", "reference:qwen-32b"]

[candidates]
decision = ["none", "rules:default"]
harness = ["reference"]

[objective]
primary = "success-rate"
select = "min-cost"

[objective.constraints]
success-rate = ">=0.5"

[budget]
strategy = "grid"
max_trials = 200

[backend]
target = "local"
"""


def _render(lf) -> str:
    import json as _json

    ev = _json.loads(lf.evidence)
    lines = [
        f"harness.lock  (lock-version {LOCK_VERSION})",
        "",
        f"harness     {lf.harness}",
        f"summary     {lf.summary()}",
        "",
        "Evidence:",
        f"  trials        {ev.get('trials')}",
        f"  success-rate  {ev.get('success_rate', {}).get('mean')}",
        f"  provenance    backend={lf.provenance}",
    ]
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover
    main()
