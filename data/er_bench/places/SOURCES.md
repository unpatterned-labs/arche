# Geographic Settlements — sources & attribution

The place-lane benchmark, used by
`examples/notebooks/07_places_on_a_public_benchmark.ipynb`.

It is here because it is the only place corpus in this repo whose ground truth
is **complete**. Kano and London are both sets we assembled and labelled
ourselves, and each measures recall only — neither can say whether an unlabelled
auto-match is wrong. This one covers every record in 820 clusters, so any pair
absent from a cluster is a known non-match and precision becomes measurable.

Using someone else's benchmark is the point. A corpus we built, labelled and
tuned against cannot falsify us.

- **Source:** Benchmark datasets for entity resolution, Database Group Leipzig.
- **URL:** https://dbs.uni-leipzig.de/research/projects/benchmark-datasets-for-entity-resolution
- **Archive:** `geographicalSettelments.zip`
- **License:** Creative Commons Attribution 4.0 (CC BY 4.0). Redistribution is
  permitted with attribution, which is what this file provides.
- **Citation:** Saeedi, A., Peukert, E., Rahm, E. *Comparative evaluation of
  distributed clustering schemes for multi-source entity resolution.* ADBIS 2017.
- **Modifications:** none to content. Files are byte-identical to the archive;
  `combinedSettlements(PerfectMatch).json` was renamed to
  `combinedSettlements_perfectMatch.json` because parentheses in filenames break
  several shells. All parsing happens at read time.

## Shape

| File | Contents |
|---|---|
| `settlements.json` | 3,054 records, JSONL: `{"data": {"label", "lat", "lon", "ontology"}, "id"}` |
| `combinedSettlements_perfectMatch.json` | 820 clusters, JSONL, members in `clusteredVertices` |
| `readMe.txt` | the publisher's own description |

Four sources — DBpedia (774), Freebase (776), NYTimes (755), GeoNames (749).
4,391 true pairs, all cross-source: every cluster holds at most one record per
source. Coordinates are present on 89.2% of records, but only **57.5%** of the
DBpedia ones.

## Two defects worth knowing before you use it

**The ground truth is internally inconsistent.** Cluster sizes are
`{1: 34, 2: 44, 3: 35, 4: 707}`, which accounts for 3,055 memberships against
3,054 records. Vertex `4216` (`Al Maḩmūdīyah`) is filed both inside a genuine
four-source cluster and again as a singleton cluster of itself. So there are 819
real clusters, not 820. It does **not** move the pair denominator, because a
singleton contributes no pairs. We record it rather than silently repairing it.

**`readMe.txt` says "5 sources" and then lists four.** There are four.

## Provenance risk, and why we do not report a single headline

NYTimes and GeoNames agree on coordinates to the last decimal for **91%** of
their shared true pairs — worse than the Kano GRID3/OpenStreetMap pair this
project disqualified at 59%. Those coordinates were copied, not independently
observed. DBpedia and Freebase sit at 25%, unsurprising since both ingest
Wikipedia.

We keep all six source pairs in the headline and report the flagged stratum
separately. Note that this check conditions on positives and its threshold is
not pre-registered, so it identifies a provenance *risk* — it is not a
statistical test of independence and should not be described as one.

## Reading the numbers

96.6% of the true pairs come from 707 fully-overlapping four-source entities,
which contribute six edges each. Pooled precision therefore weights those
entities six times over, and the edges are not independent observations — an
edge-level confidence interval would be wrong; use a cluster-level bootstrap.
Report it as *pooled micro edge precision*, alongside the macro-by-source-pair
figure and its worst case.

**Not a tuning set.** The comparators are the shipped `place` pack. The one
representation change the notebook makes — splitting the qualifier out of the
name — was chosen after looking at these names, and the notebook says so and
validates it on held-out clusters rather than presenting it as a general result.

## Scope

Benchmark evidence only, never a shipped asset. Nothing under `data/` reaches
the wheel: `packages/arche-core/pyproject.toml` sets `packages = ["src/arche"]`.

Re-run: `python examples/notebooks/build_07.py` then execute the notebook with
the `arche-venv` kernel.
