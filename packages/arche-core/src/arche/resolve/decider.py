# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""A learned pair decider: match, reject, or hold for a person.

The engine (:func:`arche.resolve.reconcile`) settles the clear pairs and holds
the rest for review. A :class:`PairDecider` takes held pairs and settles the
ones it can do safely. A cross-encoder reads the two names (each as
``name | admin2``) and gives a logit. A logistic combiner then weighs that logit
against:

* the distance between the two points, as ``log1p(km)``;
* whether the two admin2 units agree, after an alias table maps
  differently-written names of the same unit together;
* whether either point is missing.

A pair is matched at or above ``hi``, rejected at or below ``lo``, and held
otherwise. Pairs without both points use their own thresholds, learned from
location-free copies of the training pairs. A missing point therefore never
reads as "0 km apart".

A decider is a **bundle**, a directory holding:

* ``decider.json``: the features, the combiner weights, both threshold pairs,
  the alias table, and where it was trained and tested;
* ``cross_encoder/``: the Hugging Face model;
* ``MODEL_CARD.md``.

Every decision carries the bundle's pins: the cross-encoder weights digest and a
digest of ``decider.json``. So a receipt says exactly which decider made it.

The cross-encoder needs ``torch`` and ``transformers`` (``arche-core[detect2]``).
The features, thresholds and decision logic do not. Tests and callers can pass
their own ``logit_fn``.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["DECIDER_SCHEMA", "PairDecider", "PairDecision"]

DECIDER_SCHEMA = "arche.pair_decider.v1"
_EARTH_DIAMETER_KM = 12742.0


@dataclass(frozen=True)
class PairDecision:
    """One pair's outcome: ``match``, ``reject`` or ``review``."""

    outcome: str
    probability: float
    located: bool
    features: dict[str, float]
    thresholds: dict[str, float]
    pins: dict[str, str] = field(default_factory=dict)


def _fold(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _side(name: Any, admin2: Any) -> str:
    name, admin2 = " ".join(str(name or "").split()), " ".join(str(admin2 or "").split())
    return f"{name} | {admin2}" if admin2 else name


def _point(record: Mapping[str, Any]) -> tuple[float, float] | None:
    try:
        lat, lon = float(record["lat"]), float(record["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    if math.isnan(lat) or math.isnan(lon):
        return None
    return lat, lon


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return _EARTH_DIAMETER_KM * math.asin(math.sqrt(min(1.0, h)))


class PairDecider:
    """Decide record pairs with a pinned cross-encoder and a logistic combiner.

    Each pair is ``(a, b)``: two mappings with ``name``, ``admin1``, ``admin2``,
    and optionally ``lat`` and ``lon``. ``a`` is the reference side (GRID3 in
    the shipped Nigerian decider) and ``b`` the side the alias table rewrites
    (the HFR).
    """

    def __init__(self, spec: Mapping[str, Any], *,
                 logit_fn: Callable[[list[tuple[str, str]]], Sequence[float]] | None = None,
                 pins: Mapping[str, str] | None = None) -> None:
        if spec.get("schema") != DECIDER_SCHEMA:
            raise ValueError(f"not a {DECIDER_SCHEMA} spec: {spec.get('schema')!r}")
        self.spec = dict(spec)
        self.features = list(spec["features"])
        self.weights = [float(w) for w in spec["weights"]]
        if len(self.weights) != len(self.features) + 1:
            raise ValueError("weights must hold one per feature plus a bias")
        self.located = {k: float(v) for k, v in spec["thresholds"]["located"].items()}
        self.hidden = {k: float(v) for k, v in spec["thresholds"]["hidden"].items()}
        self.aliases = {k: _fold(v) for k, v in spec.get("admin2_aliases", {}).items()}
        self._logit_fn = logit_fn
        self.pins = dict(pins or {})
        self.pins.setdefault("decider_spec", "sha256:" + hashlib.sha256(
            json.dumps(self.spec, sort_keys=True).encode()).hexdigest())

    @classmethod
    def load(cls, bundle: str | Path, *, device: str | None = None) -> PairDecider:
        """Load a bundle directory; the cross-encoder loads on first use."""
        root = Path(bundle)
        spec = json.loads((root / "decider.json").read_text(encoding="utf-8"))
        model_dir = root / spec.get("cross_encoder", "cross_encoder")
        from arche.retrieval._encoder import weights_digest

        pins = {"cross_encoder": weights_digest(model_dir)}
        expected = spec.get("cross_encoder_sha256")
        if expected and expected != pins["cross_encoder"]:
            raise ValueError("cross-encoder weights differ from the ones decider.json names")
        decider = cls(spec, pins=pins)
        decider._model_dir, decider._device = model_dir, device
        return decider

    # -- the cross-encoder, loaded lazily ---------------------------------
    def _logits(self, texts: list[tuple[str, str]]) -> list[float]:
        if self._logit_fn is None:
            self._logit_fn = self._load_cross_encoder()
        return [float(z) for z in self._logit_fn(texts)]

    def _load_cross_encoder(self) -> Callable[[list[tuple[str, str]]], list[float]]:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        model_dir = getattr(self, "_model_dir", None)
        if model_dir is None:
            raise RuntimeError("no cross-encoder: load a bundle or pass logit_fn")
        device = getattr(self, "_device", None) or ("cuda" if torch.cuda.is_available() else "cpu")
        tok = AutoTokenizer.from_pretrained(model_dir)
        model = AutoModelForSequenceClassification.from_pretrained(model_dir).to(device).eval()
        max_len = int(self.spec.get("max_length", 96))

        def logits(pairs: list[tuple[str, str]], batch: int = 256) -> list[float]:
            out: list[float] = []
            with torch.inference_mode():
                for i in range(0, len(pairs), batch):
                    chunk = pairs[i:i + batch]
                    enc = tok([a for a, _ in chunk], [b for _, b in chunk], padding=True,
                              truncation=True, max_length=max_len,
                              return_tensors="pt").to(device)
                    out.extend(model(**enc).logits.squeeze(-1).float().cpu().tolist())
            return out
        return logits

    # -- features and decisions -------------------------------------------
    def _admin2_agree(self, a: Mapping[str, Any], b: Mapping[str, Any]) -> float:
        left = _fold(a.get("admin2"))
        right = _fold(b.get("admin2"))
        right = self.aliases.get(f"{_fold(b.get('admin1'))}|{right}", right)
        return 1.0 if left and left == right else 0.0

    def featurise(self, pairs: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]]
                  ) -> list[dict[str, float]]:
        """The combiner's inputs for each pair, by feature name."""
        z = self._logits([(_side(a.get("name"), a.get("admin2")),
                           _side(b.get("name"), b.get("admin2"))) for a, b in pairs])
        rows = []
        for (a, b), logit in zip(pairs, z, strict=True):
            pa, pb = _point(a), _point(b)
            located = pa is not None and pb is not None
            rows.append({"cross_encoder_logit": logit,
                         "log1p_km": math.log1p(_km(pa, pb)) if located else 0.0,
                         "admin2_agree": self._admin2_agree(a, b),
                         "coordinates_missing": 0.0 if located else 1.0})
        return rows

    def decide(self, pairs: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]]
               ) -> list[PairDecision]:
        """``match``, ``reject`` or ``review`` for each ``(a, b)`` pair."""
        out = []
        for f in self.featurise(pairs):
            s = sum(w * f[name] for w, name in zip(self.weights[:-1], self.features,
                                                    strict=True)) + self.weights[-1]
            p = 1.0 / (1.0 + math.exp(-s))
            located = f["coordinates_missing"] == 0.0
            t = self.located if located else self.hidden
            outcome = "match" if p >= t["hi"] else "reject" if p <= t["lo"] else "review"
            out.append(PairDecision(outcome, p, located, f, dict(t), dict(self.pins)))
        return out
