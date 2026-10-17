# Environment variables

`hlock` reads these variables. Only the worker (the `devbox` and `cluster`
[backends](../guides/backends.md)) uses them. The `local` backend ignores them all.

## Worker

| Variable | Default | Description |
|---|---|---|
| `HL_PYTHON` | `python3` | Interpreter the Rust core uses to launch the worker. Point it at one with `hlock` installed. |

## LLM calls

Set these to call a real model through any OpenAI-compatible endpoint. Without
`HL_LLM_BASE_URL`, the worker uses a deterministic offline reference LLM.

| Variable | Default | Description |
|---|---|---|
| `HL_LLM_BASE_URL` | unset | Base URL of an OpenAI-compatible API, e.g. `http://localhost:8000/v1` |
| `HL_LLM_MODEL` | unset | Model name to request |
| `HL_LLM_API_KEY` | unset | API key, if the endpoint needs one |

## Fine-tuning

Used by `hlock optimize --depth ft` and `--depth full`.

| Variable | Default | Description |
|---|---|---|
| `HL_FT_BASE_MODEL` | `Qwen/Qwen2-0.5B` | Base model for LoRA fine-tuning |
| `HL_FT_STEPS` | `3` | Training steps |
| `HL_GPU_COST_PER_H` | `2.0` | GPU price per hour in USD, used for cost evidence |

## Output

| Variable | Description |
|---|---|
| `NO_COLOR` | Any value turns off colored CLI output |

`hlock backend status` shows which of these are set. API keys are reported as set or
unset, never printed.
