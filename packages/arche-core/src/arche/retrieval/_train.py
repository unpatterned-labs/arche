# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Fine-tune an encoder for retrieval: pull true pairs together, push near-misses apart.

Contrastive (InfoNCE) training over ``(anchor, positive)`` pairs. Every other
positive in the batch is a negative for free, and each anchor may also carry
**hard negatives**: records that look alike and are not the same, which is
what a general-purpose embedding gets wrong (``Lagos University Teaching
Hospital`` / ``Lagos State University Teaching Hospital``). Mine them from a
retriever's own near neighbours, or take them from pairs a discriminator
refuted.

The result is a directory a :class:`~arche.retrieval.TextEncoder` loads, plus
``arche_training.json``: the base model and its weights digest, a digest of
the training pairs, the hyperparameters and seed, and the loss per epoch. The
trained weights are digested on load like any other encoder's, so a decision
made from a candidate this model proposed names the exact weights.

Train only on development entities. A pair whose entity is in the evaluation
split must never be a positive or a negative here.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TrainConfig:
    epochs: int = 2
    batch_size: int = 64
    lr: float = 2e-5
    temperature: float = 0.05
    max_length: int = 64
    warmup: float = 0.1
    seed: int = 0
    prefix: str = ""


def pairs_digest(pairs: Sequence[tuple[str, str]],
                 hard_negatives: Sequence[Sequence[str]] | None = None) -> str:
    h = hashlib.sha256()
    for i, (a, b) in enumerate(pairs):
        h.update(f"{a}\t{b}".encode())
        if hard_negatives is not None:
            h.update(("\t" + "\t".join(hard_negatives[i])).encode())
        h.update(b"\n")
    return "sha256:" + h.hexdigest()


def fine_tune(base: str, pairs: Sequence[tuple[str, str]], out_dir: str | Path, *,
              hard_negatives: Sequence[Sequence[str]] | None = None,
              config: TrainConfig | None = None, device: str | None = None,
              log=print) -> Path:
    """Train ``base`` on ``pairs`` and save it under ``out_dir``.

    ``hard_negatives[i]`` lists texts that are *not* ``pairs[i][1]``'s entity;
    at most one is used per anchor per step, chosen by the seeded generator.
    """
    import numpy as np
    import torch
    from transformers import AutoModel, AutoTokenizer, get_linear_schedule_with_warmup

    from arche.retrieval._encoder import _local_path, mean_pool, weights_digest

    config = config or TrainConfig()
    if hard_negatives is not None and len(hard_negatives) != len(pairs):
        raise ValueError("hard_negatives must align with pairs")
    random.seed(config.seed)
    np.random.seed(config.seed)
    torch.manual_seed(config.seed)
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    base_path = _local_path(base)
    tok = AutoTokenizer.from_pretrained(base_path)
    model = AutoModel.from_pretrained(base_path).to(device)
    model.train()

    def embed(texts: list[str]):
        batch = tok([config.prefix + t for t in texts], padding=True, truncation=True,
                    max_length=config.max_length, return_tensors="pt").to(device)
        out = model(**batch).last_hidden_state
        return torch.nn.functional.normalize(mean_pool(out, batch["attention_mask"]), dim=-1)

    order = list(range(len(pairs)))
    steps_per_epoch = max(1, len(order) // config.batch_size)
    total = steps_per_epoch * config.epochs
    opt = torch.optim.AdamW(model.parameters(), lr=config.lr)
    sched = get_linear_schedule_with_warmup(opt, int(total * config.warmup), total)
    rng = random.Random(config.seed)
    losses: list[float] = []
    for epoch in range(config.epochs):
        rng.shuffle(order)
        epoch_loss = 0.0
        for step in range(steps_per_epoch):
            idx = order[step * config.batch_size:(step + 1) * config.batch_size]
            anchors = [pairs[i][0] for i in idx]
            positives = [pairs[i][1] for i in idx]
            negatives = []
            if hard_negatives is not None:
                negatives = [rng.choice(hard_negatives[i]) for i in idx if hard_negatives[i]]
            a = embed(anchors)
            p = embed(positives + negatives)
            logits = (a @ p.T) / config.temperature
            # Two texts of one entity in the same batch are not negatives of
            # each other: mask duplicates of the positive.
            same = torch.tensor([[positives[r] == positives[c] if c < len(positives) else False
                                  for c in range(p.shape[0])] for r in range(len(anchors))],
                                device=device)
            eye = torch.eye(len(anchors), p.shape[0], dtype=torch.bool, device=device)
            logits = logits.masked_fill(same & ~eye, float("-inf"))
            target = torch.arange(len(anchors), device=device)
            loss = torch.nn.functional.cross_entropy(logits, target)
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            epoch_loss += float(loss.detach())
        losses.append(round(epoch_loss / steps_per_epoch, 5))
        log(f"epoch {epoch + 1}/{config.epochs}  loss {losses[-1]}")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out, safe_serialization=True)
    tok.save_pretrained(out)
    manifest: dict[str, Any] = {
        "schema": "arche.retrieval.training.v1",
        "base": base, "base_weights": weights_digest(base_path),
        "pairs": len(pairs), "pairs_sha256": pairs_digest(pairs, hard_negatives),
        "hard_negatives": hard_negatives is not None,
        "config": asdict(config), "device": device, "losses": losses,
        "torch": torch.__version__,
    }
    (out / "arche_training.json").write_text(json.dumps(manifest, indent=2, sort_keys=True),
                                             encoding="utf-8")
    return out
