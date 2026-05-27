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

"""Configuration system for arche.

Usage:
    from arche.config import configure, get_config
    configure(similarity_threshold=0.90, safe_logging=True)
    config = get_config()
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class ArcheConfig:
    """Global configuration for the arche pipeline.

    All thresholds and settings that were previously hardcoded are
    configurable here.
    """

    # Entity extraction
    # Primary: gliner_multi_pii-v1 — PII-focused model with 30 entity types
    # including first_name, last_name, street_address, city, occupation.
    # The PII model's tax_id attempts on NIN/BVN are harmlessly overridden
    # by our deterministic African ID validators (adjudication layer ensures
    # checksum-validated IDs always win over statistical guesses).
    gliner_model: str = "urchade/gliner_multi_pii-v1"
    # Fallback: medium-v2.1 is a general-purpose model that works with
    # broader labels (person, organization, location). Less granular but
    # still useful for name/org/location detection.
    gliner_fallback_model: str = "urchade/gliner_medium-v2.1"
    gliner_threshold: float = 0.35

    # Entity resolution
    similarity_threshold: float = 0.80

    # Location / gazetteer
    gazetteer_score_cutoff: int = 70

    # National ID detection
    id_context_window: int = 80

    # Input validation
    max_text_length: int = 500_000

    # PII safety
    safe_logging: bool = True

    # LLM (optional, only used when backend="auto+llm")
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"
    llm_api_key: str | None = None        # None = read from provider env var
    llm_base_url: str | None = None       # Override for Ollama/custom endpoints
    llm_temperature: float = 0.0          # Deterministic by default
    llm_timeout: float = 30.0


_config = ArcheConfig()


def get_config() -> ArcheConfig:
    """Return the current global configuration."""
    return _config


def configure(**kwargs: object) -> None:
    """Update global configuration.

    Example::

        configure(similarity_threshold=0.90, max_text_length=1_000_000)

    Raises
    ------
    TypeError
        If a value has the wrong type for its field.
    """
    global _config
    # Validate types before replacing
    import dataclasses

    field_types = {f.name: f.type for f in dataclasses.fields(ArcheConfig)}
    for key, val in kwargs.items():
        if key not in field_types:
            raise TypeError(f"Unknown config field: {key}")
        expected = field_types[key]
        if expected == "float" and not isinstance(val, (int, float)):
            raise TypeError(f"configure({key}=...): expected float, got {type(val).__name__}")
        if expected == "int" and not isinstance(val, int):
            raise TypeError(f"configure({key}=...): expected int, got {type(val).__name__}")
        if expected == "bool" and not isinstance(val, bool):
            raise TypeError(f"configure({key}=...): expected bool, got {type(val).__name__}")
        if expected == "str" and not isinstance(val, str):
            raise TypeError(f"configure({key}=...): expected str, got {type(val).__name__}")
    _config = replace(_config, **kwargs)
