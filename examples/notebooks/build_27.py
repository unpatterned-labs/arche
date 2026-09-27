# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Generate 27_what_a_variant_list_is_worth.ipynb.

    python examples/notebooks/build_27.py

The experiment Splink's author asked for, as a flow you can watch: the world,
then the list, then the coverage measured before any matcher runs, then two
Splink models that differ by one comparison level, then what EM priced the
list at, then the cost in collisions.

Needs Splink: `uv sync --extra splink` or `pip install splink duckdb pandas`.
Takes about a minute to execute.
"""
from __future__ import annotations

import json
from pathlib import Path

MD, CODE = "markdown", "code"
cells: list[tuple[str, str]] = []
md = lambda t: cells.append((MD, t.strip("\n")))      # noqa: E731
code = lambda t: cells.append((CODE, t.strip("\n")))  # noqa: E731


md("""
# What a name-variant list is worth to Splink

`Wizkid` and `Ayodeji Ibrahim Balogun` are one person. No edit distance, term
frequency weight or phonetic key will ever pair them. Only a list that says
they are the same can.

Robin Linacre, who wrote Splink, asked the obvious question: **run Splink over
the same records with such a list and without it, and say what the difference
is.** This notebook is that experiment, start to finish, on real alias data.

Five steps, one per section:

1. the world, and what a matcher is given
2. the list, and where it comes from
3. **coverage, measured before any matcher runs** (this bounds the answer)
4. two Splink models differing by one comparison level
5. what Splink itself priced the list at, and what it cost

Needs Splink and DuckDB. A repository-root `uv sync` already installs both
(`arche-core[all]` carries the `resolve` extra); run the notebook with
`uv run jupyter lab` **from the repository root**, because every path below is
relative to it. Outside this repository: `pip install arche-core[resolve]`.
""")

code("""
import contextlib
import io
import json
import logging
import warnings
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from arche_synthetic import load

warnings.filterwarnings("ignore")


# Splink narrates every EM iteration: ~170 lines per arm, which buries the four
# numbers this notebook is about. It goes out at INFO through `logging`, not
# through `print`, so silencing it needs the level and not just a stdout
# redirect. Delete the two `with quiet():` blocks below to watch it train.
@contextlib.contextmanager
def quiet():
    logging.disable(logging.INFO)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            yield
    finally:
        logging.disable(logging.NOTSET)

WORLD = Path("data/synthetic/worlds/artists_v0")
VARIANTS = Path("datasets/data/artist_variants.jsonl")

w = load(WORLD)
w.describe()
""")

md("""
## 1. The world

9,944 observations of 2,905 real African musicians, each under the alternate
names Wikidata records for them. Four catalogues write about the same artist:
a streaming service that prefers the stage name, a press archive that shouts
in capitals, a rights registry that writes the legal name.

**The generator never decides what an artist is called.** It decides which of
the artist's real aliases each catalogue writes, and what it does to it: a
lost diacritic, a typo, a truncation. That is what keeps the truth honest.

The `differences` table labels every disagreement, and one label is the whole
experiment: `alias`, meaning two records name the artist differently and the
names are not string-similar.
""")

code("""
counts = pd.Series(w.difference_counts("cause")).sort_values(ascending=False)
print(counts.to_string())
print()
print(f"{len(w.observations):,} observations of {len({r['truth_entity_id'] for r in w.tables['truth']}):,} artists")
print(f"{len(w.collisions):,} pairs of *different* artists who genuinely share a name")
""")

md("""
Three records of one artist, as four catalogues wrote them:
""")

code("""
alias_row = next(r for r in w.differences if r["cause"] == "alias")
for r in w.records_of(alias_row["entity_id"]):
    print(f"  {r['source']:<12} {r['name']}")
""")

md("""
## 2. The list, and why it is not the truth

The list a matcher is given is **MusicBrainz alias sets**, joined to the truth
by Wikidata's MusicBrainz identifier (property P434) and never by name.

That join matters more than anything else here. A list derived from the truth
would win by construction: it would know every alias because it *is* the
answer key. MusicBrainz is a different editorial community, so the list and
the truth can disagree, and the number that comes out is a number about lists
you can actually get.
""")

code("""
group_of = {}
def norm(s):
    return " ".join((s or "").casefold().split())

for line in VARIANTS.read_text(encoding="utf-8").splitlines():
    if line.strip():
        names = sorted({norm(n) for n in json.loads(line)["names"]})
        for n in names:
            group_of[n] = names

print(f"{len(set(map(tuple, group_of.values()))):,} groups, {len(group_of):,} names")
for names in list({tuple(v) for v in group_of.values()})[:4]:
    print("  ", " | ".join(names))
""")

md("""
## 3. Coverage, before any matcher runs

This is the step that keeps the experiment honest, and it comes first on
purpose. **A list that covers one alias pair in ten can lift recall on that
stratum by at most about ten points, whatever the matcher does.** Measuring
coverage before running Splink means the result can be checked against what
was possible, rather than admired on its own.
""")

code("""
truth_rows = w.tables["truth"]
by_entity = {}
for r in truth_rows:
    by_entity.setdefault(r["truth_entity_id"], []).append(r["record_id"])

name_of = {o["record_id"]: norm(o["name"]) for o in w.observations}

alias_pairs = covered = 0
for members in by_entity.values():
    for i, a in enumerate(sorted(members)):
        for b in sorted(members)[i + 1:]:
            na, nb = name_of[a], name_of[b]
            if na == nb:
                continue
            alias_pairs += 1
            if nb in group_of.get(na, []):
                covered += 1

print(f"record pairs whose names differ : {alias_pairs:,}")
print(f"          the list knows about  : {covered:,}")
print(f"                       coverage : {covered / alias_pairs:.1%}")
""")

md("""
About one in ten. Hold that number: the recall gain measured below should
land near it, and if it lands far above, something is leaking.

(`datasets/artists_dataops/coverage.py` reports the same list two other ways,
10.5% of distinct *name* pairs and 13.4% of *alias* record pairs. The
denominator above is every record pair of one artist whose two names differ,
which is the population this experiment scores on.)

## 4. Two models, differing by one level

Both arms are Splink. They are identical except for two things, and both are
the list doing its job:

- a comparison level, `ArrayIntersectLevel("name_variants")`, placed between
  exact match and Jaro-Winkler, **with its m and u estimated by EM like every
  other level**. Splink is not told what the list is worth; it learns it.
- a blocking rule on the list's canonical key, because a pair that shares no
  prefix is otherwise never proposed at all. A comparison level cannot help
  with a pair the blocking never generates.
""")

code("""
import splink.comparison_level_library as cll
import splink.comparison_library as cl
from splink import DuckDBAPI, Linker, SettingsCreator, block_on

obs = pq.read_table(WORLD / "observations.parquet").to_pandas()
obs["name"] = obs["name"].map(norm)
obs["name_variants"] = obs["name"].map(lambda n: group_of.get(n, [n]))
obs["canonical"] = obs["name_variants"].map(lambda v: v[0])
obs = obs.rename(columns={"record_id": "unique_id"})[
    ["unique_id", "name", "canonical", "name_variants", "country"]]

def settings(with_list):
    levels = [cll.NullLevel("name"),
              cll.ExactMatchLevel("name").configure(tf_adjustment_column="name")]
    if with_list:
        levels.append(cll.ArrayIntersectLevel("name_variants", min_intersection=1))
    levels += [cll.JaroWinklerLevel("name", 0.92), cll.JaroWinklerLevel("name", 0.88),
               cll.JaroWinklerLevel("name", 0.7), cll.ElseLevel()]
    rules = [block_on("name"), block_on("substr(name,1,4)")]
    if with_list:
        rules.append(block_on("canonical"))
    return SettingsCreator(
        link_type="dedupe_only",
        comparisons=[cl.CustomComparison(levels, output_column_name="name"),
                     cl.ExactMatch("country")],
        blocking_rules_to_generate_predictions=rules)

obs.head(3)
""")

md("""
The training is the same for both arms. Country is learned while blocking on
the name, and the name (with the list level) while blocking on country: Splink
treats a comparison whose column appears in the blocking rule as untrainable
in that session, so training on a name prefix would leave every name level at
its default, which is a model that never learned what a name is worth.
""")

code("""
def run(with_list):
    linker = Linker(obs, settings(with_list), db_api=DuckDBAPI())
    with quiet():
        linker.training.estimate_probability_two_random_records_match(
            [block_on("name")], recall=0.6)
        linker.training.estimate_u_using_random_sampling(max_pairs=5e6, seed=42)
        for rule in (block_on("name"), block_on("country")):
            linker.training.estimate_parameters_using_expectation_maximisation(rule)
        out = linker.inference.predict(threshold_match_probability=0.5).as_pandas_dataframe()
    pairs = {frozenset((a, b)) for a, b in zip(out.unique_id_l, out.unique_id_r, strict=False)}
    return pairs, linker

raw_pairs, raw_linker = run(with_list=False)
list_pairs, list_linker = run(with_list=True)
print(f"raw arm proposed  {len(raw_pairs):,} pairs at p >= 0.5")
print(f"list arm proposed {len(list_pairs):,}")
""")

md("""
## 5. What it bought, and what it cost

Scored against the truth, which neither model saw. The column the experiment
is about is **alias recall**: the pairs where two records name the artist
differently. Overall recall is dominated by the easy strata and hides the
answer.
""")

code("""
truth = set()
for members in by_entity.values():
    members = sorted(members)
    for i, a in enumerate(members):
        for b in members[i + 1:]:
            truth.add(frozenset((a, b)))

alias = {frozenset((r["observation_a"], r["observation_b"]))
         for r in w.differences if r["cause"] == "alias"}

rows = []
for label, got in (("splink, raw", raw_pairs), ("splink + variants", list_pairs)):
    tp, fp = len(got & truth), len(got - truth)
    rows.append({"arm": label,
                 "precision": round(tp / (tp + fp), 3),
                 "recall": round(tp / len(truth), 3),
                 "alias recall": round(len(got & alias) / len(alias), 3),
                 "false merges": fp})
pd.DataFrame(rows).set_index("arm")
""")

md("""
**Four in a thousand, to one in fifteen, at the same precision.** That is what
a list covering roughly one alias pair in ten buys on the stratum it exists
for. There is no free lunch in the inference: the value is in the list.

Now the number worth quoting. Splink was never told what the variant level is
worth; EM estimated it from the data like any other level.
""")

code("""
import math

model = list_linker.misc.save_model_to_json()
for comparison in model["comparisons"]:
    if comparison["output_column_name"] != "name":
        continue
    for level in comparison["comparison_levels"]:
        m, u = level.get("m_probability"), level.get("u_probability")
        if m and u:
            print(f"  {level['label_for_charts']:<34} {math.log2(m / u):+6.2f} bits")
""")

md("""
**The list-asserted alias is priced at about the same as the two names being
identical.** That is Splink saying, from the data and without being told, that
"a list says these are the same" carries as much evidence as "the strings
match".

And the cost, which belongs beside the gain: the artist world contains pairs
of *different* artists who genuinely share a name. A list that merges
everything it knows about will merge some of those too.
""")

code("""
collision_pairs = set()
members_of = {}
for r in truth_rows:
    members_of.setdefault(r["truth_entity_id"], []).append(r["record_id"])
for c in w.collisions:
    for a in members_of.get(c["entity_a"], []):
        for b in members_of.get(c["entity_b"], []):
            collision_pairs.add(frozenset((a, b)))

for label, got in (("splink, raw", raw_pairs), ("splink + variants", list_pairs)):
    print(f"  {label:<22} {len(got & collision_pairs):>4} collision merges")
""")

md("""
## What this settles, and what it does not

**Settles.** On the pairs no string method can see, raw Splink finds almost
none, at any threshold: its blocking never proposes them, and if it did, "all
other comparisons" is priced at about minus 7 bits. A list fixes exactly that,
delivers about what its coverage promised, and Splink prices it at roughly the
weight of an exact name match.

**Does not settle.** These are musicians. Stage names are the extreme case of
the alias problem, which is why this was the right place to measure it and the
wrong place to generalise from. Whether a variant list is worth the same on
Yoruba given names is a different experiment, and one we cannot run honestly
yet: the African name-equivalence lists we hold are CC-BY-NC-SA, and there is
no second public source of *Mohammed is Muhammad for this person* to keep the
list and the truth apart.

**One practical finding.** `ArrayIntersect` carries no term-frequency
adjustment, so an alias hit on a *common* name is priced at the full weight
while an exact hit on the same name is discounted for being common. That makes
the level arm more generous on exactly the names that collide. Canonicalising
the name before Splink sees it gets the adjustment for free, because the exact
level already has one. Until Splink has a TF-adjusted array level:
**canonicalise.**

## Where to read next

- `datasets/artists_dataops/RESULTS.md`: six arms, five thresholds, an oracle
  arm labelled as leakage, and the full stratified table.
- `datasets/artists_dataops/bench_splink_variants.py`: the script that
  produced it.
- **[26 What is in a world](26_what_is_in_a_world.ipynb)** for the data,
  **[28 Does the ledger beat batch](28_does_the_ledger_beat_batch.ipynb)** for
  the other world.
""")


def build() -> Path:
    nb = {
        "cells": [
            {
                "cell_type": kind,
                "metadata": {},
                "source": text.splitlines(keepends=True),
                **({"outputs": [], "execution_count": None} if kind == CODE else {}),
            }
            for kind, text in cells
        ],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python",
                           "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    out = Path(__file__).with_name("27_what_a_variant_list_is_worth.ipynb")
    out.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    print(build())
