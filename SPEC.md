# agent-lock — Specification (draft v0)

> **Lock your agent into place.**
> Bring your domain tasks, the models you're allowed to use, and the harness you like.
> `agent-lock` searches the stack, measures it, and writes an `agent.lock`: a pinned,
> version-controlled, enforceable description of the agent that actually works for your domain.

Status: draft · Owner: Niels Bantilan · Last updated: 2026-10-16

---

## 1. Summary

`agent-lock` is a Python package (plus a family of open-weights models and datasets) that
treats an agent system the way a package manager treats dependencies:

| Package manager            | agent-lock                                                        |
|----------------------------|-------------------------------------------------------------------|
| `pyproject.toml`           | `agentlock.toml`: the **manifest**. What you allow and require.   |
| dependency resolver        | **tuner**: search over LLMs × decision models × harnesses × policies, scored against domain tasks |
| `uv.lock` / `Cargo.lock`   | `agent.lock`: the **lockfile**. Exactly what was chosen, pinned and hashed, plus the evidence for choosing it |
| `uv sync`                  | `agent-lock sync`: materialize the locked stack in an environment |
| `uv lock --upgrade-package`| `agent-lock update <component>`: re-resolve part of the stack and diff the evidence |
| CI `--locked` check        | `agent-lock check` / `agent-lock verify`: fail if the running stack drifts from the lock |

The tuning backend runs on **Flyte 2** for durability (retries, caching, resumability,
fan-out, lineage), with a single dial for how much infrastructure it uses:

```
local  ───────────►  devbox  ───────────►  cluster (self-hosted Flyte or Union)
pure Python,          local Flyte in        remote scale, GPUs, many
zero setup            Docker: UI, durable   concurrent trials, shared cache
                      state, resume
```

Users never see Flyte unless they deliberately go down to the lowest API layer (§9).

**Positioning in one line:** agent-lock is *AutoML for agent systems*, or more precisely a
*domain agent compiler*. Give it representative tasks, available models, tools, and
harnesses. It searches the space, evaluates the traces, trains lightweight decision
policies, and locks the best agent system for your domain.

**Open-source first, with an upgrade path.** The "anyone can try it" path is fully local
and needs no account. The "why scale matters" path (durability, caching, lineage, HITL,
retries, GPUs, team-shared results) is the same program on a Flyte or Union cluster.
*Run locally in 10 minutes. Scale up when it matters.*

---

## 2. Problem and motivation

### 2.1 The problem

Teams building agents today make a set of coupled decisions mostly by vibes:

- **Which LLM(s)?** Frontier API, open weights on vLLM, local on Ollama, or a mix.
- **Which harness?** OpenCode, Pi, Claude Agent SDK, Codex CLI, LangGraph, PydanticAI,
  OpenAI Agents SDK, Hermes, a homegrown loop.
- **Where do cheap decisions go?** Routing, retry, escalate-to-human, stop, tool choice.
  A small decision model can often replace a frontier LLM call here.
- **Which policies?** Retries, timeouts, sandboxing, approval gates, memory, concurrency.
- **Which steps should stop being agentic** and become deterministic workflows?

Even after a team settles on a good configuration, it is **not reproducible**:

- Model aliases move (`claude-sonnet-latest`, `gpt-5`), and providers retire snapshots.
- Harness versions, system prompts, tool schemas, and MCP server versions change quietly.
- No artifact records *why* a configuration was chosen or how well it scored.
- Nothing fails in CI when the running agent no longer matches what was evaluated.

The result is agents that degrade silently and can't be rolled back, diffed, or audited.

### 2.2 Why now

- **The question has shifted** from "which model is best?" to "which model + harness +
  tools actually completes *my* tasks reliably?" Evaluation is moving from static QA toward
  traces, harness changes, and replay loops. Nobody yet ships an artifact that captures the
  answer and keeps it true over time.
- **Customer signal (Union).** Recurring asks from Union customers that agent-lock addresses
  directly:
  - Flyte-native agent harnesses with tool calling, MCP, memory, and human-in-the-loop.
  - Hermes and other third-party harness integration with Flyte.
  - LangGraph agents whose node functions run as Flyte tasks.
  - Open-source Flyte MCP work.
  - Sandboxed code execution and "MLE bot" style demos.
  - Agent/actor throttling, mapped (fanned-out) agent tasks, native SDK integration.
  - Dataset snapshotting/versioning, model-factory workflows, eval and observability.
- **Why an open artifact rather than a fine-tuned model alone.** A model on its own is hard
  to make broadly useful unless it beats frontier models or owns a narrow niche. A tool
  that produces comparisons, leaderboards, and a sharable lockfile has far more surface
  area, and the narrow open models (§11) ride along as companion artifacts.

## 3. Goals and non-goals

### Goals

1. **One sharable artifact.** `agent.lock` fully describes a tuned agent stack and the
   evidence behind it. It is human-readable, diffable in a PR, and machine-enforceable.
2. **Domain-specific tuning.** Optimize against *your* tasks (a task pack), not a generic
   leaderboard.
3. **Harness-agnostic.** Pluggable adapters for existing harnesses; no new agent framework
   to learn.
4. **Runs anywhere.** `pip install agent-lock` and lock on a laptop with no services.
   The same code path scales to a devbox or a cluster by changing one flag.
5. **Layered devex.** Flyte powers the backend but stays invisible until a user needs to
   customize compute or durability.
6. **Open artifacts.** Open-weights decision/judge models, open task packs, an open trace
   dataset, all under permissive licenses.
7. **Updateable.** Partial re-resolution (`update`), evidence diffs, and drift detection
   make it safe to move to new models and harness versions.

### Non-goals (v0–v1)

- Building a new general-purpose agent harness. The built-in `reference` harness exists only
  for tests and as a baseline.
- Hosting inference. agent-lock calls providers or the user's own endpoints.
- Training frontier-scale models. Fine-tuning is limited to small decision/judge models
  and, optionally, LoRA adapters on open-weights LLMs.
- Guaranteeing bit-exact determinism for closed API models. The lock pins what *can* be
  pinned and fingerprints the rest (§5.4).

---

## 4. Core concepts

| Term | Definition |
|---|---|
| **Stack** | One concrete agent configuration: LLM assignment(s) + decision model + harness + tools + prompts + policies + runtime. |
| **Component** | One axis of a stack (e.g. `llm.planner`, `decision.router`, `harness`, `policy.retries`). |
| **Manifest** (`agentlock.toml`) | User-authored constraints: candidate components, task packs, objectives, budget, backend. |
| **Search space** | The set of stacks implied by the manifest's candidates and constraints. |
| **Task pack** | Versioned set of domain tasks + fixtures + graders. The unit of evaluation. |
| **Trial** | One `(stack, task, seed)` execution. Produces a trace and grades. |
| **Trace** | Structured record of a trial: model calls, decisions, tool calls, observations, artifacts, costs, timings. |
| **Grader** | Scores a trial: deterministic checks, artifact checks, or an LLM/judge model. |
| **Decision model** | A small model (or rule set) that makes structured choices inside the harness loop: route, retry, escalate, stop, tool choice. |
| **Tuner** | The search + evaluation + selection engine that turns a manifest into a lock. |
| **Lock** (`agent.lock`) | The resolved stack, fully pinned, with hashes, provenance, and evaluation evidence. |
| **Adapter** | Plugin that teaches agent-lock how to configure, run, trace, and enforce a specific harness. |
| **Backend** | Where the tuner executes: `local`, `devbox`, or `cluster`. |

### 4.1 The loop

```
 agentlock.toml ─┐
 task packs ─────┤
                 ▼
          ┌─────────────┐   trials (fan-out)   ┌──────────────┐
          │   planner   │ ───────────────────► │ run + trace  │  ← adapters run each harness
          └─────────────┘                      └──────┬───────┘
                 ▲                                    ▼
                 │  next candidates            ┌──────────────┐
                 └──────────────────────────── │    grade     │  ← graders / judge model
                                               └──────┬───────┘
                                                      ▼
                         (optional) train decision model on traces
                                                      ▼
                                               ┌──────────────┐
                                               │ select + pin │ ──► agent.lock
                                               └──────────────┘      + traces/ + report
```

---

## 5. The `agent.lock` file

`agent.lock` is the central artifact. It has three jobs:

1. **Document.** What the agent is, and the evidence that it works.
2. **Enforce.** What the runtime must match. `check`, `sync`, and the runtime guard read it.
3. **Version.** Diffable in git, partially updateable, reproducible from the manifest.

### 5.1 Format

- **TOML**, generated, deterministic key ordering, stable formatting (so diffs are minimal).
- Begins with a `# This file is generated by agent-lock. Do not edit by hand.` header.
- Large content (prompts, tool schemas, traces, weights) is **referenced by content hash**,
  never inlined. Blobs live in `.agentlock/store/` (local) or a configured object store,
  addressed as `sha256:<digest>`.
- Secrets are **never** written. Credentials are referenced by name (`env:ANTHROPIC_API_KEY`).
- `lock-version` is the schema version. Readers must reject unknown major versions.

### 5.2 Example

```toml
# This file is generated by agent-lock. Do not edit by hand.
lock-version = 1
generated-by = "agent-lock 0.3.0"
generated-at = "2026-10-16T14:02:11Z"
manifest-hash = "sha256:9f1c…"          # agentlock.toml that produced this lock

[stack]
name = "ml-eng-debugger"
selection = "pareto:min-cost@quality>=0.85"   # how the winner was chosen
harness = "opencode"

# ---------- LLMs ----------
[[llm]]
role = "planner"
provider = "anthropic"
model = "claude-sonnet-5-5"              # never an alias; aliases are resolved at lock time
resolved-from = "anthropic:claude-sonnet-latest"
params = { temperature = 0.2, max_tokens = 8192 }
fingerprint = "sha256:41aa…"             # behavioral fingerprint, see §5.4

[[llm]]
role = "executor"
provider = "vllm"
model = "Qwen/Qwen3-32B"
revision = "a1b2c3d4…"                   # HF commit
weights = "sha256:77e0…"                 # safetensors manifest digest
adapter = { lora = "hf://acme/qwen3-32b-mleng-lora", revision = "e5f6…", weights = "sha256:0c3d…" }
serving = { engine = "vllm", engine-version = "0.11.2", dtype = "bf16" }
params = { temperature = 0.0, max_tokens = 4096, seed = 7 }
fingerprint = "sha256:b902…"

# ---------- Decision model ----------
[decision]
kind = "model"                           # model | rules | llm
model = "hf://agent-lock/decider-1.5b"
revision = "3c9e…"
weights = "sha256:5d1a…"
adapter = { lora = "store://sha256:8e7f…" }   # tuned on this project's traces
decisions = ["route", "retry", "escalate", "stop"]
thresholds = { escalate = 0.72, stop = 0.90 }

# ---------- Harness ----------
[harness]
name = "opencode"
version = "1.4.2"
source = "npm:opencode-ai@1.4.2"
integrity = "sha512-…"
adapter = "agent_lock.adapters.opencode@0.3.0"
config = "sha256:2b77…"                  # rendered harness config blob
system-prompt = "sha256:c41e…"
pattern = "plan-act-reflect"

# ---------- Tools ----------
[[tool]]
name = "python"
kind = "builtin"
schema = "sha256:aa01…"

[[tool]]
name = "github"
kind = "mcp"
source = "npm:@modelcontextprotocol/server-github@2025.9.1"
integrity = "sha512-…"
schema = "sha256:f00d…"                  # hash of the tool list the server advertised at lock time
permissions = ["read:repo", "write:pull_request"]

# ---------- Policies (enforced at runtime) ----------
[policy]
retries = 1
tool-timeout-seconds = 120
max-steps = 40
max-cost-usd-per-task = 1.50
sandbox = { enabled = true, image = "ghcr.io/agent-lock/sandbox-py@sha256:19ab…", network = "egress-allowlist" }
human-approval = "on_risky_action"
risky-actions = ["filesystem.write:/", "github.merge", "shell:rm"]
tool-allowlist = ["python", "github", "filesystem"]

# ---------- Evaluation evidence ----------
[[evidence]]
task-pack = "agent-lock/ml-engineering"
task-pack-version = "0.2.0"
task-pack-hash = "sha256:6aa2…"
split = "holdout"
trials = 150                             # 50 tasks × 3 seeds
success-rate = { mean = 0.87, ci95 = [0.81, 0.92] }
cost-usd-per-task = { mean = 0.34, p95 = 0.81 }
latency-s-per-task = { p50 = 41.0, p95 = 112.0 }
human-intervention-rate = 0.06
traces = "store://sha256:e3d9…"          # trace dataset for this evidence
report = "store://sha256:01fe…"

[evidence.baseline]                      # what the winner beat, for context in diffs
stack = "anthropic:claude-sonnet-5-5 + opencode, no decision model"
success-rate = 0.89
cost-usd-per-task = 1.12

# ---------- Drift guards ----------
[verify]
canary-tasks = 12                        # subset re-run by `agent-lock verify`
min-success-rate = 0.80                  # fail verify below this
fingerprint-tolerance = 0.15             # max behavioral distance before warning

# ---------- Provenance ----------
[provenance]
backend = "cluster"
run = "flyte://my-org/agent-lock/development/r8x2k1"
search = { strategy = "successive-halving", candidates = 48, trials = 1312, spend-usd = 214.07 }
```

### 5.3 What gets pinned

| Component | Pinned by |
|---|---|
| Closed API LLM | Exact dated model ID (alias resolved at lock time), params, behavioral fingerprint |
| Open-weights LLM | HF repo + commit + weights digest, LoRA digest, serving engine + version + dtype |
| Decision model | Weights digest (+ adapter), thresholds, decision set |
| Harness | Package source + version + integrity hash, adapter version, rendered config hash, prompts hash |
| Tools | Builtin schema hash; MCP server package + version + integrity + advertised-schema hash; permissions |
| Policies | Literal values (small, inlined so they're reviewable in PRs) |
| Runtime | Sandbox image digest, network policy |
| Task pack | Name, version, content hash |

### 5.4 Behavioral fingerprints

Closed models can't be pinned by weights, and providers sometimes change behavior under a
fixed model ID. A **fingerprint** is a hash over the model's outputs on a fixed, small
probe set (fixed prompts, `temperature=0`, structured outputs), plus an embedding summary
used for a *distance* metric. `agent-lock verify` re-probes and reports the distance. Above
`fingerprint-tolerance` it warns; with `--strict` it fails.

Fingerprints are evidence, not a guarantee. The spec says so plainly in the CLI output.

### 5.5 Enforcement

Enforcement happens at three points:

1. **`agent-lock check`** (static, fast, offline-capable). Verifies installed harness/MCP
   versions and integrity, rendered config and prompt hashes, sandbox image digest, and that
   `agentlock.toml` still hashes to `manifest-hash`. Exit codes are CI-friendly.
2. **`agent-lock verify`** (dynamic, costs money). Re-runs the canary tasks and fingerprint
   probes against live providers and compares them to the evidence and thresholds.
3. **Runtime guard** (in-process, via adapters). When the agent runs through
   `agent-lock run` or `agent_lock.runtime.guard(...)`:
   - model calls are checked against the locked provider/model/params; mismatch → error,
   - tool calls are checked against `tool-allowlist` and `permissions`,
   - `max-steps`, `max-cost-usd-per-task`, and timeouts are enforced,
   - `risky-actions` trigger the configured approval hook,
   - every run emits a trace in the standard schema (§10), so production traces can feed
     the next tuning round.

Enforcement modes: `strict` (fail), `warn` (log + continue), `off`. Configured in the manifest,
overridable per command.

### 5.6 Updating

```bash
agent-lock update llm.executor            # re-resolve one component, keep the rest pinned
agent-lock update harness --to 1.5.0      # try a specific new version
agent-lock update --all                   # full re-resolve
agent-lock diff                           # component + evidence diff vs. the committed lock
```

`update` reuses cached trials for unchanged stacks (thanks to Flyte caching, §8.3), so a
partial update only pays for new trials. `diff` renders both a structural diff and an
**evidence diff** ("success-rate 0.87 → 0.89 (+0.02, CI overlaps); cost −31%"), suitable for
pasting into a PR description. `agent-lock diff --format md` produces exactly that.

---

## 6. The manifest: `agentlock.toml`

User-authored. Declares candidates and constraints; the tuner resolves them into a lock.

```toml
[project]
name = "ml-eng-debugger"

[tasks]
packs = ["agent-lock/ml-engineering@^0.2", "./tasks/internal"]   # hub packs + local packs
splits = { search = 0.7, holdout = 0.3 }
seeds = 3

# ---- What the tuner may try ----
[candidates.llm.planner]
any-of = ["anthropic:claude-sonnet-latest", "openai:gpt-5", "vllm:Qwen/Qwen3-32B"]

[candidates.llm.executor]
any-of = ["vllm:Qwen/Qwen3-32B", "ollama:qwen3:8b", "same-as:planner"]

[candidates.decision]
any-of = ["none", "rules:default", "hf://agent-lock/decider-1.5b", "llm:openai:gpt-5-mini"]
train = "allow"                          # allow tuning a decision model on this project's traces

[candidates.harness]
any-of = ["opencode", "pi", "claude-agent-sdk", "langgraph:./graphs/debugger.py"]
pattern = ["single-agent", "plan-act-reflect", "dag+agent-loop"]   # where the harness supports it

[candidates.policy]
retries = [0, 1, 3]
human-approval = ["never", "on_risky_action", "always_before_write"]
tool-timeout-seconds = [30, 120]
memory = ["none", "session", "project"]
sandbox = [true]                         # fixed: not a search axis

[tools]
python = {}
github = { mcp = "npm:@modelcontextprotocol/server-github", permissions = ["read:repo", "write:pull_request"] }

# ---- What "best" means ----
[objective]
primary = "success-rate"
constraints = { success-rate = ">=0.85", cost-usd-per-task = "<=1.00", latency-s-p95 = "<=180" }
select = "min-cost"                      # among stacks meeting constraints

[budget]
max-spend-usd = 250
max-trials = 2000
strategy = "auto"                        # grid | random | successive-halving | bayesian | auto

[enforce]
mode = "strict"

[backend]
target = "local"                         # local | devbox | cluster
# profile = "gpu-training"              # see §9.3
```

Candidate syntax:

- `provider:model` for LLMs. Aliases are allowed in the manifest; the lock always pins them.
- `same-as:<role>` to tie roles together.
- `hf://org/repo[@rev]`, `store://sha256:…`, local paths for models/adapters.
- `langgraph:path/to/graph.py` and similar for harnesses that need user code.
- Any component accepts a constraint table instead of a list:
  `[candidates.harness.opencode] version = ">=1.4,<2"`.

---

## 7. Components

### 7.1 Task packs

A task pack is a directory (or a Hub reference) with a `pack.toml`:

```toml
[pack]
name = "agent-lock/ml-engineering"
version = "0.2.0"
license = "Apache-2.0"
domain = "ml-engineering"

[[task]]
id = "debug_failed_training_run_014"
prompt = "tasks/014/prompt.md"
fixtures = "tasks/014/workspace/"       # copied into the sandbox
tools = ["python", "filesystem", "logs"]
expected = { artifacts = ["patch.diff", "root_cause.md"] }
graders = ["tests:tasks/014/check.py", "judge:rubric/root_cause.md"]
tags = ["recovery", "code-edit"]
timeout-seconds = 600
```

Grader types:

- `tests:` a Python function `def grade(workspace, trace) -> Grade`. Deterministic, preferred.
- `artifact:` existence/schema/content checks on outputs.
- `judge:` a rubric scored by a judge model (default: the open `agent-lock/judge` model,
  §11; any LLM can be configured). Judge prompt and model are pinned in the evidence.
- `trace:` checks over the trace itself (e.g. "never called `shell` with `rm -rf`",
  "asked for approval before writing outside workspace").

Metrics computed per trial: success, score, cost, latency, steps, retries, tool-use
correctness, tool errors, recoveries, human interventions, safety violations. Aggregates
come with bootstrap CIs, plus **determinism** (outcome and trajectory variance across seeds)
and **replayability** (whether the trial reproduces from its recorded trace, §10.3).

**Bootstrapping a pack.** `agent-lock tasks new --from-traces <dir>` turns existing
production traces (in the trace schema, or imported from OTel/LangSmith/etc.) into
draft tasks with draft graders for a human to review. Domain coverage is the biggest
adoption barrier, so this path matters.

Initial official packs: `research-analyst`, `data-cleaning`, `ml-engineering`,
`code-migration`, `support-triage`. Each has 30–100 tasks and a hidden holdout split on the Hub.

The first pack, **`research-analyst`** (the "research/data agent gauntlet"), is deliberately
concrete. Its 25–50 tasks each exercise one or more of:

- reading a messy CSV,
- calling a search/retrieval tool,
- writing and running Python,
- recovering from a failing tool call,
- producing a cited answer,
- creating an artifact (report, plot),
- deciding when human approval is needed,
- not leaking a secret planted in the workspace,
- resuming from a failed step.

Every task is graded by deterministic checks first and a judge only where necessary.

Backlog of candidate packs (community or later official): `bi-analyst`,
`scientific-literature-review`, `drug-discovery-research`, `finance-forecasting`,
`workflow-debugging`.

### 7.2 LLM providers

A thin provider layer (built on LiteLLM or similar, behind our own interface) with:
alias resolution to dated IDs, price tables for cost accounting, fingerprint probing,
and serving adapters for `vllm`, `sglang`, and `ollama` that can *start* an open-weights
model from a pinned revision when the backend allows it (devbox/cluster with GPUs).

### 7.3 Decision models

The decision model makes cheap, structured choices so the LLM doesn't have to:

| Decision | Input | Output |
|---|---|---|
| `route` | task + state summary | which LLM role/size handles the next step |
| `retry` | failed step + error | retry / modify-and-retry / give up |
| `escalate` | proposed action + context | proceed / ask human |
| `stop` | trajectory so far | done / continue |
| `tool` | state + tool list | tool to call (optional, harness permitting) |

Implementations: `none`, `rules` (YAML rules, a strong baseline), `llm` (any LLM prompted
with a structured-output schema), and `model` (a small classifier/generator, §11).

**Tuning a decision model** is a tuner stage: after an initial sweep, successful and failed
trajectories are labeled (by outcome and by the judge), a LoRA is trained on top of
`agent-lock/decider`, and the stacks that use it are re-evaluated on the holdout split. The
resulting adapter is content-addressed and pinned in the lock.

Harnesses differ in where they let you intervene. Each adapter declares which decision
hooks it supports (§7.4); the tuner only proposes decision models for supported hooks.

### 7.4 Harness adapters

```python
class HarnessAdapter(Protocol):
    name: str
    supported_decisions: set[Decision]

    def resolve(self, spec: HarnessSpec) -> ResolvedHarness:
        """Pin version/source/integrity. Called at lock time."""

    def materialize(self, stack: Stack, workdir: Path) -> HarnessConfig:
        """Render config, prompts, tool wiring, decision hooks into workdir."""

    async def run(self, task: Task, config: HarnessConfig, sandbox: Sandbox,
                  recorder: TraceRecorder) -> RunResult:
        """Execute one task. Emit trace events through `recorder`."""

    def check(self, locked: LockedHarness, env: Environment) -> list[Violation]:
        """Static verification for `agent-lock check`."""
```

How adapters capture traces and enforce the lock:

- **Proxy mode (default for CLI harnesses: OpenCode, Pi, Codex CLI, Claude Code).** The
  harness is pointed at a local OpenAI/Anthropic-compatible proxy run by agent-lock. The
  proxy records model calls, enforces model/params, injects decision-model hooks, and
  meters cost. MCP traffic goes through an MCP proxy that enforces the allowlist and
  permissions.
- **In-process mode (Python frameworks: LangGraph, PydanticAI, OpenAI Agents SDK,
  Claude Agent SDK).** Instrumentation via the framework's callback/hook APIs plus the proxy
  for model calls.

v0 adapters: `reference`, `opencode`, `pi`, `claude-agent-sdk`, `langgraph`.
v1 adds: `codex-cli`, `pydantic-ai`, `openai-agents`, `hermes`, `crewai`, `custom` (any
command that reads a config and talks to a configurable model endpoint).

The proxy is effectively a small local LLM gateway (routing, metering, policy). That was
considered as a standalone product (Appendix A); here it is an internal component.

### 7.5 Sandboxes

Trials run in a sandbox: `subprocess` (local, least isolation, opt-in), `docker` (default
when Docker is available), or the cluster's container runtime. The sandbox image is pinned
by digest in the lock. Network policy: `none`, `egress-allowlist`, `open`.

---

## 8. Tuning backend (Flyte 2)

### 8.1 Why Flyte, and the one-code-path rule

Every backend runs **the same Flyte 2 program**. Local mode is Flyte's local execution,
not a separate code path. That gives us one implementation of retries, caching,
checkpointing, and fan-out, and makes "move up the dial" a config change, not a port.

`flyte` is a hard dependency of `agent-lock`. It's a pure-Python install and needs no
services for local mode.

### 8.2 The dial

| | `local` | `devbox` | `cluster` (Flyte or Union) |
|---|---|---|---|
| Setup | none | Docker; `agent-lock backend up` wraps `flyte start devbox` | existing cluster + `flyte create config` / config file |
| Where trials run | this Python process (async, bounded concurrency) | containers on the local Flyte devbox | pods on the cluster |
| Durability | local SQLite cache; resume after crash re-uses cached trials | durable run state, object store, survives restarts | durable, shared across users |
| Observability | terminal UI (`--tui`), local reports, `.agentlock/runs/` | Flyte UI at localhost | Flyte/Union UI, shared |
| Parallelism | ~4–16 concurrent trials | bounded by the laptop | hundreds–thousands of trials |
| GPUs | whatever the machine has | `flyte start devbox --gpu` on a CUDA host | GPU node pools: serve open-weights LLMs, train decision models |
| Cache sharing | per machine | per machine | per org/project: teammates reuse each other's trials |
| Good for | first lock in 10 minutes, small packs, API-only models | long runs on one box, overnight sweeps | big search spaces, open-weights serving, fine-tuning, team use |

Switching:

```bash
agent-lock lock                          # local (default)
agent-lock backend up                    # starts a devbox (flyte start devbox) and writes config
agent-lock lock --backend devbox
agent-lock lock --backend cluster        # uses ~/.flyte/config.yaml or [backend] in manifest
```

Under the hood, `--backend local` maps to Flyte local run mode; `devbox` and `cluster` call
`flyte.init(...)` / `flyte.init_from_config(...)` with the corresponding endpoint and then
`flyte.run(...)` the tuning pipeline. agent-lock owns image building for the trial
environment (`flyte.Image`), so users don't write Dockerfiles.

### 8.3 How durability maps onto the tuning pipeline

The tuning pipeline is a Flyte program:

```
lock_pipeline(manifest)                         @env.task
├── resolve_components(manifest)               @env.task  cache  (alias → pinned IDs, versions)
├── build_trial_images(resolved)               flyte.Image builds (devbox/cluster only)
├── for each round (strategy-driven):
│   ├── plan_round(state)                      @env.task  (strategy proposes stacks)
│   ├── run_trials(stacks × tasks × seeds)     fan-out via asyncio.gather / flyte.map
│   │   └── run_trial(stack, task, seed)       @trial_env.task  cache, retries
│   │       ├── model call                     @flyte.trace  (checkpointed; replay on retry)
│   │       ├── tool call                      @flyte.trace
│   │       └── decision call                  @flyte.trace
│   ├── grade_trials(results)                  @env.task  cache
│   └── update_state(grades)                   @env.task
├── train_decision_model(traces)  [optional]   @gpu_env.task  cache
├── evaluate_holdout(finalists)                fan-out of run_trial
├── fingerprint(finalist LLMs)                 @env.task
└── write_lock(winner, evidence)               @env.task → agent.lock + store blobs
```

Durability properties this gives us:

- **Trial-level caching.** `run_trial` is cached on `(stack hash, task hash, seed,
  adapter version)`. Re-running `lock` after a crash, or `update`-ing one component, only
  executes trials that don't exist yet. On a cluster, the cache is shared by the team.
- **Step-level checkpointing.** Model/tool calls inside a trial are `@flyte.trace`d, so a
  retried trial replays completed calls instead of paying for them again.
- **Retries** at the trial level for infra failures (provider 5xx, preemption), kept
  separate from agent-level retries, which are a *policy under test*.
- **Budget enforcement** in `plan_round` and as a hard stop in `run_trial` (spend is
  tracked per trial output; the planner refuses rounds that would exceed `max-spend-usd`).
- **Rate limiting** per provider via bounded concurrency in the fan-out, plus reusable
  containers (`flyte.ReusePolicy`) for trial workers on devbox/cluster to avoid cold starts.
- **Human-in-the-loop** for `human-approval` policies during tuning: by default a
  *simulated* approver (a scripted policy defined by the task pack) so tuning is unattended;
  optionally real approvals through Flyte's human-in-the-loop mechanism on devbox/cluster.
- **Lineage.** Every lock's `provenance.run` points at the Flyte run that produced it,
  and every evidence blob points at the trial outputs.

### 8.4 Search strategies

- `grid`, `random`: small spaces, baselines.
- `successive-halving` / Hyperband: run all candidates on a few tasks, keep the top
  fraction, add tasks. Default for most spaces; this is where cost savings come from.
- `bayesian`: model-based (Optuna-compatible sampler) over mixed categorical/numeric axes.
- `auto`: picks based on space size and budget.
- **Multi-objective.** Every strategy maintains a Pareto front over (quality, cost,
  latency); `[objective]` picks the winner from the front.
- **Statistical guardrails.** Final comparisons use paired bootstrap on the holdout split.
  If the winner isn't distinguishable from the runner-up, the lock records that and
  `select` tie-breaks by cost.

Strategies are pure Python behind a `Strategy` protocol (§9.2), so they're usable without
knowing Flyte.

---

## 9. Layered API

The rule: **each layer down exposes more control and requires more knowledge. Flyte appears
only at Layer 3.** Layers 0–2 import nothing from `flyte` in user code.

```
Layer 0  CLI + agentlock.toml             "I have tasks and API keys"
Layer 1  Python API (agent_lock)          "I want to script and embed this"
Layer 2  Extension points + profiles      "I need custom graders/strategies/adapters/resources"
Layer 3  Flyte-native (agent_lock.flyte)  "I'm composing this into my own Flyte pipelines/infra"
```

### 9.1 Layer 0: CLI

```bash
pip install agent-lock
agent-lock init                       # interactive: pick a pack, providers, harness → agentlock.toml
agent-lock lock                       # tune → agent.lock (+ .agentlock/report.html)
agent-lock show                       # pretty-print the lock + evidence
agent-lock sync                       # install/pin harness, MCP servers, sandbox image, adapters
agent-lock run "fix the failing test in ./repo"     # run the locked agent with runtime guard
agent-lock check                      # static lock verification (CI)
agent-lock verify                     # canary + fingerprint re-check (scheduled CI)
agent-lock update <component>|--all   # partial/full re-resolve
agent-lock diff [--format md]         # structural + evidence diff vs. committed lock
agent-lock export --format docker|flyte|langgraph   # emit a deployable bundle for the locked stack
agent-lock leaderboard [--pack <name>]              # ranked stacks from the last search (Pareto front)
agent-lock tasks new|validate|pull|push
agent-lock traces ls|show|export      # browse traces; export as HF dataset
agent-lock traces replay <trial>      # re-run a trial from its recorded trace (§10.3)
agent-lock traces explain <trial>     # failure triage via agent-lock/triage (§11)
agent-lock backend up|down|status     # devbox lifecycle (wraps flyte start/stop/get devbox)
```

`export` turns the lock into something deployable outside agent-lock, so the result is
an installable domain agent system and not only a leaderboard:

```
dist/
  agent.lock            # copied verbatim; the source of truth
  agent.yaml            # harness-native config rendered from the lock
  policy.yaml           # runtime policies for the guard
  eval_report.md        # evidence, leaderboard, and baseline comparison
  traces/               # holdout traces backing the evidence
  docker-compose.yaml   # --format docker: harness + proxy + sandbox + (optional) vLLM
  flyte_workflow.py     # --format flyte: the agent as a durable Flyte task
  graph.py              # --format langgraph: LangGraph graph whose nodes call the locked models
```

### 9.2 Layer 1: Python API

```python
import agent_lock as al

manifest = al.Manifest.load("agentlock.toml")
lock = al.lock(manifest, backend="local")       # returns al.Lock; writes agent.lock
print(lock.evidence.summary())

# Programmatic manifest
space = al.SearchSpace(
    llm={"planner": ["anthropic:claude-sonnet-latest", "vllm:Qwen/Qwen3-32B"]},
    decision=["none", "hf://agent-lock/decider-1.5b"],
    harness=["opencode", "pi"],
    policy={"retries": [0, 1]},
)
lock = al.lock(
    space,
    tasks=al.TaskPack.pull("agent-lock/data-cleaning"),
    objective=al.Objective(primary="success-rate", select="min-cost",
                           constraints={"success-rate": ">=0.8"}),
    budget=al.Budget(max_spend_usd=50),
    backend="devbox",
)

# Use the lock at runtime
agent = al.load("agent.lock")
result = await agent.run("Clean ./data/orders.csv and report anomalies")
```

`al.lock(...)` returns a handle that can be awaited, watched (`.stream()` yields trial
events), or detached on devbox/cluster (`.url`, `al.attach(url)`).

### 9.3 Layer 2: Extension points and profiles

Still no Flyte imports. Users plug in Python objects that agent-lock schedules for them.

```python
@al.grader("revenue_matches")
def revenue_matches(workspace: al.Workspace, trace: al.Trace) -> al.Grade:
    got = float(workspace.read("answer.txt"))
    return al.Grade(success=abs(got - 1_204_331.17) < 0.01)

class MyStrategy(al.Strategy):
    def propose(self, history: al.History, budget: al.BudgetState) -> list[al.Stack]: ...

@al.adapter("my-harness")
class MyHarness(al.HarnessAdapter): ...
```

**Profiles** describe compute and durability in agent-lock terms, mapped to Flyte by the
backend:

```toml
[backend.profiles.default]
trial = { cpu = 2, memory = "4Gi", concurrency = 32, retries = 2, reuse = { replicas = 8 } }

[backend.profiles.gpu-training]
train = { gpu = "A100:1", memory = "64Gi", timeout = "4h" }
serve = { gpu = "H100:2", engine = "vllm" }      # for open-weights candidates
```

```python
al.lock(manifest, backend="cluster",
        profile=al.Profile(trial=al.Resources(cpu=2, memory="4Gi", concurrency=64)))
```

Profiles are ignored where they don't apply (e.g. resource requests in local mode), matching
Flyte's own behavior.

### 9.4 Layer 3: Flyte-native

For users who want to compose tuning into their own Flyte workflows, run it on a schedule,
use custom images or secrets, or change durability behavior. Here, Flyte knowledge is
expected.

```python
import flyte
from agent_lock.flyte import envs, tasks

# Reuse and customize agent-lock's TaskEnvironments
trial_env = envs.trial.clone_with(
    name="acme_trials",
    image=envs.trial.image.with_pip_packages("acme-internal-tools"),
    secrets=[flyte.Secret(key="ACME_API_KEY")],
    resources=flyte.Resources(cpu=4, memory="8Gi"),
    reusable=flyte.ReusePolicy(replicas=16, idle_ttl=600),
)

env = flyte.TaskEnvironment(name="acme_agent_ops", depends_on=[trial_env, envs.core])

@env.task
async def nightly_relock(manifest_path: str) -> str:
    manifest = await tasks.load_manifest(manifest_path)
    resolved = await tasks.resolve_components(manifest)
    results = await tasks.run_search(resolved, trial_env=trial_env)   # same pipeline, custom env
    lock = await tasks.write_lock(results)
    await open_pr_with_lock(lock)                                       # user's own task
    return lock.hash

if __name__ == "__main__":
    flyte.init_from_config()
    run = flyte.run(nightly_relock, manifest_path="s3://acme/agents/agentlock.toml")
    print(run.url)
```

Layer 3 surface (`agent_lock.flyte`):

- `envs`: `core`, `trial`, `grade`, `train`, `serve`, as `flyte.TaskEnvironment`s.
- `tasks`: every pipeline stage in §8.3, individually importable and composable.
- `images`: the base images, as `flyte.Image` builders.
- `run_trial` as a building block for users who want their own search loop.

**Stability contract.** Layers 0–1 follow semver strictly. Layer 2 is stable from v0.3.
Layer 3 is marked *provisional* until v1.0 and versioned alongside the minimum supported
Flyte 2 version.

---

## 10. Traces and datasets

### 10.1 Trace schema

Built on the OpenTelemetry GenAI semantic conventions, with agent-lock extensions, so traces
can be exported to any OTel backend and imported from OTel-instrumented agents.

```json
{
  "trace_id": "…",
  "trial": { "stack": "sha256:…", "task": "ml-engineering/debug_failed_training_run_014", "seed": 1 },
  "events": [
    { "type": "llm.call", "role": "planner", "model": "claude-sonnet-5-5",
      "input_ref": "sha256:…", "output_ref": "sha256:…",
      "usage": { "input_tokens": 4120, "output_tokens": 611 }, "cost_usd": 0.021, "latency_ms": 2310 },
    { "type": "decision", "kind": "retry", "model": "agent-lock/decider-1.5b",
      "choice": "modify_and_retry", "confidence": 0.81 },
    { "type": "tool.call", "tool": "python", "input_ref": "sha256:…", "output_ref": "sha256:…",
      "status": "error", "error_class": "ModuleNotFoundError", "latency_ms": 840 },
    { "type": "approval", "action": "filesystem.write:/etc/hosts", "outcome": "denied", "by": "simulated" }
  ],
  "result": { "artifacts": ["patch.diff"], "final_ref": "sha256:…" },
  "grades": [ { "grader": "tests:check.py", "success": true, "score": 1.0 } ],
  "metrics": { "steps": 17, "cost_usd": 0.31, "latency_s": 48.2, "retries": 1, "human_interventions": 0 }
}
```

Payloads are content-addressed and stored separately so traces stay small and shareable,
and payloads can be redacted without breaking structure (`agent-lock traces export --redact`).

The trace layer is designed to stand on its own ("OpenTelemetry for agent traces"): the
schema, recorder, and replay are usable without the tuner, so teams can adopt tracing first
and tuning later.

### 10.2 Public datasets (Hugging Face)

- `agent-lock/traces`: traces from tuning runs over the official packs, across many
  stacks. Successes and failures, with grades. The training corpus for §11.
- `agent-lock/failures`: failed trajectories labeled with failure class and the recovery
  step that worked in a sibling trial.
- `agent-lock/tasks-*`: the official task packs (holdout splits withheld).

Users opt in to contributing traces (`agent-lock traces push --public`) with a mandatory
redaction pass. Nothing is uploaded by default.

The trace corpus is likely the most defensible long-term asset: it trains §11's models and
seeds new task packs.

### 10.3 Replay

`agent-lock traces replay <trial>` re-executes a trial using its recorded trace:

- `--mode exact` serves every model and tool response from the trace. This checks
  harness/adapter determinism and is free.
- `--mode from-step N` replays up to step N, then runs live. This is for debugging a
  failure point, or for testing a new decision model or policy against a real prefix.
- `--mode live` re-runs from scratch with the locked stack and compares outcomes.

On devbox and cluster, replay rides on Flyte's `@flyte.trace` checkpoints (§8.3). Locally,
it reads the trace store.

---

## 11. Open-weights models

Small, narrow, permissively licensed (Apache-2.0), released on Hugging Face under
`agent-lock/`, fine-tuned from a permissively licensed small open base model.

| Model | Size (target) | Job | Used by |
|---|---|---|---|
| `agent-lock/decider` | ~0.5B and ~1.5B | Structured decisions: route / retry / escalate / stop / tool | `[decision]` in locks; base for per-project LoRA tuning |
| `agent-lock/judge` | ~7–8B | Rubric grading of trajectories and artifacts, calibrated to human labels | `judge:` graders (default) |
| `agent-lock/triage` | ~1.5B | Classify a failed trace: model vs. harness vs. tool vs. task-spec failure; suggest the fix | `agent-lock traces explain`, tuner analysis |

Design requirements:

- Each runs on CPU (decider) or one consumer GPU (judge), so `local` mode can use them.
- Each ships with a model card, eval results on held-out packs, and the exact training
  recipe as an agent-lock/Flyte pipeline (`agent-lock train decider …`), so anyone can
  reproduce or retrain on their own traces.
- The judge is calibrated against human-labeled grades. Calibration error is reported, and
  the lock records which judge produced the evidence.

Marketing hooks: *"A 1.5B decision model that cuts agent cost by X% at equal success on
Y task packs."* and *"We trained a small model to debug failed agents from their traces."*
(triage). Only claim numbers we can publish with the reproduction pipeline.

These models are deliberately narrow companion artifacts. "We fine-tuned a general
assistant" is neither defensible nor useful here.

---

## 12. Security and safety

- **Secrets** are never written to the lock, traces, or store. Provider keys are resolved
  by name from env/`.env` (local) or the backend's secret store (devbox/cluster).
- **Sandboxing is on by default** for anything that executes code or touches the filesystem.
  `subprocess` sandboxing requires explicit opt-in.
- **Tool permissions** in the lock are least-privilege by default: the tuner only grants
  permissions the manifest lists, and the runtime guard enforces them.
- **Supply chain.** Harnesses and MCP servers are pinned by version and integrity hash;
  sandbox images by digest; models by weights digest. `check` fails on mismatch.
- **Trace hygiene.** Redaction hooks run before any export. Public trace contributions
  require a redaction pass and a license acknowledgment.
- **Safety graders.** Every official pack includes trace graders for exfiltration,
  destructive actions, and approval-bypass. A stack with safety violations can't be selected
  unless the manifest explicitly allows it.

---

## 13. Package layout

```
agent_lock/
  __init__.py            # Layer 1: lock(), load(), Manifest, SearchSpace, Objective, Budget, …
  cli/                   # Layer 0
  manifest/              # agentlock.toml parsing, validation, hashing
  lockfile/              # agent.lock schema, (de)serialization, diff, check
  store/                 # content-addressed blob store (local dir, s3/gcs/azure via fsspec)
  tasks/                 # task packs, graders, splits, Hub client
  providers/             # LLM providers, alias resolution, pricing, fingerprints, serving
  decision/              # rules, llm, model decision backends; training recipes
  adapters/              # harness adapters: reference, opencode, pi, claude_agent_sdk, langgraph, …
  proxy/                 # model proxy + MCP proxy (tracing, enforcement, metering)
  sandbox/               # subprocess, docker, cluster runtimes
  traces/                # schema, recorder, OTel import/export, redaction
  search/                # Strategy protocol + grid/random/halving/bayesian/auto, Pareto, stats
  runtime/               # load(), guard(), run()
  backends/              # Layer 2: Profile/Resources → Flyte mapping; local/devbox/cluster
  flyte/                 # Layer 3: envs, tasks, images (the tuning pipeline)
examples/
  research-agent/        # agentlock.toml + committed agent.lock for each example
  data-analysis-agent/
  code-execution-agent/
```

Install extras: `agent-lock[vllm]`, `agent-lock[train]`, `agent-lock[docker]`,
`agent-lock[all]`. Python ≥ 3.10. Works on macOS, Linux, and Windows (WSL for docker sandbox).

---

## 14. Roadmap

**v0.1: "first lock in 10 minutes"** (local only)
- `init`, `lock`, `show`, `check`, `run` · `agent.lock` schema v1
- Adapters: `reference`, `opencode`, `claude-agent-sdk`
- API providers only; grid/random/successive-halving; tests + judge graders (judge = any LLM)
- One official pack: `research-analyst`
- Flyte local execution with trial caching and resume

**v0.2: "durable and updateable"**
- `devbox` backend, `backend up/down`, Flyte UI links in output
- `update`, `diff --format md`, `verify` with fingerprints
- Adapters: `pi`, `langgraph` · packs: `data-cleaning`, `ml-engineering`
- Docker sandbox default · trace export to OTel and HF

**v0.3: "decision models"**
- `agent-lock/decider` + `agent-lock/judge` released · decision-model tuning stage
- Layer 2 extension points stable · profiles
- `tasks new --from-traces`

**v0.4: "scale"**
- `cluster` backend (self-hosted Flyte and Union) · shared team cache
- Open-weights candidates served on demand (vLLM/SGLang) · LoRA tuning of executor LLMs
- `agent-lock/triage` · public `agent-lock/traces` dataset · leaderboard site per pack

**v1.0**
- Lock schema v1 frozen · Layer 3 stable · `export` targets · 10+ adapters · 8+ packs

---

## 15. Launch, positioning, and success metrics

### 15.1 Taglines

- *Lock your agent into place.*
- *Don't pick an agent framework. Benchmark your domain and lock the stack.*
- *Stop vibe-checking agents. Replay, evaluate, and lock them.*
- *AutoML for agent harnesses, tool-use policies, and workflow architectures.*

### 15.2 The demo

**"We tuned an AI data analyst for your company in 20 minutes."**

1. Start from 20–50 domain tasks (an official pack, or `tasks new --from-traces`).
2. agent-lock tries stacks such as frontier LLM + LangGraph, Claude + OpenCode, Qwen +
   custom workflow, small decider + big-model fallback, and local model on a cluster backend.
3. `agent-lock leaderboard` shows the Pareto front.
4. The findings are the story. Illustrative examples of what we expect to show:
   - the frontier-only stack is best but expensive,
   - an open model + decision model gets ~90% of the quality at a fraction of the cost,
   - OpenCode beats generic tool-calling on code-edit tasks,
   - a deterministic workflow beats an agent loop for repeatable data prep.
5. `agent-lock lock` writes `agent.lock`. `export` ships it. The lock lands in a PR.

The illustrative numbers must be replaced with real, reproducible results before launch.

### 15.3 Shareable comparisons

Per-pack leaderboards produce charts and debate:

- "Claude vs GPT vs Qwen on real agent workflows."
- "LangGraph vs OpenCode vs Pi on the same tasks."
- "Which agent stack survives tool failures?"
- "Your agent isn't production-ready until it has an `agent.lock`."

### 15.4 Launch artifacts

GitHub repo · PyPI package · HF models (§11) · HF datasets (§10.2) · official task packs ·
per-pack leaderboard · three example agents (research, data analysis, code execution) ·
Flyte/Union cluster backend docs.

### 15.5 Success metrics

- Time from `pip install` to first `agent.lock` on the local backend: **< 10 minutes**.
- `agent.lock` files in public GitHub repos (search `filename:agent.lock lock-version`).
- Community task packs and adapters published.
- Downloads of `agent-lock/decider` and `agent-lock/judge`.
- Share of locks produced on devbox/cluster backends (the dial is working).
- Published case studies where a locked stack matched frontier-only quality at materially
  lower cost.

---

## 16. Open questions

1. **Name collision.** Is `agent.lock` safe from collisions with other tools' lockfiles?
   Should it be `agentlock.lock` for symmetry with `agentlock.toml`?
2. **Lock scope.** One lock per agent, or a multi-agent lock (`[[agent]]` tables) for systems
   with several cooperating agents?
3. **Prompt optimization.** Should system-prompt search (DSPy/GEPA-style) be a v1 search
   axis or remain user-supplied candidates?
4. **Workflow compilation.** Compile repeated successful trajectories into deterministic
   Flyte workflows, so steps that don't need to be agentic stop being agentic, and
   generate a workflow from a task plan. That's a strong differentiator (and a natural use
   of the triage model and trace corpus) but a large scope. Treat it as a post-v1
   `agent-lock compile` command, with the compiled workflow becoming a lockable
   `harness = "workflow:…"` candidate?
5. **Closed-model drift policy.** When a provider retires a pinned model ID, should
   `verify` auto-propose an `update`, or only fail?
6. **Judge trust.** How much of the evidence may come from judge graders before the lock
   is flagged "low-confidence"?
7. **Hub.** Host task packs and locks on Hugging Face only, or run a small registry with
   a leaderboard per pack?
8. **Harness licensing.** Some harnesses have restrictive terms for automated or benchmark
   use. We need a per-adapter compliance note before publishing leaderboards.

---

## Appendix A. Concept history and alternatives considered

agent-lock came out of an exploration of which customer problems could be fully or mostly
solved by an open artifact (model, dataset, harness, or installable system) that anyone
could try, not just Union customers.

**Evolution of the concept:**

1. **TraceForge / HarnessBench**: an open benchmark and runtime kit. A lightweight local
   harness, a public agent-trace dataset, and a benchmark measuring completion, tool-use
   correctness, recovery, cost, latency, determinism, replayability, and human-intervention
   rate, with a Flyte/Union backend for durable runs. *Kept as:* the trace layer (§10), the
   task packs and graders (§7.1), and leaderboards (§15.3).
2. **HarnessForge**: reframed from "evaluate and replay agents" to "produce the best
   domain-specialized agent system". It tunes LLM + decision model + harness + tools +
   policy against domain task packs and exports the winner. TraceForge became its data
   layer. *Kept as:* the tuner (§8), the manifest search space (§6), decision models (§7.3),
   and `export` (§9.1).
3. **agent-lock**: adds the missing piece, a sharable, enforceable, version-controlled
   result. The lockfile turns a one-time optimization into something you can commit,
   review, verify in CI, and update incrementally. It also adds the local → devbox →
   cluster dial and the layered API, so the tool is useful without any infrastructure.

**Alternatives considered:**

| Option | Artifact | Verdict |
|---|---|---|
| Agent benchmark + trace dataset | repo + dataset + benchmark | High reach; folded in as §7.1, §10, §15.3 |
| Private model-factory template | repo + workflows | Strong Union fit, but a template rather than a product; candidate future example |
| Local LLM gateway proxy | installable system | Crowded market; folded in as an internal component (§7.4 proxy) |
| Fine-tuned workflow-repair model | model + dataset | Best as a companion artifact; became `agent-lock/triage` (§11) |
| Standalone research-agent app | app/harness | Good demo but less differentiated; became an example agent + the first task pack |
