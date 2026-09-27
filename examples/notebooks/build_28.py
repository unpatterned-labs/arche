# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Generate 28_does_the_ledger_beat_batch.ipynb.

    python examples/notebooks/build_28.py

The third of three synthetic-data notebooks. 26 answers "what are these files",
27 answers the variant-list question, and this one reads the supplier
benchmark: seven arms, the stratum no public benchmark has, and the finding
that a changed address defeats every engine that reads it.

Needs arche and DuckDB, both of which a repository-root `uv sync` installs. It
reads the recorded seven-arm result rather than re-running it -- the two
incremental arms take three minutes between them -- and runs the mechanism
behind the headline live, because that is the part a reader has to see happen.
"""
from __future__ import annotations

import json
from pathlib import Path

MD, CODE = "markdown", "code"
cells: list[tuple[str, str]] = []
md = lambda t: cells.append((MD, t.strip("\n")))      # noqa: E731
code = lambda t: cells.append((CODE, t.strip("\n")))  # noqa: E731


md("""
# Does the ledger beat batch?

Every public entity-resolution benchmark asks one question: given all the
records at once, which are the same? That is not how a supplier master is
built. The ERP row is typed in 2019, the registry is checked in 2022, an
invoice is filed in 2025 — and somewhere in between the supplier moves.

`ng_supplier_v0` is built to ask the second question. Seven arms run over the
same 444 records, and because every disagreement carries **why it happened**,
each arm can be scored separately on the pairs that disagree because something
*legitimately changed*.

The headline is not that arche wins. It is that **a changed address defeats
every engine that reads the address**, including two we did not write, and no
existing benchmark can show that.

Run this from the repository root.
""")

md("""
## 1. The world, and the stratum

`change` is the column that does the work. A supplier relocating is not an
error in the data and not a different spelling: both records were true when
they were written.
""")

code("""
import json
from pathlib import Path

from arche_synthetic import load

WORLD = Path("data/synthetic/worlds/ng_supplier_v0_s150")

w = load(WORLD)
w.describe()
""")

md("""
Those kinds are per difference *row*. What an arm is scored on is the true
*pair*, and the four causes below are the ones this world exists to expose.
`ORG_RELOCATED` is the big one; the other three are reported and, at 150
suppliers, too small to score.
""")

code("""
import collections

causes = collections.Counter(
    d["cause"] for d in w.differences if d["difference_kind"] == "change")
for cause, rows in causes.most_common():
    print(f"  {cause:<20} {rows:>4} difference rows")
""")

md("""
## 2. Seven arms

Read from the recorded result rather than re-run. The five cheap arms take
about twenty seconds; the two incremental ones take three minutes, because they
resolve each arriving record against everything stored so far — n² comparisons
by design, not an inefficiency. The command that produced this file is in the
cell below, and the two invariants are checked against the world on disk so the
file cannot be quietly the wrong one.
""")

code("""
import pandas as pd

result = json.loads((WORLD / "benchmark_result.json").read_text())

# The file says which world it measured; the world says how many records it has.
assert result["world"] == WORLD.name, "result file is for another world"
assert result["records"] == len(w.observations), "result file is for another world"

rows = []
for arm in result["arms"]:
    strata = arm["recall_by_stratum"]
    rows.append({
        "arm": arm["arm"],
        "P": arm["overall"]["precision"],
        "R": arm["overall"]["recall"],
        "change": strata.get("change", {}).get("recall"),
        "relocated": strata.get("change/ORG_RELOCATED", {}).get("recall"),
        "false merges": arm["entities"]["false_merge_clusters"],
        "secs": arm["seconds"],
    })
pd.DataFrame(rows).set_index("arm")
""")

md("""
```sh
uv run python data/synthetic/run_benchmark.py --world data/synthetic/worlds/ng_supplier_v0_s150
uv run python data/synthetic/run_benchmark.py --world ... --fast   # five arms, ~20 s
```

## 3. The finding

Sort that table by the relocation column and the shape of the problem is
plain.
""")

code("""
reloc = (pd.DataFrame(rows).set_index("arm")[["relocated", "P", "R"]]
         .sort_values("relocated"))
print(reloc.to_string())
print()
print("reads the address :", ", ".join(
    a for a in reloc.index if a != "jaro_winkler"))
print("reads names only  : jaro_winkler")
""")

md("""**Every engine that reads the address sits below 0.41. The one that reads
names only sits at 0.818.**

That gap is five times the seed-to-seed spread measured for this world, which
is why it is the one comparison on this page worth quoting. The middle of the
ordering is *not*: arche 0.145, Splink 0.309 and the ledger 0.309 span less
than the 0.146 spread measured for Splink alone across five seeds. Read the
gap, not the ranking.

And Jaro-Winkler's 0.818 is not competence. It compares names and nothing
else, so a changed address cannot hurt it — and the bill arrives in the
precision column.
""")

code("""
jw = next(a for a in result["arms"] if a["arm"] == "jaro_winkler")
sp = next(a for a in result["arms"] if a["arm"] == "splink")
print(f"  jaro_winkler  relocated {jw['recall_by_stratum']['change/ORG_RELOCATED']['recall']:.3f}"
      f"   precision {jw['overall']['precision']:.3f}"
      f"   false merges {jw['entities']['false_merge_clusters']}")
print(f"  splink        relocated {sp['recall_by_stratum']['change/ORG_RELOCATED']['recall']:.3f}"
      f"   precision {sp['overall']['precision']:.3f}"
      f"   false merges {sp['entities']['false_merge_clusters']}")
print()
print("  what jaro_winkler's false merges were holding together:")
for what, n in sorted(jw["false_merges_by_what_was_shared"].items(),
                      key=lambda kv: -kv[1]):
    print(f"    {what:<16} {n}")
""")

md("""
**An arm can top the change stratum by ignoring evidence.** That is the reason
the stratum columns are reported beside precision and never alone.

## 4. Why it happens, live

arche's `cover` on this world is 0.969 while its relocation recall is 0.145. It
is not *missing* those pairs — it is **refusing** them. The `organisation`
pack compares `address` with a `premises` comparator declared
`refutes_below: 0.5`, and a wholly changed address demotes the pair to
`review` however well the name and the RC number agree.

This is the one thing on the page worth running rather than reading. Take a
supplier the world says relocated, and ask arche about the pair.
""")

code("""
import arche

by_id = {r["record_id"]: r for r in w.observations}

# The first relocation whose company name is clean. About 3% of this world's
# names carry Wikidata label residue ("Harding surname Haulage") -- a real
# defect in the name pool, recorded under limitations in DATACARD.md, and a
# distraction in an example about addresses.
moved = next(d for d in w.differences
             if d["cause"] == "ORG_RELOCATED"
             and "surname" not in by_id[d["observation_a"]]["name"].lower())
a, b = by_id[moved["observation_a"]], by_id[moved["observation_b"]]

for r in (a, b):
    print(f"  {r['source']:<9} {r['name'][:32]:<32} {r['address'][:32]:<32} {r['city']}")
print(f"  one supplier, both records true: {moved['cause']}")

receipt = arche.compare(a, b, entity="organisation")
print(f"\\n  arche says: {receipt.identity} / {receipt.action}  (score {receipt.score:.3f})")
print(f"  {receipt.explanation}")
""")

md("""
`review` / `hold`, not `different`. The refusal is deliberate and it is the
right call for one pair seen once: two records naming one company at two
addresses are exactly what a reviewer should see rather than have merged
silently. What the benchmark measures is the cost of never revisiting it.

The per-field scores say why, and the interesting pair of numbers is `address`
against `address_premises`.
""")

code("""
for field, value in sorted(receipt.factors.items()):
    if isinstance(value, (int, float)):
        print(f"  {field:<26} {value:.3f}")
""")

md("""
Look at what that pair scored. The name agrees perfectly, the RC number agrees,
`address` — the ordinary fuzzy comparator — finds 0.7 similarity between the two
streets, and the pair comes out at **0.944**, well above any threshold anyone
would set for a merge. It is held anyway.

`address_premises` is why. Asked whether those two strings name the same *door*,
it answers **0.000**, and because that comparator is declared
`refutes_below: 0.5`, the zero demotes the pair whatever the weighted score
says. A refuting comparator is not a heavy weight; it is a different kind of
thing, and this is what it does.

The pack's own comment is the argument for labelling why records disagree:

> A matching street number is weak evidence (every street has a number 12)
> while a differing one is strong evidence against, and a weight is symmetric.

Putting `refutes_below` on the address *similarity* was tried first and cannot
work. Measured, same-premises pairs score 0.867 to 1.000 while
different-premises pairs reach 0.992 -- `Unit 4, Trafford Park` against `Unit 9,
Trafford Park` scores *higher* than one address written two ways. The
distributions overlap, so no threshold divides them and the door has to be
compared on its own.
""")

md("""
## 5. What the ledger does about it

The ledger's second mechanism is that evidence arriving later supersedes an
earlier decision rather than overwriting it. `arche/ledger` feeds the same
records in `observed_at` order and calls `resolve()` on each, so a refusal made
on two records can be revisited when a third arrives.

One seed cannot carry that claim: 0.16 on relocation is inside this world's
noise. **Paired** across three worlds it can, because both arms see the same
records and world-to-world variation largely cancels.

| seed | arm | recall | precision | relocated | change |
|---|---|---|---|---|---|
| 42 | `arche/pack` | 0.739 | 0.978 | 0.121 | 0.346 |
| 42 | `arche/ledger` | 0.797 | 0.944 | 0.151 | 0.462 |
| 43 | `arche/pack` | 0.735 | 0.975 | 0.053 | 0.378 |
| 43 | `arche/ledger` | 0.812 | 0.895 | 0.158 | 0.540 |
| 44 | `arche/pack` | 0.757 | 1.000 | 0.115 | 0.460 |
| 44 | `arche/ledger` | 0.800 | 1.000 | 0.308 | 0.580 |

*Measured 2026-09-08 at 90 suppliers; these are quoted from
`data/synthetic/RESULTS.md` §3, not computed above, because six incremental
runs take some minutes.*

The `change` stratum moves **+0.115, +0.162, +0.120** — twelve to sixteen
points of legitimate change that one-shot comparison declines and incremental
resolution recovers. Relocation moves the same way every time but ranges +0.03
to +0.19, so the *direction* is the claim and the magnitude is not.

**Three worlds agreeing on sign is p = 0.125 under a sign test: suggestive,
not significant**, and it should never be called significant. What lifts it
above coincidence is that there is a mechanism which predicts exactly that
sign, and you watched it refuse in section 4.

**Precision is the honest other half, and it flips**: −0.034, −0.081, 0.000.
The ledger links transitively, so a wrong link propagates through an entity in
a way a pairwise merge does not. Which end of that trade is right depends on
whether a false merge or a false split costs more in the workflow. The point
is that the benchmark can now price both.

## 6. Reading more fields made matching worse

The last arm worth reading is `arche/custom`, which maps in the four fields the
shipped pack ignores: phone, TIN, account number, director.
""")

code("""
pack = next(a for a in result["arms"] if a["arm"] == "arche/pack")
custom = next(a for a in result["arms"] if a["arm"] == "arche/custom")
for label, key in (("overall recall", None),
                   ("ACCOUNT_CHANGED", "change/ACCOUNT_CHANGED"),
                   ("digit_mutation", "error/digit_mutation")):
    if key is None:
        x, y = pack["overall"]["recall"], custom["overall"]["recall"]
    else:
        x, y = (pack["recall_by_stratum"][key]["recall"],
                custom["recall_by_stratum"][key]["recall"])
    print(f"  {label:<16} {x:.3f} -> {y:.3f}   ({y - x:+.3f})")
print(f"\\n  precision       {pack['overall']['precision']:.3f} -> "
      f"{custom['overall']['precision']:.3f}")
""")

md("""
Those four fields are disproportionately the ones that legitimately change or
are absent, so they disagree on exactly the pairs that most need linking, and
each disagreement pulls the weighted mean down. **A comparator that helps on
the stable case can hurt on the changing one**, and no benchmark without a
`change` column would have shown it.

(The overall recall gap is inside the noise band and is not the finding. The
`ACCOUNT_CHANGED` and `digit_mutation` drops are large and mechanistically
explained, which is why those are quoted and the headline is not.)

## What this settles, and what it does not

**Settled.** A changed address is read as refuting evidence by every engine
that reads it, so a supplier moving is hard to distinguish from a supplier
being a different company. Two independent implementations agree on that, which
is evidence about the problem rather than about either engine.

**Suggested, not settled.** That incremental resolution recovers legitimate
change better than one-shot comparison. Consistent sign across three worlds
plus a mechanism that predicts it — and a precision cost that moves the other
way.

**Not measurable here.** Any ordering between arche and Splink. They land
within 0.04 recall and 0.007 precision, which is inside the noise at this
scale. `arche/ledger+observe` is an *assisted* number wherever it appears: it
looks up a registry record by RC number, an identifier the records carry, never
the truth mapping — but two records sharing an RC number are already strong
evidence, so it measures whether `observe()` propagates and re-decides
correctly, not whether arche finds the link unaided.

Read `data/synthetic/RESULTS.md` §0 before quoting any single number from this
page. At 150 suppliers an unpaired difference below ~0.10 recall cannot be
distinguished from which world you happened to draw.

## Where to read next

- **[26 What is in a world](26_what_is_in_a_world.ipynb)**: the three world
  families and how to read them.
- **[27 What a variant list is worth](27_what_a_variant_list_is_worth.ipynb)**:
  the same idea on names, and the experiment Splink's author asked for.
- `data/synthetic/RESULTS.md` for all seven arms with every caveat, and
  `DATACARD.md` for what this data is not.
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
    out = Path(__file__).with_name("28_does_the_ledger_beat_batch.ipynb")
    out.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    print(build())
