<div align="center">

# 🔒 hlock

### Lock your agent into place.

**Tune your agent stack against your own tasks, then pin the winner in a `harness.lock`.**

[![PyPI](https://img.shields.io/pypi/v/hlock?label=pypi&color=3775A9&logo=pypi&logoColor=white)](https://pypi.org/project/hlock/)
[![crates.io](https://img.shields.io/crates/v/hlock?color=E6532D&logo=rust&logoColor=white)](https://crates.io/crates/hlock)
[![CI](https://img.shields.io/github/actions/workflow/status/unionai-oss/harness-lock/ci.yml?branch=main&label=ci&logo=github)](https://github.com/unionai-oss/harness-lock/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-unionai--oss.github.io-7C3AED?logo=readthedocs&logoColor=white)](https://unionai-oss.github.io/harness-lock/)
[![Python](https://img.shields.io/pypi/pyversions/harness-lock?logo=python&logoColor=white)](https://pypi.org/project/hlock/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/unionai-oss/harness-lock/blob/main/LICENSE)

[**Documentation**](https://unionai-oss.github.io/harness-lock/) ·
[Quickstart](https://unionai-oss.github.io/harness-lock/getting-started/quickstart/) ·
[CLI reference](https://unionai-oss.github.io/harness-lock/reference/cli/) ·
[Design spec](https://github.com/unionai-oss/harness-lock/blob/main/SPEC.md)

</div>

---

`hlock` treats an agent system the way a package manager treats dependencies. You
bring your domain tasks, the models you're allowed to use, and the harness you like.
`hlock` searches the stack, measures every candidate against your tasks, and writes a
`harness.lock`: a pinned, version-controlled, enforceable description of the agent that
actually works for your domain, along with the evidence for choosing it.

| You know this from package managers | In `hlock` |
|---|---|
| 📄 `pyproject.toml` | **`harness.toml`**, the manifest: what the tuner may try, and what "best" means |
| 🧮 dependency resolver | **the tuner**: search over LLMs × decision models × harnesses × policies |
| 🔒 `uv.lock` / `Cargo.lock` | **`harness.lock`**, the lockfile: what was chosen, pinned and hashed, plus the evidence |
| ✅ CI `--locked` check | **`hlock check`**: fail when the manifest drifts from the lock |

## Install

```bash
pip install hlock        # or: uv add hlock  ·  uvx hlock --help
```

Prebuilt wheels cover Linux (x86_64, aarch64), macOS (arm64, x86_64), and Windows (x64)
for CPython 3.9+. For Rust, use `cargo add hlock`.

> [!NOTE]
> `hlock` is the short name for [`harness-lock`](https://pypi.org/project/harness-lock/).
> Both names install the same package at the same version, so `import hlock` and
> `import harness_lock` are the same API.

## Quickstart

No accounts or API keys needed. The built-in `reference` provider and harness are
deterministic and offline, so the whole loop runs on a laptop.

```bash
hlock init --name demo --pack ./tasks   # write a starter harness.toml
hlock resolve                           # tune the search space -> harness.lock
hlock check                             # fail if harness.toml drifted from the lock
hlock run "clean ./data/orders.csv"     # run the locked agent
```

<p align="center">
  <img src="https://raw.githubusercontent.com/unionai-oss/harness-lock/main/docs/assets/quickstart.svg" alt="An hlock session: init, resolve, check, and run" width="640">
</p>

From there: `hlock show` prints the locked stack and its evidence, `hlock tree` prints the
component graph, `hlock upgrade` plans model upgrades, and `hlock optimize` tunes prompts,
hyperparameters, and small models into a `harness.opt.lock`.

<details>
<summary><b>Python API</b></summary>

```python
import json
import hlock
from hlock import SearchSpace, Objective, Budget

space = SearchSpace(
    llm={"planner": ["reference:qwen-7b", "reference:qwen-32b"]},
    decision=["none", "rules:default"],
    harness=["reference"],
    objective=Objective(select="min-cost", constraints={"success-rate": ">=0.5"}),
    budget=Budget(max_trials=50),
    tasks=json.dumps({"packs": ["./tasks"], "seeds": 2}),
)
lock = hlock.resolve(space, backend="local")   # writes ./harness.lock
print(lock.summary())

agent = hlock.load("harness.lock")
print(agent.run("clean ./data/orders.csv"))   # {"success": true, "model": "qwen-7b", ...}
```

</details>

## How it works

```mermaid
flowchart LR
    subgraph inputs["You declare"]
        direction TB
        M["📄 harness.toml<br/><sub>candidates · objective · budget</sub>"]
        T["🧪 task packs<br/><sub>prompts · fixtures · graders</sub>"]
    end

    subgraph tuner["hlock resolve"]
        direction TB
        S["search<br/><sub>LLMs × decision × harness × policy</sub>"]
        E["evaluate<br/><sub>run every trial on your tasks</sub>"]
        P["select<br/><sub>Pareto front + constraints</sub>"]
        S --> E --> P
    end

    L["🔒 harness.lock<br/><sub>pinned · hashed · with evidence</sub>"]

    subgraph use["You ship"]
        direction TB
        C["✅ hlock check<br/><sub>CI drift gate</sub>"]
        R["▶️ hlock run<br/><sub>the pinned stack</sub>"]
    end

    M --> S
    T --> E
    P --> L
    L --> C
    L --> R
```

## Architecture

A Rust core does all the deterministic work. Anything that needs the Python ML
ecosystem or a GPU runs in a Python worker, which can lift each piece of work to a
Flyte task on a cluster.

```mermaid
flowchart TB
    subgraph py["🐍 Python  ·  pip install hlock"]
        direction LR
        CLI["hlock CLI"]
        API["import hlock"]
    end

    subgraph core["🦀 harness-lock-core  ·  Rust"]
        direction LR
        MF["manifest"] ~~~ LK["lockfile"] ~~~ ST["store"] ~~~ TP["task packs"] ~~~ SR["search"] ~~~ TU["tuner"]
    end

    py -- "PyO3 bindings" --> core

    core -- "backend = local" --> LOCAL["⚡ in-process reference harness<br/><sub>deterministic · offline · CI-friendly</sub>"]
    core -- "backend = devbox / cluster<br/><sub>versioned JSON contract</sub>" --> W["🐍 Python worker<br/><sub>harness_lock.tasks.worker</sub>"]

    W --> HEAVY["real LLM calls · trace loading · synthetic data<br/>grading · prompt search · LoRA fine-tuning"]
    W -. "optional" .-> FLYTE["☁️ Flyte / Union tasks<br/><sub>CPU + GPU images · caching · lineage</sub>"]
```

| Path | What lives there |
|---|---|
| [`crates/harness-lock-core`](https://github.com/unionai-oss/harness-lock/tree/main/crates/harness-lock-core) | The core library (pure Rust): manifests, lockfiles, search planning, trial bookkeeping, evidence, lock construction. It orchestrates and aggregates, and never does heavy compute itself. |
| [`crates/harness-lock-py`](https://github.com/unionai-oss/harness-lock/tree/main/crates/harness-lock-py) | PyO3 bindings, compiled into `harness_lock._harness_lock` and shipped only inside the wheel. |
| [`crates/harness-lock`](https://github.com/unionai-oss/harness-lock/tree/main/crates/harness-lock), [`crates/hlock`](https://github.com/unionai-oss/harness-lock/tree/main/crates/hlock) | Thin crates that re-export the core under both names. |
| [`harness_lock/`](https://github.com/unionai-oss/harness-lock/tree/main/harness_lock) | The Python package: the `hlock` CLI and the heavy-work worker ([`tasks/worker.py`](https://github.com/unionai-oss/harness-lock/blob/main/harness_lock/tasks/worker.py)). |
| [`packaging/hlock`](https://github.com/unionai-oss/harness-lock/tree/main/packaging/hlock) | The `hlock` PyPI alias, which pins the matching `harness-lock` release. |
| [`docs/`](https://github.com/unionai-oss/harness-lock/tree/main/docs) | The documentation site ([Zensical](https://zensical.org)), published to GitHub Pages. |

## Backends

| Backend | Where trials run | Use it for |
|---|---|---|
| `local` *(default)* | in-process Rust reference harness | trying it out, CI, deterministic tests |
| `devbox` | Python worker on this machine | real LLM calls, your own traces, `flyte local` |
| `cluster` | Python worker that lifts each stage to Flyte/Union | GPUs, fan-out, durable caching, shared results |

```bash
hlock optimize --backend devbox --depth probe --max-trials 10
# real LLM calls: export HL_LLM_BASE_URL=http://… HL_LLM_MODEL=qwen-32b [HL_LLM_API_KEY=…]
hlock optimize --backend cluster --depth ft --data user:./runs   # LoRA on a GPU worker
```

See [Backends](https://unionai-oss.github.io/harness-lock/guides/backends/) for setup and
the `HL_*` environment variables.

## Development

```bash
python3.13 -m venv .venv && source .venv/bin/activate
pip install maturin click pytest ruff
maturin develop -m crates/harness-lock-py/Cargo.toml   # build + install the extension

cargo test -p harness-lock-core    # Rust core + integration tests
python -m pytest tests             # Python bindings + worker
ruff check harness_lock tests packaging/hlock

pip install -r docs/requirements.txt && zensical serve   # docs at http://localhost:8000
```

Releases are cut from tags. See [RELEASING.md](https://github.com/unionai-oss/harness-lock/blob/main/RELEASING.md).

## Status

`hlock` is at **v0.1**. What works today: manifest and lockfile schema v1, a
content-addressed store, task packs with graders, the reference provider and harness,
grid search with Pareto selection, `upgrade` (plan/apply/rollback), and `optimize` across
the `local`, `devbox`, and `cluster` backends. [SPEC.md](https://github.com/unionai-oss/harness-lock/blob/main/SPEC.md) describes the full design,
much of which is still on the roadmap.

## License

[Apache-2.0](https://github.com/unionai-oss/harness-lock/blob/main/LICENSE)
