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
task packs, search strategies, Flyte backend, open-weights models).

## Install

```bash
pip install -e ".[dev]"      # from this repo
```

This installs the `hpm` command and the `hpm` Python import.

## Quickstart (local, no accounts)

```bash
hpm init --name demo --pack ./tasks   # write a starter agentlock.toml
hpm lock                              # tune the search space -> agent.lock + report
hpm show                              # pretty-print the locked stack + evidence
hpm check                             # static verification (CI-friendly exit code)
hpm tree                              # component dependency graph
hpm run "solve this task"             # run the locked agent with the runtime guard
hpm diff                              # structural + evidence diff vs. committed lock
hpm backend status                    # report the active backend / Flyte config
```

The built-in `reference` provider and harness are deterministic and offline, so the
whole loop runs with zero setup and no API keys, producing a real-looking
leaderboard and lock.

## Backends

- `local` — in-process async runner (default).
- `devbox` / `cluster` — a Flyte 2 pipeline (`hpm.flyte`); reads `~/.flyte/config.yaml`
  for cluster targets and calls `flyte.run`. `flyte` is an optional extra
  (`pip install harness-package-manager[flyte]`).

## Python API (Layer 1)

```python
import hpm

lock = hpm.lock("agentlock.toml", backend="local")   # tune + write agent.lock
print(lock.evidence.summary() if hasattr(lock.evidence, "summary") else lock)

agent = hpm.load("agent.lock", mode="strict")        # runnable, guarded agent
outcome = await agent.run("clean ./data/orders.csv")
```

## Layout

- `hpm/` — the package: manifest, lockfile, store, components, providers, adapters,
  tasks, search, traces, runtime, backends, flyte, CLI.
- `tasks/` — a small example task pack (`pack.toml` + tasks + graders).
- `tests/` — unit + end-to-end tests.

## Status

Early v0.1: manifest + lockfile schema v1, content-addressed store, task packs with
graders, reference provider/harness, grid search + Pareto selection, the `init /
lock / show / check / tree / run / diff / backend` CLI, and a provisional Flyte
backend wired to `~/.flyte/config.yaml`.
