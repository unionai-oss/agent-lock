# Task packs

A task pack is the set of tasks that defines "works" for your domain. Every candidate
stack runs against it, and the evidence in `harness.lock` comes from it, so the pack
matters more than any other input. A good pack looks like the work you actually want
the agent to do.

## Layout

A pack is a directory with a `pack.toml` and one folder per task:

```text
tasks/
├── pack.toml
├── clean_csv/
│   ├── prompt.md
│   └── workspace/
│       └── orders.csv
└── summarize_report/
    └── prompt.md
```

## `pack.toml`

```toml title="tasks/pack.toml"
[pack]
name = "harness-lock/demo"
version = "0.1.0"
license = "Apache-2.0"
domain = "research-analyst"

[[task]]
id = "clean_csv"
prompt = "clean_csv/prompt.md"
fixtures = "clean_csv/workspace/"
tools = ["python"]
expected = { artifacts = ["cleaned.csv"] }
tags = ["data-cleaning"]
timeout-seconds = 600

[[task]]
id = "summarize_report"
prompt = "summarize_report/prompt.md"
tools = ["python", "filesystem"]
expected = { artifacts = ["summary.md"] }
tags = ["writing"]
```

### `[pack]`

| Key | Required | Description |
|---|---|---|
| `name` | yes | Pack identifier, conventionally `owner/name` |
| `version` | yes | Pack version. Change it when you change the tasks. |
| `domain` | yes | The domain the pack represents |
| `license` | no | License of the pack contents |

### `[[task]]`

| Key | Required | Default | Description |
|---|---|---|---|
| `id` | yes | | Unique task id within the pack |
| `prompt` | yes | | Path to the prompt file, relative to the pack directory |
| `fixtures` | no | | Directory copied into the task's workspace before the run |
| `tools` | no | `[]` | Tools the task may use |
| `expected` | no | `{}` | What a successful run produces, e.g. `{ artifacts = ["out.csv"] }` |
| `graders` | no | `[]` | Grader ids. Empty means artifact checks on `expected.artifacts`. |
| `tags` | no | `[]` | Free-form labels for slicing results |
| `timeout-seconds` | no | `600` | Per-task timeout |

## Grading

In v0.1, a task succeeds when every file in `expected.artifacts` exists in the task's
workspace after the run. This is the `artifact:` grader, and it's the default when
`graders` is empty. Richer graders (tests, rubric judges) are on the
[roadmap](https://github.com/unionai-oss/harness-lock/blob/main/SPEC.md).

## Using a pack

Point the manifest at one or more packs:

```toml title="harness.toml"
[tasks]
packs = ["./tasks", "../shared-packs/support-tickets"]
seeds = 3               # runs per task per candidate; default 3

[tasks.splits]
search = 0.7            # fraction of tasks used to pick the winner; the rest is holdout
```

Pack paths are relative to the directory you run `hlock` in. Each pack's contents are
hashed, and the hash is recorded so evidence can be traced back to the exact tasks.

## Writing good tasks

- **Sample real work.** Pull tasks from tickets, logs, or traces you already have.
  Synthetic tasks are useful for filling gaps, but they shouldn't make up the core.
- **Keep the split meaningful.** With fewer than about ten tasks, the holdout split is
  too small to say much. Add tasks before you trust a narrow win.
- **Make success checkable.** Every task should produce something a grader can check
  without a human.
- **Version the pack.** Bump `version` when tasks change, so evidence from different
  versions isn't compared by accident.
