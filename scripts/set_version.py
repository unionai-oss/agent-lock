#!/usr/bin/env python3
"""Single place to read, check, and bump the release version.

The Cargo workspace (``[workspace.package].version`` in ``Cargo.toml``) is the source
of truth. The Python package reads it through maturin (``dynamic = ["version"]`` in
``pyproject.toml``), and the bindings crate pins ``harness-lock-core`` to the same
version so ``cargo publish`` resolves the matching release.

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
BINDINGS = ROOT / "crates" / "harness-lock" / "Cargo.toml"
PYPROJECT = ROOT / "pyproject.toml"
CORE = "harness-lock-core"

SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
# `version = "…"` inside the [workspace.package] table only.
WORKSPACE_VERSION = re.compile(r'(\[workspace\.package\][^\[]*?^version\s*=\s*")([^"]+)(")', re.M | re.S)
# `harness-lock-core = { …, version = "…" }` in the bindings crate.
CORE_DEP_VERSION = re.compile(rf'(^{CORE}\s*=\s*\{{[^}}]*?version\s*=\s*")([^"]+)(")', re.M)


def read_versions() -> dict[str, str | None]:
    workspace = tomllib.loads(WORKSPACE.read_text())
    bindings = tomllib.loads(BINDINGS.read_text())
    pyproject = tomllib.loads(PYPROJECT.read_text())
    return {
        "Cargo.toml [workspace.package].version": workspace["workspace"]["package"]["version"],
        f"crates/harness-lock/Cargo.toml {CORE} dependency": bindings["dependencies"][CORE].get("version"),
        "pyproject.toml": "dynamic" if "version" in pyproject["project"].get("dynamic", []) else pyproject["project"].get("version"),
    }


def current() -> str:
    return read_versions()["Cargo.toml [workspace.package].version"]


def check(tag: str | None) -> int:
    versions = read_versions()
    version = current()
    errors = []
    for where, value in versions.items():
        if where.startswith("pyproject"):
            if value != "dynamic":
                errors.append(f'{where}: expected dynamic = ["version"], found static {value!r}')
        elif value != version:
            errors.append(f"{where}: {value!r} != {version!r}")
    if tag is not None and tag.removeprefix("v") != version:
        errors.append(f"tag {tag!r} does not match version {version!r}; run scripts/set_version.py {tag.removeprefix('v')} and re-tag")
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    if not errors:
        print(version)
    return 1 if errors else 0


def substitute(path: Path, pattern: re.Pattern[str], version: str) -> None:
    text, count = pattern.subn(rf"\g<1>{version}\g<3>", path.read_text(), count=1)
    if count != 1:
        sys.exit(f"error: could not find the version field to update in {path.relative_to(ROOT)}")
    path.write_text(text)


def bump(version: str) -> int:
    if not SEMVER.match(version):
        sys.exit(f"error: {version!r} is not a semver version (X.Y.Z)")
    substitute(WORKSPACE, WORKSPACE_VERSION, version)
    substitute(BINDINGS, CORE_DEP_VERSION, version)
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
