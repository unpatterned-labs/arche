# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""What is a name-variant list worth to Splink? One world, one variable, six arms.

    uv run python datasets/artists_dataops/bench_splink_variants.py
    uv run python datasets/artists_dataops/bench_splink_variants.py --arche   # + the arche arm, slow

Every arm is Splink. What changes is whether it is given a list of name
variants, which list, and how:

    raw              name and country, term frequency on. What a Splink user
                     runs today.
    canon/indep      each name replaced by its list group's canonical form
                     before Splink sees it. The obvious way to use a list.
    level/indep      raw name kept; a `name_variants` array column added and an
                     ArrayIntersect comparison level placed between exact and
                     Jaro-Winkler. Splink estimates m and u for that level
                     itself -- its own opinion of the list.
    both/indep       canonical name AND the variant level.
    canon/oracle     as canon, but the list is the truth's own alias groups.
    level/oracle     as level, with the truth's aliases.

`indep` is the list you can actually get: MusicBrainz joined by Wikidata P434
plus 38 curated groups, **10.5% coverage** of the truth's alias pairs
(`coverage.py`). `oracle` is 100% coverage by construction and is **leakage,
labelled**: it says what a complete list would be worth, and the gap between
the two is the value of building one. Presenting oracle as indep would be the
lie; presenting both, named, is the experiment.

Blocking is part of the treatment. `Wizkid` and `Ayodeji Ibrahim Balogun`
share no prefix, so a name-blocked model never proposes the pair; the list
arms also block on the list key. That is not the harness helping the list --
it is what a list is *for*, and the `blocking` column in the result says how
much of each arm's recall was reachable at all.

Scoring is the world's own evaluator (`arche_synthetic.evaluate`): recall by
stratum, false merges, and -- new here -- false merges on **collision** pairs,
distinct artists who genuinely share a name. That is the price of a list, and
it is reported beside the gain or the gain is not worth reporting.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
import warnings
from collections import defaultdict
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "data" / "synthetic"))
from arche_synthetic.evaluate import Benchmark, Predictions, pair  # noqa: E402

WORLD = _REPO / "data" / "synthetic" / "worlds" / "artists_v0"
VARIANTS = _REPO / "datasets" / "data" / "artist_variants.jsonl"
OUT = Path(__file__).with_name("bench_splink_variants_result.json")

THRESHOLDS = (0.1, 0.2, 0.3, 0.5, 0.9)
ARMS = ("raw", "canon/indep", "level/indep", "both/indep", "canon/oracle", "level/oracle")


def norm(name: str) -> str:
    return " ".join((name or "").casefold().split())


# --- the lists ---------------------------------------------------------------

def independent_list() -> dict[str, dict[str, Any]]:
    """name -> {canonical, names} from the MusicBrainz + curated list."""
    by_name: dict[str, dict[str, Any]] = {}
    for line in VARIANTS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        g = json.loads(line)
        names = sorted({norm(n) for n in g["names"]})
        for n in names:
            # A name in two list groups (the same artist listed twice) gets
            # the union, so nothing the list knows is thrown away.
            if n in by_name:
                merged = sorted(set(by_name[n]["names"]) | set(names))
                by_name[n] = {"canonical": min(merged), "names": merged}
                for m in merged:
                    by_name[m] = by_name[n]
            else:
                by_name[n] = {"canonical": names[0], "names": names}
    return by_name


def oracle_list(out: Path) -> dict[str, dict[str, Any]]:
    """name -> group, from the truth. Leakage, and named as such."""
    import pyarrow.parquet as pq

    truth = pq.read_table(out / "truth.parquet").to_pylist()
    obs = {r["record_id"]: r for r in
           pq.read_table(out / "observations.parquet").to_pylist()}
    names_of: dict[str, set[str]] = defaultdict(set)
    for t in truth:
        names_of[t["truth_entity_id"]].add(norm(obs[t["record_id"]]["name"]))
    by_name: dict[str, dict[str, Any]] = {}
    for names in names_of.values():
        names = sorted(names)
        for n in names:
            if n in by_name:
                merged = sorted(set(by_name[n]["names"]) | set(names))
                by_name[n] = {"canonical": min(merged), "names": merged}
                for m in merged:
                    by_name[m] = by_name[n]
            else:
                by_name[n] = {"canonical": names[0], "names": names}
    return by_name


# --- the frame ---------------------------------------------------------------

def frame(bench: Benchmark, lookup: dict[str, dict[str, Any]] | None):
    import pandas as pd

    rows = []
    for o in bench.observations:
        n = norm(o["name"])
        g = lookup.get(n) if lookup else None
        rows.append({
            "unique_id": o["record_id"],
            "name": n,
            "canonical": g["canonical"] if g else n,
            "name_variants": g["names"] if g else [n],
            "country": o.get("country") or None,
        })
    return pd.DataFrame(rows)


# --- the model ---------------------------------------------------------------

def settings(arm: str):
    import splink.comparison_level_library as cll
    import splink.comparison_library as cl
    from splink import SettingsCreator, block_on

    canon = arm.startswith(("canon", "both"))
    level = arm.startswith(("level", "both"))
    name_col = "canonical" if canon else "name"

    rules = [block_on(name_col), block_on(f"substr({name_col},1,4)")]
    if level:
        # Reach pairs that share a variant but no prefix. Splink has no
        # array-overlap blocking rule; the canonical key is the cheap
        # equivalent and it is exactly the key the list defines.
        rules.append(block_on("canonical"))

    levels = [cll.NullLevel(name_col),
              cll.ExactMatchLevel(name_col).configure(tf_adjustment_column=name_col)]
    if level:
        levels.append(cll.ArrayIntersectLevel("name_variants", min_intersection=1))
    levels += [cll.JaroWinklerLevel(name_col, 0.92),
               cll.JaroWinklerLevel(name_col, 0.88),
               cll.JaroWinklerLevel(name_col, 0.7),
               cll.ElseLevel()]
    return SettingsCreator(
        link_type="dedupe_only",
        blocking_rules_to_generate_predictions=rules,
        comparisons=[cl.CustomComparison(levels, output_column_name="name"),
                     cl.ExactMatch("country")],
        retain_intermediate_calculation_columns=False,
    ), name_col


def run_splink(df, arm: str) -> tuple[list[tuple[tuple[str, str], float]], dict[str, Any]]:
    from splink import DuckDBAPI, Linker, block_on

    s, name_col = settings(arm)
    linker = Linker(df, s, db_api=DuckDBAPI())
    linker.training.estimate_probability_two_random_records_match(
        [block_on(name_col)], recall=0.6)
    # Seeded. Unseeded, the canonicalised oracle arm's false-merge count at
    # p >= 0.3 landed at 4,258 on one run and 1,180 on the next -- recall by
    # stratum was identical both times, precision was not. The seed makes a
    # run reproducible; it does not make the number less sensitive, and the
    # instability is reported with the result rather than hidden by it.
    linker.training.estimate_u_using_random_sampling(max_pairs=5e6, seed=42)
    # Two EM sessions so every comparison is trained on a rule that does not
    # fix it: country is learned while blocking on the name; the name (and
    # the variant level) while blocking on country. Not on a name prefix --
    # Splink treats any comparison whose column appears in the blocking rule
    # as untrainable in that session, so `substr(name,1,2)` left every name
    # level with m=None and the first run of this script scored a model that
    # had never learned what a name is worth (measured, not assumed).
    for rule in (block_on(name_col), block_on("country")):
        try:
            linker.training.estimate_parameters_using_expectation_maximisation(rule)
        except Exception as exc:      # noqa: BLE001
            print(f"    EM on {rule} did not converge: {exc}", flush=True)

    model = linker.misc.save_model_to_json()
    learned = {}
    for c in model["comparisons"]:
        if c["output_column_name"] != "name":
            continue
        for lv in c["comparison_levels"]:
            m, u = lv.get("m_probability"), lv.get("u_probability")
            if m and u:
                learned[lv["label_for_charts"]] = round(math.log2(m / u), 2)

    out = linker.inference.predict(threshold_match_probability=0.001).as_pandas_dataframe()
    got = [((str(a), str(b)), float(p)) for a, b, p in
           zip(out["unique_id_l"], out["unique_id_r"], out["match_probability"], strict=False)]
    return got, learned


# --- arche, for the record ----------------------------------------------------

def run_arche(bench: Benchmark) -> tuple[set, set]:
    from arche.resolve import reconcile

    records = [{"id": o["record_id"], "name": o["name"], "country": o.get("country")}
               for o in bench.observations]
    res = reconcile(records, records, entity="artist", id_field="id")
    match = {pair(e["a_id"], e["b_id"]) for e in res["matches"]
             if e["a_id"] != e["b_id"] and e["decision"] == "match"}
    review = {pair(e["a_id"], e["b_id"]) for e in res["matches"]
              if e["a_id"] != e["b_id"] and e["decision"] == "review"}
    return match, review


# --- collisions ----------------------------------------------------------------

def collision_pairs(bench: Benchmark, out: Path) -> set:
    """Record pairs whose entities are a known collision (distinct, same name)."""
    import pyarrow.parquet as pq

    rows = pq.read_table(out / "collisions.parquet").to_pylist()
    colliding = {frozenset((r["entity_a"], r["entity_b"])) for r in rows}
    pairs = set()
    for a, b in ((a, b) for a in bench.by_entity for b in bench.by_entity if a < b):
        if frozenset((a, b)) in colliding:
            for ra in bench.by_entity[a]:
                for rb in bench.by_entity[b]:
                    pairs.add(pair(ra, rb))
    return pairs


# --- main ----------------------------------------------------------------------

def main() -> int:
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--world", default=str(WORLD))
    ap.add_argument("--arche", action="store_true", help="also run the arche artist pack")
    args = ap.parse_args()
    out = Path(args.world)

    bench = Benchmark.load(out)
    collisions = collision_pairs(bench, out)
    indep = independent_list()
    oracle = oracle_list(out)
    print(f"  {len(bench.observations):,} records, {len(bench.true_pairs):,} true pairs, "
          f"{len(collisions):,} collision record pairs")
    print(f"  independent list: {len(set(id(v) for v in indep.values())):,} groups; "
          f"oracle: {len(set(id(v) for v in oracle.values())):,}\n", flush=True)

    # The list's ceiling in the world's own currency: the share of alias
    # *record* pairs whose two names sit in one list group. Higher than the
    # name-pair coverage in coverage.py, because well-known artists -- the
    # ones MusicBrainz knows -- also have more records.
    by_id = {o["record_id"]: norm(o["name"]) for o in bench.observations}
    alias_pairs = bench.by_cause.get("representation/alias", set())

    def reachable(lookup: dict[str, dict[str, Any]]) -> float:
        hit = sum(1 for a, b in alias_pairs
                  if by_id[a] in lookup and by_id[b] in lookup
                  and lookup[by_id[a]]["canonical"] == lookup[by_id[b]]["canonical"])
        return round(hit / len(alias_pairs), 4) if alias_pairs else 0.0

    ceilings = {"indep": reachable(indep), "oracle": reachable(oracle)}

    # The alias stratum is bounded at Jaro-Winkler 0.88 on the *intended*
    # names, so it still holds pairs a lenient string level can reach (a
    # JW >= 0.7 level is in every arm and EM prices it at about +7 bits).
    # The claim the article makes is about pairs no string method can see, so
    # that sub-stratum is carved out here on the observed names: alias pairs
    # whose two records are below 0.7. Nothing but a list reaches these.
    from arche_synthetic.artists import jaro_winkler
    hard_alias = {p for p in alias_pairs if jaro_winkler(by_id[p[0]], by_id[p[1]]) < 0.7}
    print(f"  alias pairs below JW 0.7 on observed names: {len(hard_alias):,} of "
          f"{len(alias_pairs):,}", flush=True)
    print(f"  alias record pairs the list can reach: indep {ceilings['indep']:.1%}, "
          f"oracle {ceilings['oracle']:.1%}\n", flush=True)

    report: dict[str, Any] = {"world": out.name, "records": len(bench.observations),
                              "true_pairs": len(bench.true_pairs),
                              "collision_pairs": len(collisions),
                              "alias_ceiling": ceilings, "arms": {}}

    def record(label: str, pairs: set, *, candidates: set | None = None,
               abstentions: set | None = None, seconds: float = 0.0,
               notes: dict | None = None) -> None:
        r = bench.score(Predictions(arm=label, pairs=pairs, candidates=candidates or set(),
                                    abstentions=abstentions or set(), seconds=seconds,
                                    notes=notes or {}))
        claimed = {p for p in pairs if p[0] in bench.truth and p[1] in bench.truth}
        false_pairs = claimed - bench.true_pairs
        r["false"] = len(false_pairs)
        r["false_on_collisions"] = len(false_pairs & collisions)
        r["recall_by_stratum"]["representation/alias<0.7"] = {
            "true_pairs": len(hard_alias),
            "recall": round(len(claimed & hard_alias) / len(hard_alias), 4)
            if hard_alias else 0.0}
        report["arms"][label] = r

    for arm in ARMS:
        lookup = None if arm == "raw" else (oracle if arm.endswith("oracle") else indep)
        df = frame(bench, lookup)
        print(f"  splink {arm} ...", flush=True)
        t0 = time.time()
        got, learned = run_splink(df, arm)
        seconds = time.time() - t0
        candidates = {pair(a, b) for (a, b), _ in got}
        for t in THRESHOLDS:
            record(f"splink {arm} p>={t}", {pair(a, b) for (a, b), p in got if p >= t},
                   candidates=candidates, seconds=seconds, notes={"learned_bits": learned})
        # The arm's own best operating point, so arms are also compared where
        # each does best rather than only at thresholds chosen in advance.
        best_t, best_f1 = None, -1.0
        for t in (i / 100 for i in range(5, 96, 5)):
            claimed = {pair(a, b) for (a, b), p in got if p >= t}
            tp = len(claimed & bench.true_pairs)
            prec = tp / len(claimed) if claimed else 0.0
            rec = tp / len(bench.true_pairs)
            f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
            if f1 > best_f1:
                best_t, best_f1 = t, f1
        record(f"splink {arm} best-F1 (p>={best_t:.2f})",
               {pair(a, b) for (a, b), p in got if p >= best_t},
               candidates=candidates, seconds=seconds,
               notes={"learned_bits": learned, "best_threshold": best_t})
        if "Array intersection size >= 1" in learned or any("intersect" in k.lower() for k in learned):
            key = next(k for k in learned if "intersect" in k.lower())
            print(f"    variant level learned at {learned[key]:+.2f} bits", flush=True)

    if args.arche:
        print("  arche artist pack ...", flush=True)
        t0 = time.time()
        match, review = run_arche(bench)
        record("arche artist pack (curated list)", match, abstentions=review,
               seconds=time.time() - t0)

    # --- print ---------------------------------------------------------------
    strata = ("representation/alias", "representation/alias<0.7",
              "representation/spelling", "error/typo")
    width = max(len(k) for k in report["arms"])
    print(f"\n  {'arm':<{width}}{'prec':>7}{'recall':>8}{'F1':>7}{'false':>7}"
          f"{'on coll.':>9}{'alias':>7}{'<0.7':>7}{'spell':>7}{'typo':>7}{'block':>7}")
    for label, r in report["arms"].items():
        s = r["recall_by_stratum"]
        o = r["overall"]
        b = r["blocking"].get("recall") if r["blocking"].get("measured") else None
        print(f"  {label:<{width}}{o['precision']:>7.3f}{o['recall']:>8.3f}{o['f1']:>7.3f}"
              f"{r['false']:>7,}{r['false_on_collisions']:>9,}"
              + "".join(f"{s.get(k, {}).get('recall', float('nan')):>7.3f}" for k in strata)
              + (f"{b:>7.3f}" if b is not None else f"{'--':>7}"))

    print("\n  what Splink learned the name levels are worth (bits), per arm:")
    seen = set()
    for label, r in report["arms"].items():
        arm = label.split(" p>=")[0]
        if arm in seen or "learned_bits" not in r["notes"]:
            continue
        seen.add(arm)
        print(f"    {arm:<14} " + "  ".join(f"{k[:22]}={v:+.1f}"
                                          for k, v in r["notes"]["learned_bits"].items()))

    OUT.write_text(json.dumps(report, indent=2, default=str) + "\n",
                   encoding="utf-8", newline="\n")
    print(f"\n  wrote {OUT.relative_to(_REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
