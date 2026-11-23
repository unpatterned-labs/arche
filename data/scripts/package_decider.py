#!/usr/bin/env python
"""Package the tested X8 decider as an ``arche.resolve.PairDecider`` bundle.

The shipped decider is X8's ``augmented`` arm on seed 0, exactly as
preregistered and tested. It uses X8's cross-encoder and a combiner over
[cross-encoder logit, log1p km, admin2 agree through the LGA alias table,
coordinates missing], fitted on the 1,707 development labels together with
their location-free copies. It has separate thresholds for located pairs and
for pairs without location. Name uniqueness is left out (X8:
``uniqueness_helps_hidden`` false). Nothing is refitted on the Anambra test
labels, so the bundle is the artefact that was tested.

The combiner is refitted here from the same inputs with the same code
(``x8_uniqueness.fit_arm``), because the result file rounds its weights. The
script then scores the X8 test pack through the bundle and refuses to finish
unless coverage, errors and false merges equal X8's recorded seed-0 numbers for
both views.

    ~/.cache/arche-scratch/e0/bin/python data/scripts/package_decider.py \\
        --out ~/.cache/arche/models/nigeria-facility-decider-v1
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "packages" / "arche-core" / "src"))
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("x8_uniqueness", HERE / "x8_uniqueness.py")
x8 = importlib.util.module_from_spec(_spec)
sys.modules["x8_uniqueness"] = x8
_spec.loader.exec_module(x8)
x5, x3, x1, x0, tr = x8.x5, x8.x3, x8.x1, x8.x0, x8.tr

from arche.resolve.decider import DECIDER_SCHEMA, PairDecider  # noqa: E402

SEED = 0
RESULT = x8.DATA / "er_bench" / "benchmark_x8_uniqueness_result.json"
TEST_LABELS = x8.TEST_PACK.parent / x3.REVIEWED
CARD = x8.DATA / "models" / "nigeria_facility_decider_v1" / "MODEL_CARD.md"


def record(row: dict, side: str) -> dict:
    path = json.loads(row[f"{side}_admin_path"])
    return {"name": row[f"{side}_name"], "admin1": path.get("admin1", row.get("state", "")),
            "admin2": path.get("admin2", ""), "lat": row.get(f"{side}_lat"),
            "lon": row.get(f"{side}_lon")}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    model_dir = x8.MODELS / f"seed{SEED}"
    prereg = json.loads(x8.PREREG.read_text(encoding="utf-8"))
    if x0.weights_digest(model_dir) != prereg["models"][f"seed{SEED}"]:
        raise SystemExit("the cross-encoder differs from the preregistered one")

    dev = x8.read_dev()
    y = x1.labels(dev)
    folds = np.array([x3.fold_of(r) for r in dev])
    gxy, hxy = x8.coordinates()
    aliases = json.loads(x5.ALIASES.read_text(encoding="utf-8"))["aliases"]
    ce = x0.CrossEncoder(model_dir, "cuda" if x1._cuda() else "cpu")
    z = ce.logits(x1.texts(dev))
    w, (lo, hi), (hlo, hhi), _ = x8.fit_arm(x5.features(dev, gxy, hxy, z, aliases), y, folds,
                                           augment=True)
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    recorded = result["augmented_located"][f"seed{SEED}"]
    if [round(float(v), 4) for v in w] != recorded["weights"]:
        raise SystemExit("refitted weights differ from X8's recorded ones")

    spec = {
        "schema": DECIDER_SCHEMA,
        "name": "nigeria-facility-decider-v1",
        "features": ["cross_encoder_logit", "log1p_km", "admin2_agree", "coordinates_missing"],
        "weights": [float(v) for v in w],
        "thresholds": {"located": {"lo": float(lo), "hi": float(hi)},
                       "hidden": {"lo": float(hlo), "hi": float(hhi)}},
        "text": "name | admin2, each side; pairs fed (a, b)",
        "max_length": x0.MAX_LEN,
        "cross_encoder": "cross_encoder",
        "cross_encoder_sha256": x0.weights_digest(model_dir),
        "admin2_aliases": aliases,
        "provenance": {
            "experiment": "X8 augmented arm, seed 0",
            "preregistration": "data/er_bench/benchmark_x8_uniqueness_preregistration.json",
            "preregistration_sha256": tr._sha(x8.PREREG),
            "result": "data/er_bench/benchmark_x8_uniqueness_result.json",
            "result_sha256": tr._sha(RESULT),
            "development_labels": len(dev),
            "base_model": x0.BASE},
    }
    out = args.out.expanduser()
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(model_dir, out / "cross_encoder")
    (out / "decider.json").write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n",
                                      encoding="utf-8")
    if CARD.exists():
        shutil.copy(CARD, out / "MODEL_CARD.md")

    # Fidelity: the bundle must reproduce X8's seed-0 numbers on the test pack.
    decider = PairDecider.load(out)
    test = x3.read(TEST_LABELS)
    yt = x1.labels(test)
    pairs = [(record(r, "grid3"), record(r, "hfr")) for r in test]
    checks = {}
    for view, hide in (("located", False), ("hidden", True)):
        ps = [(a, {**b, "lat": None, "lon": None}) if hide else (a, b) for a, b in pairs]
        d = decider.decide(ps)
        match = np.array([x.outcome == "match" for x in d])
        reject = np.array([x.outcome == "reject" for x in d])
        got = {"coverage": round(float((match | reject).mean()), 4),
               "errors": int((match & (yt == 0)).sum() + (reject & (yt == 1)).sum()),
               "false_merges": int((match & (yt == 0)).sum())}
        want = result[f"augmented_{view}"][f"seed{SEED}"]
        expected = {"coverage": want["coverage"], "errors": want["errors"],
                    "false_merges": want["false_merges"]["auto_matched"]}
        checks[view] = {"bundle": got, "x8": expected}
        if got != expected:
            raise SystemExit(f"bundle does not reproduce X8 ({view}): {got} != {expected}")
    (out / "fidelity.json").write_text(json.dumps(checks, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"bundle": str(out), "fidelity": checks,
                      "decider_spec": decider.pins["decider_spec"]}))


if __name__ == "__main__":
    main()
