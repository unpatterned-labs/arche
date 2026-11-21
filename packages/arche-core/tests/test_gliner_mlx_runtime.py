# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""`gliner2_runtime="mlx"`: GLiNER 2.5 through mlx-vlm (Apple Silicon, or an
NVIDIA GPU on Linux/WSL2 via MLX's CUDA backend).

The integration test runs only where mlx-vlm and the model are available;
everything else is checked without them.
"""

from __future__ import annotations

import importlib.util
import json

import pytest
from arche import configure
from arche._models import _mlx_ready_gliner
from arche.config import get_config
from arche.detect._gliner2 import propose, runtime_label


@pytest.fixture(autouse=True)
def _restore_runtime():
    before = get_config().gliner2_runtime
    yield
    configure(gliner2_runtime=before)


def test_torch_is_the_default_and_names_carry_the_runtime():
    assert get_config().gliner2_runtime == "torch"
    assert runtime_label("fastino/gliner2.5-base-v1") == "fastino/gliner2.5-base-v1"
    assert runtime_label("fastino/gliner2.5-base-v1", "mlx") == "fastino/gliner2.5-base-v1@mlx"


def test_an_unknown_runtime_is_refused():
    with pytest.raises(ValueError, match="torch' or 'mlx"):
        propose("x", ["person"], runtime="onnx")


@pytest.mark.skipif(importlib.util.find_spec("mlx_vlm") is not None,
                    reason="mlx-vlm installed; the missing-package path does not apply")
def test_mlx_without_mlx_vlm_names_the_package():
    with pytest.raises(ImportError, match="mlx-vlm"):
        propose("Karfi Primary Health Centre", ["health facility"], runtime="mlx")


def _checkpoint(tmp_path, **config):
    (tmp_path / "config.json").write_text(json.dumps(config))
    (tmp_path / "model.safetensors").write_bytes(b"weights")
    return tmp_path


def test_a_renamed_boundary_checkpoint_gets_an_mlx_ready_copy(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "ckpt").mkdir()
    src = _checkpoint(tmp_path / "ckpt", architectures=["Gliner2ForSchemaExtraction"],
                      architecture="boundary")
    out = _mlx_ready_gliner(src)
    assert out != src
    assert json.loads((out / "config.json").read_text())["architectures"] == ["BoundaryExtractor"]
    assert (out / "model.safetensors").resolve() == (src / "model.safetensors").resolve()
    # The source is untouched.
    assert json.loads((src / "config.json").read_text())["architectures"] == [
        "Gliner2ForSchemaExtraction"]


def test_an_already_mlx_ready_checkpoint_is_used_as_is(tmp_path):
    src = _checkpoint(tmp_path, architectures=["BoundaryExtractor"])
    assert _mlx_ready_gliner(src) == src


def test_a_span_checkpoint_is_refused(tmp_path):
    src = _checkpoint(tmp_path, model_type="extractor")
    with pytest.raises(ValueError, match="boundary checkpoints only"):
        _mlx_ready_gliner(src)


@pytest.mark.skipif(importlib.util.find_spec("mlx_vlm") is None, reason="needs mlx-vlm")
def test_mlx_and_torch_find_the_same_spans():
    text = ("Mrs Amina Bello was seen at Karfi Primary Health Centre, Kura LGA, Kano, and "
            "referred to Aminu Kano Teaching Hospital.")
    labels = ["person", "health facility", "location"]
    mlx = propose(text, labels, runtime="mlx")
    try:
        torch = propose(text, labels, runtime="torch")
    except ImportError:
        pytest.skip("gliner2[local] not installed alongside")
    assert [(s.label, s.start, s.end) for s in mlx] == [(s.label, s.start, s.end) for s in torch]
    pairs = zip(mlx, torch, strict=True)
    assert all(abs(a.confidence - round(b.confidence, 3)) <= 0.002 for a, b in pairs)
