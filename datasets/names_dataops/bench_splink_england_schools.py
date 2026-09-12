# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Splink and arche on the England schools crosswalk, against real labels.

The three Splink comparisons so far -- Febrl 4, `historical_50k` and the
Nigerian school register -- were all *dedupe* problems, and Splink won all
three. This is the fourth, and it differs in two ways that matter.

It is a **link**, not a dedupe. Two registers, OSM and GIAS, neither carrying
the other's identifier, which is the shape most reconciliation work actually
has. `link_type="link_only"` is Splink's own answer to that shape.

And the labels are **real**. 93% of Leeds OSM school features carry a
`ref:edubase` tag, which is an editor asserting *this mapped school is that
URN*. Nobody created those tags for this benchmark. Febrl's records were
invented by a generator; the Nigerian positives were constructed by us. These
were not.

Why this run exists
-------------------
`docs-site/docs/guides/school-reconciliation.md` scores this crosswalk against
exact match, token Jaccard and `token_set_ratio` -- the things people reach for
first -- and reports that arche's shipped place pack lands at F1 0.931 against
plain exact matching's 0.930. Splink is absent from that table, and it is the
only labelled place benchmark in the repository where adding it would mean
anything. (The GRID3 x OpenStreetMap crosswalk has no ground-truth identifier
at all; `about/place-benchmark.md` calls it a consistency check and measures
precision, never recall.)

Two scoring rules, and both are reported
----------------------------------------
The guide's rule counts any predicted pair outside the truth set as a false
merge. 282 of the 308 OSM features carry a label, so a correct link to one of
the other 26 is scored as an error. That rule is kept, because the existing
table uses it and a number that cannot be dropped into that table is not much
use -- but it penalises recall on unlabelled features, and it penalises
whichever engine finds more of them.

So a second rule is reported beside it: **restricted**, which scores only pairs
whose OSM feature carries a label. On that rule a false merge is genuinely a
merge of two things an editor said were different.

Neither rule is the "right" one. They bound the answer from both sides.

Thresholds
----------
Splink's decision is a probability, and no single threshold is its answer.
Borrowing one is how an earlier benchmark in this repository lost half a point
of recall to a 0.99 threshold copied from a Febrl recipe. The sweep is printed
in full and the best operating point is named rather than assumed.

arche is scored on its own vocabulary: `match` is a merge, `review` is a queue
and not a merge.

Run it with::

    uv run python datasets/names_dataops/bench_splink_england_schools.py

Stage the sources first (fetched, never committed)::

    python data/scripts/fetch_england_schools.py --la Leeds
"""
from __future__ import annotations

import csv
import json
import re
import sys
import warnings
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
DATA = _REPO / "data" / "_cache" / "schools"
OUT = Path(__file__).with_name("bench_splink_england_schools_result.json")

#: Probabilities to score Splink at. 0.01 is the prediction floor, so every
#: pair the blocking proposed is present and the sweep is over the full range
#: rather than over whatever survived a cutoff chosen in advance.
THRESHOLDS = (0.01, 0.1, 0.5, 0.9, 0.95, 0.99)


# --- data --------------------------------------------------------------------

def load() -> tuple[list[dict], list[dict], set[tuple[str, str]]]:
    """The three staged files, loaded exactly as notebook 13 loads them.

    The truth set is filtered to URNs GIAS still lists as open, which is what
    turns 286 tagged features into the 282 pairs the guide reports: four tags
    point at establishments that have since closed.
    """
    if not (DATA / "gias.csv").exists():
        raise SystemExit(
            "Stage the sources first (they are fetched, never committed):\n"
            "    python data/scripts/fetch_england_schools.py --la Leeds"
        )
    gias = list(csv.DictReader((DATA / "gias.csv").open(encoding="utf-8")))
    osm = list(csv.DictReader((DATA / "osm.csv").open(encoding="utf-8")))
    truth = {(r["osm_id"], r["urn"])
             for r in csv.DictReader((DATA / "truth_pairs.csv").open(encoding="utf-8"))}
    known = {g["urn"] for g in gias}
    return gias, osm, {(o, u) for o, u in truth if u in known}


# --- scoring -----------------------------------------------------------------

def score(pairs: set[tuple[str, str]], truth: set[tuple[str, str]],
          labelled: set[str]) -> dict:
    """Precision, recall and F1 under both rules.

    `pairs` is what the engine decided to merge, as (osm_id, urn). The two
    rules differ only in whether a link to an unlabelled OSM feature counts
    against the engine.
    """
    tp = len(pairs & truth)
    fp_all = len(pairs - truth)
    # Restricted: only pairs whose OSM feature carries a label are scored, so a
    # correct link to one of the 26 unlabelled features is neither credited nor
    # penalised.
    fp_res = len({(o, u) for o, u in pairs - truth if o in labelled})

    def _row(fp: int) -> dict:
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / len(truth) if truth else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        return {"true": tp, "false": fp, "precision": round(prec, 6),
                "recall": round(rec, 6), "f1": round(f1, 6)}

    return {"guide_rule": _row(fp_all), "restricted": _row(fp_res)}


# --- splink ------------------------------------------------------------------

def splink_settings(with_coords: bool):
    """The hand-written configuration.

    Deliberately the same shape as `bench_splink_nigeria.splink_settings`: name
    with term-frequency adjustments on, which is Splink's own answer to a name
    that repeats, plus a distance comparison when coordinates are in play.
    `link_only` is the difference, and it is the point -- OSM and GIAS are two
    registers, and asking Splink to dedupe their concatenation would be asking
    it the wrong question.
    """
    import splink.comparison_library as cl
    from splink import SettingsCreator, block_on

    rules = [block_on("name"), block_on("substr(name,1,8)")]
    comparisons = [cl.NameComparison("name")
                   .configure(term_frequency_adjustments=True)]
    if with_coords:
        # arche's place pack gets these coordinates, so withholding them here
        # would be the harness choosing the winner.
        rules += [block_on("round(lat,2)", "round(lon,2)"),
                  block_on("round(lat,1)", "round(lon,1)")]
        comparisons.append(cl.DistanceInKMAtThresholds("lat", "lon",
                                                       [0.1, 0.5, 2, 10]))
    return SettingsCreator(
        link_type="link_only",
        blocking_rules_to_generate_predictions=rules,
        comparisons=comparisons,
        retain_intermediate_calculation_columns=False,
    )


def run_splink(osm: list[dict], gias: list[dict], *, with_coords: bool
               ) -> list[tuple[tuple[str, str], float]]:
    """Every proposed pair with its match probability, as ((osm_id, urn), p)."""
    import pandas as pd
    from splink import DuckDBAPI, Linker, block_on

    def frame(rows: list[dict], key: str) -> "pd.DataFrame":
        cols = {"unique_id": [r[key] for r in rows],
                "name": [r["name"] for r in rows]}
        if with_coords:
            cols["lat"] = [float(r["lat"]) for r in rows]
            cols["lon"] = [float(r["lon"]) for r in rows]
        return pd.DataFrame(cols)

    a, b = frame(osm, "osm_id"), frame(gias, "urn")
    linker = Linker([a, b], splink_settings(with_coords), db_api=DuckDBAPI(),
                    input_table_aliases=["osm", "gias"])

    linker.training.estimate_probability_two_random_records_match(
        [block_on("name")], recall=0.5)
    linker.training.estimate_u_using_random_sampling(max_pairs=2e6)
    # EM needs to block on one field and learn another. The names-only model
    # has exactly one comparison, so there is no such pair and EM cannot run:
    # blocking on `name` leaves the name comparison with no variation, and
    # blocking on a prefix of the name raises inside Splink's own counting SQL
    # (measured, not assumed). That arm therefore predicts with Splink's
    # default m values, which Splink itself warns about at predict time. It is
    # reported because the guide has an "arche, names only" arm and dropping
    # its counterpart would be the harness choosing the winner -- but it is a
    # weaker model than the coords arm, not a like-for-like one.
    trained = False
    if with_coords:
        for rule in (block_on("round(lat,2)", "round(lon,2)"), block_on("name")):
            try:
                linker.training.estimate_parameters_using_expectation_maximisation(rule)
                trained = True
            except Exception as exc:      # noqa: BLE001
                print(f"    EM on {rule} did not converge: {exc}", flush=True)
    print(f"    EM trained: {trained}", flush=True)

    out = linker.inference.predict(
        threshold_match_probability=0.01).as_pandas_dataframe()
    # link_only keeps the frames apart, but which side lands in `_l` is not
    # guaranteed, so the OSM id is identified by shape rather than by position.
    got = []
    for left, right, p in zip(out["unique_id_l"], out["unique_id_r"],
                              out["match_probability"], strict=False):
        left, right = str(left), str(right)
        osm_id, urn = (left, right) if "/" in left else (right, left)
        got.append(((osm_id, urn), float(p)))
    return got


# --- arche -------------------------------------------------------------------

def run_arche(osm: list[dict], gias: list[dict], *, with_coords: bool
              ) -> dict[tuple[str, str], dict]:
    """The shipped place pack, exactly as notebook 13 calls it."""
    from arche.resolve import reconcile

    def rows(src: list[dict]) -> list[dict]:
        if with_coords:
            return [{"name": r["name"], "lat": r["lat"], "lon": r["lon"]}
                    for r in src]
        return [{"name": r["name"]} for r in src]

    res = reconcile(rows(osm), rows(gias), entity="place")
    return {(osm[e["a_id"]]["osm_id"], gias[e["b_id"]]["urn"]): e
            for e in res["matches"]}


# --- baselines ---------------------------------------------------------------

def _toks(s: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", s.casefold()) if t}


def baselines(osm: list[dict], gias: list[dict]) -> dict[str, set]:
    """The guide's string arms, reproduced so the table is self-contained."""
    from rapidfuzz import fuzz

    def jaccard(x: str, y: str) -> float:
        tx, ty = _toks(x), _toks(y)
        return len(tx & ty) / len(tx | ty) if tx and ty else 0.0

    arms = {
        "exact name (casefold)": lambda x, y: x.casefold().strip() == y.casefold().strip(),
        "token Jaccard >= 0.5": lambda x, y: jaccard(x, y) >= 0.5,
        "token_set_ratio >= 90": lambda x, y: fuzz.token_set_ratio(x, y) >= 90,
    }
    out: dict[str, set] = {k: set() for k in arms}
    for o in osm:
        for g in gias:
            for label, decide in arms.items():
                if decide(o["name"], g["name"]):
                    out[label].add((o["osm_id"], g["urn"]))
    return out


# --- main --------------------------------------------------------------------

def main() -> int:
    warnings.filterwarnings("ignore")
    gias, osm, truth = load()
    labelled = {o for o, _ in truth}
    print(f"  GIAS open establishments : {len(gias):>4}")
    print(f"  OSM named school features: {len(osm):>4}  "
          f"({len(labelled)} carry a ref:edubase label)")
    print(f"  truth pairs              : {len(truth):>4}\n", flush=True)

    report: dict = {"gias": len(gias), "osm": len(osm), "truth": len(truth),
                    "arms": {}}

    def record(label: str, pairs: set) -> None:
        report["arms"][label] = score(pairs, truth, labelled)

    for label, pairs in baselines(osm, gias).items():
        record(label, pairs)

    for coords in (False, True):
        suffix = "name + coords" if coords else "names only"
        print(f"  running arche ({suffix}) ...", flush=True)
        pred = run_arche(osm, gias, with_coords=coords)
        record(f"arche, {suffix}",
               {k for k, e in pred.items() if e["decision"] == "match"})
        surfaced = {k for k, e in pred.items()
                    if e["decision"] in ("match", "review")}
        report["arms"][f"arche, {suffix} (surfaced)"] = score(
            surfaced, truth, labelled)

        print(f"  running splink ({suffix}) ...", flush=True)
        sp = run_splink(osm, gias, with_coords=coords)
        for t in THRESHOLDS:
            record(f"splink p >= {t}, {suffix}",
                   {k for k, p in sp if p >= t})

    width = max(len(k) for k in report["arms"])
    for rule in ("guide_rule", "restricted"):
        title = ("every predicted pair outside the truth set is a false merge"
                 if rule == "guide_rule"
                 else "only pairs whose OSM feature carries a label are scored")
        print(f"\n  {rule}  --  {title}")
        print(f"  {'approach':<{width}}{'precision':>11}{'recall':>9}"
              f"{'F1':>8}{'true':>8}{'false':>9}")
        for label, r in report["arms"].items():
            row = r[rule]
            print(f"  {label:<{width}}{row['precision']:>11.3f}"
                  f"{row['recall']:>9.3f}{row['f1']:>8.3f}"
                  f"{row['true']:>8,}{row['false']:>9,}")

    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8",
                   newline="\n")
    print(f"\n  wrote {OUT.relative_to(_REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
