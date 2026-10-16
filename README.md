# harness-package-manager (hpm)

**Lock your agent into place.**

`hpm` treats an agent system the way a package manager treats dependencies. You
bring your domain tasks, the models you're allowed to use, and the harness you
like. `hpm` searches the stack, measures it, and writes an `agent.lock`: a pinned,
version-controlled, enforceable description of the agent that actually works for
your domain.

| Package manager            | hpm                                                            |
|----------------------------|----------------------------------------------------------------|
| `pyproject.toml`           | `agentlock.toml` — the **manifest**: what you allow and require |
| dependency resolver        | **tuner**: search over LLMs × decision models × harnesses × policies |
| `uv.lock`                  | `agent.lock` — the **lockfile**: what was chosen, pinned, hashed, plus the evidence |
| CI `--locked` check        | `hpm check` — fail if the running stack drifts from the lock |

See `SPEC.md` for the full design (manifest, lockfile schema, component model,
task packs, search strategies, the Flyte backend, open-weights models).
The (superseded) reference pure-Python implementation is preserved under
`python-legacy/`.

## Architecture

```
            Python API/CLI  (import hpm, `hpm` command)     <- PyO3 bindings
                         │
                         ▼
                  hpm-core (Rust)          manifest · lockfile · store ·
                                           task packs · search · tuner
                         │
                         └── flyte backend (flyte-sdk-rs, optional feature)
```

- `crates/hpm-core` — the core library (pure Rust, no Python).
- `crates/hpm` — PyO3 extension (`hpm._hpm`) exposing the same user-facing
  Python API as the reference implementation via the `hpm` package.
- `hpm/` — the mixed Python package: re-exports the compiled `hpm._hpm` and the
  `hpm` CLI.
- `crates/hpm-core/src/flyte.rs` — provisional backend integration using
  [flyte-sdk-rs](https://github.com/flyteorg/flyte-sdk-rs) behind the `flyte`
  cargo feature.

## Install

From the Rust side you depend on the crate; from Python you get native bindings.

```bash
# Python bindings — pip / uv / uvx
pip install harness-package-manager          # or: uv add / uvx
uv pip install -e .                            # editable dev install (this repo)

# Rust crate  (publish later; locally)
cargo add hpm-core --path crates/hpm-core
```

A local editable build needs a Rust toolchain + a Python ≤3.13 interpreter:

```bash
python3.13 -m venv .venv && .venv/bin/pip install click pytest
maturin develop -m crates/hpm/Cargo.toml      # builds + installs the hpm wheel
```

## Quickstart (local, no accounts)

```bash
hpm init --name demo --pack ./tasks   # write a starter agentlock.toml
hpm lock                              # tune the search space -> agent.lock + report
hpm show                              # pretty-print the locked stack + evidence
hpm check                             # static verification (CI-friendly exit code)
hpm tree                              # component dependency graph
hpm run "solve this task"             # run the locked agent with the runtime guard
hpm backend status                    # report the active backend / Flyte config
```

The built-in `reference` provider and harness are deterministic and offline, so the
whole loop runs with zero setup and no API keys.

## Python API (Layer 1)

```python
import hpm
from hpm import SearchSpace, Objective, Budget

space = SearchSpace(
    llm={"planner": ["reference:qwen-7b", "reference:qwen-32b"]},
    decision=["none", "rules:default"],
    harness=["reference"],
    tasks='{"packs": ["./tasks"], "seeds": 2}',
)
lock = hpm.lock(space, backend="local", workdir=".agentlock")
print(lock.summary())

agent = hpm.load("agent.lock")
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
cargo test -p hpm-core            # Rust core + integration tests
.venv/bin/python -m pytest tests  # Python bindings tests
ruff check hpm/tests              # lint the Python layer
```

## Status

Early v0.1 (Rust core): manifest + lockfile schema v1, content-addressed store,
task packs with graders, reference provider/harness, grid search + Pareto
selection, a working `init / lock / show / check / tree / run / backend` CLI via
PyO3 bindings, and installable via pip/uv (crate not yet published).
