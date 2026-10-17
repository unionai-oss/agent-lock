"""Layer 0 — the ``hlock`` command line interface."""

from __future__ import annotations

import asyncio
import sys

import click

from harness_lock import __version__


@click.group()
@click.version_option(__version__, prog_name="hlock")
def main() -> None:
    """hlock — lock your agent into place."""


@main.command()
@click.option("--name", default="agent", show_default=True, help="Project/agent name")
@click.option("--pack", default="./tasks", show_default=True, help="Path to a task pack directory")
@click.option("--force", is_flag=True, help="Overwrite an existing harness.toml")
def init(name: str, pack: str, force: bool) -> None:
    """Write a starter harness.toml manifest."""
    from pathlib import Path

    p = Path("harness.toml")
    if p.exists() and not force:
        click.echo("harness.toml already exists (use --force to overwrite)")
        sys.exit(1)
    from hlock.scaffold import render_default_manifest

    p.write_text(render_default_manifest(name=name, pack=pack))
    click.echo(f"wrote {p}")


@main.command()
@click.option("--backend", default=None, help="local | devbox | cluster (override manifest)")
@click.option("--config", default=None, help="Flyte config path for devbox/cluster backends")
@click.option("--max-trials", default=None, type=int, help="Cap the number of trials")
def resolve(backend: str | None, config: str | None, max_trials: int | None) -> None:
    """Tune the search space and write harness.lock."""
    from harness_lock import backends
    from hlock.api import resolve as _resolve
    from hlock.manifest import Manifest

    m = Manifest.load("harness.toml")
    if backend:
        m.backend.target = backend  # type: ignore[assignment]
    if max_trials is not None:
        m.budget.max_trials = max_trials
    tuner = backends.make_backend(m.backend.target, config=config)
    lf = _resolve(m, backend=tuner)
    click.echo("wrote harness.lock")
    click.echo(lf.summary())


@main.command()
def show() -> None:
    """Pretty-print the locked stack and evidence."""
    from harness.lockfile import Lockfile

    lf = Lockfile.load("harness.lock")
    click.echo(_render_resolve(lf))


@main.command()
def check() -> None:
    """Static verification (CI-friendly exit code)."""

    from harness.lockfile import Lockfile
    from hlock.manifest import Manifest

    m = Manifest.load("harness.toml")
    lf = Lockfile.load("harness.lock")
    problems = lf.check_manifest(m.manifest_hash())
    if problems:
        for p in problems:
            click.echo(f"FAIL: {p}")
        sys.exit(1)
    click.echo("check passed: manifest matches lock")
    sys.exit(0)


@main.command()
def tree() -> None:
    """Print the locked component dependency graph."""
    from harness.lockfile import Lockfile

    lf = Lockfile.load("harness.lock")
    click.echo(f"[stack] {lf.stack.get('name', 'agent')}")
    for llm in lf.llms:
        click.echo(f"  ├─ [llm:{llm.role}] {llm.provider}:{llm.model}")
    click.echo(f"  ├─ [harness] {lf.harness.name} ({lf.harness.pattern or 'single-agent'})")
    click.echo(f"  ├─ [decision] {lf.decision.kind}")
    for t in lf.tools:
        click.echo(f"  ├─ [tool:{t.kind}] {t.name}")
    for s in lf.skills:
        click.echo(f"  ├─ [skill:{s.origin}] {s.name}")
    for i in lf.instructions:
        click.echo(f"  └─ [instructions:{i.scope}] {i.name}")


@main.command()
@click.argument("prompt")
def run(prompt: str) -> None:
    """Run the locked agent on a prompt (with runtime guard)."""
    from hlock.api import load

    agent = load("harness.lock", mode="strict")
    outcome = asyncio.run(agent.run(prompt))
    click.echo(f"success={outcome.success} steps={outcome.metrics.get('steps')} "
               f"cost=${outcome.metrics.get('cost_usd', 0):.4f}")
    sys.exit(0 if outcome.success else 1)


@main.command()
@click.option("--format", "fmt", default="text", type=click.Choice(["text", "md"]))
def diff(fmt: str) -> None:
    """Structural + evidence diff vs. the committed harness.lock."""
    from hlock.diffing import Diff

    click.echo(Diff().run(fmt=fmt))


@main.group()
def backend() -> None:
    """Inspect the tuning backend (local | devbox | cluster)."""


@backend.command("status")
@click.option("--config", default=None, help="Flyte config path (default ~/.flyte/config.yaml)")
def backend_status(config: str | None) -> None:
    """Report the active backend and Flyte config connectivity."""
    from harness_lock import backends
    from hlock.manifest import Manifest

    try:
        m = Manifest.load("harness.toml")
    except Exception:
        m = None
    target = m.backend.target if m else "local"
    click.echo(f"configured backend (manifest): {target}")
    bk = backends.make_backend(target, config=config)
    click.echo(bk.describe())
    if target in ("devbox", "cluster"):
        if bk.available():
            click.echo(f"flyte config init kwargs: {bk.init_kwargs()}")
            # verify connectivity without launching work
            click.echo("flyte SDK present; connection verified at lock/run time")
        else:
            click.echo("flyte SDK not importable — install `pip install harness-lock[flyte]`")


def _render_resolve(lf) -> str:
    lines = [f"harness.lock  (lock-version {lf.lock_version}, generated by {lf.generated_by})", ""]
    lines.append(f"stack       {lf.stack.get('name', 'agent')}  selection={lf.stack.get('selection')}")
    for llm in lf.llms:
        lines.append(f"llm:{llm.role:<8} {llm.provider}:{llm.model}")
    lines.append(f"harness     {lf.harness.name}")
    lines.append(f"decision    {lf.decision.kind}")
    for t in lf.tools:
        lines.append(f"tool        {t.name} ({t.kind})")
    for s in lf.skills:
        lines.append(f"skill       {s.name} ({s.origin})")
    lines.append("")
    ev = lf.evidence
    lines.append("Evidence:")
    lines.append(f"  trials        {ev.trials}")
    lines.append(f"  success-rate  {ev.success_rate.get('mean')}")
    lines.append(f"  cost/task     {ev.cost_usd_per_task.get('mean')}")
    lines.append(f"  latency p95   {ev.latency_s_per_task.get('p95')}")
    lines.append(f"  provenance    backend={lf.provenance.backend} strategy={lf.provenance.search.get('strategy')}")
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover
    main()
