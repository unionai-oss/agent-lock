# Harness profiles

A profile is a TOML file that describes one harness or one local inference runtime. hlock's
harness-aware commands read profiles instead of hard-coding each harness, so supporting a
new harness, or fixing a path for an existing one, means editing a file.

!!! note "What reads which fields"

    Profiles drive detection, versions and install sources, `hlock harness show`, targeting,
    [`hlock pin`](pin.md) (`model`, `providers`, `mcp`, `skills`, `bundles`, `instructions`,
    `files`), and [`hlock sync`](sync.md) (`install`, `files`, `skills.write`,
    `config-root`). The `launch` and `run` fields are for the upcoming `hlock launch` (design:
    [SPEC §7.8](https://github.com/unionai-oss/hlock/blob/main/SPEC.md)).

## Where profiles come from

Built-in profiles ship with hlock (source:
[`crates/harness-lock-core/profiles`](https://github.com/unionai-oss/hlock/tree/main/crates/harness-lock-core/profiles)).
hlock then reads these directories, lowest precedence first:

1. `~/.config/hlock/profiles/`
2. each directory in `HLOCK_PROFILE_PATH` (`:`-separated)
3. `./.hlock/profiles/`

Each directory holds `harnesses/*.toml` and `runtimes/*.toml`. A profile with the same `id`
as an earlier one replaces it, so you can override a built-in. `hlock harness show <name>`
prints where the active profile came from.

## A harness profile

```toml
id = "my-agent"
name = "My Agent"
kind = "cli"                       # cli | framework | custom
aliases = ["myagent"]
binaries = ["my-agent"]
version = { args = ["--version"] }
active-env = ["MY_AGENT_SESSION"]  # set by the harness in the processes it spawns
config-root = { env = "MY_AGENT_HOME", default = "~/.my-agent" }
instructions = ["AGENTS.md", "{root}/AGENTS.md"]

[[install]]
method = "npm"                     # npm | brew | brew-cask | pip | uv-tool | script | app | manual
package = "my-agent"
[[install]]
method = "script"
command = "curl -fsSL https://example.com/install.sh | bash"
path-hints = ["/.my-agent/bin/"]   # identifies this method from the binary's real path

[files.settings]
path = "{root}/settings.json"
format = "json"                    # json | jsonc | toml | yaml
restore = "whole"                  # whole | pointers | record

[model]
default = ["env:MY_AGENT_MODEL", "settings#/model"]
provider = ["settings#/provider"]

[mcp]
sources = ["settings#/mcpServers"]
write = "settings#/mcpServers"

[skills]
dirs = ["{root}/skills", ".my-agent/skills"]
write = "{root}/skills"

[launch]
model-flag = "--model"
```

### Paths

`~` is your home directory and `{root}` is the config root. A relative path is relative to
the project (the current directory). `config-root.env` is the variable that relocates the
root; when it names a parent directory (like `XDG_CONFIG_HOME`), add
`suffix = "<subdir>"`. A file that lives outside the root by default but inside it when the
root is relocated (Claude Code's `~/.claude.json`) sets `isolated = "{root}/…"`.

### Sources

`model`, `mcp` and `providers` take ordered lists of sources, and the first one that has a
value wins:

- `env:VAR` reads an environment variable.
- `<file>#<pointer>` reads a value from a named file in `[files]`, where `<pointer>` is a
  [JSON pointer](https://datatracker.ietf.org/doc/html/rfc6901), applied to TOML and YAML
  files as if they were JSON. `{cwd}` inside a pointer is replaced with the escaped project
  path (Claude Code keeps per-project MCP servers under `/projects/{cwd}/mcpServers`).

Set `model.format = "provider/model"` when the model value carries its provider (OpenCode's
`anthropic/claude-sonnet-4-5`), or `model.default-provider` when the harness only talks to one.

### Restore policies

`restore` says what a file contributes to a locked setup: `whole` (the whole file),
`pointers` (only the subtrees listed in `pointers`, for files that also hold unrelated state),
or `record` (a digest only, for project files that are already in git).

### Field reference

| Field | Meaning |
|---|---|
| `id`, `name`, `aliases` | Identity; any alias works wherever a harness name does |
| `kind` | `cli`, `framework`, or `custom` (default: `cli`, or `custom` with `run`) |
| `support` | `full` or `basic` (default `basic`) |
| `vendor`, `homepage` | Informational |
| `binaries` | Names to look up on `PATH`, in order |
| `version.args` | Arguments that print the version; the first dotted number is used |
| `active-env` | Variables whose presence means hlock runs inside this harness |
| `config-root` | `env`, `suffix`, `default` |
| `install` | Install methods, most preferred first: `method`, `package`, `command`, `path-hints` |
| `files.<id>` | `path`, `isolated`, `format`, `restore`, `pointers` |
| `model` | `default`, `small`, `provider`, `base-url` sources; `format`; `default-provider` |
| `providers` | `source`, plus pointers into each provider for `base-url` and `models` |
| `mcp` | `sources`, `write` |
| `skills` | `dirs`, `write`, `builtin-dirs`, `builtin-manifest` |
| `bundles` | Plugins/packages: `kind`, `extractor` (`claude-plugins`, `pi-packages`, `npm-list`), `source`, `lockfile` |
| `instructions` | Instruction files the harness reads |
| `launch` | `args`, `model-flag` |
| `packages` | Packages to pin for code harnesses, e.g. `pypi:pydantic-ai` |
| `framework` | For `custom` harnesses: a framework profile to inherit packages from |
| `run` | For code harnesses: `entrypoint`, `command`, `python`, `env` |

## A runtime profile

```toml
id = "my-runtime"
name = "My Runtime"
binaries = ["myrt"]
version = { args = ["--version"] }
ports = [9000]                          # recognizes a provider base URL like http://localhost:9000/v1
provider-names = ["myrt"]               # provider names harness configs use for it
pull = "myrt pull {model}"
serve = "myrt serve"

[models]
layout = "hf-cache"                     # ollama | publisher-repo | hf-cache
dirs = ["env:MYRT_MODELS", "~/.myrt/models"]

[[install]]
method = "brew"
package = "myrt"
```

## Project harnesses

Agents you write yourself don't need a profile file: declare them under
`[harnesses.<id>]` in `harness.toml` (see [Harnesses](harnesses.md#your-own-agent-frameworks-and-custom-scripts)).
They accept every harness-profile field, plus `entrypoint`, `command`, `python` and `env` at
the top level of the table.

If you write a profile for a harness others use, please contribute it.
