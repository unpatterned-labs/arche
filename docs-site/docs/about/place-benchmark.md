# The place benchmark

*What the GRID3 × OpenStreetMap crosswalk actually measures, why it is a consistency check rather than validation, and a portable test for whether two datasets are independent at all.*

---

!!! note "Which frequency table these numbers were measured against"

    Every figure on this page was produced with the shipped place frequency
    table **`sha256:ffd230b66df60188`**, and that string appears in the `tf`
    pin of every edge the run produced (`shipped:place@sha256:ffd230b66df60188`).

    This matters more than a version note usually does. Token rarity is not only
    a comparator input, it is a **blocking key**, so rebuilding the table
    changes which pairs are proposed for scoring at all, and therefore changes
    the match and review counts even when no threshold moved. A page of numbers
    without the table that produced them is not reproducible.

    The numbers here are frozen against that table version. They are not
    re-measured on every rebuild; they are re-measured when the pin changes and
    the change is deliberate.

The headline first, because it is a correction. arche's place pack is tuned against a Kano State crosswalk between GRID3 reference data and OpenStreetMap. That crosswalk reports 88.1% precision under an LGA weak label. **It is not independent validation.** OSM's health facilities for this state share lineage with GRID3, and we can now show that from the data rather than argue it. The number is a consistency check: useful for tuning a threshold, worthless as evidence that the matcher is right about the world.

We caught it with a test that takes about ten lines and works on any two datasets. That test, [below](#the-independence-test), is the most reusable thing on this page.

## What the benchmark is

Two lists for Kano State, both in this repository.

| Source | Records | What it is | Licence |
|---|---|---|---|
| **GRID3** | 1,723 (Kano) of 51,022 national | Gates/FCDO-funded geospatial reference data | CC-BY |
| **OpenStreetMap** | 685 named | Crowd-mapped, via the Overpass API | ODbL |

```python
import csv

with open("data/GRID3_NGA_health_facilities_v2.csv", encoding="utf-8-sig") as fh:
    grid3 = [r for r in csv.DictReader(fh) if r["state"] == "Kano"]
with open("data/osm_kano.csv", encoding="utf-8-sig") as fh:
    osm = [r for r in csv.DictReader(fh) if r["name"].strip()]
```

`crosswalk(osm, grid3, entity="place")` on that pair compares 1,180,255 possible pairs, blocks them down to 39,701 scored (a 96.6% reduction), and returns 907 edges in about 16 seconds on a laptop, offline.

## The weak label, and what it cannot tell you

Neither list carries a ground-truth identifier that the other also carries. So the benchmark uses a **weak label**: both sources independently record the Local Government Area a facility sits in, and two records that are the same facility must be in the same LGA.

That gives one usable signal, and only one:

> Of the matched pairs that carry an LGA on both sides, what fraction agree?

Read the limits honestly, because they are large.

- **It measures precision, never recall.** A true match arche never found contributes nothing. There is no denominator of real facilities here.
- **Agreeing on an LGA does not make a pair correct.** Kano has 44 LGAs. Two genuinely different clinics in the same LGA agree on the label and are counted as a success.
- **It is a proxy for distance, and the veto is a distance rule.** Tuning `veto_km` against LGA agreement is not fully independent of the thing being tuned. The sweep below is a sanity check on a threshold, not a proof that the threshold is optimal.
- **LGA strings are themselves messy.** Both sides are lower-cased and stripped before comparison. Records missing an LGA on either side are excluded and their count is reported (2 of 564 at the shipped setting).

A weak label is worth having when the alternative is no label. It is not worth promoting to "accuracy".

## The geographic veto, and the sweep that set it

Before v0.3.0a1, geography was a scored signal at weight 1.0 against name + tftoken's combined 4.0. It could be outvoted, and it was: two Kano facilities sharing a common Hausa name merged **143 km apart**, with the geo comparator itself scoring 0.000. A weighted signal cannot refuse.

`veto_km` makes distance a constraint instead. Beyond the threshold the pair is demoted to `review`, carrying `geo_conflict_km` in its evidence. Two properties are deliberate:

- **It never produces `no_match`.** Distance says a human must look, not that the answer is no.
- **Records without usable coordinates are never vetoed.** You cannot refute a claim on evidence you do not have.

### Reproduce the sweep

Runs offline on data already in the repository. Save as `sweep.py` in the repo root and run `uv run python sweep.py`.

```python
import copy, csv

from arche.resolve import ENTITY_PACKS, crosswalk

with open("data/GRID3_NGA_health_facilities_v2.csv", encoding="utf-8-sig") as fh:
    grid3 = [r for r in csv.DictReader(fh) if r["state"] == "Kano"]
with open("data/osm_kano.csv", encoding="utf-8-sig") as fh:
    osm = [r for r in csv.DictReader(fh) if r["name"].strip()]

A = [{"name": r["name"], "lat": r["lat"], "lon": r["lon"]} for r in osm]
B = [{"name": r["facility_name"], "lat": r["latitude"],
      "lon": r["longitude"]} for r in grid3]
lga_a = [r["lga"].strip().lower() for r in osm]
lga_b = [r["lga"].strip().lower() for r in grid3]


def pack(veto_km):
    """The shipped place pack with `veto_km` set, or removed entirely."""
    out = copy.deepcopy(ENTITY_PACKS["place"])
    for spec in out:
        if spec["kind"] == "geo":
            spec.pop("veto_km", None)
            if veto_km is not None:
                spec["veto_km"] = veto_km
    return out


print(f"{'veto':>7} {'matches':>8} {'same':>6} {'diff':>6} {'prec':>7} "
      f"{'>10km':>6} {'max km':>7} {'review':>7}")
for veto in (None, 50.0, 25.0, 10.0):
    result = crosswalk(A, B, comparators=pack(veto))
    m = [e for e in result["matches"] if e["decision"] == "match"]
    same = sum(1 for e in m if lga_a[e["a_id"]] and lga_b[e["b_id"]]
               and lga_a[e["a_id"]] == lga_b[e["b_id"]])
    diff = sum(1 for e in m if lga_a[e["a_id"]] and lga_b[e["b_id"]]
               and lga_a[e["a_id"]] != lga_b[e["b_id"]])
    km = [e["evidence"]["distance_km"] for e in m]
    print(f"{('none' if veto is None else f'{veto:g} km'):>7} {len(m):>8} "
          f"{same:>6} {diff:>6} {same / (same + diff):>6.1%} "
          f"{sum(1 for d in km if d > 10):>6} {max(km):>7.2f} "
          f"{sum(1 for e in result['matches'] if e['decision'] == 'review'):>7}")
```

```text
   veto  matches   same   diff    prec  >10km  max km  review
   none      636    497    137  78.4%     72  143.02     457
  50 km      594    481    110  81.4%     49   49.13     313
  25 km      561    481     77  86.2%     16   24.30     346
  10 km      564    495     67  88.1%      0    8.97     529
```

### Why 10 km

The shape of the sweep is the argument. Loosening from 10 km to 25 km buys back two same-LGA matches and lets in thirteen cross-LGA ones. That is a bad trade under an asymmetric cost: a veto costs a human glance, a wrong merge costs a clinic its place on the national list and its allocation with it.

At the shipped setting: **564 matches, 88.1% LGA agreement, maximum matched distance 8.97 km, and 279 pairs moved to `review` carrying `geo_conflict_km` as the reason.** Nothing is matched beyond 10 km, which is the property the threshold exists to guarantee.

### A known false negative

The threshold is tuned on rural point features, and there is at least one place it is visibly wrong. In the GRID3 × Overture crosswalk:

```text
review score=0.694   10.06 km  'Aminu kano teaching hospital AKTH' <> 'Aminu Kano Teaching Hospital'
```

That is Aminu Kano Teaching Hospital against Aminu Kano Teaching Hospital, at six metres over the threshold. A large urban campus can legitimately be recorded at its gate, its main block, or its administrative address, and those can sit kilometres apart. A single national threshold is the wrong shape for that, and we do not yet have a better one. It is recorded here rather than tuned away, because tuning it away on a single example is how a benchmark stops meaning anything.

## The Hausa orthography pack, on the same benchmark

A separate failure the benchmark exposed: arche will not merge two references until they share a *distinctive* token. That is what stops "Fatima Hospital" and "Fatouma Hospital" fusing. It also means `Mai Tsidau` and `Maitsidau` share no token at all, so a true match is dropped before it is ever scored.

`resolve/_data/orthography.yaml` is an inspectable rule pack with three mechanisms: adjacent-token boundary collapsing, nasal assimilation (`n` becomes `m` before `b`/`p`), and ten curated equivalence groups. It is off by default and passed explicitly.

```python
import csv

from arche.resolve import TokenFrequencyTable
from arche.resolve._gate import shared_name_distinctiveness

with open("data/GRID3_NGA_health_facilities_v2.csv", encoding="utf-8-sig") as fh:
    grid3 = [r for r in csv.DictReader(fh) if r["state"] == "Kano"]
with open("data/osm_kano.csv", encoding="utf-8-sig") as fh:
    osm = [r for r in csv.DictReader(fh) if r["name"].strip()]

# The frequency table is calibrated on the population being reconciled, which
# is what makes "Health Post" common and "Kafinmaiko" rare.
tf = TokenFrequencyTable.from_corpus(
    [r["name"] for r in osm] + [r["facility_name"] for r in grid3]
)

pairs = [
    # word-boundary variation, the class the pack exists for
    ("Yangwarzo Health Post", "Yan Gwarzo Health Post"),
    ("Kafinmaiko Health Post", "Kafin Maiko Health Post"),
    # nasal assimilation, n -> m before b
    ("Sambauna Primary Health Centre", "Sanbauna Primary Health Center"),
    # curated equivalents: malam/mallam, amadu/ahmadu
    ("Unguwar Malam Amadu Health Post", "Unguwar Mallam Ahmadu Health Post"),
    # negatives that must not move
    ("Kurugu Health Post", "Alfindi Health Post"),
    ("Ririwai Primary Health Centre", "Riruwai Primary Health Center"),
]

print(f"{'off':>6} {'hausa':>6}   pair")
for a, b in pairs:
    off = shared_name_distinctiveness(a, b, tf)
    on = shared_name_distinctiveness(a, b, tf, orthography="hausa")
    print(f"{off:>6.3f} {on:>6.3f}   {a!r} <> {b!r}")
```

```text
   off  hausa   pair
 0.162  0.788   'Yangwarzo Health Post' <> 'Yan Gwarzo Health Post'
 0.162  0.788   'Kafinmaiko Health Post' <> 'Kafin Maiko Health Post'
 0.252  0.788   'Sambauna Primary Health Centre' <> 'Sanbauna Primary Health Center'
 0.477  0.788   'Unguwar Malam Amadu Health Post' <> 'Unguwar Mallam Ahmadu Health Post'
 0.162  0.162   'Kurugu Health Post' <> 'Alfindi Health Post'
 0.252  0.252   'Ririwai Primary Health Centre' <> 'Riruwai Primary Health Center'
```

### Additive by construction, because the first version was not

Scoring the TF-weighted Jaccard over orthographic keys *instead of* literal tokens restructures the denominator. On this crosswalk that recovered 13 pairs and demoted 79. Both `shared_name_distinctiveness` and `weighted_token_sim` now return `max(literal, keyed)`, so a pack can only ever recover a pair the literal comparison was dropping.

Measured over all 39,701 scored pairs in the Kano crosswalk, enabling the pack raises `shared_name_distinctiveness` on 60 pairs and `weighted_token_sim` on 59, and lowers neither on any pair. Threaded end to end through the place pack, that is **13 pairs promoted from `review` to `match`, 0 demoted, and no edge's score falling**. All 13 are within 20 metres of each other:

```text
review -> match  score=0.989  d=0.0 km   'Dunbule Health Post' <> 'Dumbule Health Post'
review -> match  score=0.821  d=0.0 km   'Sambauna Primary Health Centre' <> 'Sanbauna Primary Health Center'
review -> match  score=0.774  d=0.0 km   'Unguwar Malam Amadu Health Post' <> 'Unguwar Mallam Ahmadu Health Post'
review -> match  score=0.741  d=0.0 km   'Fanidau Health Post' <> "Fan'Idau Health Post"
review -> match  score=0.731  d=0.0 km   'Kafinmaiko Health Post' <> 'Kafin Maiko Health Post'
review -> match  score=0.721  d=0.01 km  'Fadi Sonka Health Post' <> 'Fadisonka Health Post'
review -> match  score=0.721  d=0.0 km   'Tashar Basa Health Post' <> 'Tasharbasa Health Post'
review -> match  score=0.719  d=0.02 km  'Gurungawa Health Post' <> 'Gurun Gawa Health Post'
review -> match  score=0.715  d=0.0 km   'Kafin Sidda Health Post' <> 'Kafinsidda Health Post'
review -> match  score=0.709  d=0.0 km   'Unguwar Turaki Health Post' <> 'Unguwarturaki Health Post'
review -> match  score=0.708  d=0.0 km   'Yangwarzo Health Post' <> 'Yan Gwarzo Health Post'
review -> match  score=0.704  d=0.0 km   'Yankamaye Health Post' <> 'Yan Kamaye Health Post'
review -> match  score=0.704  d=0.0 km   'Yankwada Health Post' <> 'Yan Kwada Health Post'
```

!!! warning "Not wired into `crosswalk` in 0.3.0a1"

    `orthography=` is a parameter on `shared_name_distinctiveness` and `TokenFrequencyTable.weighted_token_sim`, and it defaults to `None` on both. The `place` entity pack does not set it, so `crosswalk(..., entity="place")` does not use the Hausa pack. The 13-pair figure above was measured by binding `weighted_token_sim` to `orthography="hausa"` and re-running the crosswalk. Plumbing it through the comparator spec is outstanding work.

### What the pack deliberately does not do

Vowel alternations such as `Ririwai` / `Riruwai` and `Sarigarin` / `Sari Girin` are recorded in the YAML under `known_gaps` and are **not** handled. Whether `gari` and `girin` are one morpheme with a vowel alternation or two distinct words is a question about Hausa, not about string distance. A rule general enough to fold those vowels would also merge genuinely distinct settlement names. That needs a Hausa speaker, so the gap is written down instead of guessed at, and there are tests asserting those pairs do not move.

## The independence test

This is the part worth taking away, whatever you are reconciling.

When two datasets match at a high rate, there are two explanations, and a precision score cannot tell them apart:

1. Your matcher is good.
2. One dataset is downstream of the other, and you are measuring a copy.

The second is worthless as validation. You have confirmed that a copy resembles its original.

**The test: look at the coordinate distance between the pairs your matcher agreed on.** Independent field surveys of the same building do not agree exactly. Handheld GPS error is 3 to 10 metres in good conditions and worse under tree cover or beside a wall. Two teams, two devices, two visits, and you expect tens of metres of disagreement, distributed.

So a median near zero with a large fraction at *exactly* zero means derivation. A median in the tens of metres with few exact ties is what independence looks like.

```python
import csv, statistics

from arche.resolve import crosswalk


def independence_report(label, A, B):
    """Does this pairing look like two surveys, or like a copy?

    A: the source under suspicion. B: the reference it claims to be
    independent of. Both are lists of {name, lat, lon}.
    """
    result = crosswalk(A, B, entity="place")
    matched = [m for m in result["matches"] if m["decision"] == "match"]
    d = sorted(m["evidence"].get("distance_km", 0.0) for m in matched)
    if not d:
        print(f"{label}: nothing matched, no judgement possible")
        return
    exact = sum(1 for x in d if x == 0.0)
    covered = len({m["a_id"] for m in matched})
    print(f"{label}")
    print(f"   records            : {len(A):,}")
    print(f"   matched            : {covered:,} ({100 * covered / len(A):.1f}% coverage)")
    print(f"   median distance    : {statistics.median(d):.3f} km")
    print(f"   90th percentile    : {d[int(0.9 * len(d))]:.3f} km")
    print(f"   at EXACTLY 0.00 km : {exact} ({100 * exact / len(d):.0f}% of matches)")


with open("data/GRID3_NGA_health_facilities_v2.csv", encoding="utf-8-sig") as fh:
    grid3 = [r for r in csv.DictReader(fh) if r["state"] == "Kano"]
with open("data/osm_kano.csv", encoding="utf-8-sig") as fh:
    osm = [r for r in csv.DictReader(fh) if r["name"].strip()]

GRID3 = [{"name": r["facility_name"], "lat": r["latitude"],
          "lon": r["longitude"]} for r in grid3]
OSM = [{"name": r["name"], "lat": r["lat"], "lon": r["lon"]} for r in osm]

independence_report("GRID3 x OpenStreetMap", OSM, GRID3)
```

```text
GRID3 x OpenStreetMap
   records            : 685
   matched            : 521 (76.1% coverage)
   median distance    : 0.000 km
   90th percentile    : 0.050 km
   at EXACTLY 0.00 km : 319 (59% of matches)
```

Read that carefully. A median of 0.000 km, and 59% of matches at exactly zero. There is no way two independent surveys produce that. The OSM health facilities for this state carry the same lineage as GRID3, most likely via the Nigeria Health Facility Registry that GRID3 also draws on.

### The circularity we had already found, and then walked into

We had a reason for using OSM. **34,541 of GRID3's 51,022 national records, or 68%, carry `facility_name_source: NHFR_2024`.** In Kano it is 1,426 of 1,723, and every one of those also carries an `nhfr_facility_code`. NHFR is the Nigeria Health Facility Registry, which is what the Humanitarian Data Exchange mirrors. Comparing GRID3 against the HDX mirror measures agreement between two views with a shared ancestor, and where both sides carry the same facility code it is not entity resolution at all, it is a key join.

So we used OSM instead, and did not apply the same scrutiny to that choice. The test above would have taken two lines and caught it before we published a number.

### A source with published lineage

Most datasets make you infer provenance. Overture Maps publishes it per feature, so you can check independence directly.

!!! note "This section needs network and DuckDB"

    The pull below reads Overture's public S3 parquet. Figures here are from release `2026-07-22.0`; a different release will give different counts. `pip install duckdb`, then:

```python
import duckdb

BBOX = (7.4, 10.3, 9.6, 12.7)          # Kano State, generous
RELEASE = "2026-07-22.0"

con = duckdb.connect()
con.execute("INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;")
con.execute("SET s3_region='us-west-2';")

path = f"s3://overturemaps-us-west-2/release/{RELEASE}/theme=places/type=place/*"
rows = con.execute(f"""
    SELECT names.primary AS name,
           categories.primary AS category,
           ROUND(ST_Y(geometry), 6) AS lat,
           ROUND(ST_X(geometry), 6) AS lon,
           sources
    FROM read_parquet('{path}', filename=true, hive_partitioning=1)
    WHERE bbox.xmin BETWEEN {BBOX[0]} AND {BBOX[2]}
      AND bbox.ymin BETWEEN {BBOX[1]} AND {BBOX[3]}
      AND names.primary IS NOT NULL
""").fetchall()
```

That returns 7,345 named places in the bounding box. Filtering to health categories and counting the declared source of each feature:

```text
Overture health places in Kano: 358
   meta         354
   Microsoft    3
   Foursquare   1
```

Meta, Microsoft, Foursquare. No OpenStreetMap, no GRID3, no NHFR. That is a genuinely independent compilation of the same territory, and it is stated in the data rather than assumed.

### What independence looks like

Run the same report on both:

```text
GRID3 x OpenStreetMap
   records            : 685
   matched            : 521 (76.1% coverage)
   median distance    : 0.000 km
   90th percentile    : 0.050 km
   at EXACTLY 0.00 km : 319 (59% of matches)

GRID3 x Overture (Meta)
   records            : 358
   matched            : 37 (10.3% coverage)
   median distance    : 0.050 km
   90th percentile    : 0.750 km
   at EXACTLY 0.00 km : 3 (8% of matches)
```

| | OSM | Overture |
|---|---|---|
| records | 685 | 358 |
| matched | 521 | 37 |
| coverage | 76.1% | 10.3% |
| median distance | 0.000 km | 0.050 km |
| at exactly 0.00 km | 319 (59%) | 3 (8%) |

Two completely different signatures. The independent source agrees on fewer facilities and agrees less precisely about where they are. That is not the matcher performing worse. It is what honest disagreement between two observations looks like.

### The coverage gap is a finding, not a defect

Overture matches about a tenth of its health places to GRID3, and that is a statement about populations rather than about matching. GRID3 is overwhelmingly rural primary health centres and health posts. Meta's place data covers named, signed, commercial facilities, which skews urban. An independent source can validate the urban tier and says almost nothing about the rural network, which is exactly where a national facility list matters most.

Knowing that is more useful than a precision score.

### Applying it to your own data

Short enough to inline. `OVERTURE` here is the health-filtered pull from the previous section, in the same `{name, lat, lon}` shape as `OSM`:

```python
import statistics


def looks_derived(distances_km, exact_threshold=0.25, median_threshold=0.005):
    """A blunt instrument. Catches re-publication, not quality."""
    if not distances_km:
        return None
    exact = sum(1 for d in distances_km if d == 0.0) / len(distances_km)
    med = statistics.median(distances_km)
    return {
        "fraction_exact": round(exact, 3),
        "median_km": round(med, 4),
        "verdict": ("likely derived"
                    if exact > exact_threshold and med < median_threshold
                    else "consistent with independence"),
    }


for label, A in [("OpenStreetMap", OSM), ("Overture", OVERTURE)]:
    res = crosswalk(A, GRID3, entity="place")
    d = [m["evidence"]["distance_km"] for m in res["matches"]
         if m["decision"] == "match"]
    print(f"{label:16} {looks_derived(d)}")
```

```text
OpenStreetMap    {'fraction_exact': 0.585, 'median_km': 0.0, 'verdict': 'likely derived'}
Overture         {'fraction_exact': 0.081, 'median_km': 0.05, 'verdict': 'consistent with independence'}
```

### Caveats, because this is a blunt instrument

- **Rounding matters.** `distance_km` in the crosswalk evidence is rounded to two decimal places, so anything under about five metres reads as exactly zero. Tighten it if your coordinates are more precise than that.
- **Some exact ties are legitimate.** Two sources that both geocode to a postcode or settlement centroid will agree exactly without either copying the other. Read the *fraction*, not individual pairs.
- **It detects derivation, not quality.** A derived source can be perfectly good data. It just cannot validate its own ancestor.
- **Low coverage is not evidence of independence on its own.** A bad matcher also produces low coverage. Read coverage and distance together.
- **The thresholds are a heuristic**: chosen so this pair of datasets lands on the right side of them. They are not calibrated against a labelled corpus of derived and independent dataset pairs, because no such corpus exists.

## What to take from this page

1. **Ask where a dataset came from before you validate against it.** Overture publishes lineage. Most sources do not, and you have to infer.
2. **The coordinate-distance distribution is a cheap lineage test.** A median near zero plus a large exact-tie fraction means derivation.
3. **Independent sources disagree, and that is the point.** If your validation source agrees with you perfectly, it is probably not a source.
4. **Apply the scrutiny to your own choices.** We caught the GRID3/HDX circularity and then walked into a softer version of it. The test that catches other people is the test worth running on yourself.
5. **88.1% is a consistency figure.** It is what the place pack was tuned against, and it is not a claim about accuracy in the world.

## Next

- [Verify a merge against an external source](../how-to/verify-with-external-sources.md) for what an actually independent gazetteer can and cannot tell you
- [Read the crosswalk output](../how-to/read-crosswalk-output.md) for the shape of the evidence the sweep above reads
- [The same clinic, three spellings](../tutorials/reconciling-nigerias-health-facilities.md) for the reconciliation this benchmark measures
