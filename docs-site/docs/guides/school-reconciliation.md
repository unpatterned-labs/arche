# Reconcile schools in England

You have an authoritative register and a map somebody else made. Neither
carries the other's identifiers. This is the shape of most reconciliation work,
and this guide runs it end to end on public English school data.

The [England schools notebook](https://github.com/unpatterned-labs/arche/blob/main/examples/notebooks/13_england_schools.ipynb)
stages both sources, runs one call, and scores the result against 282 labels
nobody involved created for this purpose.

## The two sources

**GIAS** is the Department for Education's register of educational
establishments. Every open school in England has a URN and GIAS is where it is
issued. Crown copyright, Open Government Licence.

**OpenStreetMap** is surveyed and crowd-mapped. It is ODbL, so it is used here
as benchmark evidence only and never enters a shipped pack.

93% of Leeds OSM school features carry a `ref:edubase` tag, which is an editor
asserting *this mapped school is that URN*. That tag becomes the label. The
matcher never sees it.

## The call

Two lists of dictionaries, one line.

```python
from arche.resolve import crosswalk

osm  = [{"name": r["name"], "lat": r["lat"], "lon": r["lon"]} for r in osm_rows]
gias = [{"name": r["name"], "lat": r["lat"], "lon": r["lon"]} for r in gias_rows]

result = crosswalk(osm, gias, entity="place")

for edge in result["matches"]:
    print(edge["decision"], round(edge["score"], 3), edge["evidence"])
```

## What comes back

```text
auto-matched       278 / 282   (98.6%)
routed to review     3
never proposed       1
surfaced           281 / 282   (99.6%)
```

Against the alternatives on the same labels:

```text
approach                 precision   recall      F1  false merges
exact name (casefold)        0.992    0.876   0.930             2
token Jaccard >= 0.5         0.053    0.989   0.101         4,953
token_set_ratio >= 90        0.671    0.947   0.785           131
arche, names only            0.651    0.986   0.784           149
arche, name + coords         0.883    0.986   0.931            37
```

Read that honestly. On F1 the shipped pack and plain exact matching are level
here, because English school names are unusually standardised. What arche buys
is recall: 0.986 against 0.876, which is 31 more true pairs found. If your two
sources spell things identically, exact matching is a fine answer.

The fuzzy rows show why one threshold cannot serve both directions. Loosening
from exact to token overlap takes recall from 0.876 to 0.989 and turns 2 false
merges into 4,953.

## What to look for

**Three identifiers that are not interchangeable.** URN identifies an
establishment and is reissued when a school legally becomes a new one, which an
academy conversion usually is. UKPRN identifies a provider. LAESTAB is the
local-authority composite that predates both. A school can keep its buildings,
staff and name through a conversion and come out with a new URN.

**Run the cheapest audit you have.** Where both sides carry a UKPRN, compare
them. It costs one join and it checks the matcher against evidence the matcher
never saw. In this run 99 of 111 agreed. The 12 that did not were not
near-misses:

```text
Co-op Academy Woodlands   matched 4 different GIAS schools
Co-op Academy Leeds       matched 4 different GIAS schools
Co-op Academy Oakwood     matched 2 different GIAS schools
```

An academy chain whose brand prefix is two thirds of every name, with campuses
close enough that coordinates do not settle it. That is the second failure
mode, many entities sharing one name, and chain branding produces it wholesale.
Supermarket estates, clinic networks and franchise groups all have this shape.

**So the headline is not 98.6% on its own.** It is 98.6% on the labelled pairs,
plus a family of false merges among the unlabelled ones that only surfaced
because a third identifier happened to be available.

## Run it locally

The sources are fetched, never committed. Pin the export date so the run
repeats.

```bash
python data/scripts/fetch_england_schools.py --la Leeds --date 20260819
cd examples/notebooks
uv run --package arche-core jupyter notebook 13_england_schools.ipynb
```

Staged files land in `data/_cache/schools/`, which is gitignored.

## What this does not show

The labels cover the features an editor happened to tag, so this measures
auto-match rate against known-true pairs and not complete recall. It is one
local authority. And it compares against currently open establishments only, so
it never meets a school whose URN changed underneath it, which is the harder
problem and needs a historical GIAS export.
