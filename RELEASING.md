# Releasing harness-lock

One tag publishes two things:

| Registry | Package | Workflow | Auth |
|---|---|---|---|
| PyPI | `harness-lock` (wheels for Linux x86_64/aarch64, macOS arm64/x86_64, Windows x64 + sdist) | `.github/workflows/publish-python.yml` | trusted publishing (OIDC), owned by the unionai-oss PyPI account |
| crates.io | `harness-lock-core` | `.github/workflows/publish-cargo.yml` | `CARGO_REGISTRY_TOKEN` until the crate exists, then trusted publishing |

The PyO3 bindings crate (`crates/harness-lock`) is `publish = false`: it's a Python
extension module, not linkable from Rust, and ships only inside the PyPI wheel.

The version lives in one place, `[workspace.package].version` in `Cargo.toml`. maturin
reads it for the Python package (`dynamic = ["version"]`), and `scripts/set_version.py`
keeps the bindings crate's `harness-lock-core` requirement and `Cargo.lock` in step.

## First-time setup

Needed once per repository, not once per release.

**GitHub**

- [ ] Make sure Actions runs for this repo (org Settings → Actions: enabled, allowed
      actions include `PyO3/maturin-action`, `pypa/gh-action-pypi-publish`,
      `dtolnay/rust-toolchain`, `Swatinem/rust-cache`).
- [ ] Create an environment named `pypi` (Settings → Environments). Add required
      reviewers if you want a human gate before each publish.
- [ ] Create an environment named `crates-io` and add the `CARGO_REGISTRY_TOKEN`
      secret to it (below).

**PyPI**: log in at <https://pypi.org/manage/account/publishing/> **as the
unionai-oss PyPI account** (whoever registers the publisher becomes the project owner)
and add a **pending publisher** (the project doesn't exist until the first upload):

| Field | Value |
|---|---|
| PyPI project name | `harness-lock` |
| Owner | `unionai-oss` |
| Repository name | `harness-lock` |
| Workflow name | `publish-python.yml` |
| Environment name | `pypi` |

No API token is stored anywhere. The `pypi` job's `id-token: write` permission is what
authenticates.

**crates.io**: crates.io has no pending publishers, so the first publish needs a token.

- [ ] Log in to <https://crates.io> (ideally with a unionai-oss account) and verify the
      account email (publishing requires it).
- [ ] Create an API token with `publish-new` + `publish-update` scopes, restricted to
      `harness-lock*`, and save it as `CARGO_REGISTRY_TOKEN` in the `crates-io` environment.
- [ ] After the first release: add co-owners
      (`cargo owner --add github:unionai-oss:<team> harness-lock-core`), configure
      trusted publishing for the crate on crates.io, then delete the token.

## Release checklist

1. [ ] Bump the version on a branch:
       ```bash
       python scripts/set_version.py 0.2.0
       python scripts/set_version.py --check   # prints 0.2.0
       ```
       Commit `Cargo.toml`, `crates/harness-lock/Cargo.toml`, and `Cargo.lock`, open a PR,
       and wait for `ci` to go green (its `packaging` job builds the wheel and sdist,
       runs `twine check`, installs the wheel, and does `cargo publish --dry-run`).
2. [ ] Optional rehearsal: run **publish-python** and **publish-cargo** manually from
       `main` with `dry_run: true` (the default). They build and verify every artifact
       and stop before publishing.
3. [ ] Merge, then tag the merge commit and push the tag:
       ```bash
       git switch main && git pull
       git tag v0.2.0 && git push origin v0.2.0
       ```
       Both publish workflows refuse to run if the tag doesn't match the version.
4. [ ] Approve the `pypi` / `crates-io` environment deployments if reviewers are required.
5. [ ] Check the results:
       - <https://pypi.org/project/harness-lock/> lists the version with 5 wheels + sdist
       - <https://crates.io/crates/harness-lock-core> lists the version; docs.rs builds
       - a GitHub release for the tag exists with the artifacts attached
6. [ ] Smoke-test from a clean environment:
       ```bash
       uvx --from harness-lock==0.2.0 hlock --version
       python -c "import harness_lock; print(harness_lock.__version__)"
       ```

## If something goes wrong

- **Re-running the tag** is safe for PyPI (`skip-existing: true` skips files already
  uploaded, so a run that failed halfway finishes the rest). crates.io rejects a version
  that already exists, so the cargo publish step fails on a re-run; that's expected.
- **A broken release can't be overwritten.** Neither registry accepts the same version
  twice (crates.io allows `cargo yank`, PyPI allows yanking a release). Fix forward with
  a patch release: `python scripts/set_version.py 0.2.1`.
- **Tag/version mismatch**: delete the tag (`git push --delete origin vX.Y.Z && git tag -d vX.Y.Z`),
  run `scripts/set_version.py`, merge, and re-tag.
