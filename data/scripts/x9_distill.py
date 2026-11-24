#!/usr/bin/env python
"""X9: distil a local Qwen teacher into the decider's cross-encoder.

The cross-encoder learns from the GRID3 v2 / HFR id crosswalk. Positives are
twins; negatives are same-LGA records with similar names that are not the twin.
Some of those negatives are the same facility listed twice in the HFR, and some
positives are wrong id links, so the labels are noisy exactly where names are
hard. X9 asks a local Qwen2.5-7B-Instruct (``x9_teacher.py``, 4-bit, no pair
leaves the machine) to judge the hard pairs, and trains the student on a blend.

Three hard subsets, from the training states only:

* ``close_negatives``: negatives whose names have trigram cosine >= ``CLOSE``;
* ``far_positives``: positives whose names have trigram cosine < 0.5;
* ``review_pairs``: the engine's held pairs in the training states. They are new
  to training. Hard label 1 if the HFR record is the GRID3 facility's twin, 0 if
  the facility has a twin in the state and this is another record, none
  otherwise.

Arms (cross-encoder X0 recipe, 3 seeds, the same states held out as X8):

* ``baseline``: X8's cross-encoder, unchanged.
* ``hard``: X8's training examples plus the review pairs that have a hard label.
  This separates "more hard pairs" from "the teacher".
* ``student``: X8's training examples plus every review pair. Each target is
  ``0.5 * hard + 0.5 * teacher`` where a hard label exists, the teacher alone
  otherwise. The close negatives and far positives are blended the same way.

Every arm gets X8's decider on top: an augmented combiner fitted on the 1,707
development labels, with located thresholds. The test is the engine's held pairs
in the seven held-out states, against the id crosswalk (the teacher never saw
those states' pairs). Only aggregates are written.

    python data/scripts/x9_distill.py --build      # writes the teacher's input
    python data/scripts/x9_teacher.py --pairs ~/.cache/arche/x9/teacher_in.jsonl \\
        --out ~/.cache/arche/x9/teacher_out.jsonl
    python data/scripts/x9_distill.py --train
    python data/scripts/x9_distill.py --out data/er_bench/benchmark_x9_distill_result.json
"""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import importlib.util
import json
import math
import re
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("x8_uniqueness", HERE / "x8_uniqueness.py")
x8 = importlib.util.module_from_spec(_spec)
sys.modules["x8_uniqueness"] = x8
_spec.loader.exec_module(x8)
x5, x3, x1, x0, tr = x8.x5, x8.x3, x8.x1, x8.x0, x8.tr

WORK = Path.home() / ".cache" / "arche" / "x9"
MODELS = Path.home() / ".cache" / "arche" / "models" / "x9"
NATIONAL = Path.home() / ".cache" / "arche" / "national"
PREREG = x8.DATA / "er_bench" / "benchmark_x9_distill_preregistration.json"
CLOSE = 0.85
HELD_OUT = x8.HELD_OUT


def trigram_cos(a: str, b: str) -> float:
    def grams(s: str) -> collections.Counter:
        s = " " + re.sub(r"\s+", " ", s.split(" | ")[0].casefold()) + " "
        return collections.Counter(s[i:i + 3] for i in range(len(s) - 2))
    ga, gb = grams(a), grams(b)
    dot = sum(ga[k] * gb[k] for k in ga)
    norm = math.sqrt(sum(v * v for v in ga.values()) * sum(v * v for v in gb.values()))
    return dot / norm if norm else 0.0


def pid(a: str, b: str) -> str:
    return hashlib.sha256(f"{a}\0{b}".encode()).hexdigest()[:20]


def twins_by_state() -> tuple[dict[str, str], dict[str, str]]:
    with x3.HFR_NATIONAL.open(encoding="utf-8") as fh:
        hfr_state = {f["properties"]["global_id"]: (f["properties"].get("state_name") or "")
                     .strip().casefold() for f in json.load(fh)["features"]}
    grid3_state = {}
    with (x8.DATA / "GRID3_NGA_health_facilities_v2.csv").open(encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            grid3_state[r["globalid"]] = r["state"].strip().casefold()
    return grid3_state, hfr_state


def review_pairs(states: set[str], held_out: bool) -> list[dict]:
    """The engine's held pairs per state, with the id-crosswalk label where it has one."""
    grid3_state, hfr_state = twins_by_state()
    rows = []
    for d in sorted(NATIONAL.iterdir()):
        state = d.name.replace("_", " ")
        if not (d / "candidate_edges.csv").exists() or (state in states) != held_out:
            continue
        with (d / "candidate_edges.csv").open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r["decision"] != "review":
                    continue
                g, h = r["grid3_id"].split(":", 1)[1], r["hfr_id"].split(":", 1)[1]
                has_twin = hfr_state.get(g) == grid3_state.get(g) == state
                r["hard"] = 1 if h == g else (0 if has_twin else None)
                r["state"] = state
                rows.append(r)
    return rows


def build() -> dict[str, Any]:
    data = x8.examples()
    train = data["train"]
    teacher_in, counts = {}, collections.Counter()
    for a, b, y in train:
        c = trigram_cos(a, b)
        if (y == 0 and c >= CLOSE) or (y == 1 and c < 0.5):
            teacher_in[pid(a, b)] = {"id": pid(a, b), "a": a, "b": b, "hard": y,
                                     "subset": "close_negatives" if y == 0 else "far_positives"}
            counts["close_negatives" if y == 0 else "far_positives"] += 1
    for r in review_pairs(set(HELD_OUT), held_out=False):
        a, b = x1.texts([r])[0]
        teacher_in[pid(a, b)] = {"id": pid(a, b), "a": a, "b": b, "hard": r["hard"],
                                 "subset": "review_pairs"}
        counts["review_pairs"] += 1
        counts["review_pairs_hard"] += r["hard"] is not None
    WORK.mkdir(parents=True, exist_ok=True)
    with (WORK / "teacher_in.jsonl").open("w", encoding="utf-8") as fh:
        for r in teacher_in.values():
            fh.write(json.dumps(r) + "\n")
    print(json.dumps({"train_examples": len(train), **counts, "teacher_pairs": len(teacher_in)}))
    return teacher_in


def training_sets() -> dict[str, list[tuple[str, str, float]]]:
    train = x8.examples()["train"]
    teach = {r["id"]: r for r in map(json.loads, (WORK / "teacher_out.jsonl")
                                     .open(encoding="utf-8"))}
    hard, student = [], []
    for a, b, y in train:
        hard.append((a, b, float(y)))
        t = teach.get(pid(a, b))
        student.append((a, b, 0.5 * y + 0.5 * t["teacher"] if t else float(y)))
    for r in teach.values():
        if r["subset"] != "review_pairs":
            continue
        if r["hard"] is not None:
            hard.append((r["a"], r["b"], float(r["hard"])))
            student.append((r["a"], r["b"], 0.5 * r["hard"] + 0.5 * r["teacher"]))
        else:
            student.append((r["a"], r["b"], float(r["teacher"])))
    return {"hard": hard, "student": student}


def evaluate(arm: str, seed: int, dev: list[dict], test: list[dict], gxy, hxy, aliases,
             folds) -> dict[str, Any]:
    path = x8.MODELS / f"seed{seed}" if arm == "baseline" else MODELS / arm / f"seed{seed}"
    ce = x0.CrossEncoder(path, "cuda" if x1._cuda() else "cpu")
    z_dev, z_test = ce.logits(x1.texts(dev)), ce.logits(x1.texts(test))
    del ce
    y_dev = x1.labels(dev)
    w, (lo, hi), _, _ = x8.fit_arm(x5.features(dev, gxy, hxy, z_dev, aliases), y_dev, folds,
                                   augment=True)
    p = x0.predict(w, x5.features(test, gxy, hxy, z_test, aliases))
    ev = np.array([r["hard"] is not None for r in test])
    y = np.array([r["hard"] or 0 for r in test])
    match, reject = p >= hi, p <= lo
    return {"weights_digest": x0.weights_digest(path),
            "auc_cross_encoder": round(tr.auc(z_test[ev], y[ev]), 4),
            "auc_decider": round(tr.auc(p[ev], y[ev]), 4),
            "matched": int(match.sum()), "rejected": int(reject.sum()),
            "held": int((~match & ~reject).sum()),
            "twins_matched": int((match & ev & (y == 1)).sum()),
            "wrong_matched": int((match & ev & (y == 0)).sum()),
            "twins_rejected": int((reject & ev & (y == 1)).sum()),
            "matched_unscorable": int((match & ~ev).sum())}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--train", action="store_true")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    if args.build:
        build()
        return
    device = "cuda" if x1._cuda() else "cpu"
    if args.train:
        sets = training_sets()
        for arm, data in sets.items():
            print(f"{arm}: {len(data)} examples", flush=True)
            for seed in x0.SEEDS:
                x0.train(data, seed, MODELS / arm / f"seed{seed}", device)
        return
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    if x0.fc._digest(prereg["rule"]) != prereg["rule_sha256"]:
        raise SystemExit("rule differs from its recorded digest; refusing to run")
    for arm in ("hard", "student"):
        for seed in x0.SEEDS:
            if x0.weights_digest(MODELS / arm / f"seed{seed}") != prereg["models"][arm][f"seed{seed}"]:
                raise SystemExit(f"{arm} seed {seed} weights differ from the preregistered ones")
    started = time.time()
    dev = x8.read_dev()
    folds = np.array([x3.fold_of(r) for r in dev])
    gxy, hxy = x8.coordinates()
    aliases = json.loads(x5.ALIASES.read_text(encoding="utf-8"))["aliases"]
    test = review_pairs(set(HELD_OUT), held_out=True)
    result: dict[str, Any] = {"schema": "arche.x9_distill.v1",
                              "preregistration_sha256": tr._sha(PREREG),
                              "test": {"pairs": len(test),
                                       "scorable": sum(r["hard"] is not None for r in test),
                                       "twins": sum(r["hard"] == 1 for r in test)}}
    for arm in ("baseline", "hard", "student"):
        result[arm] = {f"seed{s}": evaluate(arm, s, dev, test, gxy, hxy, aliases, folds)
                       for s in x0.SEEDS}
        print(arm, json.dumps({k: (v["twins_matched"], v["wrong_matched"], v["auc_cross_encoder"])
                               for k, v in result[arm].items()}), flush=True)

    def mean(arm: str, key: str) -> float:
        return float(np.mean([v[key] for v in result[arm].values()]))

    verdict = {
        "student_more_twins": mean("student", "twins_matched")
        >= 1.05 * mean("baseline", "twins_matched"),
        "student_wrong_no_worse": mean("student", "wrong_matched")
        <= mean("baseline", "wrong_matched"),
        "teacher_helps": mean("student", "twins_matched") >= mean("hard", "twins_matched")
        and mean("student", "wrong_matched") <= mean("hard", "wrong_matched"),
    }
    verdict["student_pass"] = verdict["student_more_twins"] and verdict["student_wrong_no_worse"]
    result["means"] = {a: {k: round(mean(a, k), 2) for k in
                           ("twins_matched", "wrong_matched", "held", "auc_cross_encoder")}
                       for a in ("baseline", "hard", "student")}
    result["verdict"] = verdict
    result["seconds"] = round(time.time() - started, 1)
    print(json.dumps(result["means"]), json.dumps(verdict, indent=1))
    if args.out:
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
