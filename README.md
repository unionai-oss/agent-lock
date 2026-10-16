# agent-lock (al)

**Lock your agent into place.**

`al` treats an agent system the way a package manager treats dependencies. You
bring your domain tasks, the models you're allowed to use, and the harness you
like. `al` searches the stack, measures it, and writes an `hpm.lock`: a pinned,
version-controlled, enforceable description of the agent that actually works for
your domain.

| Package manager            | al                                                            |
|----------------------------|----------------------------------------------------------------|
| `pyproject.toml`           | `hpm.toml` — the **manifest**: what you allow and require |
| dependency resolver        | **tuner**: search over LLMs × decision models × harnesses × policies |
| `uv.lock`                  | `hpm.lock` — the **lockfile**: what was chosen, pinned, hashed, plus the evidence |
| CI `--locked` check        | `al check` — fail if the running stack drifts from the lock |

See `SPEC.md` for the full design (manifest, lockfile schema, component model,
task packs, search strategies, the Flyte backend, open-weights models).
The (superseded) reference pure-Python implementation is preserved under
`python-legacy/`.

## Architecture

```
            Python API/CLI  (import agent_lock as al, `al` command)     <- PyO3 bindings
                         │
                         ▼
                  al-core (Rust)          manifest · lockfile · store ·
                                           task packs · search · tuner
                         │
                         └── flyte backend (flyte-sdk-rs, optional feature)
```

- `crates/agent-lock-core` — the core library (pure Rust, no Python).
- `crates/agent-lock` — PyO3 extension (`agent_lock._agent_lock`) exposing the same user-facing
  Python API as the reference implementation via the `al` package.
- `al/` — the mixed Python package: re-exports the compiled `al._agent_lock` and the
  `al` CLI.
- `crates/agent-lock-core/src/flyte.rs` — provisional backend integration using
  [flyte-sdk-rs](https://github.com/flyteorg/flyte-sdk-rs) behind the `flyte`
  cargo feature.

## Install

From the Rust side you depend on the crate; from Python you get native bindings.

```bash
# Python bindings — pip / uv / uvx
pip install agent-lock          # or: uv add / uvx
uv pip install -e .                            # editable dev install (this repo)

# Rust crate(s)  (publish later; locally)
cargo add agent-lock --path crates/agent-lock
# core library, if you depend on it directly
cargo add agent-lock-core --path crates/agent-lock-core
```

A local editable build needs a Rust toolchain + a Python ≤3.13 interpreter:

```bash
python3.13 -m venv .venv && .venv/bin/pip install click pytest
maturin develop -m crates/agent-lock/Cargo.toml      # builds + installs the al wheel
```

## Quickstart (local, no accounts)

```bash
al init --name demo --pack ./tasks   # write a starter hpm.toml
al lock                              # tune the search space -> hpm.lock + report
al show                              # pretty-print the locked stack + evidence
al check                             # static verification (CI-friendly exit code)
al tree                              # component dependency graph
al run "solve this task"             # run the locked agent with the runtime guard
al backend status                    # report the active backend / Flyte config
```

The built-in `reference` provider and harness are deterministic and offline, so the
whole loop runs with zero setup and no API keys.

## Python API (Layer 1)

```python
import agent_lock as al
from agent_lock import SearchSpace, Objective, Budget

space = SearchSpace(
    llm={"planner": ["reference:qwen-7b", "reference:qwen-32b"]},
    decision=["none", "rules:default"],
    harness=["reference"],
    tasks='{"packs": ["./tasks"], "seeds": 2}',
)
lock = hpm.lock(space, backend="local", workdir=".agentlock")
print(lock.summary())

agent = al.load("hpm.lock")
print(agent.run("clean ./data/orders.csv"))
```

## Backends

- `local` — in-process Rust async loop (default).
- `devbox` / `cluster` — a [flyte-sdk-rs](https://github.com/flyteorg/flyte-sdk-rs)
  backend (`cargo build --features flyte`) with a `flyteplugins-rs` Python
  launcher registering the trial task against a Flyte / Union cluster
  (`~/.flyte/config.yaml`). Provisional.

## Development

```bash
cargo test -p agent-lock-core            # Rust core + integration tests
.venv/bin/python -m pytest tests  # Python bindings tests
ruff check al/tests              # lint the Python layer
```

## Release & publishing

CI/CD publishes on git tags `v*` (and via `workflow_dispatch`):

- **Python bindings** → PyPI as `agent-lock` (`.github/workflows/publish-python.yml`).
  `maturin` builds an **abi3** wheel (CPython ≥ 3.9) for Linux/macOS/Windows and a source dist.
  Publishing uses [trusted publishing](https://docs.pypi.org/trusted-publishers/) (OIDC) —
  register this GitHub repo as a PyPI publisher for the `pypi` environment — or set a token.
  For test-PyPI publishes, run the workflow with `--pypi test` and set `TEST_PYPI_TOKEN`.
- **Rust crates** → crates.io as `agent-lock-core` (dependency) then
  `agent-lock` (`.github/workflows/publish-cargo.yml`).
  Set the `CARGO_REGISTRY_TOKEN` secret.

Daily CI (`ci.yml`) runs `cargo test` for the core and `pytest` + `ruff` for the bindings on
Python 3.9/3.12/3.13.

```bash
git tag v0.1.0 && git push origin v0.1.0   # triggers both publishing workflows
```

## Status

Early v0.1 (Rust core): manifest + lockfile schema v1, content-addressed store,
task packs with graders, reference provider/harness, grid search + Pareto
selection, a working `init / lock / show / check / tree / run / backend` CLI via
PyO3 bindings, and installable via pip/uv (crate not yet published).
