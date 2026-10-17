# Harnesses

hlock knows about the agent harnesses people actually use, and lets you say which one a lock
is for. Each harness is described by a [profile](harness-profiles.md), so hlock knows where
it keeps its config, model, MCP servers, skills and plugins, and how it was installed.

## What's on this machine

```console
$ hlock harness list
Agent CLIs
   harness       installed           source                              support
●  claude-code   2.1.285             brew-cask:claude-code@2.1.285       full
   codex         —                                                       full
   pi            1.0.0               npm:@earendil-works/pi-coding-agen  full
                                     t@1.0.0
   opencode      1.18.18             brew:opencode@1.18.18               full
   hermes        0.20.0              script@0.20.0                       full
   cursor-agent  2026.05.28-a70ca7c  script@2026.05.28-a70ca7c           full
   gemini-cli    —                                                       basic
   copilot-cli   —                                                       basic
   goose         —                                                       basic
   amp           —                                                       basic

Frameworks
  harness           installed  source
  pydantic-ai       —
  deepagents        —
  …

● you're running inside Claude Code
```

The `●` marks the harness hlock is running inside, detected from the variables each harness
sets in the processes it spawns. `source` is how the installed copy was installed, which is
what a lock pins. `full` profiles are covered by tests for every harness-aware command;
`basic` ones cover detection, version, MCP servers and skills.

| Kind | Harnesses |
|---|---|
| Agent CLIs | `claude-code` (`claude`), `codex`, `pi`, `opencode`, `hermes`, `cursor-agent` (`cursor`), `gemini-cli`, `copilot-cli`, `goose`, `amp` |
| Frameworks | `pydantic-ai`, `deepagents`, `langgraph`, `openai-agents`, `claude-agent-sdk`, `google-adk`, `smolagents`, `crewai` |

`hlock harness show <name>` prints a profile and the exact paths it resolves to here:

```console
$ hlock harness show pi
╭─ Pi ─────────────────────────────────────────────────────────────────────╮
│  id                       pi  pi-coding-agent, pi-agent                  │
│  kind                     cli                                            │
│  support                  full                                           │
│  installed                1.0.0  /Users/you/.nvm/versions/node/v22…/pi   │
│  source                   npm:@earendil-works/pi-coding-agent@1.0.0      │
│  config root              /Users/you/.pi/agent  ($PI_CODING_AGENT_DIR)   │
│  file · mcp               /Users/you/.pi/agent/mcp.json                  │
│  file · models            /Users/you/.pi/agent/models.json               │
│  file · settings          /Users/you/.pi/agent/settings.json             │
│  skills                   /Users/you/.pi/agent/skills                    │
│  …                                                                       │
╰──────────────────────────────────────────────────────────────────────────╯
```

`hlock runtime list` does the same for local inference runtimes (Ollama, LM Studio,
llama.cpp, vLLM, SGLang, MLX LM, LocalAI, Docker Model Runner, Jan).

## Target a harness

Put the harness a lock is for in the manifest:

```toml
[target]
harness = "claude-code"        # an id or alias: claude, codex, pi, opencode, …
```

It belongs in `harness.toml` rather than only on the command line because it changes what
the lock means, and the manifest hash covers it. `hlock init` writes it for you when you run
it inside a harness, or when you pass `--harness`:

```console
$ hlock init --pack ./tasks --harness claude
✓ wrote harness.toml  (project 'demo', task pack ./tasks)
target claude-code  (--harness)
next → hlock resolve
```

Commands that act on a harness pick it in this order:

1. `--harness <name>`
2. the `HLOCK_HARNESS` environment variable
3. `[target] harness` in `harness.toml`
4. the harness hlock is running inside
5. the only harness installed on `PATH`

The flag is `--harness`, not `--target`, because `[backend] target` already names the
execution backend.

## Resolve for a target

With a target, `resolve` narrows `[candidates] harness` to it. With no harness candidates,
or only the default `reference`, the target becomes the only candidate; otherwise it has to
be one of them. The lock's `[harness]` pins the version and install source of the copy on
this machine:

```console
$ hlock resolve
✓ wrote harness.lock
╭─ 🔒 harness.lock ────────────────────────╮
│  Stack                                   │
│  harness        claude-code 2.1.285      │
│  llm · planner  reference:qwen-7b        │
│  …                                       │
╰──────────────────────────────────────────╯
! trials ran on the reference adapter; native claude-code execution isn't built yet, so
the evidence is a stand-in
```

hlock can't drive agent CLIs inside trials yet, so trials run on the backend's adapter, and
`[harness] adapter` in the lock records which one. `hlock resolve --harness <name>` overrides
the target for one run and reminds you to record it in `harness.toml`.

`hlock check` then also fails when:

- the lock is for a different harness than `[target]`, or
- the installed harness version differs from the version the lock pins.

A harness that isn't installed (on a CI runner, say) skips the version check.

## Your own agent: frameworks and custom scripts

Agents built on a framework, or written from scratch, are declared in the manifest as
**project harnesses**:

```toml
[target]
harness = "triage"

[harnesses.triage]
framework = "pydantic-ai"            # pins the framework's packages
entrypoint = "triage.agent:run"      # a Python module:callable

[harnesses.loop]
command = ["./bin/agent", "--model", "{model}", "{prompt}"]   # or any executable
packages = ["pypi:httpx"]
```

A project harness needs an `entrypoint` or a `command`. `framework` names a framework
profile, whose packages are added to `packages`; `hlock harness show triage` lists each
package with the version installed in the Python that `HL_PYTHON` (or `python3`) points at.
Project harnesses appear in `hlock harness list` and can be targeted like any other.

## Add a harness hlock doesn't know

Write a profile. See [Harness profiles](harness-profiles.md).
