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

"""Shared model registry -- one cache for the GLiNER 2 family.

Provides offline loading via the ``ARCHE_MODEL_DIR`` environment variable,
the standard cache at ``~/.cache/arche/models/``, and a Hugging Face fallback.

Usage:
    from arche._models import get_gliner2
    model = get_gliner2()                                   # the general extractor
    model = get_gliner2("fastino/gliner2-privacy-filter-PII-multi")  # the PII proposer
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger("arche.models")

# Model cache: cache key -> loaded model object
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
        # Model name like "fastino/gliner2.5-base-v1" -> folder name
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


def get_gliner2(name_or_path: str | None = None) -> Any:
    """Load a GLiNER 2 model, cached, offline-aware.

    Loaded through ``AutoExtractor``, which reads the checkpoint metadata and
    dispatches to the span or boundary architecture -- so one loader serves
    both the general GLiNER 2.5 checkpoints and GLiNER2-PII.
    ``GLiNER2.from_pretrained`` is NOT used: it assumes the span architecture
    and dies on a boundary checkpoint with a missing ``max_width``.

    Requires ``arche-core[detect2]``. Note that this pulls ``gliner2[local]``
    and not bare ``gliner2`` -- the base package is an API client that sends
    text to a hosted service, which would quietly turn local extraction into a
    network call on someone else's machine. The ``[local]`` extra is what
    brings the on-device weights.
    """
    from .config import get_config

    if name_or_path is None:
        name_or_path = get_config().gliner2_model

    cache_key = f"gliner2:{name_or_path}"
    if cache_key in _cache:
        return _cache[cache_key]

    try:
        from gliner2 import AutoExtractor
    except ImportError as exc:  # pragma: no cover - exercised without the extra
        import importlib.util

        if importlib.util.find_spec("gliner2") is not None:
            # The package is there and something *inside* it failed to import
            # -- a missing transitive dependency, a torch build that does not
            # load on this machine. Saying "not installed" here sent one
            # container build chasing the wrong fix; name the real failure.
            raise ImportError(
                f"GLiNER 2 is installed but failed to import: {exc}\n"
                "The `gliner2[local]` extra's own dependencies (torch, "
                "transformers) are the usual cause; `pip check` will name it."
            ) from exc
        raise ImportError(
            "GLiNER 2 is not installed. Install it with:\n"
            "    pip install 'arche-core[detect2]'\n"
            "Note the [local] marker inside that extra: bare `gliner2` is an "
            "API client that sends text to a hosted service, which is not what "
            "arche means by extraction."
        ) from exc

    resolved_path = _resolve_model_path(name_or_path)
    is_local = resolved_path != name_or_path
    _log.info("Loading GLiNER 2 model %r%s...", name_or_path,
              f" (from {resolved_path})" if is_local else " (first use -- downloading)")
    t0 = time.perf_counter()
    # gliner2 prints a configuration banner, emoji first, while it loads. On a
    # Windows console or any cp1252 pipe -- a service manager's log, a CI
    # step -- that print raises UnicodeEncodeError, a ValueError, from inside a
    # detection call. The banner is not ours and not the caller's; swallow it.
    import contextlib
    import io

    with contextlib.redirect_stdout(io.StringIO()):
        model = AutoExtractor.from_pretrained(resolved_path)
    elapsed = time.perf_counter() - t0
    _log.info("GLiNER 2 loaded in %.1fs.", elapsed)
    if elapsed > 60 and not is_local:
        _log.warning(
            "Model download took %.0fs. For faster startup, set ARCHE_MODEL_DIR "
            "to a directory holding %s", elapsed, name_or_path,
        )
    _cache[cache_key] = model
    return model


#: The architecture name mlx-vlm's GLiNER 2.5 port recognises, and the one the
#: upstream checkpoints were renamed to after the port was written.
_MLX_GLINER_ARCH = "BoundaryExtractor"
_UPSTREAM_GLINER_ARCH = "Gliner2ForSchemaExtraction"


def _mlx_ready_gliner(path: Path) -> Path:
    """A directory mlx-vlm can load for this checkpoint; ``path`` itself if it can.

    The upstream GLiNER 2.5 checkpoints now declare ``Gliner2ForSchemaExtraction``;
    mlx-vlm dispatches on ``BoundaryExtractor``. The weights are the same (checked
    20 Nov 2026: they load and give the torch model's spans). So when needed this
    writes a copy under ``~/.cache/arche/models/mlx--<name>/`` whose files link to
    the originals and whose config names the architecture mlx-vlm expects. The
    Hugging Face cache is never modified.

    Only boundary checkpoints are supported: mlx-vlm's port does not cover the
    span architecture, which is what GLiNER2-PII uses.
    """
    import json

    config = json.loads((path / "config.json").read_text(encoding="utf-8"))
    archs = config.get("architectures") or []
    if _MLX_GLINER_ARCH in archs:
        return path
    if config.get("architecture") != "boundary" and _UPSTREAM_GLINER_ARCH not in archs:
        raise ValueError(
            f"{path.name}: gliner2_runtime='mlx' runs GLiNER 2.5 boundary checkpoints "
            "only (mlx-vlm's port); this one is not (GLiNER2-PII is span-architecture). "
            "Use gliner2_runtime='torch' for it."
        )
    target = Path.home() / ".cache" / "arche" / "models" / f"mlx--{path.name}"
    target.mkdir(parents=True, exist_ok=True)
    for item in path.iterdir():
        link = target / item.name
        if item.name != "config.json" and not link.exists():
            link.symlink_to(item.resolve())
    config["architectures"] = [_MLX_GLINER_ARCH]
    (target / "config.json").write_text(json.dumps(config, indent=1), encoding="utf-8")
    return target


def get_gliner2_mlx(name_or_path: str | None = None) -> tuple[Any, Any]:
    """Load a GLiNER 2.5 boundary checkpoint through mlx-vlm, cached.

    Returns ``(model, processor)``. Needs ``mlx-vlm`` (and, on Linux, MLX's
    CUDA or CPU backend: ``pip install "mlx[cuda]" mlx-vlm``). On Linux/WSL2
    MLX compiles kernels at first use and needs CUDA headers: ``pip install
    nvidia-cuda-runtime-cu12 nvidia-cuda-cccl-cu12`` and point ``CUDA_HOME``
    at ``site-packages/nvidia/cuda_runtime``.
    """
    from .config import get_config

    if name_or_path is None:
        name_or_path = get_config().gliner2_model
    cache_key = f"gliner2-mlx:{name_or_path}"
    if cache_key in _cache:
        return _cache[cache_key]
    try:
        from mlx_vlm import load
    except ImportError as exc:
        raise ImportError(
            "gliner2_runtime='mlx' needs mlx-vlm: pip install mlx-vlm "
            "(on Linux also \"mlx[cuda]\" or \"mlx[cpu]\")."
        ) from exc
    resolved = _resolve_model_path(name_or_path)
    if resolved == name_or_path and not Path(resolved).is_dir():
        from huggingface_hub import snapshot_download

        # Only what the model needs: a repo's banner images are not weights, and
        # asking for the whole repo fails offline on a cache that holds the model.
        resolved = snapshot_download(
            name_or_path,
            allow_patterns=["*.json", "*.safetensors", "encoder_config/*", "tokenizer*"],
        )
    t0 = time.perf_counter()
    model, processor = load(str(_mlx_ready_gliner(Path(resolved))))
    _log.info("GLiNER 2.5 (mlx) loaded in %.1fs.", time.perf_counter() - t0)
    _cache[cache_key] = (model, processor)
    return model, processor


def clear_cache() -> None:
    """Clear all cached models (useful for testing)."""
    _cache.clear()
