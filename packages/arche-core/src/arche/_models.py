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

"""Shared model registry — single cache for GliNER and future models.

Provides offline loading via ``ARCHE_MODEL_DIR`` environment variable,
standard cache at ``~/.cache/arche/models/``, and HuggingFace fallback.

Usage:
    from arche._models import get_gliner
    model = get_gliner()  # uses config model name, cached after first load
    model = get_gliner("urchade/gliner_large-v2.1")  # specific model
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger("arche.models")

# Model cache: model_name_or_path -> loaded model object
_cache: dict[str, Any] = {}


def _resolve_model_path(name_or_path: str) -> str:
    """Resolve a model name to a local path if available.

    Search order:
    1. ``ARCHE_MODEL_DIR`` environment variable (air-gapped deployments)
    2. ``~/.cache/arche/models/{name}/`` (standard local cache)
    3. Return original name (triggers HuggingFace download)
    """
    # 1. ARCHE_MODEL_DIR
    model_dir = os.environ.get("ARCHE_MODEL_DIR", "")
    if model_dir:
        # Model name like "urchade/gliner_medium-v2.1" → folder name
        folder_name = name_or_path.replace("/", "--")
        candidate = Path(model_dir) / folder_name
        if candidate.is_dir() and any(candidate.iterdir()):
            _log.debug("Found model at ARCHE_MODEL_DIR: %s", candidate)
            return str(candidate)
        # Also try the raw name as a subdirectory
        candidate = Path(model_dir) / name_or_path.split("/")[-1]
        if candidate.is_dir() and any(candidate.iterdir()):
            return str(candidate)

    # 2. Standard cache
    cache_dir = Path.home() / ".cache" / "arche" / "models"
    folder_name = name_or_path.replace("/", "--")
    candidate = cache_dir / folder_name
    if candidate.is_dir() and any(candidate.iterdir()):
        _log.debug("Found model in cache: %s", candidate)
        return str(candidate)

    # 3. Return original (HuggingFace will download)
    return name_or_path


def get_gliner(name_or_path: str | None = None) -> Any:
    """Load and cache a GliNER model.

    Parameters
    ----------
    name_or_path:
        Model name (HuggingFace) or local path. If ``None``, reads from
        ``get_config().gliner_model``.

    Returns
    -------
    GLiNER
        The loaded model, cached for subsequent calls.

    Raises
    ------
    ImportError
        If the ``gliner`` package is not installed.
    """
    from .config import get_config

    if name_or_path is None:
        name_or_path = get_config().gliner_model

    if name_or_path in _cache:
        return _cache[name_or_path]

    from gliner import GLiNER

    resolved_path = _resolve_model_path(name_or_path)
    is_local = resolved_path != name_or_path

    _log.info(
        "Loading GliNER model '%s'%s...",
        name_or_path,
        f" (from {resolved_path})" if is_local else " (first use — downloading)",
    )

    t0 = time.perf_counter()
    try:
        model = GLiNER.from_pretrained(resolved_path)
    except Exception as primary_err:
        # Fallback: try the configured fallback model before giving up.
        # Default chain: gliner_medium-v2.1 (primary) -> gliner_multi_pii-v1 (fallback).
        cfg = get_config()
        fallback = cfg.gliner_fallback_model
        if fallback and fallback != name_or_path:
            _log.warning(
                "Primary model '%s' failed (%s), falling back to '%s'",
                name_or_path, primary_err, fallback,
            )
            resolved_fallback = _resolve_model_path(fallback)
            model = GLiNER.from_pretrained(resolved_fallback)
            # Cache under both keys so the fallback is reused
            _cache[fallback] = model
            _cache[name_or_path] = model
            elapsed = time.perf_counter() - t0
            _log.info("Fallback model loaded in %.1fs.", elapsed)
            return model
        raise  # No fallback configured, propagate the error
    elapsed = time.perf_counter() - t0

    _log.info("Model loaded in %.1fs. Cached for subsequent calls.", elapsed)
    if elapsed > 60 and not is_local:
        _log.warning(
            "Model download took %.0fs. For faster startup, set ARCHE_MODEL_DIR "
            "or run: arche models download %s",
            elapsed,
            name_or_path,
        )

    _cache[name_or_path] = model
    return model


def clear_cache() -> None:
    """Clear all cached models (useful for testing)."""
    _cache.clear()
