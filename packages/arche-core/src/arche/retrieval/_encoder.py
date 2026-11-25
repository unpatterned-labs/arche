# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""A text encoder whose weights are part of every receipt it touches.

Mean-pooled, L2-normalised sentence vectors from any Hugging Face encoder
(``intfloat/multilingual-e5-small``, a fine-tuned copy of it, ...). The
weights are digested once on load: two encoders that differ in a single byte
pin differently, so a candidate list says exactly which model proposed it.

Needs ``torch`` and ``transformers`` (``arche-core[detect2]``).
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

#: Files that decide what an encoder computes: weights, config, tokenizer.
_WEIGHT_GLOBS = ("*.safetensors", "*.bin", "config.json", "tokenizer.json",
                 "tokenizer_config.json", "special_tokens_map.json",
                 "sentencepiece.bpe.model", "vocab.txt", "*.model")


def weights_digest(path: str | Path) -> str:
    """``sha256:`` over the files that decide an encoder's output, by name."""
    root = Path(path)
    files = sorted({f for pattern in _WEIGHT_GLOBS for f in root.glob(pattern) if f.is_file()})
    if not files:
        raise ValueError(f"no model files under {root}")
    digest = hashlib.sha256()
    for f in files:
        digest.update(f.name.encode() + b"\0")
        with open(f, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _local_path(model: str) -> Path:
    if Path(model).is_dir():
        return Path(model)
    from huggingface_hub import snapshot_download

    return Path(snapshot_download(model, allow_patterns=list(_WEIGHT_GLOBS)))


class TextEncoder:
    """``encode(texts) -> (n, d)`` float32, unit rows.

    ``prefix`` is prepended to every text (E5 models expect ``"query: "`` for
    symmetric matching). ``device`` defaults to CUDA when available.

    ``threads`` caps torch's CPU threads while encoding and restores them
    after; ``None`` follows ``configure(torch_threads=...)``, which caps them
    automatically (one query on a 16-thread WSL2 laptop: 6 ms capped, 556 ms
    at torch's default of 16). Not in ``pins()``: speed, not output.
    """

    def __init__(self, model: str, *, prefix: str = "", max_length: int = 64,
                 batch_size: int = 128, device: str | None = None,
                 threads: int | None = None) -> None:
        import torch
        from transformers import AutoModel, AutoTokenizer

        self.name = model
        self.path = _local_path(model)
        self.prefix = prefix
        self.max_length = max_length
        self.batch_size = batch_size
        self.threads = threads
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._digest = weights_digest(self.path)
        self.tokenizer = AutoTokenizer.from_pretrained(self.path)
        self.model = AutoModel.from_pretrained(self.path).to(self.device).eval()

    def encode(self, texts: Sequence[str]):
        import numpy as np

        from arche._models import torch_threads

        out: list = []
        with torch_threads(self.threads):
            self._encode_into(texts, out)
        return np.concatenate(out) if out else np.zeros((0, 1), dtype="float32")

    def _encode_into(self, texts: Sequence[str], out: list) -> None:
        import torch

        with torch.inference_mode():
            for i in range(0, len(texts), self.batch_size):
                batch = [self.prefix + t for t in texts[i:i + self.batch_size]]
                tok = self.tokenizer(batch, padding=True, truncation=True,
                                     max_length=self.max_length,
                                     return_tensors="pt").to(self.device)
                hidden = self.model(**tok).last_hidden_state
                vec = mean_pool(hidden, tok["attention_mask"])
                out.append(torch.nn.functional.normalize(vec, dim=-1).float().cpu().numpy())

    def pins(self) -> dict[str, Any]:
        return {"encoder": self.name if not Path(self.name).is_dir() else Path(self.name).name,
                "weights": self._digest, "pooling": "mean", "prefix": self.prefix,
                "max_length": self.max_length}


def mean_pool(hidden, mask):
    """Mean of the token vectors the attention mask keeps."""
    mask = mask.unsqueeze(-1).to(hidden.dtype)
    return (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)


class EncoderIndex:
    """Exact nearest neighbours by dot product over unit vectors."""

    def __init__(self, texts: Sequence[str], encoder: TextEncoder) -> None:
        self.encoder = encoder
        self._matrix = encoder.encode(list(texts))

    def __len__(self) -> int:
        return int(self._matrix.shape[0])

    def search(self, text: str, k: int = 10) -> list[tuple[int, float]]:
        return self.search_many([text], k)[0]

    def search_many(self, texts: Sequence[str], k: int = 10) -> list[list[tuple[int, float]]]:
        import numpy as np

        q = self.encoder.encode(list(texts))
        sims = q @ self._matrix.T
        k = min(k, sims.shape[1])
        out = []
        for row in sims:
            top = np.argpartition(-row, k - 1)[:k] if k < len(row) else np.arange(len(row))
            ranked = sorted(top.tolist(), key=lambda j: (-float(row[j]), j))
            out.append([(j, round(float(row[j]), 6)) for j in ranked])
        return out

    def pins(self) -> dict[str, Any]:
        return {"retriever": "encoder", "rows": len(self), **self.encoder.pins()}
