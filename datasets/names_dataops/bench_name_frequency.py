#!/usr/bin/env python
# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Does the name-frequency signal prevent false merges, and does it ship?

    python datasets/names_dataops/bench_name_frequency.py

Why this script exists
----------------------
`arche` has claimed, in its README and in `concepts/the-whole-picture`, that
adding the frequency signal takes false merges from 40% to 0% on a set of 60
positives and 60 hard negatives. That number was not reproducible: the set was
never committed, no script computed it, and the document both pages cited did
not exist. This replaces it with something anyone can re-run.

It is not a like-for-like replacement. The old number came from pairs we wrote
ourselves, chosen to exhibit the failure the signal was built to fix. The
negatives here are drawn from a real population register, so the pairs are
whatever the register happens to contain.

Three arms, because "the frequency signal" is three different things
--------------------------------------------------------------------
A `tftoken` comparator needs a table of how common each token is. Where that
table comes from changes the answer, and `crosswalk` resolves it differently
depending on how it is called:

* **blind** — the `person` pack with the `tftoken` comparator removed. No
  frequency information at all.
* **shipped** — `reconcile(entity="person")`, exactly what a user gets. The
  pack contains `tftoken`, but `person` is absent from `_PACK_TF_DOMAIN`, so
  no shipped table is loaded and `crosswalk` falls back to self-calibrating a
  table over the two lists being linked (`resolve/__init__.py`, the
  `if tf is None` branch).
* **population** — the same pack with `tf="person"`, which loads
  `name_frequencies.json.gz`: 50,591 tokens built from the 2010 US Census
  surname file and the African names lexicon.

The distinction matters because a self-calibrated table measures the lists in
front of it, not a population. Two lists of a few hundred names cannot know
that *Smith* is ordinary. This is the same defect the `organisation` pack was
given a `_PACK_TF_DOMAIN` entry to fix, with a code comment saying so; `person`
never got one.

So the third arm is not a variant. It is the question of whether the README's
claim describes the software people install.

What is measured
----------------
One linkage run per arm over the same two lists, which is how the engine is
actually used — not pair by pair, because that would starve the self-calibrated
arm of the population it is entitled to.

A *false merge* is any pair the arm decided `match` that is not the designated
same-person pair, including merges onto some third record. `review` is not a
merge; abstention is the behaviour under test, not a failure of it.

The two classes are not equally trustworthy, and that matters more than any
number below.

* **Negatives are observed.** Two records from the register with the same
  surname, different first names, different birth years and different voter
  IDs. Real people who really do share a surname. Nothing is constructed,
  including how similar their given names happen to be.
* **Positives are constructed.** One real record rendered two ways: with its
  middle name, and with the middle name dropped or reduced to an initial. That
  is an ordinary recording difference and it is the case this project keeps
  citing ("John Smith" vs "John Evelyn Smith"), but we generated the second
  form. Recall describes that generated distribution, not an observed one.

**The false-merge column is evidence; the recall column is a sanity check.**

Pass criteria, declared before the run
---------------------------------------
1. `population` has a lower overall false-merge rate than `blind`.
2. `population` recall is no more than 10 points below `blind`. A safety gain
   bought by refusing to match anyone is not a gain.
3. `shipped` — what users actually get — lands nearer `population` than
   `blind` on false merges. This is the criterion that decides whether the
   README's claim is about the installed software or about a configuration
   the caller has to know to ask for.

Published whichever way they fall.

An earlier version of this script compared only `blind` against `population`,
pair by pair. Those numbers are superseded because the design was wrong, not
because of how it scored: it omitted the arm users actually get, and giving
self-calibration a two-record population was a test no arm could meaningfully
pass. Criteria above were re-declared before the corrected run.

What this still does not establish
-----------------------------------
* **One county, one country.** Alamance County, North Carolina. US naming, US
  population structure. It says nothing about whether the effect holds on
  Nigerian, Ghanaian or Kenyan registers, which is where this project claims
  its calibration is deepest. That benchmark does not exist and this is not it.
* **Surname frequency is banded using the register itself**, not arche's
  table, which keeps band assignment independent of the treatment's data. Both
  still describe US surnames, so they correlate.
* **Given-name similarity is uncontrolled.** Real pairs vary in how confusable
  they are. That is the point, but it makes the absolute false-merge rate a
  property of this register rather than a constant.
* **No comparison against a learned matcher or a frontier model.** Still the
  most important missing experiment.

Data and licence
----------------
North Carolina voter registration data, published as public record by the NC
State Board of Elections. It is **fetched at run time and never vendored**: the
file holds real people's names, addresses and birth years, and a PII-protection
project does not check that into a public repository. The cache directory is
gitignored. The committed result file holds aggregate counts only and contains
no names.

    https://www.ncsbe.gov/results-data/voter-registration-data
"""

from __future__ import annotations

import csv
import io
import json
import random
import sys
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
CACHE = _REPO / "data" / "_cache" / "ncvr"
NCVR_URL = "https://s3.amazonaws.com/dl.ncsbe.gov/data/ncvoter1.zip"
SEED = 20260816
PER_BAND = 300

sys.path.insert(0, str(_REPO / "packages" / "arche-core" / "src"))

# Surname frequency bands, counted within the register. Chosen to span the
# distribution rather than to flatter a result: the top band is where a
# frequency-blind matcher should struggle most, the bottom band is where the
# arms should agree.
BANDS = (
    ("very common", 500, 10**9),
    ("common", 100, 499),
    ("uncommon", 20, 99),
    ("rare", 5, 19),
    ("very rare", 2, 4),
)


def _fetch() -> list[dict]:
    """Real voter records. Downloaded once into a gitignored cache."""
    CACHE.mkdir(parents=True, exist_ok=True)
    blob = CACHE / "ncvoter1.zip"
    if not blob.exists():
        print(f"  downloading NCVR -> {blob} (~8 MB)", flush=True)
        req = urllib.request.Request(
            NCVR_URL, headers={"User-Agent": "arche-dataops/0.4"})
        with urllib.request.urlopen(req, timeout=300) as r:  # noqa: S310
            blob.write_bytes(r.read())
    with zipfile.ZipFile(blob) as z, z.open("ncvoter1.txt") as fh:
        return list(csv.DictReader(
            io.TextIOWrapper(fh, encoding="latin-1"), delimiter="\t"))


def _clean(s: str) -> str:
    return " ".join(s.strip().upper().split())


def _usable(r: dict) -> bool:
    """Alphabetic names long enough to compare. Initials are not names."""
    first, last = _clean(r["first_name"]), _clean(r["last_name"])
    return (len(first) >= 2 and len(last) >= 2
            and first.isalpha() and last.isalpha()
            and r["birth_year"].strip().isdigit())


def _band_of(n: int) -> str | None:
    for label, lo, hi in BANDS:
        if lo <= n <= hi:
            return label
    return None


def _full(r: dict) -> str:
    parts = [_clean(r["first_name"]), _clean(r["middle_name"]),
             _clean(r["last_name"])]
    return " ".join(p for p in parts if p)


def _first_distinct_pair(recs: list[dict]) -> tuple[str, str] | None:
    """Two records that are certainly different people, or None.

    Different voter ID, different first name and different birth year. The
    birth-year test is the one that matters: voter rolls really do contain
    duplicate registrations of one person, and those would silently become
    mislabelled negatives.
    """
    for i in range(len(recs)):
        for j in range(i + 1, len(recs)):
            a, b = recs[i], recs[j]
            if (a["ncid"] != b["ncid"]
                    and _clean(a["first_name"]) != _clean(b["first_name"])
                    and a["birth_year"] != b["birth_year"]):
                return _full(a), _full(b)
    return None


def _build_pairs(rows: list[dict]) -> list[dict]:
    """Sample negatives (observed) and positives (constructed), by band."""
    rng = random.Random(SEED)
    rows = [r for r in rows if _usable(r)]

    by_surname: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_surname[_clean(r["last_name"])].append(r)

    in_band: dict[str, list[str]] = defaultdict(list)
    for sur, recs in by_surname.items():
        band = _band_of(len(recs))
        if band:
            in_band[band].append(sur)
    for band in in_band:
        in_band[band].sort()               # determinism before shuffling
        rng.shuffle(in_band[band])

    pairs: list[dict] = []
    for label, _, _ in BANDS:
        pool = in_band[label]

        # --- negatives: real people who share a surname --------------------
        # At most one pair per surname, so one very common surname cannot
        # dominate its band.
        taken = 0
        for sur in pool:
            if taken >= PER_BAND:
                break
            recs = sorted(by_surname[sur], key=lambda r: r["ncid"])
            rng.shuffle(recs)
            pair = _first_distinct_pair(recs)
            if pair:
                pairs.append({"band": label, "cls": "neg",
                              "a": pair[0], "b": pair[1]})
                taken += 1

        # --- positives: one real person, two recordings --------------------
        cands = [r for sur in pool for r in by_surname[sur]
                 if len(_clean(r["middle_name"])) >= 2
                 and _clean(r["middle_name"]).isalpha()]
        rng.shuffle(cands)
        for k, r in enumerate(cands[:PER_BAND]):
            first, mid, last = (_clean(r["first_name"]),
                                _clean(r["middle_name"]),
                                _clean(r["last_name"]))
            # Half drop the middle name, half reduce it to an initial. Both
            # are ordinary recording differences, applied identically in every
            # band so that band is the only thing varying.
            other = (f"{first} {last}" if k % 2 == 0
                     else f"{first} {mid[0]} {last}")
            pairs.append({"band": label, "cls": "pos",
                          "a": f"{first} {mid} {last}", "b": other})
    return pairs


def _run_arm(pairs: list[dict], **kw) -> dict[str, dict]:
    """One linkage run over both lists; score edges against designated truth.

    Scoring counts merges onto a *third* record as false merges too, which
    pair-by-pair scoring cannot see. That is the real task: a linkage run is
    free to propose any candidate blocking surfaces.
    """
    from arche.resolve import reconcile

    list_a = [{"id": f"a{i}", "name": p["a"]} for i, p in enumerate(pairs)]
    list_b = [{"id": f"b{i}", "name": p["b"]} for i, p in enumerate(pairs)]
    truth = {(f"a{i}", f"b{i}") for i, p in enumerate(pairs)
             if p["cls"] == "pos"}

    res = reconcile(list_a, list_b, id_field="id", **kw)

    per_band: dict[str, dict] = {
        b: {"true_merges": 0, "false_merges": 0} for b, _, _ in BANDS}
    for edge in res["matches"]:
        if edge["decision"] != "match":
            continue
        left, right = edge["a_id"], edge["b_id"]
        idx = int(left[1:])
        band = pairs[idx]["band"]
        if (left, right) in truth:
            per_band[band]["true_merges"] += 1
        else:
            per_band[band]["false_merges"] += 1

    out: dict[str, dict] = {}
    for label, _, _ in BANDS:
        npos = sum(1 for p in pairs if p["band"] == label and p["cls"] == "pos")
        nneg = sum(1 for p in pairs if p["band"] == label and p["cls"] == "neg")
        tm, fm = per_band[label]["true_merges"], per_band[label]["false_merges"]
        prec = tm / (tm + fm) if (tm + fm) else 0.0
        rec = tm / npos if npos else 0.0
        out[label] = {
            "positives": npos, "negatives": nneg,
            "true_merges": tm, "false_merges": fm,
            "recall": round(rec, 4) if npos else None,
            "precision": round(prec, 4),
            "f1": round(2 * prec * rec / (prec + rec), 4) if prec + rec else 0.0,
            # Denominator is the observed negatives in this band. False merges
            # also include merges onto a third record, so the rate can exceed
            # 100%: an arm that links everything to everything produces far
            # more wrong edges than there are negative pairs. Read the count.
            "false_merge_rate": round(fm / nneg, 4) if nneg else None,
        }
    return out


def main() -> int:
    from arche.resolve import ENTITY_PACKS

    full_pack = ENTITY_PACKS["person"]
    blind_pack = [c for c in full_pack if c.get("kind") != "tftoken"]
    assert len(blind_pack) == len(full_pack) - 1, "ablation removed nothing"

    rows = _fetch()
    pairs = _build_pairs(rows)
    n_pos = sum(1 for p in pairs if p["cls"] == "pos")
    n_neg = sum(1 for p in pairs if p["cls"] == "neg")
    print(f"NCVR Alamance County: {len(rows):,} real registrations")
    print(f"  {n_neg} observed negatives, {n_pos} constructed positives, "
          f"seed {SEED}\n", flush=True)

    arms = {
        "blind": {"comparators": blind_pack},
        "shipped": {"entity": "person"},
        "population": {"comparators": full_pack, "tf": "person"},
    }
    results = {}
    for arm, kw in arms.items():
        print(f"  running {arm} ...", flush=True)
        results[arm] = _run_arm(pairs, **kw)

    def table(metric: str, fmt: str = "{:>9.1%}") -> None:
        print(f"\n  {metric}")
        print(f"  {'band':<12} {'n-':>5} {'n+':>5}  "
              + "".join(f"{a:>11}" for a in arms))
        for label, _, _ in BANDS:
            r0 = results["blind"][label]
            line = f"  {label:<12} {r0['negatives']:>5} {r0['positives']:>5}  "
            for a in arms:
                v = results[a][label][metric]
                line += (f"{fmt.format(v):>11}" if v is not None
                         else f"{'-':>11}")
            print(line)

    table("false_merge_rate")
    print("    (denominator is observed negatives; merges onto a third record"
          "\n     count too, so >100% means the arm links near-everything)")
    table("recall")
    table("precision")

    overall = {}
    for a in arms:
        tm = sum(results[a][b]["true_merges"] for b, _, _ in BANDS)
        fm = sum(results[a][b]["false_merges"] for b, _, _ in BANDS)
        prec = tm / (tm + fm) if (tm + fm) else 0.0
        rec = tm / n_pos
        overall[a] = {
            "true_merges": tm, "false_merges": fm,
            "recall": round(rec, 4), "precision": round(prec, 4),
            "f1": round(2 * prec * rec / (prec + rec), 4) if prec + rec else 0.0,
            "false_merge_rate": round(fm / n_neg, 4)}

    print(f"\n  {'OVERALL':<12} {n_neg:>5} {n_pos:>5}")
    for m in ("false_merges", "false_merge_rate", "recall", "precision", "f1"):
        line = f"    {m:<18}"
        for a in arms:
            v = overall[a][m]
            line += (f"{v:>11,}" if m == "false_merges" else f"{v:>11.1%}")
        print(line)
    print(f"    {'':<18}" + "".join(f"{a:>11}" for a in arms))

    ob, os_, op = overall["blind"], overall["shipped"], overall["population"]
    c1 = op["false_merge_rate"] < ob["false_merge_rate"]
    c2 = (ob["recall"] - op["recall"]) <= 0.10
    c3 = (abs(os_["false_merge_rate"] - op["false_merge_rate"])
          < abs(os_["false_merge_rate"] - ob["false_merge_rate"]))

    print("\n  pre-declared criteria (set before the run):")
    print(f"    1. population beats blind on false merges : "
          f"{op['false_merge_rate']:.1%} vs {ob['false_merge_rate']:.1%}  "
          f"{'PASS' if c1 else 'FAIL'}")
    print(f"    2. population recall within 10pt of blind : "
          f"{op['recall'] - ob['recall']:+.1%}  {'PASS' if c2 else 'FAIL'}")
    print(f"    3. shipped behaves like population        : "
          f"shipped {os_['false_merge_rate']:.1%} sits nearer "
          f"{'population' if c3 else 'blind'}  {'PASS' if c3 else 'FAIL'}")
    verdict = "PASS" if (c1 and c2 and c3) else "FAIL"
    print(f"\n  VERDICT: {verdict} — published either way, per standing practice.")

    # Criterion 2 is left failing rather than rewritten into a pass. Two
    # things are true at once and both belong in the record:
    #
    #   * The criterion was badly chosen. It benchmarks recall against an arm
    #     with 16% precision, and any matcher can reach 99% recall by merging
    #     everything, which is exactly what `blind` does — 7,705 wrong edges
    #     against 1,114 negatives. "Stay within 10 points of that" is a
    #     demand to also merge everything.
    #   * The cost it points at is real anyway. Both frequency-aware arms
    #     match well under half of same-person pairs that differ only by a
    #     dropped middle name. That is a recall cost worth publishing, and no
    #     previous statement of this result mentioned one.
    #
    # F1 above is the metric that makes the trade legible. It is reported, not
    # scored, because it was not declared in advance.
    print("\n  note: criterion 2 compares recall against an arm with 16.2%"
          "\n  precision, which reaches high recall by merging almost"
          "\n  everything. The criterion is weak; the recall cost it points"
          "\n  at is real. See the comment in main() and the F1 row above.")

    out = _HERE / "bench_name_frequency_result.json"
    out.write_text(json.dumps({
        "benchmark": "NCVR Alamance County (NC public voter register)",
        "what_it_is": "three-arm ablation of the person pack's tftoken "
                      "comparator: absent, self-calibrated (the shipped "
                      "default), and the shipped population table. Negatives "
                      "observed, positives constructed.",
        "source_url": NCVR_URL,
        "registrations": len(rows),
        "seed": SEED,
        "negatives": n_neg,
        "positives": n_pos,
        "bands": results,
        "overall": overall,
        "criteria": {"population_beats_blind": c1,
                     "recall_within_10pt": c2,
                     "shipped_behaves_like_population": c3},
        "verdict": verdict,
    }, indent=2), encoding="utf-8")
    print(f"  -> {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
