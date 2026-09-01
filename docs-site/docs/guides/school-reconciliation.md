# Reconcile schools

You have an authoritative register and a map somebody else made. Neither carries the other's identifiers. This is the shape of most reconciliation work, and this guide runs it end to end on public school data.

The England example below is a labelled benchmark. The Nigeria example at the end is a three-source reconciliation with a review pack, not an accuracy claim.

The [England schools notebook](https://github.com/unpatterned-labs/arche/blob/main/examples/notebooks/13_england_schools.ipynb) stages both sources, runs one call, and scores the result against 282 labels nobody involved created for this purpose.

## The two sources

**GIAS** is the Department for Education's register of educational establishments. Every open school in England has a URN and GIAS is where it is issued. Crown copyright, Open Government Licence.

**OpenStreetMap** is surveyed and crowd-mapped. It is ODbL, so it is used here as benchmark evidence only and never enters a shipped pack.

93% of Leeds OSM school features carry a `ref:edubase` tag, which is an editor asserting *this mapped school is that URN*. That tag becomes the label. The matcher never sees it.

## The call

Two lists of dictionaries, one line.

```python
from arche.resolve import reconcile

# Two rows each, standing in for the full exports.
osm_rows  = [{"name": "Roundhay School", "lat": "53.8386", "lon": "-1.4996"},
             {"name": "Allerton High School", "lat": "53.8452", "lon": "-1.5410"}]
gias_rows = [{"name": "Roundhay School", "lat": "53.8387", "lon": "-1.4995"},
             {"name": "Allerton High School", "lat": "53.8451", "lon": "-1.5412"}]

osm  = [{"name": r["name"], "lat": r["lat"], "lon": r["lon"]} for r in osm_rows]
gias = [{"name": r["name"], "lat": r["lat"], "lon": r["lon"]} for r in gias_rows]

result = reconcile(osm, gias, entity="place")

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

Read that honestly. On F1 the shipped pack and plain exact matching are level here, because English school names are unusually standardised. What arche buys is recall: 0.986 against 0.876, which is 31 more true pairs found. If your two sources spell things identically, exact matching is a fine answer.

The fuzzy rows show why one threshold cannot serve both directions. Loosening from exact to token overlap takes recall from 0.876 to 0.989 and turns 2 false merges into 4,953.

## What to look for

**Three identifiers that are not interchangeable.** URN identifies an establishment and is reissued when a school legally becomes a new one, which an academy conversion usually is. UKPRN identifies a provider. LAESTAB is the local-authority composite that predates both. A school can keep its buildings, staff and name through a conversion and come out with a new URN.

**Run the cheapest audit you have.** Where both sides carry a UKPRN, compare them. It costs one join and it checks the matcher against evidence the matcher never saw. In this run 99 of 111 agreed. The 12 that did not were not near-misses:

```text
Co-op Academy Woodlands   matched 4 different GIAS schools
Co-op Academy Leeds       matched 4 different GIAS schools
Co-op Academy Oakwood     matched 2 different GIAS schools
```

An academy chain whose brand prefix is two thirds of every name, with campuses close enough that coordinates do not settle it. That is the second failure mode, many entities sharing one name, and chain branding produces it wholesale. Supermarket estates, clinic networks and franchise groups all have this shape.

**So the headline is not 98.6% on its own.** It is 98.6% on the labelled pairs, plus a family of false merges among the unlabelled ones that only surfaced because a third identifier happened to be available.

## Run it locally

The sources are fetched, never committed. Pin the export date so the run repeats.

```bash
python data/scripts/fetch_england_schools.py --la Leeds --date 20260819
cd examples/notebooks
uv run --package arche-core jupyter notebook 13_england_schools.ipynb
```

Staged files land in `data/_cache/schools/`, which is gitignored.

## What this does not show

The labels cover the features an editor happened to tag, so this measures auto-match rate against known-true pairs and not complete recall. It is one local authority. And it compares against currently open establishments only, so it never meets a school whose URN changed underneath it, which is the harder problem and needs a historical GIAS export.

## Nigeria: where exact matching becomes the dangerous option

The [Nigeria schools notebook](https://github.com/unpatterned-labs/arche/blob/main/examples/notebooks/14_nigeria_schools.ipynb) runs the same process as notebook 13, step for step, on two independent surveys of the same schools.

Leeds says exact name matching is safe. Precision 0.992, two false merges. If that were the general lesson, none of this project would be necessary.

Run the same methods on the [Nigeria schools register](https://grid3.gov.ng/) and it inverts.

```bash
python data/scripts/nigeria_school_false_merges.py     --csv Schools_in_Nigeria.csv --out data/nigeria_school_false_merges_result.json
```

### Why this is measurable without labels

The Nigeria sources carry no pair labels, which is why this guide used to make no accuracy claim. But one class of label is free and certain: **two schools in different states are not the same school.**

That gives 400 pairs which share a name *exactly* and sit in different states. Nobody constructed them and nobody chose them to flatter a result. Every method below is scored on pairs it should never merge.

The rule is boundary-aware: a pair counts only if it is in different states **and** more than N km apart. Choosing one N would mean picking a number after seeing the results, so every N is reported.

```text
method                           >0 km       >1 km       >5 km      >25 km
exact name (casefold)              400         399         399         390
token Jaccard >= 0.5               400         399         399         390
token_set_ratio >= 90              399         398         398         389
arche (name + coords)                2           1           1           0
(pairs remaining)                  400         399         399         390
```

arche routed **397 of 400 to review** rather than merging them or throwing them away.

Read the columns rather than a single number. Only one pair of 400 sits within a kilometre and the median separation is **243 km**, so the border doubt is real but small. The string methods do not move: 390 of 390 wrong at over 25 km apart, which no boundary subtlety explains. arche's two errors are exactly where the labels are weakest, and both leave as the rule tightens.

### Read the construction honestly

These pairs were selected *because* they share a name, so exact matching merging all 400 is true by construction. That is not a trick, it is the finding. The question is how often that construction is available, and the register answers it:

```text
distinct names            98,248 of 107,670
names held by >1 school    3,959
records sharing a name    13,381  (12%)

  200x  COMMUNITY PRIMARY SCHOOL             across 21 states
  120x  LGEA PRIMARY SCHOOL                  across 11 states
   99x  NOMADIC PRIMARY SCHOOL               across 24 states
```

Two hundred schools are called `COMMUNITY PRIMARY SCHOOL`. In Leeds, two schools sharing a name exactly were nearly always the same school. Here they are nearly always different ones, and one in eight records is exposed to it.

### What changed, and what did not

The maths did not change. The comparator did not change. What changed is that Nigerian school names are built from generic words, so a name carries almost no distinguishing information and the thing that decides is what the name is *worth*, not how similar two strings are.

That is the whole argument this project makes, and it is why the Leeds result matters as much as this one. On standardised names arche buys you very little over exact matching. On these names it is the difference between 2 errors and 400.

### What this does not measure

**Recall.** There are no positive labels here, so a method that refuses everything would score perfectly. The Leeds run is the control: the same engine, on labelled data, reaches recall 0.986. Without that number beside it, this table would only prove that abstaining is safe.

**arche is not clean either.** It merged 2 of the 400. Those two are in the result file, and they are the ones worth reading.

