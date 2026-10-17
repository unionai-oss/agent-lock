# Releasing harness-lock

harness-lock is installable under two names on each registry: `harness-lock` and the
short `hlock`. One tag publishes all of them:

| Registry | Package | What it is | Workflow |
|---|---|---|---|
| PyPI | `harness-lock` | the package: wheels for Linux x86_64/aarch64, macOS arm64/x86_64, Windows x64, plus an sdist | `publish-python.yml` |
| PyPI | `hlock` | pure-Python alias (`packaging/hlock`): pins `harness-lock==<same version>`, re-exports it as `import hlock` | `publish-python.yml` |
| crates.io | `harness-lock-core` | the Rust library | `publish-cargo.yml` |
| crates.io | `harness-lock` | re-exports `harness-lock-core` (`cargo add harness-lock`) | `publish-cargo.yml` |
| crates.io | `hlock` | re-exports `harness-lock-core` (`cargo add hlock`) | `publish-cargo.yml` |

PyPI uses trusted publishing (OIDC) under the unionai-oss PyPI account. crates.io uses a
`CARGO_REGISTRY_TOKEN` until the crates exist, then trusted publishing.

Why the aliases are thin rather than full copies: the PyPI wheel is compiled, and two
distributions shipping the same `harness_lock` module would overwrite each other when
both are installed. With the alias, `pip install hlock` and `pip install harness-lock`
install the identical package, and installing both is harmless. The same goes for the
crates: one implementation (`harness-lock-core`), two names that re-export it.

The PyO3 bindings crate (`crates/harness-lock-py`) is `publish = false`: it's a Python
extension module, not linkable from Rust, and ships only inside the PyPI wheel.

The version lives in one place, `[workspace.package].version` in `Cargo.toml`.
`scripts/set_version.py` keeps every other copy in step: maturin reads the workspace
version for `harness-lock` (`dynamic = ["version"]`), the `harness-lock` and `hlock` crates
pin `harness-lock-core = "=X.Y.Z"`, and `packaging/hlock/pyproject.toml` carries the
version and the `harness-lock==X.Y.Z` pin (PEP 440 spelling, e.g. `0.2.0rc1` for
`0.2.0-rc.1`).

## First-time setup

Needed once per repository, not once per release.

**GitHub**

- [ ] Make sure Actions runs for this repo (org Settings → Actions: enabled, allowed
      actions include `PyO3/maturin-action`, `pypa/gh-action-pypi-publish`,
      `dtolnay/rust-toolchain`, `Swatinem/rust-cache`).
- [ ] Create two environments (Settings → Environments): `pypi`, which publishes
      `harness-lock`, and `pypi-hlock`, which publishes `hlock`. Give them the same
      deployment tag rules and required reviewers, if you want a human gate before each
      publish.
- [ ] Create an environment named `crates-io` and add the `CARGO_REGISTRY_TOKEN`
      secret to it (below).

**PyPI**: log in at <https://pypi.org/manage/account/publishing/> **as the
unionai-oss PyPI account** (whoever registers the publisher becomes the project owner)
and add two **pending publishers**, one per package name (the projects don't exist until
the first upload). They differ in project name and environment; PyPI won't register two
pending publishers with identical owner/repository/workflow/environment:

| Field | `harness-lock` | `hlock` |
|---|---|---|
| PyPI project name | `harness-lock` | `hlock` |
| Owner | `unionai-oss` | `unionai-oss` |
| Repository name | `harness-lock` | `harness-lock` |
| Workflow name | `publish-python.yml` | `publish-python.yml` |
| Environment name | `pypi` | `pypi-hlock` |

No API token is stored anywhere. The publish jobs' `id-token: write` permission is
what authenticates.

**crates.io**: crates.io has no pending publishers, so the first publish needs a token.

- [ ] Log in to <https://crates.io> (ideally with a unionai-oss account) and verify the
      account email (publishing requires it).
- [ ] Create an API token with `publish-new` + `publish-update` scopes, restricted to the
      crate patterns `harness-lock*` and `hlock`, and save it as `CARGO_REGISTRY_TOKEN` in
      the `crates-io` environment.
- [ ] After the first release, for each of `harness-lock-core`, `harness-lock`, and
      `hlock`: add co-owners (`cargo owner --add github:unionai-oss:<team> <crate>`) and
      configure trusted publishing on crates.io. Then delete the token.

## Release checklist

1. [ ] Bump the version on a branch:
       ```bash
       python scripts/set_version.py 0.2.0
       python scripts/set_version.py --check   # prints 0.2.0
       ```
       Commit the changed files (`Cargo.toml`, `Cargo.lock`, `crates/*/Cargo.toml`,
       `packaging/hlock/pyproject.toml`), open a PR, and wait for `ci` to go green. Its
       `packaging` job builds the wheel, sdist, and `hlock` alias, runs `twine check`,
       installs `hlock` (which pulls in the matching `harness-lock`), and runs
       `cargo publish --workspace --dry-run` for all three crates.
2. [ ] Optional rehearsal: run **publish-python** and **publish-cargo** manually from
       `main` with `dry_run: true` (the default). They build and verify every artifact
       and stop before publishing.
3. [ ] Merge, then tag the merge commit and push the tag:
       ```bash
       git switch main && git pull
       git tag v0.2.0 && git push origin v0.2.0
       ```
       Both publish workflows refuse to run if the tag doesn't match the version.
4. [ ] Approve the `pypi` / `pypi-hlock` / `crates-io` environment deployments if reviewers are required.
5. [ ] Check the results:
       - <https://pypi.org/project/harness-lock/> lists the version with 5 wheels + sdist
       - <https://pypi.org/project/hlock/> lists the same version (1 wheel + sdist)
       - <https://crates.io/crates/harness-lock-core>, <https://crates.io/crates/harness-lock>,
         and <https://crates.io/crates/hlock> list the version; docs.rs builds
       - a GitHub release for the tag exists with the artifacts attached
6. [ ] Smoke-test from a clean environment:
       ```bash
       uvx --from harness-lock==0.2.0 hlock --version
       uvx --from hlock==0.2.0 hlock --version
       python -c "import hlock, harness_lock; print(hlock.__version__, harness_lock.__version__)"
       ```
       and in a scratch Rust project: `cargo add harness-lock hlock && cargo build`.

## If something goes wrong

- **Re-running the tag** is safe for PyPI (`skip-existing: true` skips files already
  uploaded, so a run that failed halfway finishes the rest). crates.io rejects a version
  that already exists, so re-running `cargo publish --workspace` fails at the first crate
  that already published. If a run stopped partway (say `harness-lock-core` published but
  `hlock` didn't), publish the rest by hand with the same token:
  `cargo publish --locked -p harness-lock -p hlock`.
- **A broken release can't be overwritten.** Neither registry accepts the same version
  twice (crates.io allows `cargo yank`, PyPI allows yanking a release). Fix forward with
  a patch release: `python scripts/set_version.py 0.2.1`.
- **Tag/version mismatch**: delete the tag (`git push --delete origin vX.Y.Z && git tag -d vX.Y.Z`),
  run `scripts/set_version.py`, merge, and re-tag.
