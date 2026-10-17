# Contributing to hlock

Thanks for helping out! The contributing guide lives in the docs:
**<https://unionai-oss.github.io/hlock/project/contributing/>**
(source: [`docs/project/contributing.md`](docs/project/contributing.md)).

Quick version:

```bash
uv sync
uv run pytest
uv run ruff check harness_lock tests packaging/hlock
cargo test -p harness-lock-core
```

Open an issue before starting anything larger than a small fix. Coding agents:
read [`AGENTS.md`](AGENTS.md) first.
