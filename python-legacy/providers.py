"""LLM providers.

A thin provider layer in front of LiteLLM (or a deterministic reference provider
for local no-account testing). Providers resolve aliases to pinned model IDs,
meter cost, and can probe behavioral fingerprints.

The ``reference`` provider produces deterministic outputs from input hashes so the
whole tuner loop runs with zero setup and no API keys. Provider selection for real
LLMs is wired here so adapters stay provider-agnostic.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from hpm.errors import AgentLockError, content_hash

PLANNER = "planner"
EXECUTOR = "executor"


class ProviderError(AgentLockError):
    pass


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class ProviderResponse:
    role: str
    content: str
    usage: Usage = field(default_factory=Usage)
    cost_usd: float = 0.0
    latency_ms: float = 0.0


@runtime_checkable
class Provider(Protocol):
    name: str

    def resolve_alias(self, alias: str) -> tuple[str, str]:
        """Resolve a manifest alias like ``anthropic:claude-sonnet-latest`` to a
        pinned ``(provider, model_id)`` pair (dropping moving ``-latest`` refs)."""
        ...

    def complete(self, model: str, messages: list[dict], **params: Any) -> ProviderResponse: ...
    def fingerprint(self, model: str) -> str: ...


# --------------------------------------------------------------------------- #
# Reference (deterministic) provider
# --------------------------------------------------------------------------- #
class ReferenceProvider:
    """Deterministic, offline provider used for local no-account testing.

    It "succeeds" more often for certain model aliases so the tuner can
    discriminate between candidate configurations and produce a real-looking
    leaderboard + lock, without any network or API key.
    """

    name = "reference"

    # Model alias -> (provider, pinned id, quality score in [0,1])
    _QUALITY = {
        "qwen-1.5b": ("vllm", "Qwen/Qwen1.5B", 0.55),
        "qwen-7b": ("vllm", "Qwen/Qwen2.5-7B", 0.75),
        "qwen-32b": ("vllm", "Qwen/Qwen3-32B", 0.88),
    }

    def __init__(self, seed: int = 0) -> None:
        self.seed = seed

    def resolve_alias(self, alias: str) -> tuple[str, str]:
        # manifest aliases look like "provider:model" — for the reference we map
        # friendly ids to pinned specs.
        if ":" in alias:
            prov, model = alias.split(":", 1)
            if prov != "reference":
                # keep the provider tag but pin a stable id
                return prov, model
        return "reference", alias

    def _quality(self, model: str) -> float:
        if model in self._QUALITY:
            return self._QUALITY[model][2]
        # deterministic pseudo-quality from the model id
        h = int(hashlib.sha256(model.encode()).hexdigest()[:8], 16)
        return 0.4 + (h % 5000) / 10000.0

    def complete(self, model: str, messages: list[dict], **params: Any) -> ProviderResponse:
        import random

        rng = random.Random(self.seed + sum(len(m.get("content", "")) for m in messages))
        q = self._quality(model)
        # Higher-quality models "answer correctly" more often.
        succeeded = rng.random() < q
        content = ("ANSWER_OK" if succeeded else "ANSWER_UNCERTAIN") + f"|{model}"
        usage = Usage(input_tokens=200, output_tokens=50)
        return ProviderResponse(
            role="assistant",
            content=content,
            usage=usage,
            cost_usd=round(0.0001 * (1.0 if "32" not in model else 4.0), 6),
            latency_ms=round(100 + rng.random() * 800, 1),
        )

    def fingerprint(self, model: str) -> str:
        return f"sha256:{content_hash({'provider': 'reference', 'model': model})}"


@runtime_checkable
class ProviderRegistry(Protocol):
    def get(self, name: str) -> Provider: ...


class _Registry:
    def __init__(self) -> None:
        self._providers: dict[str, Any] = {"reference": ReferenceProvider()}

    def register(self, provider: Provider) -> None:
        self._providers[provider.name] = provider

    def get(self, name: str) -> Provider:
        if name not in self._providers:
            raise ProviderError(f"unknown provider: {name!r}")
        return self._providers[name]

    def names(self) -> list[str]:
        return sorted(self._providers)


PROVIDERS = _Registry()
