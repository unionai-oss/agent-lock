# Development

## Prerequisites

- A [Rust toolchain](https://rustup.rs) (stable)
- Python 3.9 to 3.13
- [maturin](https://www.maturin.rs) to build the extension

## Set up

```bash
git clone https://github.com/unionai-oss/harness-lock
cd harness-lock
python3.13 -m venv .venv && source .venv/bin/activate
pip install maturin click rich rich-click pytest ruff
maturin develop -m crates/harness-lock-py/Cargo.toml
```

`maturin develop` compiles the Rust core and the PyO3 bindings and installs the package
in editable mode. Python changes take effect immediately. Rerun `maturin develop` after
changing Rust code.

## Test and lint

```bash
cargo test -p harness-lock-core               # Rust core + integration tests
python -m pytest tests                        # bindings, CLI, worker
ruff check harness_lock tests packaging/hlock
```

CI runs the same commands on every PR, on Python 3.9, 3.12, and 3.13. It also builds
the wheel, the sdist, and the `hlock` alias, installs them, and dry-runs
`cargo publish` for all three crates.

## Docs

The site uses [Zensical](https://zensical.org), from the team behind Material for
MkDocs. Pages are Markdown in `docs/`, and the configuration is `zensical.toml`.

```bash
pip install -r docs/requirements.txt
zensical serve                  # http://localhost:8000, with live reload
zensical build --clean          # static site in site/
```

Every push to `main` publishes the site to GitHub Pages
(`.github/workflows/docs.yml`). PRs that touch the docs build the site, so a broken
page fails review before it ships.

The terminal screenshot on the home page and in the README is rendered from a real CLI
session. Regenerate it after changing CLI output:

```bash
python scripts/cli_screenshot.py      # writes docs/assets/quickstart.svg
```

## Where things live

See [Architecture](../concepts/architecture.md#repository-layout) for the repository
layout, and [SPEC.md](https://github.com/unionai-oss/harness-lock/blob/main/SPEC.md) for
the full design.
