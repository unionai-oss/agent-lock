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

from harness_lock import (
    LOCK_VERSION,
    Lockfile,
    Manifest,
    __version__,
    harness_profile,
    harnesses,
    load,
    runtimes,
    sync_dockerfile,
    sync_plan,
    sync_run_step,
    sync_skill,
)
from harness_lock import check_pin as _check_pin
from harness_lock import optimize as al_optimize
from harness_lock import pin as _pin
from harness_lock import resolve as _resolve
from harness_lock import select_harness as _select_harness
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
        {"name": "Lock", "commands": ["init", "resolve", "pin", "check"]},
        {"name": "Rehydrate", "commands": ["sync"]},
        {"name": "Harness", "commands": ["harness", "runtime"]},
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
    if "unknown harness" in message:
        return "list the known harnesses with [cmd]hlock harness list[/]"
    if "several harnesses are installed" in message or "no supported harness" in message:
        return f"pass [cmd]--harness <name>[/] or set [key]\\[target] harness[/] in [path]{MANIFEST}[/]"
    if "resolved lock with evidence" in message:
        return "use [cmd]hlock pin -o pinned.lock[/] to keep both"
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
    version = f" [muted]{lf.harness_version}[/]" if lf.harness_version else ""
    stack.add_row("harness", f"[bold]{lf.harness}[/]{version}")
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


def _count_by(items, key) -> str:
    counts: dict[str, int] = {}
    for it in items:
        counts[it.get(key) or "?"] = counts.get(it.get(key) or "?", 0) + 1
    return ", ".join(f"{n} {k}" for k, n in sorted(counts.items(), key=lambda kv: -kv[1]))


def _pin_panel(lock: dict, title: str = LOCK) -> Panel:
    """The summary panel for a pinned lock (no evidence; components instead)."""
    h = lock.get("harness") or {}
    t = _kv_table()
    t.add_row("harness", f"[bold]{h.get('name')}[/] {h.get('version') or ''}  [muted]{h.get('source') or ''}[/]")
    for llm in lock.get("llm") or []:
        where = f"  [muted]via {llm['runtime']}[/]" if llm.get("runtime") else (
            f"  [muted]{llm['endpoint']}[/]" if llm.get("endpoint") else "")
        t.add_row(f"llm · {llm['role']}", f"[bold]{llm['provider']}:{llm['model']}[/]{where}")
    for rt in lock.get("runtime") or []:
        models = rt.get("model") or []
        present = sum(1 for m in models if m.get("present"))
        loc = "local" if rt.get("location") == "local" else "network"
        detail = f"{len(models)} model{'s' if len(models) != 1 else ''}" + (f", {present} on disk" if loc == "local" else "")
        t.add_row("runtime", f"[bold]{rt['name']}[/] {rt.get('version') or ''}  [muted]({loc}, {detail})[/]")
    tools = lock.get("tool") or []
    if tools:
        t.add_row("mcp", ", ".join(f"{x['name']} [muted]({x.get('transport', '?')})[/]" for x in tools))
    skills = lock.get("skill") or []
    if skills:
        t.add_row("skills", f"{len(skills)}  [muted]({_count_by(skills, 'origin')})[/]")
    natives = lock.get("native") or []
    if natives:
        kinds = _count_by([{"k": n["kind"].split(".")[-1]} for n in natives], "k")
        t.add_row("plugins", f"{len(natives)}  [muted]({kinds})[/]")
    ins = lock.get("instructions") or []
    if ins:
        t.add_row("instructions", ", ".join(i["name"] for i in ins))
    cfg = lock.get("config") or []
    if cfg:
        t.add_row("config", ", ".join(c["path"] + (f" [muted]{','.join(c['pointers'])}[/]" if c.get("pointers") else "")
                                      for c in cfg))
    secrets = lock.get("secret") or []
    if secrets:
        t.add_row("secrets", f"{len(secrets)} redacted  [muted](supplied as HLOCK_SECRET_* when syncing)[/]")
    return Panel(t, title=f"[brand]📌 {title} · pinned[/]", title_align="left", border_style="magenta",
                 expand=False, padding=(1, 2))


def _print_lock(lf, title: str = LOCK) -> None:
    if lf.kind == "pin":
        console.print(_pin_panel(json.loads(lf.to_json()), title))
    else:
        console.print(_lock_panel(lf, title))


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, "-V", "--version", prog_name="hlock")
def main() -> None:
    """[brand]hlock[/] · make your agent harness setup pinnable, portable, and tunable.

    Tune your agent stack against your own tasks, then pin the winner in a
    [path]harness.lock[/].

    Get started: [cmd]hlock init[/] → [cmd]hlock resolve[/] → [cmd]hlock check[/]
    """


@main.command()
@click.option("--name", default="demo", show_default=True, help="Project name for the manifest.")
@click.option("--pack", default="./tasks", show_default=True, help="Path to a task pack directory.")
@click.option("--harness", "harness", default=None,
              help="Target harness for \\[target]. [dim]\\[default: the one you're running in, if any][/]")
@click.option("--force", is_flag=True, help="Overwrite an existing harness.toml.")
def init(name: str, pack: str, harness: str | None, force: bool) -> None:
    """Write a starter [path]harness.toml[/] manifest."""
    p = Path(MANIFEST)
    if p.exists() and not force:
        _fail(f"{MANIFEST} already exists", "pass [cmd]--force[/] to overwrite it")
    target = None
    if harness:
        with _friendly_errors():
            target = json.loads(_select_harness(harness))
    else:
        # Only an unambiguous signal (running inside a harness) picks one silently.
        try:
            sel = json.loads(_select_harness())
            target = sel if sel["reason"] == "running inside it" else None
        except ValueError:
            target = None
    p.write_text(_default_manifest(name, pack, target["id"] if target else None))
    _ok(f"wrote [path]{p}[/]  [muted](project {name!r}, task pack {pack})[/]")
    if target:
        console.print(f"[key]target[/] [bold]{target['id']}[/]  [muted]({target['reason']})[/]")
    if not (Path(pack) / "pack.toml").exists():
        console.print(f"[warn]![/] no [path]pack.toml[/] found in [path]{pack}[/]; add one before resolving")
    _next("hlock resolve")


@main.command()
@click.option("--backend", default=None, type=click.Choice(["local", "devbox", "cluster"]),
              help="Override the manifest's \\[backend] target.")
@click.option("--harness", "harness", default=None,
              help="Target harness, overriding \\[target] harness (e.g. claude, codex, pi, opencode).")
@click.option("--workdir", default=None, help="Where to put trial artifacts.  [dim]\\[default: .harnesslock][/]")
def resolve(backend: str | None, harness: str | None, workdir: str | None) -> None:
    """Tune the search space and write [path]harness.lock[/]."""
    with _working(f"Resolving {MANIFEST} on the {backend or 'configured'} backend…"):
        lf = _resolve(MANIFEST, backend=backend, workdir=workdir or ".harnesslock", harness=harness)
    _ok(f"wrote [path]{LOCK}[/]")
    console.print(_lock_panel(lf))
    lock = json.loads(lf.to_json())
    adapter = (lock.get("harness") or {}).get("adapter")
    if adapter and adapter != lf.harness:
        console.print(
            f"[warn]![/] trials ran on the [bold]{adapter}[/] adapter; native {lf.harness} execution "
            "isn't built yet, so the evidence is a stand-in"
        )
    if harness:
        with _friendly_errors():
            m = Manifest.load(MANIFEST)
        if m.target_harness is None or json.loads(_select_harness(m.target_harness))["id"] != lf.harness:
            console.print(
                f"[warn]![/] --harness isn't recorded in [path]{MANIFEST}[/]; add "
                f'[key]\\[target] harness = "{lf.harness}"[/] so [cmd]hlock check[/] can enforce it'
            )
    _next("hlock check", 'hlock run "<prompt>"')


@main.command()
@click.option("--harness", "harness", default=None,
              help="Harness to pin. [dim]\\[default: \\[target], else the one you're running in][/]")
@click.option("-o", "--out", default=LOCK, show_default=True, help="Where to write the pinned lock.")
@click.option("--no-vendor", is_flag=True, help="Don't copy unfetchable skills and config into .hlock/vendor.")
@click.option("--force", is_flag=True, help="Replace a resolved lock (one with evidence).")
@click.option("--json", "as_json", is_flag=True, help="Print the result as JSON.")
def pin(harness: str | None, out: str, no_vendor: bool, force: bool, as_json: bool) -> None:
    """Pin your current harness setup into [path]harness.lock[/].

    Captures the harness version and install source, the default and small models,
    local inference runtimes and their models, MCP servers, skills, plugins,
    instruction files, and config. Secrets are replaced with
    [key]HLOCK_SECRET_*[/] placeholders; content another machine can't fetch is
    vendored into [path].hlock/vendor/[/]. No [path]harness.toml[/] needed.
    """
    with _working("Pinning your harness setup…"):
        result = json.loads(_pin(harness=harness, out=out, vendor=not no_vendor, force=force))
    if as_json:
        console.print_json(data=result)
        return
    lock, sel = result["lock"], result["selection"]
    h = lock["harness"]
    _ok(f"pinned [bold]{h['name']}[/] {h.get('version') or ''} → [path]{out}[/]  [muted]({sel['reason']})[/]")
    for w in result["warnings"]:
        console.print(f"[warn]![/] {w}")
    console.print(_pin_panel(lock, out))
    if result["vendored"]:
        console.print(f"[muted]vendored {len(result['vendored'])} files into[/] [path].hlock/vendor/{h['name']}/[/]  "
                      "[muted]· review before committing[/]")
    if result["previous"]:
        if result["diff"]:
            console.print("[bold]changes since the last pin[/]")
            for line in result["diff"]:
                style = {"+": "ok", "-": "fail", "~": "warn"}.get(line[:1], "muted")
                console.print(f"  [{style}]{line}[/]")
        else:
            console.print("[muted]no changes since the last pin[/]")
    _next("hlock check", "hlock sync")


_STATUS = {"satisfied": "[ok]✓[/]", "auto": "[brand]●[/]", "manual": "[warn]○[/]"}
MANUAL_EXIT = 3


def _plan_table(plan: dict, verbose: bool = False) -> Table:
    t = Table(box=None, show_header=False, pad_edge=False)
    t.add_column(no_wrap=True)
    t.add_column(style="key", no_wrap=True)
    t.add_column(overflow="fold")
    by_kind: dict[tuple[str, str], list[dict]] = {}
    for st in plan["steps"]:
        if st.get("optional") and st["status"] != "satisfied" and not verbose:
            continue
        by_kind.setdefault((st["kind"], st["status"]), []).append(st)
    order = {"satisfied": 0, "auto": 1, "manual": 2}
    for (kind, status), steps in sorted(by_kind.items(), key=lambda kv: order[kv[0][1]]):
        if len(steps) > 6 and not verbose:
            verb = {"satisfied": "match the lock", "auto": "to restore", "manual": "need you"}[status]
            t.add_row(_STATUS[status], kind, f"{len(steps)} {kind}s {verb}")
            continue
        for st in steps:
            detail = st["title"]
            if st["status"] != "satisfied" and st.get("reason"):
                detail += f"  [muted]{st['reason']}[/]"
            t.add_row(_STATUS[st["status"]], kind, detail)
    return t


def _rel(path: str) -> str:
    """A path relative to the working directory when it's inside it."""
    try:
        return str(Path(path).resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return path


def _manual_steps(plan: dict) -> list[dict]:
    return [st for st in plan["steps"] if st["status"] == "manual" and not st.get("optional")]


@main.command()
@click.argument("lock", default=LOCK, required=False)
@click.option("--plan", "plan_only", is_flag=True, help="Print the plan and change nothing.")
@click.option("--json", "as_json", is_flag=True, help="Print the plan as JSON and change nothing.")
@click.option("-y", "--yes", is_flag=True, help="Don't ask before running automatic steps.")
@click.option("--install", is_flag=True, help="Let hlock run package managers (npm, brew, uv, install scripts).")
@click.option("--pull", is_flag=True, help="Let hlock download model weights through installed runtimes.")
@click.option("--all-models", is_flag=True, help="Include models a provider lists but no locked role uses.")
@click.option("--prefix", default=None, help="Materialize into an isolated config root under DIR, not your real one.")
@click.option("--docker", "docker", is_flag=True, help="Write a Docker build context and Dockerfile to .hlock/docker/<harness>.")
@click.option("--build", is_flag=True, help="With --docker: also run docker build.")
@click.option("--skill", "skill", is_flag=True, help="Write an Agent Skill that guides an agent through the remaining steps.")
@click.option("--skill-dir", default=".agents/skills/hlock-rehydrate", show_default=True, help="Where --skill writes SKILL.md.")
@click.option("--exact", is_flag=True, help="Also remove skills that aren't in the lock (moved aside, not deleted).")
@click.option("-v", "--verbose", is_flag=True, help="List every step, including optional ones.")
def sync(lock: str, plan_only: bool, as_json: bool, yes: bool, install: bool, pull: bool, all_models: bool,
         prefix: str | None, docker: bool, build: bool, skill: bool, skill_dir: str, exact: bool, verbose: bool) -> None:
    """Rehydrate the setup in [path]harness.lock[/] on this machine.

    Builds a plan in which each step is [ok]✓ satisfied[/], [brand]● automatic[/] (hlock does it), or
    [warn]○ manual[/] (hlock prints what to run and why). Automatic steps restore config, skills
    and instruction files and install plugins through the harness's own CLI. Package
    installs need [cmd]--install[/] and model downloads need [cmd]--pull[/]. Exits 3 while manual
    steps remain, so it's safe to re-run until it's clean.
    """
    docker_dir = None
    if docker:
        with _friendly_errors():
            harness_id = Lockfile.load(lock).harness
        docker_dir = str(Path(".hlock/docker") / harness_id)
    with _working("Planning…"):
        plan = json.loads(sync_plan(lock, prefix=prefix, docker=docker_dir, install=install, pull=pull,
                                    all_models=all_models, exact=exact))
    if as_json:
        console.print_json(data=plan)
        return
    where = {"home": "your config", "prefix": f"[path]{_rel(plan['root'])}[/]",
             "docker": f"[path]{docker_dir}[/]"}[plan["mode"]]
    console.print(f"[bold]Sync plan[/] for {plan['harness_name']} {plan.get('version') or ''} → {where}")
    console.print(_plan_table(plan, verbose))

    if skill:
        path = Path(skill_dir) / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(sync_skill(json.dumps(plan), lock))
        _ok(f"wrote [path]{path}[/]")
        console.print("[muted]open your agent here and ask it to rehydrate the harness with the hlock-rehydrate skill[/]")
        return
    if plan_only:
        return

    auto = [st for st in plan["steps"] if st["status"] == "auto"]
    if docker:
        auto = [st for st in auto if st["kind"] in ("config", "skill", "instructions")]
    if auto and not yes and not docker:
        if not sys.stdin.isatty():
            _fail(f"{len(auto)} automatic steps to run", "pass [cmd]--yes[/] to run them, or [cmd]--plan[/] to just look")
        if not click.confirm(f"Run {len(auto)} automatic step{'s' if len(auto) != 1 else ''}?", default=True):
            sys.exit(1)
    failed = 0
    groups: dict[str, list[dict]] = {}
    for st in auto:
        groups.setdefault(st["kind"], []).append(st)
    for kind, steps in groups.items():
        quiet = len(steps) > 6
        done = 0
        for st in steps:
            with console.status(f"[brand]{st['title']}…[/]", spinner="dots"):
                try:
                    msg = sync_run_step(json.dumps(st))
                except ValueError as e:
                    failed += 1
                    err_console.print(f"[fail]✗[/] {st['title']}\n  [muted]{e}[/]")
                    continue
            done += 1
            if not quiet:
                notes = []
                if "previous:" in msg:
                    notes.append("kept the old file as .hlock-bak")
                if "placeholders left" in msg:
                    notes.append("placeholders for missing secrets")
                if st["kind"] in ("plugin", "harness", "runtime", "model", "package"):
                    notes.append(msg)
                console.print(f"[ok]✓[/] {st['title']}" + (f"  [muted]{'; '.join(notes)}[/]" if notes else ""))
        if quiet and done:
            console.print(f"[ok]✓[/] restored {done} {kind}s")

    if docker:
        files = json.loads(sync_dockerfile(json.dumps(plan), lock))
        ctx = Path(docker_dir)
        (ctx / "home").mkdir(parents=True, exist_ok=True)
        (ctx / "Dockerfile").write_text(files["dockerfile"])
        entry = ctx / "hlock-entrypoint"
        entry.write_text(files["entrypoint"])
        entry.chmod(0o755)
        _ok(f"wrote [path]{ctx / 'Dockerfile'}[/]")
        tag = f"hlock-{plan['harness']}"
        secrets = " ".join(f"-e {st['id'].split(':', 1)[1]}" for st in plan["steps"] if st["kind"] == "secret")
        if build:
            import subprocess

            console.print(f"[brand]docker build -t {tag} {ctx}[/]")
            if subprocess.run(["docker", "build", "-t", tag, str(ctx)], check=False).returncode != 0:
                _fail("docker build failed")
            _ok(f"built [bold]{tag}[/]")
        console.print("[muted]next →[/]")
        if not build:
            console.print(f"  [cmd]docker build -t {tag} {ctx}[/]", soft_wrap=True)
        run_cmd = f"docker run -it --rm {secrets + ' ' if secrets else ''}-v \"$PWD:/workspace\" {tag}"
        console.print(f"  [cmd]{run_cmd}[/]", soft_wrap=True)
        sys.exit(1 if failed else 0)

    remaining = _manual_steps(plan)
    if remaining:
        secrets = [st for st in remaining if st["kind"] == "secret"]
        others = [st for st in remaining if st["kind"] != "secret"]
        console.print(f"\n[warn]{len(remaining)} step{'s need' if len(remaining) != 1 else ' needs'} you:[/]")
        for i, st in enumerate(others, 1):
            console.print(f"  {i}. {st['title']}" + (f"  [muted]{st['reason']}[/]" if st.get("reason") else ""))
            if st.get("command"):
                console.print(f"     [cmd]{st['command']}[/]")
        if secrets:
            n = len(others) + 1
            console.print(f"  {n}. Set {len(secrets)} secret{'s' if len(secrets) != 1 else ''}, then re-run "
                          "[cmd]hlock sync[/] [muted](values stay out of the lock)[/]")
            for st in secrets:
                name, _, used = st["title"].partition(" (")
                console.print(f"     [cmd]export {name}=…[/]  [muted]# {used.rstrip(')')}[/]")
        hints = []
        if any("--install" in (st.get("reason") or "") for st in remaining):
            hints.append("hlock sync --install")
        if any("--pull" in (st.get("reason") or "") for st in remaining):
            hints.append("hlock sync --pull")
        hints.append("hlock sync --skill [muted](let your agent do it)[/]")
        _next(*hints)
    if failed:
        sys.exit(1)
    if remaining:
        sys.exit(MANUAL_EXIT)
    if plan["mode"] == "prefix":
        env = " ".join(f"{k}={_rel(v)}" for k, v in plan["isolation"].items())
        _ok(f"in sync at [path]{_rel(plan['root'])}[/]")
        console.print(f"[muted]use it:[/] [cmd]{env} {plan.get('binary') or plan['harness']}[/]", soft_wrap=True)
    else:
        _ok(f"in sync with [path]{lock}[/]")


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Print the lockfile as JSON.")
def show(as_json: bool) -> None:
    """Show the locked stack and the evidence behind it."""
    with _friendly_errors():
        lf = Lockfile.load(LOCK)
    if as_json:
        console.print_json(lf.to_json())
        return
    _print_lock(lf)


@main.command()
def check() -> None:
    """Fail if [path]harness.toml[/] has drifted from [path]harness.lock[/] (CI-friendly).

    For a pinned lock, re-capture the harness and fail if the setup changed.
    """
    with _friendly_errors():
        lf = Lockfile.load(LOCK)
    if lf.kind == "pin":
        with _working(f"Re-capturing {lf.harness}…"):
            drift = json.loads(_check_pin(LOCK))
        if drift:
            err_console.print(f"[fail]✗ drift:[/] your {lf.harness} setup changed since {LOCK} was pinned")
            for line in drift:
                err_console.print(f"  {line}")
            err_console.print("  [muted]hint:[/] re-pin with [cmd]hlock pin[/], or restore it with [cmd]hlock sync[/]")
            sys.exit(1)
        _ok(f"your {lf.harness} setup matches [path]{LOCK}[/]")
        return
    with _friendly_errors():
        m = Manifest.load(MANIFEST)
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
    if m.target_harness:
        with _friendly_errors():
            want = json.loads(_select_harness(m.target_harness))["id"]
        if want != lf.harness:
            _fail(f"{LOCK} is for harness {lf.harness!r} but {MANIFEST} targets {want!r}",
                  "re-lock with [cmd]hlock resolve[/]")
    if lf.harness_version:
        probe = json.loads(harness_profile(lf.harness))["probe"] if _known_harness(lf.harness) else None
        if probe and probe["installed"] and probe.get("version") and probe["version"] != lf.harness_version:
            _fail(f"installed {lf.harness} is {probe['version']}, {LOCK} pins {lf.harness_version}",
                  f"install {lf.harness} {lf.harness_version}, or re-lock with [cmd]hlock resolve[/]")
    _ok(f"[path]{LOCK}[/] matches [path]{MANIFEST}[/]  [muted]{live.split(':', 1)[-1][:12]}[/]")


@main.command()
def tree() -> None:
    """Print the locked component dependency graph."""
    with _friendly_errors():
        lf = Lockfile.load(LOCK)
    if lf.kind == "pin":
        console.print(_pin_tree(json.loads(lf.to_json())))
        return
    root = Tree(f"[brand]🔒 {LOCK}[/]", guide_style="magenta")
    stack = root.add(f"[bold]stack[/] [muted]harness={lf.harness}[/]")
    llms = stack.add("[key]llm[/]")
    for role, spec in json.loads(lf.llm):
        llms.add(f"{role}  [bold]{spec}[/]")
    stack.add(f"[key]decision[/]  {lf.decision}")
    stack.add(f"[key]harness[/]  [bold]{lf.harness}[/]")
    root.add(f"[key]provenance[/]  backend={lf.provenance}")
    console.print(root)


def _pin_tree(lock: dict) -> Tree:
    h = lock.get("harness") or {}
    root = Tree(f"[brand]📌 {LOCK}[/] [muted]pinned[/]", guide_style="magenta")
    hn = root.add(f"[bold]{h.get('name')}[/] {h.get('version') or ''}  [muted]{h.get('source') or ''}[/]")
    if lock.get("llm"):
        node = hn.add("[key]llm[/]")
        for llm in lock["llm"]:
            node.add(f"{llm['role']}  [bold]{llm['provider']}:{llm['model']}[/]")
    for rt in lock.get("runtime") or []:
        node = root.add(f"[key]runtime[/] [bold]{rt['name']}[/] {rt.get('version') or ''} [muted]({rt.get('location')})[/]")
        for m in rt.get("model") or []:
            mark = "" if rt.get("location") != "local" else ("  [ok]on disk[/]" if m.get("present") else "  [warn]missing[/]")
            node.add(f"{m['id']}  [muted]{m.get('source') or ''}[/]{mark}")
    if lock.get("tool"):
        node = hn.add("[key]mcp[/]")
        for x in lock["tool"]:
            node.add(f"{x['name']}  [muted]{x.get('transport', '')} {x.get('source') or x.get('url') or x.get('command') or ''}[/]")
    if lock.get("skill"):
        node = hn.add(f"[key]skills[/] [muted]({len(lock['skill'])})[/]")
        for sk in lock["skill"]:
            node.add(f"{sk['name']}  [muted]{sk.get('origin')}[/]")
    if lock.get("native"):
        node = hn.add("[key]plugins[/]")
        for n in lock["native"]:
            off = "" if n.get("enabled", True) else "  [muted](disabled)[/]"
            node.add(f"{n['name']} {n.get('version') or ''}  [muted]{n['kind']}[/]{off}")
    return root


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


def _known_harness(name: str) -> bool:
    try:
        _select_harness(name)
        return True
    except ValueError:
        return False


def _support_badge(support: str) -> str:
    return "[ok]full[/]" if support == "full" else "[muted]basic[/]"


@main.group()
def harness() -> None:
    """Inspect the agent harnesses hlock knows about (Claude Code, Codex, Pi, …)."""


@harness.command("list")
@click.option("--json", "as_json", is_flag=True, help="Print the list as JSON.")
def harness_list(as_json: bool) -> None:
    """List known harnesses and what's installed on this machine.

    [bold]cli[/] harnesses are agent CLIs, [bold]framework[/] harnesses are agent libraries a
    project builds on, and [bold]custom[/] harnesses come from [key]\\[harnesses.<id>][/] in
    [path]harness.toml[/].
    """
    with _working("Probing installed harnesses…"):
        rows = json.loads(harnesses())
    if as_json:
        console.print_json(data=rows)
        return
    for kind, title in (("cli", "Agent CLIs"), ("framework", "Frameworks"), ("custom", f"Project harnesses ({MANIFEST})")):
        group = [r for r in rows if r["kind"] == kind]
        if not group:
            continue
        t = Table(box=None, header_style="bold", pad_edge=False, title=title, title_justify="left",
                  title_style="bold")
        t.add_column("")
        t.add_column("harness", style="key", no_wrap=True)
        t.add_column("installed", no_wrap=True)
        t.add_column("source", style="muted", overflow="fold")
        if kind == "cli":
            t.add_column("support")
        for r in group:
            p = r["probe"]
            installed = f"[bold]{p.get('version') or 'yes'}[/]" if p["installed"] else "[muted]—[/]"
            cells = ["[ok]●[/]" if p["active"] else "", r["id"], installed, p.get("source") or ""]
            if kind == "cli":
                cells.append(_support_badge(r["support"]))
            t.add_row(*cells)
        console.print(t)
        console.print()
    active = next((r for r in rows if r["probe"]["active"]), None)
    if active:
        console.print(f"[ok]●[/] [muted]you're running inside {active['name']}[/]")
    _next("hlock harness show <name>")


@harness.command("show")
@click.argument("name", required=False)
@click.option("--json", "as_json", is_flag=True, help="Print the profile as JSON.")
def harness_show(name: str | None, as_json: bool) -> None:
    """Show a harness profile and the paths it reads on this machine.

    NAME defaults to the target harness (see [cmd]hlock harness list[/]).
    """
    with _friendly_errors():
        if name is None:
            name = json.loads(_select_harness(None, _manifest_target()))["id"]
        info = json.loads(harness_profile(name))
    if as_json:
        console.print_json(data=info)
        return
    prof, probe, paths = info["profile"], info["probe"], info["paths"]
    t = _kv_table()
    t.add_row("id", f"[bold]{prof['id']}[/]  [muted]{', '.join(prof['aliases'])}[/]")
    t.add_row("kind", prof["kind"] + (f"  [muted](framework {prof['framework']})[/]" if prof.get("framework") else ""))
    if prof["kind"] == "cli":
        t.add_row("support", _support_badge(prof["support"]))
    run = prof.get("run") or {}
    if run.get("entrypoint"):
        t.add_row("entrypoint", f"[bold]{run['entrypoint']}[/]")
    if run.get("command"):
        t.add_row("command", " ".join(run["command"]))
    for pkg in prof.get("packages") or []:
        have = (probe.get("packages") or {}).get(pkg)
        t.add_row("package", f"{pkg}  " + (f"[bold]{have}[/]" if have else "[muted]not installed[/]"))
    if prof["kind"] == "cli":
        if probe["installed"]:
            t.add_row("installed", f"[bold]{probe.get('version') or '?'}[/]  [muted]{probe.get('binary')}[/]")
            t.add_row("source", probe.get("source") or "[muted]unknown install method[/]")
        else:
            t.add_row("installed", "[muted]no[/]")
        root_env = info.get("isolation_env")
        relocate = f"  [muted](${root_env})[/]" if root_env else ""
        t.add_row("config root", f"[path]{paths['config_root']}[/]{relocate}")
    for fid, f in paths["files"].items():
        mark = "" if f["exists"] else "  [muted](missing)[/]"
        t.add_row(f"file · {fid}", f"{f['path']}{mark}")
    for d in paths["skills"]:
        mark = "" if d["exists"] else "  [muted](missing)[/]"
        t.add_row("skills", f"{d['path']}{mark}")
    t.add_row("profile", "[muted]built in[/]" if prof["origin"] == "builtin" else f"[path]{prof['origin']}[/]")
    console.print(Panel(t, title=f"[brand]{prof['name']}[/]", title_align="left", border_style="magenta",
                        expand=False, padding=(1, 2)))


@main.group()
def runtime() -> None:
    """Inspect local inference runtimes (Ollama, LM Studio, vLLM, …)."""


@runtime.command("list")
@click.option("--json", "as_json", is_flag=True, help="Print the list as JSON.")
def runtime_list(as_json: bool) -> None:
    """List known inference runtimes and what's installed on this machine."""
    with _working("Probing inference runtimes…"):
        rows = json.loads(runtimes())
    if as_json:
        console.print_json(data=rows)
        return
    t = Table(box=None, header_style="bold", pad_edge=False)
    t.add_column("runtime", style="key")
    t.add_column("installed")
    t.add_column("port", style="muted")
    t.add_column("models dir", style="muted")
    for r in rows:
        p = r["probe"]
        installed = f"[bold]{p.get('version') or 'yes'}[/]" if p["installed"] else "[muted]—[/]"
        t.add_row(r["id"], installed, ", ".join(str(x) for x in r["ports"]), r.get("models_dir") or "")
    console.print(t)


def _manifest_target() -> str | None:
    try:
        return Manifest.load(MANIFEST).target_harness
    except ValueError:
        return None


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


def _default_manifest(name: str, pack: str, target: str | None = None) -> str:
    target_block = (
        f'[target]\nharness = "{target}"            # the harness this lock is for\n'
        if target
        else '# [target]\n# harness = "claude-code"      # the harness this lock is for (see: hlock harness list)\n'
    )
    return f"""# hlock manifest — declare what the resolver may try and what 'best' means.
[project]
name = "{name}"

{target_block}
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
