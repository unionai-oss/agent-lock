"""The `hpm` command line interface.

Thin Python layer over the compiled Rust bindings (`hpm`), so the CLI story stays
consistent with the Python API. Install the wheel (pip / uv / uvx) and run `hpm`.
"""

from __future__ import annotations

import sys

import click

from hpm import LOCK_VERSION, Lockfile, Manifest, __version__, load
from hpm import lock as _lock


@click.group()
@click.version_option(__version__, prog_name="hpm")
def main() -> None:
    """hpm — harness-package-manager: lock your agent into place."""


@main.command()
@click.option("--name", default="demo", show_default=True)
@click.option("--pack", default="./tasks", show_default=True)
@click.option("--force", is_flag=True)
def init(name: str, pack: str, force: bool) -> None:
    """Write a starter agentlock.toml manifest."""
    from pathlib import Path

    p = Path("agentlock.toml")
    if p.exists() and not force:
        click.echo("agentlock.toml already exists (use --force to overwrite)")
        sys.exit(1)
    p.write_text(_default_manifest(name, pack))
    click.echo(f"wrote {p}")


@main.command()
@click.option("--backend", default=None, help="local | devbox | cluster")
@click.option("--workdir", default=None, help="Where to put .agentlock artifacts")
def lock(backend: str | None, workdir: str | None) -> None:
    """Tune the search space and write agent.lock."""
    lf = _lock("agentlock.toml", backend=backend, workdir=workdir or ".agentlock")
    click.echo("wrote agent.lock")
    click.echo(lf.summary())


@main.command()
def show() -> None:
    """Pretty-print the locked stack and evidence."""
    lf = Lockfile.load("agent.lock")
    click.echo(_render(lf))


@main.command()
def check() -> None:
    """Static verification (CI-friendly exit code)."""
    m = Manifest.load("agentlock.toml")
    lf = Lockfile.load("agent.lock")
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

    lf = Lockfile.load("agent.lock")
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

    agent = load("agent.lock")
    outcome = json.loads(agent.run(prompt))
    ok = bool(outcome.get("success"))
    click.echo(f"success={ok} model={outcome.get('model')} cost=${outcome.get('cost_usd', 0):.4f}")
    sys.exit(0 if ok else 1)


@main.group()
def backend() -> None:
    """Inspect the tuning backend."""


@backend.command("status")
def backend_status() -> None:
    """Report the active backend."""
    try:
        m = Manifest.load("agentlock.toml")
        click.echo(f"configured backend (manifest): {m.backend}")
    except Exception:  # noqa: BLE001 - manifest may be absent
        click.echo("configured backend (manifest): local (no agentlock.toml)")


def _default_manifest(name: str, pack: str) -> str:
    return f"""# hpm manifest — declare what the tuner may try and what 'best' means.
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
        f"agent.lock  (lock-version {LOCK_VERSION})",
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
