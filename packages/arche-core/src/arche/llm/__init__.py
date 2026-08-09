# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

# Copyright 2026 unpatterned.org
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""LLM provider abstraction for arche.

LLMs are an **additional proposer** — they feed into the same validation
pipeline as GliNER and regex.  The design principle:

    LLM proposes entities (fuzzy, improving over time)
        |
    arche validates (deterministic, checksums, format, typed -- ALWAYS runs)
        |
    Output is always IdentityEvidence with validator_status -- deterministic regardless of source

Providers are loaded lazily.  No imports happen until a user calls an
LLM-backed function.  The base package has zero LLM dependencies.

Supported providers:
    - "openai"    -> uses the openai Python SDK (pip install arche-core[llm])
    - "anthropic" -> uses the anthropic Python SDK (pip install arche-core[llm])
    - "ollama"    -> uses HTTP calls to local Ollama (no extra deps)
    - "litellm"   -> uses litellm for 100+ providers (pip install arche-core[litellm])
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


_VALID_PROVIDERS = {"openai", "anthropic", "ollama", "litellm"}


@dataclass(frozen=True)
class LLMConfig:
    """Configuration for an LLM provider.

    Passed to ``detect()``, ``extract()``, or ``resolve()`` when
    ``backend="auto+llm"``.  The LLM acts as an additional proposer
    alongside GliNER and regex -- all proposals flow through the same
    deterministic validators.

    Parameters
    ----------
    provider:
        One of ``"openai"``, ``"anthropic"``, ``"ollama"``, ``"litellm"``.
    model:
        Model name (provider-specific).  Defaults to ``"gpt-4o-mini"``.
    api_key:
        API key.  ``None`` reads from the provider's environment variable
        (``OPENAI_API_KEY``, ``ANTHROPIC_API_KEY``, etc.).
    base_url:
        Override for Ollama or custom-hosted endpoints.
    temperature:
        Sampling temperature.  ``0.0`` (default) for determinism.
    max_tokens:
        Maximum tokens in the LLM response.
    timeout:
        HTTP timeout in seconds.
    extra:
        Extra keyword arguments forwarded to the provider SDK.
    """

    provider: str = "openai"
    model: str = "gpt-4o-mini"
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 0.0
    max_tokens: int = 4096
    timeout: float = 30.0
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.provider not in _VALID_PROVIDERS:
            raise ValueError(
                f"Unknown LLM provider: {self.provider!r}. "
                f"Supported: {', '.join(sorted(_VALID_PROVIDERS))}"
            )
        if self.temperature < 0.0 or self.temperature > 2.0:
            raise ValueError(
                f"temperature must be between 0.0 and 2.0, got {self.temperature}"
            )
        if self.max_tokens < 1:
            raise ValueError(f"max_tokens must be >= 1, got {self.max_tokens}")
        if self.timeout <= 0:
            raise ValueError(f"timeout must be > 0, got {self.timeout}")


__all__ = [
    "LLMConfig",
    # Declaration-driven extraction (LLM lane).
    "DeclaredExtraction",
    "build_messages",
    "extract_declared",
    # The evaluation harness. HarnessReport and Divergence are what
    # grade_pairs returns, so they have to be importable from here — you
    # cannot annotate a function against a type you cannot name.
    "Divergence",
    "HarnessReport",
    "grade_extractions",
    "grade_pairs",
    # Spatial role extraction.
    "LLMPlaceExtraction",
    "build_places_messages",
    "extract_places_llm",
]

# Which submodule each lazily-loaded public name lives in. Keeping this as
# data rather than a chain of `if name in (...)` branches means __getattr__
# and __dir__ cannot disagree about what the module exports.
_LAZY: dict[str, str] = {
    "DeclaredExtraction": "declarative",
    "build_messages": "declarative",
    "extract_declared": "declarative",
    "Divergence": "harness",
    "HarnessReport": "harness",
    "grade_extractions": "harness",
    "grade_pairs": "harness",
    "LLMPlaceExtraction": "spatial",
    "build_places_messages": "spatial",
    "extract_places_llm": "spatial",
}


def __getattr__(name):  # lazy: keep base import light, avoid cycles
    module = _LAZY.get(name)
    if module is not None:
        import importlib

        return getattr(importlib.import_module(f"arche.llm.{module}"), name)
    raise AttributeError(f"module 'arche.llm' has no attribute {name!r}")


def __dir__() -> list[str]:
    """The public surface, plus the submodules callers import directly.

    Python's default module ``dir()`` reads ``__dict__``, so nothing reached
    through ``__getattr__`` appears until it has already been imported. That
    left ``dir(arche.llm)`` showing ``LLMConfig`` beside implementation
    imports like ``dataclass``, ``field`` and ``Any``, and none of the actual
    API — unhelpful at a REPL and invisible to tab-completion.

    The result is deterministic: it does not change as a side effect of which
    submodules happen to have been imported already.
    """
    return sorted(set(__all__) | {"declarative", "harness", "providers", "spatial"})
