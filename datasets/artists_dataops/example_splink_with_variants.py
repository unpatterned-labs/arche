# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Splink over the artist world, with and without the variant list. Nothing else.

    uv run python datasets/artists_dataops/example_splink_with_variants.py

This is the whole experiment in one file, for a Splink user who wants to see it
without reading arche's harness. It reads the world's Parquet files and the
variant list directly, runs Splink twice, and scores both against
`truth.parquet`. It imports nothing from arche.

`bench_splink_variants.py` is the full version: six arms, strata, collisions,
threshold sweeps, the oracle. This one is the shape of it.
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import splink.comparison_level_library as cll
import splink.comparison_library as cl
from splink import DuckDBAPI, Linker, SettingsCreator, block_on

warnings.filterwarnings("ignore")
REPO = Path(__file__).resolve().parents[2]
WORLD = REPO / "data" / "synthetic" / "worlds" / "artists_v0"
VARIANTS = REPO / "datasets" / "data" / "artist_variants.jsonl"


def norm(s: str) -> str:
    return " ".join((s or "").casefold().split())


# --- 1. the records a matcher is given (no truth column in this file) --------
obs = pq.read_table(WORLD / "observations.parquet").to_pandas()
obs["name"] = obs["name"].map(norm)

# --- 2. the variant list: name -> its group ----------------------------------
group_of: dict[str, list[str]] = {}
for line in VARIANTS.read_text(encoding="utf-8").splitlines():
    if line.strip():
        names = sorted({norm(n) for n in json.loads(line)["names"]})
        for n in names:
            group_of[n] = names

obs["name_variants"] = obs["name"].map(lambda n: group_of.get(n, [n]))
obs["canonical"] = obs["name_variants"].map(lambda v: v[0])
obs = obs.rename(columns={"record_id": "unique_id"})[
    ["unique_id", "name", "canonical", "name_variants", "country"]]


# --- 3. two models: without the list, and with it as a comparison level -----
def settings(with_list: bool) -> SettingsCreator:
    levels = [cll.NullLevel("name"),
              cll.ExactMatchLevel("name").configure(tf_adjustment_column="name")]
    if with_list:
        levels.append(cll.ArrayIntersectLevel("name_variants", min_intersection=1))
    levels += [cll.JaroWinklerLevel("name", 0.92), cll.JaroWinklerLevel("name", 0.88),
               cll.JaroWinklerLevel("name", 0.7), cll.ElseLevel()]
    rules = [block_on("name"), block_on("substr(name,1,4)")]
    if with_list:
        rules.append(block_on("canonical"))     # reach pairs that share no prefix
    return SettingsCreator(
        link_type="dedupe_only",
        comparisons=[cl.CustomComparison(levels, output_column_name="name"),
                     cl.ExactMatch("country")],
        blocking_rules_to_generate_predictions=rules,
    )


def run(with_list: bool) -> set[frozenset]:
    linker = Linker(obs, settings(with_list), db_api=DuckDBAPI())
    linker.training.estimate_probability_two_random_records_match([block_on("name")], recall=0.6)
    linker.training.estimate_u_using_random_sampling(max_pairs=5e6, seed=42)
    # Country is learned while blocking on the name; the name (and the list
    # level) while blocking on country. Not on a name prefix: Splink treats a
    # comparison whose column appears in the blocking rule as untrainable in
    # that session, and a name-prefix rule leaves every name level at its
    # default -- a model that never learned what a name is worth.
    for rule in (block_on("name"), block_on("country")):
        linker.training.estimate_parameters_using_expectation_maximisation(rule)
    out = linker.inference.predict(threshold_match_probability=0.5).as_pandas_dataframe()
    return {frozenset((a, b)) for a, b in zip(out.unique_id_l, out.unique_id_r, strict=False)}


# --- 4. the truth, read only to score --------------------------------------------
truth_df = pq.read_table(WORLD / "truth.parquet").to_pandas()
truth: set[frozenset] = set()
for _, ids in truth_df.groupby("truth_entity_id")["record_id"]:
    ids = sorted(ids)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            truth.add(frozenset((a, b)))

# The stratum the list exists for: pairs whose names are not string-similar.
diffs = pq.read_table(WORLD / "differences.parquet").to_pandas()
alias = {frozenset((a, b)) for a, b, c in
         zip(diffs.observation_a, diffs.observation_b, diffs.cause, strict=False) if c == "alias"}

print(f"{'arm':<22}{'precision':>10}{'recall':>8}{'alias recall':>14}{'false':>7}")
for label, with_list in (("splink, raw", False), ("splink + variants", True)):
    got = run(with_list)
    tp, fp = len(got & truth), len(got - truth)
    print(f"{label:<22}{tp / (tp + fp):>10.3f}{tp / len(truth):>8.3f}"
          f"{len(got & alias) / len(alias):>14.3f}{fp:>7,}")
