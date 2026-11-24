#!/usr/bin/env python
"""X10: synthetic name variants for the decider's cross-encoder.

X9's teacher was a noisy source of labels. X10 makes training pairs whose answer
is known by construction, aimed at the variations the reviews showed. From each
sampled GRID3 facility in the training states (never the held-out ones), with
its LGA kept on both sides:

Same facility (label 1):

* ``swap``: a facility-type phrase replaced by one it is swapped with between
  id-linked records, drawn by how often (``SWAPS``: health post / dispensary
  1,555 times, primary health clinic / primary health center 377, ...);
* ``fuse``: a space removed, joining a word to the next ("Ipokeprimary",
  "Okeeletu");
* ``spell``: one edit in the longest place word: a vowel changed, an ``h``
  added after the first consonant, or a doubled letter made single or a single
  one doubled (Ubasharu / Ubosharu, Okuesan / Okhuesan);
* ``abbrev``: primary health center / care / care center to PHC, basic health
  center to BHC, maternity and child health to MCH.

Different facility (label 0):

* ``number``: a number changed (Zango 1 / Zango 2), or a "2" added;
* ``level`` (built but **not used**): a primary-care type phrase replaced by
  general hospital or comprehensive health center. Facilities get upgraded and
  the reviewer has called such pairs the same (Owo Comprehensive / Owo PHC), so
  a level change is not a safe "different" label.

Arms (X0 recipe, 3 seeds, X8's held-out states), each with X8's decider on top
(augmented combiner on the 1,707 development labels, located thresholds):

* ``baseline``: X8's cross-encoder;
* ``synth``: X8's training examples plus the synthetic pairs;
* ``synth_hard``: plus the engine's held pairs in the training states with
  their id labels (X9's ``hard`` arm, which matched 7% more id links).

The test is X9's: the engine's held pairs in the seven held-out states, against
the id crosswalk. It was read once, for X9; X10 is fixed before it is scored
again.

    python data/scripts/x10_synthetic.py --build
    python data/scripts/x10_synthetic.py --train
    python data/scripts/x10_synthetic.py --out data/er_bench/benchmark_x10_synthetic_result.json
"""

from __future__ import annotations

import argparse
import collections
import csv
import importlib.util
import json
import random
import re
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("x9_distill", HERE / "x9_distill.py")
x9 = importlib.util.module_from_spec(_spec)
sys.modules["x9_distill"] = x9
_spec.loader.exec_module(x9)
x8, x5, x3, x1, x0, tr = x9.x8, x9.x5, x9.x3, x9.x1, x9.x0, x9.tr

WORK = Path.home() / ".cache" / "arche" / "x10"
MODELS = Path.home() / ".cache" / "arche" / "models" / "x10"
PREREG = x8.DATA / "er_bench" / "benchmark_x10_synthetic_preregistration.json"
SEED = 20261123
N_POSITIVE, N_NEGATIVE = 12000, 4000
MIN_SWAP = 30
PRIMARY = ("primary health care center", "primary health center", "primary health care",
           "primary health clinic", "basic health center", "health center", "health clinic",
           "health post", "dispensary")
ABBREV = {"primary health care center": "phc", "primary health center": "phc",
          "primary health care": "phc", "basic health center": "bhc",
          "maternity and child health": "mch"}
LEVELS = ("general hospital", "comprehensive health center")
VOWELS = {"a": "o", "o": "a", "e": "i", "i": "e", "u": "o"}


def fold(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s.casefold()).split())


def mine_swaps() -> dict[str, list[tuple[str, int]]]:
    """Type-phrase swaps between id-linked training pairs with equal name cores."""
    c: collections.Counter = collections.Counter()
    for a, b, y in x8.examples()["train"]:
        if y != 1:
            continue
        na, nb = a.split(" | ")[0], b.split(" | ")[0]
        if x8.core(na) and x8.core(na) == x8.core(nb):
            ta = " ".join(t for t in x8._fold(na).split() if t in x8.TYPE_WORDS)
            tb = " ".join(t for t in x8._fold(nb).split() if t in x8.TYPE_WORDS)
            if ta and tb and ta != tb:
                c[(ta, tb)] += 1
    out: dict[str, list[tuple[str, int]]] = collections.defaultdict(list)
    for (ta, tb), n in c.items():
        if n >= MIN_SWAP:
            out[ta].append((tb, n))
    return dict(out)


def find(name: str, phrases) -> str | None:
    padded = f" {name} "
    for p in sorted(phrases, key=len, reverse=True):
        if f" {p} " in padded:
            return p
    return None


def replace(name: str, old: str, new: str) -> str:
    return " ".join(f" {name} ".replace(f" {old} ", f" {new} ", 1).split())


def variant(name: str, kind: str, swaps, rng: random.Random) -> str | None:
    words = name.split()
    if kind == "swap":
        p = find(name, swaps)
        if not p:
            return None
        options, weights = zip(*swaps[p], strict=True)
        return replace(name, p, rng.choices(options, weights)[0])
    if kind == "fuse":
        if len(words) < 2:
            return None
        i = rng.randrange(len(words) - 1)
        return " ".join(words[:i] + [words[i] + words[i + 1]] + words[i + 2:])
    if kind == "spell":
        place = [w for w in words if w not in x8.TYPE_WORDS and len(w) >= 4 and w.isalpha()]
        if not place:
            return None
        w = max(place, key=len)
        edit = rng.choice(("vowel", "h", "double"))
        if edit == "vowel":
            idx = [i for i, ch in enumerate(w) if ch in VOWELS and 0 < i < len(w) - 1]
            if not idx:
                return None
            i = rng.choice(idx)
            new = w[:i] + VOWELS[w[i]] + w[i + 1:]
        elif edit == "h":
            i = next((i for i, ch in enumerate(w) if ch not in "aeiou"), None)
            if i is None or i + 1 >= len(w) or w[i + 1] == "h":
                return None
            new = w[:i + 1] + "h" + w[i + 1:]
        else:
            m = re.search(r"([b-df-hj-np-tv-z])\1", w)
            if m:
                new = w[:m.start()] + w[m.start() + 1:]
            else:
                i = rng.randrange(1, len(w) - 1)
                new = w[:i] + w[i] + w[i:] if w[i] not in "aeiou" else None
                if new is None:
                    return None
        return replace(name, w, new)
    if kind == "abbrev":
        p = find(name, ABBREV)
        return replace(name, p, ABBREV[p]) if p else None
    if kind == "number":
        m = re.search(r"\b(\d+)\b", name)
        if m:
            n = int(m.group(1))
            return name[:m.start()] + str(n + 1 if n < 9 else n - 1) + name[m.end():]
        p = find(name, PRIMARY)
        return replace(name, p, f"2 {p}") if p else None
    if kind == "level":
        if any(w in words for w in ("comprehensive", "general", "hospital", "specialist")):
            return None
        p = find(name, PRIMARY)
        return replace(name, p, rng.choice(LEVELS)) if p else None
    raise ValueError(kind)


def build() -> dict[str, Any]:
    rng = random.Random(SEED)
    swaps = mine_swaps()
    held = set(x8.HELD_OUT)
    facilities = []
    with (x8.DATA / "GRID3_NGA_health_facilities_v2.csv").open(encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            if r["state"].strip().casefold() not in held and fold(r["facility_name"]):
                facilities.append((fold(r["facility_name"]), " ".join(r["lga"].split())))
    rng.shuffle(facilities)
    pairs, counts, seen = [], collections.Counter(), set()
    want = {1: N_POSITIVE, 0: N_NEGATIVE}
    kinds = {1: ("swap", "fuse", "spell", "abbrev"), 0: ("number",)}
    for name, lga in facilities:
        for label in (1, 0):
            if counts[label] >= want[label]:
                continue
            kind = rng.choice(kinds[label])
            v = variant(name, kind, swaps, rng)
            if not v or v == name or (name, v) in seen:
                continue
            seen.add((name, v))
            a, b = (name, v) if rng.random() < 0.5 else (v, name)
            pairs.append((x0.side(a.title(), lga), x0.side(b.title(), lga), label, kind))
            counts[label] += 1
            counts[kind] += 1
        if counts[1] >= N_POSITIVE and counts[0] >= N_NEGATIVE:
            break
    WORK.mkdir(parents=True, exist_ok=True)
    with (WORK / "synthetic.jsonl").open("w", encoding="utf-8") as fh:
        for a, b, y, kind in pairs:
            fh.write(json.dumps({"a": a, "b": b, "y": y, "kind": kind}) + "\n")
    (WORK / "swaps.json").write_text(json.dumps(swaps, indent=1, sort_keys=True) + "\n",
                                     encoding="utf-8")
    print(json.dumps(dict(counts)))
    return dict(counts)


def training_sets() -> dict[str, list[tuple[str, str, float]]]:
    base = [(a, b, float(y)) for a, b, y in x8.examples()["train"]]
    synth = [(r["a"], r["b"], float(r["y"])) for r in
             map(json.loads, (WORK / "synthetic.jsonl").open(encoding="utf-8"))]
    hard = [(*x1.texts([r])[0], float(r["hard"]))
            for r in x9.review_pairs(set(x8.HELD_OUT), held_out=False) if r["hard"] is not None]
    return {"synth": base + synth, "synth_hard": base + synth + hard}


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
        for arm, data in training_sets().items():
            print(f"{arm}: {len(data)} examples", flush=True)
            for seed in x0.SEEDS:
                x0.train(data, seed, MODELS / arm / f"seed{seed}", device)
        return
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    if x0.fc._digest(prereg["rule"]) != prereg["rule_sha256"]:
        raise SystemExit("rule differs from its recorded digest; refusing to run")
    for arm in ("synth", "synth_hard"):
        for seed in x0.SEEDS:
            got = x0.weights_digest(MODELS / arm / f"seed{seed}")
            if got != prereg["models"][arm][f"seed{seed}"]:
                raise SystemExit(f"{arm} seed {seed} weights differ from the preregistered ones")
    started = time.time()
    dev = x8.read_dev()
    folds = np.array([x3.fold_of(r) for r in dev])
    gxy, hxy = x8.coordinates()
    aliases = json.loads(x5.ALIASES.read_text(encoding="utf-8"))["aliases"]
    test = x9.review_pairs(set(x8.HELD_OUT), held_out=True)
    x9.MODELS = MODELS          # evaluate() looks up non-baseline arms here
    result: dict[str, Any] = {"schema": "arche.x10_synthetic.v1",
                              "preregistration_sha256": tr._sha(PREREG),
                              "test": {"pairs": len(test),
                                       "scorable": sum(r["hard"] is not None for r in test)}}
    for arm in ("baseline", "synth", "synth_hard"):
        result[arm] = {f"seed{s}": x9.evaluate(arm, s, dev, test, gxy, hxy, aliases, folds)
                       for s in x0.SEEDS}
        print(arm, json.dumps({k: (v["twins_matched"], v["wrong_matched"], v["held"])
                               for k, v in result[arm].items()}), flush=True)

    def mean(arm: str, key: str) -> float:
        return float(np.mean([v[key] for v in result[arm].values()]))

    verdict = {}
    for arm in ("synth", "synth_hard"):
        verdict[f"{arm}_more_twins"] = (mean(arm, "twins_matched")
                                        >= 1.05 * mean("baseline", "twins_matched"))
        verdict[f"{arm}_wrong_no_worse"] = (mean(arm, "wrong_matched")
                                            <= mean("baseline", "wrong_matched"))
        verdict[f"{arm}_pass"] = verdict[f"{arm}_more_twins"] and verdict[f"{arm}_wrong_no_worse"]
    result["means"] = {a: {k: round(mean(a, k), 2) for k in
                           ("twins_matched", "wrong_matched", "held", "auc_cross_encoder")}
                       for a in ("baseline", "synth", "synth_hard")}
    result["verdict"] = verdict
    result["seconds"] = round(time.time() - started, 1)
    print(json.dumps(result["means"]), json.dumps(verdict, indent=1))
    if args.out:
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
