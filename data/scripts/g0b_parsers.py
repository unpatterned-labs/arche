#!/usr/bin/env python
"""G0b: address parsing on African addresses -- arche, arche with fixed capitalisation, libpostal.

G0a (``g0_parsers.py``) scored the parsers on libpostal's own test set (US, GB,
AU, ZA), where arche's parser failed mostly because the addresses were
lower-case. G0b asks the question where arche's users are: NG, KE and GH.

Arms (each receives the address string only):

* ``arche``: ``arche.addr.parse.parse_address``, mapped to fields as in G0a.
* ``arche_cased``: the same parser, but an input with no lower-case letters or
  no upper-case letters is first re-cased word by word (``ROAD`` -> ``Road``,
  ``ikeja`` -> ``Ikeja``). Mixed-case input is passed unchanged.
* ``libpostal``: libpostal with Senzing's v1.2 model, as in G0a. libpostal is
  trained on OSM; its output is measured here and never used as a label.

Sets:

* **primary**: the blind pack (``build_g0b_pack.py``), labelled by a person in
  ``labels.csv``; rows marked ``skip`` are dropped. Only scored after the
  preregistration is written.
* **secondary**: 300 synthetic NG/GH addresses from synthetic-dev's sanov
  generator (``23 Airport Road, Ikorodu, Lagos State``), each as generated,
  upper-cased and lower-cased, with the parts known from the template. This is a
  sanity check, not evidence: one template, no landmarks.

Fields and matching are G0a's (house_number, road, unit, suburb, city, state,
postcode; equal after case folding and removing non-alphanumerics; a field the
gold leaves empty must be empty), with one addition: a trailing "state",
"region" or "county" is dropped from the state field on both sides. A labelled
``landmark`` is reported, not scored. Only aggregates are written.

    LIBPOSTAL_DATA_DIR=... uv run --package arche-core --with postal python \\
        data/scripts/g0b_parsers.py --out data/er_bench/benchmark_g0b_parsers_result.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import re
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
_spec = importlib.util.spec_from_file_location("g0_parsers", HERE / "g0_parsers.py")
g0 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(g0)

G0B = Path.home() / ".cache" / "arche" / "g0b"
PREREG = REPO / "data" / "er_bench" / "benchmark_g0b_parsers_preregistration.json"
FIELDS = g0.FIELDS
_STATE_SUFFIX = re.compile(r"(?i)\s+(state|region|county)\s*$")


def sha(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def recase(text: str) -> str:
    if text == text.upper() or text == text.lower():
        return re.sub(r"[A-Za-z]+", lambda m: m.group(0).capitalize(), text)
    return text


def arms() -> dict[str, Any]:
    arche = g0.arche_arm()
    return {"arche": arche, "arche_cased": lambda t: arche(recase(t)),
            "libpostal": g0.libpostal_arm()}


def tidy(row: dict) -> dict:
    out = {f: (row.get(f) or "") for f in FIELDS}
    out["state"] = _STATE_SUFFIX.sub("", out["state"])
    return out


def read_primary() -> list[dict]:
    with (G0B / "pack" / "labels.csv").open(encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if not (r.get("skip") or "").strip()
                and ("labelled_by" not in r or (r["labelled_by"] or "").strip())]
    return rows


def read_synth() -> list[dict]:
    with (G0B / "synth.csv").open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def run(rows: list[dict], parsers: dict[str, Any], by: str) -> dict[str, Any]:
    gold = [tidy(r) for r in rows]
    preds = {a: [tidy(p(r["address"]) or {}) for r in rows] for a, p in parsers.items()}
    out: dict[str, Any] = {"arms": {}, "comparisons": {}}
    ok: dict[str, list[bool]] = {}
    for a, ps in preds.items():
        out["arms"][a] = {}
        for group in ["all", *sorted({r[by] for r in rows})]:
            ix = [i for i, r in enumerate(rows) if group == "all" or r[by] == group]
            res, correct = g0.score([gold[i] for i in ix], [ps[i] for i in ix])
            out["arms"][a][group] = res
            if group == "all":
                ok[a] = correct
    for x, y in (("libpostal", "arche"), ("arche_cased", "arche"), ("libpostal", "arche_cased")):
        out["comparisons"][f"{x}_minus_{y}"] = {}
        for group in ["all", *sorted({r[by] for r in rows})]:
            ix = [i for i, r in enumerate(rows) if group == "all" or r[by] == group]
            out["comparisons"][f"{x}_minus_{y}"][group] = g0.paired_diff(
                [ok[x][i] for i in ix], [ok[y][i] for i in ix])
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--synthetic-only", action="store_true",
                    help="score the synthetic set only (no labels read)")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    started = time.time()
    parsers = arms()
    result: dict[str, Any] = {"schema": "arche.g0b_parsers.v1"}
    if not args.synthetic_only:
        prereg = json.loads(PREREG.read_text(encoding="utf-8"))
        if "sha256:" + hashlib.sha256(json.dumps(prereg["rule"], sort_keys=True).encode()) \
                .hexdigest() != prereg["rule_sha256"]:
            raise SystemExit("rule differs from its recorded digest")
        for name, digest in prereg["code"].items():
            if sha(HERE / name) != digest:
                raise SystemExit(f"{name} changed since the preregistration")
        if sha(G0B / "pack" / "addresses.csv") != prereg["pack"]["addresses_sha256"]:
            raise SystemExit("the pack changed since the preregistration")
        result["preregistration_sha256"] = sha(PREREG)
        rows = read_primary()
        result["primary"] = run(rows, parsers, "country")
        result["primary"]["labelled"] = len(rows)
        verdict = {}
        comp = result["primary"]["comparisons"]
        for c in ["all", *sorted({r["country"] for r in rows})]:
            cased = comp["arche_cased_minus_arche"][c]["bootstrap95"][0] > 0
            best = "arche_cased" if cased else "arche"
            lo, hi = comp[f"libpostal_minus_{best}"][c]["bootstrap95"]
            verdict[c] = {"arche_cased_beats_arche": cased, "best_arche": best,
                          "default": "libpostal" if lo > 0 else best if hi < 0
                          else f"no_difference ({best} stays)"}
        result["verdict"] = verdict
    result["secondary_synthetic"] = run(read_synth(), parsers, "variant")
    result["seconds"] = round(time.time() - started, 1)
    for k in ("primary", "secondary_synthetic"):
        if k in result:
            print(k, json.dumps({a: v["all"]["parse_correct_rate"]
                                 for a, v in result[k]["arms"].items()}))
    if "verdict" in result:
        print(json.dumps(result["verdict"]))
    if args.out:
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
