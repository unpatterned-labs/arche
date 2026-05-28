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


__all__ = ["LLMConfig"]
