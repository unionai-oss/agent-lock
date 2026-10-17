# Installation

`hlock` ships as a Python package with a compiled Rust core. Prebuilt wheels cover:

| Platform | Architectures |
|---|---|
| Linux (manylinux) | x86_64, aarch64 |
| macOS | arm64 (Apple silicon), x86_64 (Intel) |
| Windows | x64 |

One wheel per platform covers **CPython 3.9 and newer** (abi3). On other platforms,
pip builds from the source distribution, which needs a [Rust toolchain](https://rustup.rs).

## Install the CLI and Python package

=== "pip"

    ```bash
    pip install hlock
    ```

=== "uv"

    ```bash
    uv add hlock            # add to a project
    uv tool install hlock   # or install the CLI globally
    ```

=== "uvx (no install)"

    ```bash
    uvx hlock --help
    ```

=== "pipx"

    ```bash
    pipx install hlock
    ```

Check that it worked:

```console
$ hlock --version
hlock, version 0.1.2
```

!!! info "`hlock` and `harness-lock` are the same package"

    `hlock` is the short name for [`harness-lock`](https://pypi.org/project/harness-lock/).
    Each `hlock` release pins the identical `harness-lock` release, so installing either
    name gives you the same `hlock` command and the same API: `import hlock` and
    `import harness_lock` are interchangeable. These docs use `hlock` everywhere.

## Optional extras

| Extra | Install | Adds |
|---|---|---|
| `flyte` | `pip install "hlock[flyte]"` | `flyteplugins-rs`, so the [`cluster` backend](../guides/backends.md) can lift work to Flyte/Union tasks |

The worker that runs heavy optimization stages (`devbox` and `cluster` backends) imports
`pandas`/`polars`, `torch`/`peft`/`trl`, and `flyte` lazily, and only when a stage needs
them. Install those in the worker's environment when you use the stages that need them;
see [Backends](../guides/backends.md).

## Use it from Rust

The core library is published on crates.io under the same names:

```bash
cargo add hlock               # or: cargo add harness-lock
```

Both crates re-export [`harness-lock-core`](https://crates.io/crates/harness-lock-core).
See the [Rust API](../reference/rust-api.md) reference for an example and the key types.

## Build from source

See [Development](../project/development.md).
