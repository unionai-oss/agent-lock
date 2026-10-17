"""The `hlock` command line interface.

Thin Python layer over the compiled Rust bindings (`hlock`), so the CLI story stays
consistent with the Python API. Install the wheel (pip / uv / uvx) and run `hlock`.

Output is rendered with `rich`: color and spinners on a terminal, plain text when piped
(or with ``NO_COLOR`` set). Commands that read state also take ``--json`` for scripting.
"""

from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path

import rich_click as click
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme
from rich.tree import Tree

from harness_lock import LOCK_VERSION, Lockfile, Manifest, __version__, load
from harness_lock import optimize as al_optimize
from harness_lock import resolve as _resolve
from harness_lock import upgrade as al_upgrade

MANIFEST = "harness.toml"
LOCK = "harness.lock"

THEME = Theme(
    {
        "brand": "bold magenta",
        "ok": "bold green",
        "fail": "bold red",
        "warn": "bold yellow",
        "key": "cyan",
        "path": "bold blue",
        "cmd": "bold cyan",
        "muted": "dim",
    }
)
console = Console(theme=THEME, highlight=False)
err_console = Console(theme=THEME, stderr=True, highlight=False)

click.rich_click.TEXT_MARKUP = "rich"
click.rich_click.STYLE_OPTION = "bold cyan"
click.rich_click.STYLE_COMMAND = "bold cyan"
click.rich_click.STYLE_SWITCH = "bold green"
click.rich_click.STYLE_METAVAR = "yellow"
click.rich_click.STYLE_USAGE = "bold magenta"
click.rich_click.MAX_WIDTH = 100
click.rich_click.COMMAND_GROUPS = {
    "hlock": [
        {"name": "Lock", "commands": ["init", "resolve", "check"]},
        {"name": "Inspect", "commands": ["show", "tree", "backend"]},
        {"name": "Run & evolve", "commands": ["run", "upgrade", "optimize"]},
    ]
}


def _fail(message: str, hint: str | None = None) -> None:
    """Exit 1 with a one-line error (and an optional hint), never a traceback."""
    err_console.print(f"[fail]✗ error:[/] {message}")
    if hint:
        err_console.print(f"  [muted]hint:[/] {hint}")
    sys.exit(1)


def _hint_for(message: str) -> str | None:
    if "cannot read" in message and MANIFEST in message:
        return "create one with [cmd]hlock init[/]"
    if "cannot read" in message and LOCK in message:
        return "write one with [cmd]hlock resolve[/]"
    if "no tasks loaded" in message or "no viable stack" in message:
        return f"check that [key]\\[tasks] packs[/] in [path]{MANIFEST}[/] point at a directory with a pack.toml"
    if "task pack" in message:
        return f"check the [key]\\[tasks] packs[/] paths in [path]{MANIFEST}[/]"
    if "python worker" in message:
        return "set [key]HL_PYTHON[/] to an interpreter that has hlock installed"
    return None


@contextmanager
def _friendly_errors():
    """Turn binding errors (ValueError from the Rust core) into a clean CLI error."""
    try:
        yield
    except ValueError as e:
        msg = str(e).strip()
        _fail(msg, _hint_for(msg))


@contextmanager
def _working(message: str):
    with _friendly_errors(), console.status(f"[brand]{message}[/]", spinner="dots"):
        yield


def _next(*steps: str) -> None:
    console.print(Text.from_markup("[muted]next →[/] " + "[muted]  ·  [/]".join(f"[cmd]{s}[/]" for s in steps)))


def _ok(message: str) -> None:
    console.print(f"[ok]✓[/] {message}")


def _pct(v) -> str:
    return "—" if v is None else f"{float(v):.0%}"


def _usd(v) -> str:
    return "—" if v is None else f"${float(v):.4f}"


def _secs(v) -> str:
    return "—" if v is None else f"{float(v):.2f}s"


def _signed_pct(v) -> Text:
    v = float(v or 0.0)
    style = "ok" if v > 0 else ("fail" if v < 0 else "muted")
    return Text(f"{v:+.0%}", style=style)


def _kv_table() -> Table:
    t = Table.grid(padding=(0, 2))
    t.add_column(style="key", no_wrap=True)
    t.add_column()
    return t


def _lock_panel(lf, title: str = LOCK) -> Panel:
    ev = json.loads(lf.evidence)
    stack = _kv_table()
    stack.add_row("harness", f"[bold]{lf.harness}[/]")
    for role, spec in json.loads(lf.llm):
        stack.add_row(f"llm · {role}", f"[bold]{spec}[/]")
    stack.add_row("decision", lf.decision)
    stack.add_row("backend", lf.provenance)

    evidence = _kv_table()
    sr = (ev.get("success_rate") or {}).get("mean")
    evidence.add_row("success rate", Text(_pct(sr), style="ok" if (sr or 0) >= 0.5 else "warn"))
    evidence.add_row("cost / task", _usd((ev.get("cost_usd_per_task") or {}).get("mean")))
    lat = ev.get("latency_s_per_task") or {}
    evidence.add_row("latency", f"p50 {_secs(lat.get('p50'))}  ·  p95 {_secs(lat.get('p95'))}")
    evidence.add_row("trials", str(ev.get("trials", "—")))

    digest = (lf.manifest_hash or "—").split(":", 1)[-1][:12]
    return Panel(
        Group(
            Text("Stack", style="bold"), stack, Text(""),
            Text("Evidence", style="bold"), evidence, Text(""),
            Text(f"lock-version {LOCK_VERSION} · manifest {digest}", style="muted"),
        ),
        title=f"[brand]🔒 {title}[/]",
        title_align="left",
        border_style="magenta",
        expand=False,
        padding=(1, 2),
    )


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, "-V", "--version", prog_name="hlock")
def main() -> None:
    """[brand]hlock[/] · lock your agent into place.

    Tune your agent stack against your own tasks, then pin the winner in a
    [path]harness.lock[/].

    Get started: [cmd]hlock init[/] → [cmd]hlock resolve[/] → [cmd]hlock check[/]
    """


@main.command()
@click.option("--name", default="demo", show_default=True, help="Project name for the manifest.")
@click.option("--pack", default="./tasks", show_default=True, help="Path to a task pack directory.")
@click.option("--force", is_flag=True, help="Overwrite an existing harness.toml.")
def init(name: str, pack: str, force: bool) -> None:
    """Write a starter [path]harness.toml[/] manifest."""
    p = Path(MANIFEST)
    if p.exists() and not force:
        _fail(f"{MANIFEST} already exists", "pass [cmd]--force[/] to overwrite it")
    p.write_text(_default_manifest(name, pack))
    _ok(f"wrote [path]{p}[/]  [muted](project {name!r}, task pack {pack})[/]")
    if not (Path(pack) / "pack.toml").exists():
        console.print(f"[warn]![/] no [path]pack.toml[/] found in [path]{pack}[/]; add one before resolving")
    _next("hlock resolve")


@main.command()
@click.option("--backend", default=None, type=click.Choice(["local", "devbox", "cluster"]),
              help="Override the manifest's \\[backend] target.")
@click.option("--workdir", default=None, help="Where to put trial artifacts.  [dim]\\[default: .harnesslock][/]")
def resolve(backend: str | None, workdir: str | None) -> None:
    """Tune the search space and write [path]harness.lock[/]."""
    with _working(f"Resolving {MANIFEST} on the {backend or 'configured'} backend…"):
        lf = _resolve(MANIFEST, backend=backend, workdir=workdir or ".harnesslock")
    _ok(f"wrote [path]{LOCK}[/]")
    console.print(_lock_panel(lf))
    _next("hlock check", 'hlock run "<prompt>"')


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Print the lockfile as JSON.")
def show(as_json: bool) -> None:
    """Show the locked stack and the evidence behind it."""
    with _friendly_errors():
        lf = Lockfile.load(LOCK)
    if as_json:
        console.print_json(lf.to_json())
        return
    console.print(_lock_panel(lf))


@main.command()
def check() -> None:
    """Fail if [path]harness.toml[/] has drifted from [path]harness.lock[/] (CI-friendly)."""
    with _friendly_errors():
        m = Manifest.load(MANIFEST)
        lf = Lockfile.load(LOCK)
    if lf.manifest_hash is None:
        _fail(f"{LOCK} has no manifest-hash", "re-create it with [cmd]hlock resolve[/]")
    live = m.manifest_hash()
    locked = lf.manifest_hash
    if locked.split(":", 1)[-1] != live.split(":", 1)[-1]:
        err_console.print(f"[fail]✗ drift:[/] {MANIFEST} changed since {LOCK} was written")
        grid = _kv_table()
        grid.add_row("locked", f"[muted]{locked}[/]")
        grid.add_row("live", f"[muted]{live}[/]")
        err_console.print(grid)
        err_console.print("  [muted]hint:[/] re-lock with [cmd]hlock resolve[/], then commit both files")
        sys.exit(1)
    _ok(f"[path]{LOCK}[/] matches [path]{MANIFEST}[/]  [muted]{live.split(':', 1)[-1][:12]}[/]")


@main.command()
def tree() -> None:
    """Print the locked component dependency graph."""
    with _friendly_errors():
        lf = Lockfile.load(LOCK)
    root = Tree(f"[brand]🔒 {LOCK}[/]", guide_style="magenta")
    stack = root.add(f"[bold]stack[/] [muted]harness={lf.harness}[/]")
    llms = stack.add("[key]llm[/]")
    for role, spec in json.loads(lf.llm):
        llms.add(f"{role}  [bold]{spec}[/]")
    stack.add(f"[key]decision[/]  {lf.decision}")
    stack.add(f"[key]harness[/]  [bold]{lf.harness}[/]")
    root.add(f"[key]provenance[/]  backend={lf.provenance}")
    console.print(root)


@main.command()
@click.argument("prompt")
@click.option("--json", "as_json", is_flag=True, help="Print the raw outcome as JSON.")
def run(prompt: str, as_json: bool) -> None:
    """Run the locked agent on PROMPT."""
    with _friendly_errors():
        agent = load(LOCK)
    with _working("Running the locked agent…"):
        raw = agent.run(prompt)
    outcome = json.loads(raw)
    ok = bool(outcome.get("success"))
    if as_json:
        console.print_json(raw)
    else:
        mark = "[ok]✓ success[/]" if ok else "[fail]✗ failed[/]"
        console.print(
            f"{mark}  [muted]model[/] {outcome.get('model')}  "
            f"[muted]cost[/] {_usd(outcome.get('cost_usd', 0))}"
        )
    sys.exit(0 if ok else 1)


@main.command()
@click.option("--to", default=None, help="Target model/version to upgrade to.")
@click.option("--all", "all_", is_flag=True, help="Upgrade every upgradeable component.")
@click.option("--apply", is_flag=True, help="Perform the upgrade (default is plan-only).")
@click.option("--rollback", is_flag=True, help="Restore harness.lock from harness.lock.prev.")
@click.option("--force", is_flag=True, help="Apply even if the success rate regresses.")
@click.option("--workdir", default=None, help="Where to put trial artifacts.")
def upgrade(to: str | None, all_: bool, apply: bool, rollback: bool, force: bool, workdir: str | None) -> None:
    """Plan, apply, or roll back upgrades to locked components."""
    label = "Rolling back…" if rollback else ("Applying upgrade…" if apply else "Planning upgrades…")
    with _working(label):
        result = json.loads(
            al_upgrade(to=to, all=all_, apply=apply, rollback=rollback, force=force, workdir=workdir)
        )
    items = result.get("plan", {}).get("upgradeable", [])
    if items:
        t = Table(box=None, header_style="bold", pad_edge=False)
        t.add_column("component", style="key")
        t.add_column("locked")
        t.add_column("")
        t.add_column("available", style="bold green")
        for item in items:
            t.add_row(item["role"], item["from"], "→", item["to"])
        console.print(t)
    if result.get("rolled_back"):
        _ok(f"restored [path]{LOCK}[/] from [path]{LOCK}.prev[/]")
    elif result.get("applied"):
        _ok(
            f"upgraded  [muted]success rate[/] {_pct(result.get('before'))} → "
            f"[bold]{_pct(result.get('after'))}[/]  [muted](previous lock kept at {LOCK}.prev)[/]"
        )
    else:
        console.print(f"[muted]{result.get('message', '')}[/]")
        if items and not apply:
            _next("hlock upgrade --all --apply")


@main.command()
@click.option("--depth", default="auto", show_default=True,
              type=click.Choice(["probe", "prompt", "hpo", "ft", "full", "auto"]), help="How deep to optimize.")
@click.option("--data", default="user", show_default=True, help="user | user:<paths> | synthetic\\[:n] | hub:<pack>")
@click.option("--harness", default=None, help="Restrict to one harness.")
@click.option("--out", default="harness.opt.lock", show_default=True, help="Output opt-lock filename.")
@click.option("--strict", is_flag=True, help="Fail unless the opt lock beats the base.")
@click.option("--apply", is_flag=True, help="Also adopt the result into harness.lock.")
@click.option("--max-trials", default=None, type=int, help="Cap the number of trials.")
@click.option("--backend", default=None, type=click.Choice(["local", "devbox", "cluster"]),
              help="Override the manifest's \\[backend] target.")
@click.option("--workdir", default=None, help="Where to put trial artifacts.")
def optimize(depth: str, data: str, harness: str | None, out: str, strict: bool, apply: bool,
             max_trials: int | None, backend: str | None, workdir: str | None) -> None:
    """Tune prompts, hyperparameters and small models into [path]harness.opt.lock[/]."""
    with _working(f"Optimizing (depth={depth}, data={data})…"):
        result = json.loads(
            al_optimize(depth=depth, data=data, harness=harness, out=out, strict=strict, apply=apply,
                        max_trials=max_trials, backend=backend, workdir=workdir)
        )
    r = result.get("report", {})
    best = r.get("best") or {}
    _ok(f"wrote [path]{result.get('path')}[/]")

    run_info = _kv_table()
    run_info.add_row("depth", str(r.get("depth")))
    run_info.add_row("backend", str(r.get("backend")))
    run_info.add_row("data", str(r.get("data_mode") or r.get("data")))
    run_info.add_row("grid", f"{r.get('grid')} configurations")

    chosen = _kv_table()
    for k, v in best.items():
        if k in ("success_rate", "cost_usd", "trials"):
            continue
        chosen.add_row(k.replace("_", " "), f"[bold]{v}[/]")

    result_row = Text.assemble(
        ("success rate  ", "key"), _pct(r.get("baseline_success_rate")), "  →  ",
        (_pct(best.get("success_rate")), "bold"), "   ", _signed_pct(r.get("gain_success_rate")),
    )
    console.print(Panel(
        Group(run_info, Text(""), Text("Best configuration", style="bold"), chosen, Text(""), result_row),
        title="[brand]⚙ optimize[/]", title_align="left", border_style="magenta", expand=False, padding=(1, 2),
    ))
    if apply:
        _ok(f"adopted into [path]{LOCK}[/]")
    else:
        _next("hlock optimize --apply")


@main.group()
def backend() -> None:
    """Inspect the tuning backend."""


@backend.command("status")
def backend_status() -> None:
    """Show the configured backend and the environment it will use."""
    try:
        target = Manifest.load(MANIFEST).backend
        source = f"from {MANIFEST}"
    except ValueError:
        target, source = "local", f"no {MANIFEST}, using the default"

    t = _kv_table()
    t.add_row("backend", f"[bold]{target}[/]  [muted]({source})[/]")
    t.add_row("HL_PYTHON", os.environ.get("HL_PYTHON") or "[muted]python3 (default)[/]")
    llm = os.environ.get("HL_LLM_BASE_URL")
    t.add_row("HL_LLM_BASE_URL", llm or "[muted]unset: offline reference LLM[/]")
    if llm:
        t.add_row("HL_LLM_MODEL", os.environ.get("HL_LLM_MODEL") or "[muted]unset[/]")
        t.add_row("HL_LLM_API_KEY", "[ok]set[/]" if os.environ.get("HL_LLM_API_KEY") else "[muted]unset[/]")
    flyte_cfg = Path.home() / ".flyte" / "config.yaml"
    t.add_row("flyte config", f"[path]{flyte_cfg}[/]" if flyte_cfg.exists() else "[muted]not found[/]")
    console.print(t)


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


if __name__ == "__main__":  # pragma: no cover
    main()
