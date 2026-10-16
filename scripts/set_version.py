#!/usr/bin/env python3
"""Single place to read, check, and bump the release version.

The Cargo workspace (``[workspace.package].version`` in ``Cargo.toml``) is the source
of truth. Everything else follows it:

* every crate that depends on ``harness-lock-core`` pins it exactly (``=X.Y.Z``), so
  the published ``harness-lock`` and ``hlock`` crates always match the core release;
* the ``harness-lock`` Python package reads the version through maturin
  (``dynamic = ["version"]`` in ``pyproject.toml``);
* the ``hlock`` Python alias (``packaging/hlock``) carries the same version and pins
  ``harness-lock==X.Y.Z``.

Usage:
    python scripts/set_version.py --print           # print the current version
    python scripts/set_version.py --check [vX.Y.Z]  # fail unless every location agrees
                                                    # (and matches the tag, if given)
    python scripts/set_version.py X.Y.Z             # bump every location, refresh Cargo.lock
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT / "Cargo.toml"
PYPROJECT = ROOT / "pyproject.toml"
HLOCK_PYPROJECT = ROOT / "packaging" / "hlock" / "pyproject.toml"
CORE = "harness-lock-core"
# Crates that depend on the core crate (the PyO3 bindings and the two published facades).
DEPENDENTS = [ROOT / "crates" / name / "Cargo.toml" for name in ("harness-lock-py", "harness-lock", "hlock")]

SEMVER = re.compile(r"^(\d+\.\d+\.\d+)(?:-(alpha|a|beta|b|rc)\.?(\d+))?$")
PEP440_PRE = {"alpha": "a", "a": "a", "beta": "b", "b": "b", "rc": "rc"}

# `version = "…"` inside the [workspace.package] table only.
WORKSPACE_VERSION = re.compile(r'(\[workspace\.package\][^\[]*?^version\s*=\s*")([^"]+)(")', re.M | re.S)
# `harness-lock-core = { …, version = "=…" }` in a dependent crate.
CORE_DEP_VERSION = re.compile(rf'(^{CORE}\s*=\s*\{{[^}}]*?version\s*=\s*"=?)([^"]+)(")', re.M)
# `version = "…"` in the [project] table of the hlock pyproject.
PROJECT_VERSION = re.compile(r'(\[project\][^\[]*?^version\s*=\s*")([^"]+)(")', re.M | re.S)
# Every `harness-lock==…` / `harness-lock[extra]==…` pin in the hlock pyproject.
HARNESS_LOCK_PIN = re.compile(r'("harness-lock(?:\[[^\]]*\])?==)([^"]+)(")')


def pep440(version: str) -> str:
    """Cargo semver -> PEP 440 (0.2.0-rc.1 -> 0.2.0rc1)."""
    match = SEMVER.match(version)
    if not match:
        sys.exit(f"error: {version!r} is not a supported version (X.Y.Z or X.Y.Z-rc.N / -beta.N / -alpha.N)")
    release, pre, number = match.groups()
    return f"{release}{PEP440_PRE[pre]}{number}" if pre else release


def current() -> str:
    return tomllib.loads(WORKSPACE.read_text())["workspace"]["package"]["version"]


def check(tag: str | None) -> int:
    version = current()
    errors = []

    for path in DEPENDENTS:
        dep = tomllib.loads(path.read_text())["dependencies"][CORE]
        if dep.get("version") != f"={version}":
            errors.append(f"{path.relative_to(ROOT)}: {CORE} version {dep.get('version')!r} != '={version}'")

    project = tomllib.loads(PYPROJECT.read_text())["project"]
    if "version" not in project.get("dynamic", []):
        errors.append(f'pyproject.toml: expected dynamic = ["version"], found static {project.get("version")!r}')

    py_version = pep440(version)
    hlock_text = HLOCK_PYPROJECT.read_text()
    hlock = tomllib.loads(hlock_text)["project"]
    if hlock["version"] != py_version:
        errors.append(f"packaging/hlock/pyproject.toml: version {hlock['version']!r} != {py_version!r}")
    pins = HARNESS_LOCK_PIN.findall(hlock_text)
    if not pins:
        errors.append("packaging/hlock/pyproject.toml: no harness-lock==… pin found")
    for _, pinned, _ in pins:
        if pinned != py_version:
            errors.append(f"packaging/hlock/pyproject.toml: harness-lock pin {pinned!r} != {py_version!r}")

    if tag is not None and tag.removeprefix("v") != version:
        errors.append(f"tag {tag!r} does not match version {version!r}; run scripts/set_version.py {tag.removeprefix('v')} and re-tag")

    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    if not errors:
        print(version)
    return 1 if errors else 0


def substitute(path: Path, pattern: re.Pattern[str], value: str, *, every: bool = False) -> None:
    """Replace the first match (or every match) of `pattern`'s middle group with `value`."""
    text, n = pattern.subn(rf"\g<1>{value}\g<3>", path.read_text(), count=0 if every else 1)
    if n == 0:
        sys.exit(f"error: could not find the version field to update in {path.relative_to(ROOT)}")
    path.write_text(text)


def bump(version: str) -> int:
    py_version = pep440(version)  # validates the format
    substitute(WORKSPACE, WORKSPACE_VERSION, version)
    for path in DEPENDENTS:
        substitute(path, CORE_DEP_VERSION, version)
    substitute(HLOCK_PYPROJECT, PROJECT_VERSION, py_version)
    substitute(HLOCK_PYPROJECT, HARNESS_LOCK_PIN, py_version, every=True)
    # Refresh the workspace members' entries in Cargo.lock without touching other deps.
    subprocess.run(["cargo", "update", "--workspace", "--offline"], cwd=ROOT, check=False)
    return check(None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("version", nargs="?", help="new version to write, e.g. 0.2.0")
    group.add_argument("--print", action="store_true", help="print the current version")
    group.add_argument("--check", nargs="?", const="", metavar="TAG", help="verify all versions agree (and match TAG)")
    args = parser.parse_args()

    if args.print:
        print(current())
        return 0
    if args.check is not None:
        return check(args.check or None)
    return bump(args.version)


if __name__ == "__main__":
    sys.exit(main())
