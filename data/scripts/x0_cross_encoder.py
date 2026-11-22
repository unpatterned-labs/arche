#!/usr/bin/env python
"""X0: can a cross-encoder decide part of the Nigerian review band on its own?

The review band is the 180 GRID3/HFR pairs the engine held for a person. A
cross-encoder reads both records at once and says how likely they are the same
facility. It is trained on the GRID3 v2 / HFR crosswalk (``globalid`` =
``global_id``) of the 34 states other than Edo, Kano and Ondo, calibrated and
thresholded on a held-out slice of those states, and only then scored on the
maintainer's 180 labels, once.

A pair is auto-matched above ``hi``, auto-rejected below ``lo``, and otherwise
still held. ``hi`` and ``lo`` are fixed by error rates on the development slice
(at most 1% false positives above ``hi``, at most 1% false negatives below
``lo``), never by the labels. The rule is in
data/er_bench/benchmark_x0_cross_encoder_preregistration.json; this script
refuses to run if it, or the labels, changed.

Against it: the gate alone (holds all 180), and a logistic regression over the
TF-IDF and E0c-encoder cosines of the two names. Only aggregates are written.

    python data/scripts/x0_cross_encoder.py \
        --out data/er_bench/benchmark_x0_cross_encoder_result.json
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import random
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
for _name in ("e0b_transfer", "e0c_facility"):
    _spec = importlib.util.spec_from_file_location(_name, HERE / f"{_name}.py")
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_name] = _mod
    _spec.loader.exec_module(_mod)
tr, fc = sys.modules["e0b_transfer"], sys.modules["e0c_facility"]

from arche._models import torch_threads  # noqa: E402
from arche.retrieval import CharNgramIndex, TextEncoder  # noqa: E402
from arche.retrieval._encoder import _local_path, weights_digest  # noqa: E402

PREREG = tr.DATA / "er_bench" / "benchmark_x0_cross_encoder_preregistration.json"
MODELS = Path.home() / ".cache" / "arche" / "models" / "x0"
E0C_ENCODER = Path.home() / ".cache" / "arche" / "models" / "e0c" / "crosswalk" / "seed0"
BASE = "intfloat/multilingual-e5-small"
SEEDS = (0, 1, 2)
EPOCHS, LR, BATCH, MAX_LEN, WARMUP = 1, 3e-5, 32, 96, 0.1
FPR_MAX = FNR_MAX = 0.01


def _salted(*parts: str) -> int:
    return int(hashlib.sha256("\0".join(("x0",) + parts).encode()).hexdigest()[:12], 16)


def side(name: str, lga: str) -> str:
    name, lga = " ".join((name or "").split()), " ".join((lga or "").split())
    return f"{name} | {lga}" if lga else name


# ------------------------------------------------------------------ data


def examples() -> dict[str, list[tuple[str, str, int]]]:
    pairs, hfr = fc.crosswalk()
    train_states = lambda s: s.strip().lower() not in fc.TEST_STATES  # noqa: E731
    by_lga: dict[tuple[str, str], list[tuple[str, str, str]]] = defaultdict(list)
    for gid, h in hfr.items():
        if train_states(h["state_name"]) and h.get("name"):
            by_lga[(h["state_name"], h["lga_name"])].append(
                (gid, " ".join(h["name"].split()), h["lga_name"]))
    index = {k: CharNgramIndex([t for _, t, _ in v]) for k, v in by_lga.items()}
    out: dict[str, list[tuple[str, str, int]]] = {"train": [], "dev": []}
    for g, h in pairs:
        if not (train_states(g["state"]) and train_states(h["state_name"])):
            continue
        split = "dev" if _salted("split", g["globalid"]) % 10 == 0 else "train"
        gn, hn = g["facility_name"], h["name"] or ""
        if not gn.strip() or not hn.strip():
            continue
        same_text = fc.fold(gn) == fc.fold(hn)
        if not same_text or _salted("ident", g["globalid"]) % 4 == 0:
            out[split].append((side(gn, g["lga"]), side(hn, h["lga_name"]), 1))
        key = (h["state_name"], h["lga_name"])
        rows = by_lga.get(key, [])
        if not rows:
            continue
        found = [rows[i] for i, _ in index[key].search(gn, k=10)]
        negs = [(t, lga) for gid, t, lga in found
                if gid != h["global_id"] and fc.fold(t) not in (fc.fold(gn), fc.fold(hn))][:3]
        out[split] += [(side(gn, g["lga"]), side(t, lga), 0) for t, lga in negs]
    return out


def review_band(prereg: dict) -> tuple[list[tuple[str, str]], np.ndarray, list[dict]]:
    rows, _ = tr.load({"labels": prereg["labels"]})
    rows.sort(key=lambda r: (r["state"], r["decision_id"]))
    texts = [(side(r["grid3_name"], json.loads(r["grid3_admin_path"]).get("admin2", "")),
              side(r["hfr_name"], json.loads(r["hfr_admin_path"]).get("admin2", "")))
             for r in rows]
    y = np.array([r["review_outcome"] == "same_entity" for r in rows], dtype=int)
    return texts, y, rows


# ------------------------------------------------------------------ model


def train(data: list[tuple[str, str, int]], seed: int, out: Path, device: str) -> Path:
    import torch
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        get_linear_schedule_with_warmup,
    )

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    base = _local_path(BASE)
    tok = AutoTokenizer.from_pretrained(base)
    model = AutoModelForSequenceClassification.from_pretrained(base, num_labels=1).to(device)
    model.train()
    order = list(range(len(data)))
    steps = (len(order) // BATCH) * EPOCHS
    opt = torch.optim.AdamW(model.parameters(), lr=LR)
    sched = get_linear_schedule_with_warmup(opt, int(steps * WARMUP), steps)
    rng = random.Random(seed)
    loss_fn = torch.nn.BCEWithLogitsLoss()
    losses = []
    for _ in range(EPOCHS):
        rng.shuffle(order)
        total = 0.0
        for s in range(len(order) // BATCH):
            idx = order[s * BATCH:(s + 1) * BATCH]
            batch = tok([data[i][0] for i in idx], [data[i][1] for i in idx], padding=True,
                        truncation=True, max_length=MAX_LEN, return_tensors="pt").to(device)
            target = torch.tensor([float(data[i][2]) for i in idx], device=device)
            loss = loss_fn(model(**batch).logits.squeeze(-1), target)
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            total += float(loss.detach())
        losses.append(round(total / max(1, len(order) // BATCH), 5))
        print(f"  seed {seed}: loss {losses[-1]}", flush=True)
    out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out, safe_serialization=True)
    tok.save_pretrained(out)
    manifest = {"schema": "arche.x0.training.v1", "base": BASE,
                "base_weights": weights_digest(base), "examples": len(data),
                "positives": sum(d[2] for d in data), "seed": seed, "epochs": EPOCHS,
                "lr": LR, "batch": BATCH, "max_length": MAX_LEN, "losses": losses,
                "device": device, "torch": torch.__version__}
    (out / "arche_training.json").write_text(json.dumps(manifest, indent=2, sort_keys=True),
                                             encoding="utf-8")
    return out


class CrossEncoder:
    def __init__(self, path: Path, device: str):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(path)
        self.model = AutoModelForSequenceClassification.from_pretrained(path).to(device).eval()
        self.device = device
        self.weights = weights_digest(path)

    def logits(self, pairs: list[tuple[str, str]], batch: int = 256) -> np.ndarray:
        out = []
        with self.torch.inference_mode():
            for i in range(0, len(pairs), batch):
                chunk = pairs[i:i + batch]
                enc = self.tok([a for a, _ in chunk], [b for _, b in chunk], padding=True,
                               truncation=True, max_length=MAX_LEN,
                               return_tensors="pt").to(self.device)
                out.append(self.model(**enc).logits.squeeze(-1).float().cpu().numpy())
        return np.concatenate(out)

    def cpu_p95_ms(self, pairs: list[tuple[str, str]], threads: int = 4) -> float:
        self.model.to("cpu")
        self.device = "cpu"
        times = []
        with torch_threads(threads):
            self.logits(pairs[:8], batch=1)
            for p in pairs:
                t = time.perf_counter()
                self.logits([p], batch=1)
                times.append((time.perf_counter() - t) * 1000)
        return round(float(np.percentile(times, 95)), 2)


def fit_logistic(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Weights (with bias last) by LBFGS on the log loss."""
    import torch

    xt = torch.tensor(np.c_[x, np.ones(len(x))], dtype=torch.float64)
    yt = torch.tensor(y, dtype=torch.float64)
    w = torch.zeros(xt.shape[1], dtype=torch.float64, requires_grad=True)
    opt = torch.optim.LBFGS([w], max_iter=200, line_search_fn="strong_wolfe")

    def closure():
        opt.zero_grad()
        loss = torch.nn.functional.binary_cross_entropy_with_logits(xt @ w, yt)
        loss.backward()
        return loss

    opt.step(closure)
    return w.detach().numpy()


def predict(w: np.ndarray, x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-(np.c_[x, np.ones(len(x))] @ w)))


# ------------------------------------------------------------------ rule


def thresholds(p: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """hi: smallest t with FPR(P >= t) <= 1%; lo: largest t with FNR(P <= t) <= 1%."""
    neg, pos = np.sort(p[y == 0]), np.sort(p[y == 1])
    k_neg = int(math.floor(FPR_MAX * len(neg)))       # negatives allowed at or above hi
    hi = float(np.nextafter(neg[len(neg) - k_neg - 1], 1.0)) if k_neg < len(neg) else 0.0
    k_pos = int(math.floor(FNR_MAX * len(pos)))       # positives allowed at or below lo
    lo = float(np.nextafter(pos[k_pos], 0.0)) if k_pos < len(pos) else 1.0
    return min(lo, float(np.nextafter(hi, 0.0))), hi


def wilson_upper(errors: int, n: int, z: float = 1.96) -> float:
    if n == 0:
        return 1.0
    p = errors / n
    centre = p + z * z / (2 * n)
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre + spread) / (1 + z * z / n)


def apply(p: np.ndarray, y: np.ndarray, lo: float, hi: float) -> dict[str, Any]:
    match, reject = p >= hi, p <= lo
    decided = match | reject
    errors = int((match & (y == 0)).sum() + (reject & (y == 1)).sum())
    n = int(decided.sum())
    lo_b, hi_b = tr.boot(lambda ix: float(decided[ix].mean()), len(y))
    rule = {"coverage": round(float(decided.mean()), 4), "coverage_bootstrap95":
            [round(lo_b, 4), round(hi_b, 4)], "auto_match": int(match.sum()),
            "auto_reject": int(reject.sum()), "held": int((~decided).sum()), "errors": errors,
            "error_rate": round(errors / n, 4) if n else None,
            "error_wilson95_upper": round(wilson_upper(errors, n), 4),
            "thresholds": {"lo": round(lo, 6), "hi": round(hi, 6)}}
    rule["fewer_held"] = rule["coverage"] >= 0.20 and lo_b >= 0.10
    rule["error_bound"] = (n > 0 and errors / n <= 0.03 and rule["error_wilson95_upper"] <= 0.10)
    return {**rule, "_decided": decided}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=None)
    ap.add_argument("--retrain", action="store_true")
    args = ap.parse_args()
    import torch

    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    if fc._digest(prereg["rule"]) != prereg["rule_sha256"]:
        raise SystemExit("rule differs from its recorded digest; refusing to run")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    started = time.time()
    data = examples()
    for k, v in data.items():
        print(f"{k}: {len(v)} examples, {sum(d[2] for d in v)} positive")
    dev_pairs = [(a, b) for a, b, _ in data["dev"]]
    y_dev = np.array([d[2] for d in data["dev"]])
    texts, y, _rows = review_band(prereg)
    print(f"review band: {len(y)} pairs, {int(y.sum())} same_entity")

    seeds: dict[str, Any] = {}
    probs = {}
    for seed in SEEDS:
        out = MODELS / f"seed{seed}"
        if args.retrain or not (out / "arche_training.json").exists():
            train(data["train"], seed, out, device)
        ce = CrossEncoder(out, device)
        z_dev, z = ce.logits(dev_pairs), ce.logits(texts)
        w = fit_logistic(z_dev[:, None], y_dev)          # Platt, on dev only
        p_dev, p = predict(w, z_dev[:, None]), predict(w, z[:, None])
        lo, hi = thresholds(p_dev, y_dev)
        res = apply(p, y, lo, hi)
        probs[seed] = (p, res.pop("_decided"))
        res.update({"weights": ce.weights, "platt": [round(float(v), 5) for v in w],
                    "dev_auc": round(tr.auc(p_dev, y_dev), 4), "review_auc": round(tr.auc(p, y), 4),
                    "cpu_p95_ms_per_pair": ce.cpu_p95_ms(texts)})
        seeds[f"seed{seed}"] = res
        print(f"seed {seed}: {json.dumps(res)}", flush=True)
        del ce
        torch.cuda.empty_cache()

    # The cheap baseline: two cosines and a logistic.
    enc = TextEncoder(str(E0C_ENCODER), prefix=tr.PREFIX)
    names = lambda pairs: ([a.split(" | ")[0] for a, _ in pairs],  # noqa: E731
                           [b.split(" | ")[0] for _, b in pairs])

    def feats(pairs):
        a, b = names(pairs)
        return np.c_[tr.TfidfArm().cosine(a, b), np.sum(enc.encode(a) * enc.encode(b), axis=1)]

    rng = random.Random(0)
    sample = rng.sample(data["train"], min(40_000, len(data["train"])))
    w = fit_logistic(feats([(a, b) for a, b, _ in sample]), np.array([d[2] for d in sample]))
    x_dev, x_rb = feats(dev_pairs), feats(texts)
    lo, hi = thresholds(predict(w, x_dev), y_dev)
    p_base = predict(w, x_rb)
    baseline = apply(p_base, y, lo, hi)
    base_decided = baseline.pop("_decided")
    baseline.update({"weights": [round(float(v), 5) for v in w],
                     "review_auc": round(tr.auc(p_base, y), 4)})
    print("logistic baseline:", json.dumps(baseline))

    tf_cos, enc_cos = x_rb[:, 0], x_rb[:, 1]
    secondary = {}
    for seed, (p, decided) in probs.items():
        d = decided.astype(float) - base_decided.astype(float)
        lo_d, hi_d = tr.boot(lambda ix, d=d: float(d[ix].mean()), len(y))
        a_lo, a_hi = tr.boot(lambda ix, p=p: tr.auc(p[ix], y[ix]) - tr.auc(tf_cos[ix], y[ix])
                             if 0 < y[ix].sum() < len(ix) else 0.0, len(y), seed=1)
        secondary[f"seed{seed}"] = {
            "coverage_minus_baseline": round(float(d.mean()), 4),
            "coverage_minus_baseline_bootstrap95": [round(lo_d, 4), round(hi_d, 4)],
            "worth_its_cost": lo_d > 0,
            "auc_minus_tfidf_cosine": round(tr.auc(p, y) - tr.auc(tf_cos, y), 4),
            "auc_minus_tfidf_cosine_bootstrap95": [round(a_lo, 4), round(a_hi, 4)]}

    verdict = {"pass": all(s["fewer_held"] and s["error_bound"] for s in seeds.values()),
               "latency": all(s["cpu_p95_ms_per_pair"] <= 50 for s in seeds.values()),
               "worth_its_cost": all(s["worth_its_cost"] for s in secondary.values())}
    print(json.dumps({"secondary": secondary, "verdict": verdict}, indent=2))
    out = {"schema": "arche.x0_cross_encoder.v1", "preregistration_sha256": tr._sha(PREREG),
           "examples": {k: {"n": len(v), "positive": sum(d[2] for d in v)}
                        for k, v in data.items()},
           "review_band": {"pairs": len(y), "same_entity": int(y.sum())},
           "reference_auc": {"tfidf_cosine": round(tr.auc(tf_cos, y), 4),
                             "e0c_encoder_cosine": round(tr.auc(enc_cos, y), 4)},
           "gate_alone": {"coverage": 0.0, "held": len(y)},
           "cross_encoder": seeds, "logistic_baseline": baseline, "secondary": secondary,
           "verdict": verdict, "llm_judge": "deferred: would send pairs to an outside service",
           "seconds": round(time.time() - started, 1)}
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2, sort_keys=True) + "\n",
                                  encoding="utf-8")
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
