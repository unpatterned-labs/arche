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

"""LLM provider dispatch -- thin wrappers around provider SDKs.

Each provider implements one function: send a list of messages, get a
string back.  No agents, no chains, no tools.  A completion call.

Design decisions:
    - No framework dependency.  We call ``openai.OpenAI()`` and
      ``anthropic.Anthropic()`` directly.
    - Ollama uses stdlib ``urllib`` -- zero extra dependencies.
    - LiteLLM is the escape hatch for 100+ providers.
    - JSON mode is requested from every provider for structured output.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import LLMConfig

_log = logging.getLogger("arche.llm")


def complete(config: LLMConfig, messages: list[dict[str, str]]) -> str:
    """Send a chat completion request to the configured LLM provider.

    Returns the assistant's response text.  Raises on API errors.
    This is the only function that touches provider SDKs.

    Parameters
    ----------
    config:
        Provider configuration (model, API key, etc.).
    messages:
        Chat messages in OpenAI format (list of ``{"role": ..., "content": ...}``).

    Returns
    -------
    str
        The assistant's response text.

    Raises
    ------
    RuntimeError
        If the provider SDK is not installed or the API call fails.
    """
    if config.provider == "openai":
        return _complete_openai(config, messages)
    elif config.provider == "anthropic":
        return _complete_anthropic(config, messages)
    elif config.provider == "ollama":
        return _complete_ollama(config, messages)
    elif config.provider == "litellm":
        return _complete_litellm(config, messages)
    else:
        raise ValueError(f"Unknown provider: {config.provider!r}")


def _complete_openai(config: LLMConfig, messages: list[dict[str, str]]) -> str:
    """OpenAI / Azure OpenAI completion."""
    try:
        import openai  # lazy import
    except ImportError:
        raise RuntimeError(
            "openai package not installed. Install with: pip install arche-core[llm]"
        )

    client = openai.OpenAI(
        api_key=config.api_key,  # None = uses OPENAI_API_KEY env var
        base_url=config.base_url,
        timeout=config.timeout,
    )
    response = client.chat.completions.create(
        model=config.model,
        messages=messages,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        response_format={"type": "json_object"},
        **config.extra,
    )
    return response.choices[0].message.content


def _complete_anthropic(config: LLMConfig, messages: list[dict[str, str]]) -> str:
    """Anthropic Claude completion."""
    try:
        import anthropic  # lazy import
    except ImportError:
        raise RuntimeError(
            "anthropic package not installed. Install with: pip install arche-core[llm]"
        )

    client = anthropic.Anthropic(
        api_key=config.api_key,  # None = uses ANTHROPIC_API_KEY env var
        timeout=config.timeout,
    )
    # Anthropic uses system as a separate param
    system_msg = ""
    chat_messages = []
    for m in messages:
        if m["role"] == "system":
            system_msg = m["content"]
        else:
            chat_messages.append(m)

    response = client.messages.create(
        model=config.model,
        system=system_msg,
        messages=chat_messages,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        **config.extra,
    )
    return response.content[0].text


def _complete_ollama(config: LLMConfig, messages: list[dict[str, str]]) -> str:
    """Ollama local model completion.  No extra dependencies -- uses urllib."""
    import urllib.request

    base = config.base_url or "http://localhost:11434"
    url = f"{base}/api/chat"
    payload = json.dumps({
        "model": config.model,
        "messages": messages,
        "stream": False,
        "format": "json",
        "options": {"temperature": config.temperature},
    }).encode()

    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=config.timeout) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        raise RuntimeError(
            f"Ollama request failed ({url}): {exc}. "
            "Ensure Ollama is running: https://ollama.com"
        ) from exc
    return data["message"]["content"]


def _complete_litellm(config: LLMConfig, messages: list[dict[str, str]]) -> str:
    """LiteLLM -- 100+ providers through one interface."""
    try:
        import litellm  # lazy import
    except ImportError:
        raise RuntimeError(
            "litellm package not installed. Install with: pip install arche-core[litellm]"
        )

    response = litellm.completion(
        model=config.model,
        messages=messages,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        api_key=config.api_key,
        api_base=config.base_url,
        timeout=config.timeout,
        response_format={"type": "json_object"},
        **config.extra,
    )
    return response.choices[0].message.content
