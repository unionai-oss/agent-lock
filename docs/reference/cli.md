# CLI reference

```console
$ hlock --help
 Usage: hlock [OPTIONS] COMMAND [ARGS]...

 hlock · make your agent harness setup pinnable, portable, and tunable.
```

Every command works on `harness.toml` and `harness.lock` in the current directory.
Output is colored on a terminal and plain text when piped or when `NO_COLOR` is set.
Failures print a one-line error with a hint and exit `1`.

| Command | Purpose |
|---|---|
| [`init`](#init) | Write a starter `harness.toml` |
| [`resolve`](#resolve) | Tune the search space and write `harness.lock` |
| [`check`](#check) | Fail if `harness.toml` has drifted from `harness.lock` |
| [`show`](#show) | Show the locked stack and its evidence |
| [`tree`](#tree) | Print the locked component graph |
| [`backend status`](#backend-status) | Show the configured backend and environment |
| [`run`](#run) | Run the locked agent on a prompt |
| [`upgrade`](#upgrade) | Plan, apply, or roll back component upgrades |
| [`optimize`](#optimize) | Tune prompts, hyperparameters, and small models into `harness.opt.lock` |

Global options: `-V`/`--version` and `-h`/`--help`.

## `init`

Write a starter `harness.toml` that uses the reference provider.

```bash
hlock init [--name NAME] [--pack PATH] [--force]
```

| Option | Default | Description |
|---|---|---|
| `--name` | `demo` | Project name |
| `--pack` | `./tasks` | Task pack directory. Warns if it has no `pack.toml`. |
| `--force` | | Overwrite an existing `harness.toml` |

## `resolve`

Run the resolver over the manifest's search space, write `harness.lock`, and print the
chosen stack with its evidence.

```bash
hlock resolve [--backend local|devbox|cluster] [--workdir DIR]
```

| Option | Default | Description |
|---|---|---|
| `--backend` | manifest `[backend] target` | Where trials run |
| `--workdir` | `.harnesslock` | Where trial artifacts go |

## `check`

Compare the manifest hash recorded in `harness.lock` with the hash of the current
`harness.toml`. Exits `0` when they match and `1` on drift, or when either file is
missing. See [Using hlock in CI](../guides/ci.md).

```bash
hlock check
```

## `show`

Print the locked stack (harness, models by role, decision model, backend) and the
evidence (success rate, cost per task, latency p50/p95, trials).

```bash
hlock show [--json]
```

| Option | Description |
|---|---|
| `--json` | Print the full lockfile as JSON |

## `tree`

Print the locked components as a tree.

```bash
hlock tree
```

## `backend status`

Show the configured backend, and which `HL_*` variables and Flyte config the worker
will use. API keys are reported as set or unset, never printed.

```bash
hlock backend status
```

## `run`

Load `harness.lock` and run the locked stack on `PROMPT`. Exits `0` when the task
succeeds and `1` when it fails.

```bash
hlock run PROMPT [--json]
```

| Option | Description |
|---|---|
| `--json` | Print the raw outcome: `{"success": …, "model": …, "cost_usd": …}` |

!!! note "v0.1"

    `run` executes the locked model on the offline reference provider. Running real
    providers and harnesses from the lock is on the roadmap.

## `upgrade`

Find newer versions of locked components, re-measure the stack, and apply only on
request. See [Upgrading components](../guides/upgrade.md).

```bash
hlock upgrade [--all | --to TARGET] [--apply] [--force] [--rollback] [--workdir DIR]
```

| Option | Description |
|---|---|
| `--all` | Consider every upgradeable component |
| `--to TARGET` | Upgrade to a specific model/version |
| `--apply` | Perform the upgrade. Without it, only print the plan. |
| `--force` | Keep the upgrade even if the success rate drops |
| `--rollback` | Restore `harness.lock` from `harness.lock.prev` |
| `--workdir DIR` | Where trial artifacts go |

## `optimize`

Tune prompts, hyperparameters, and small models, and write the result to
`harness.opt.lock`. See [Optimizing](../guides/optimize.md).

```bash
hlock optimize [--depth LEVEL] [--data SOURCE] [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--depth` | `auto` | `probe`, `prompt`, `hpo`, `ft`, `full`, or `auto` |
| `--data` | `user` | `user`, `user:<paths>`, `synthetic[:n]`, or `hub:<pack>` |
| `--harness NAME` | | Restrict to one harness |
| `--out FILE` | `harness.opt.lock` | Output file |
| `--strict` | | Fail unless the result beats the base lock |
| `--apply` | | Also adopt the result into `harness.lock` |
| `--max-trials N` | | Cap the number of trials |
| `--backend` | manifest `[backend] target` | `local`, `devbox`, or `cluster` |
| `--workdir DIR` | `.harnesslock` | Where trial artifacts go |

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Failure: drift (`check`), a failed task (`run`), a missing or invalid file, or a tuning error |
| `2` | Invalid command-line usage |
