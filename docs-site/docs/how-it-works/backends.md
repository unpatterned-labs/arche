# Backends: arche, Splink, auto

`reconcile` can score a batch with arche's own engine or with Splink, and by default it chooses. At the end of this page you know what each scorer is, why Splink wins above a thousand records and what was measured to find that out, how `backend="auto"` decides and reports, what the shipped recipes are and what they withhold, and how to hand Splink a configuration of your own.

```python
import arche

suppliers = [
    {"id": "s1", "name": "Kijani Tea Exporters Ltd", "city": "Nairobi"},
    {"id": "s2", "name": "Zenith Bank Plc", "city": "Lagos"},
]
registry = [
    {"id": "r1", "name": "Kijani Tea Exporters Limited", "city": "Nairobi"},
    {"id": "r2", "name": "Kijani Coffee", "city": "Nairobi"},
]

result = arche.reconcile(suppliers, registry, entity="organisation", backend="auto")
for edge in result["matches"]:
    print(edge["a_id"], edge["b_id"], edge["decision"], edge["score"])
print(result["backend"])
print(result["pins"]["engine"])
```

```text
s1 r1 match 1.0
s1 r2 review 0.5798
{'floor': 1000, 'records': 4, 'chosen': 'arche', 'reason': '4 records is below the floor of 1000'}
crosswalk.v1
```

`backend="auto"` is the default, so leaving it out gives the same result. Four records is under the floor, arche's engine scored the pairs, and `result["backend"]` says so in words.

## What arche's engine is

The engine behind `crosswalk.v1` is a fixed-weight evidence aggregator with gates. A pack declares which fields to read, how to compare each one, and what each is worth; the engine computes one similarity per field, takes the weighted mean as `score`, and then applies the rules that are not weights: the distinctive-signal gate, refutation, and the geographic veto. It does not learn. The weights are the pack's, the frequency table is shipped or built from the batch, and nothing is estimated from the records being linked.

```python
from arche.resolve import describe_pack

for f in describe_pack("organisation")["fields"]:
    print(f"{f['field']:16} {f['weight']:<4} {'refutes' if f['refutes'] else ''}")
```

```text
name             4.0  
registration_id  3.0  
address          1.0  refutes
lat + lon        0.5  
entity_class     0.0  refutes
```

That is the whole model for an organisation: five fields, five weights, two of them able to refute. The `person` path that `compare` runs is a Fellegi-Sunter sum too, but with `m` and `u` fixed per jurisdiction rather than trained. Two properties follow from having no training step. The engine gives the same answer on two records as on two million, because nothing it uses depends on the batch except a self-calibrated frequency table where no shipped one exists. And it has no threshold to choose: a pack ships its operating point and the verdicts are `match`, `review` or silence. [Evidence, gates and distinctiveness](evidence.md) is what the gates do.

## What Splink is

[Splink](https://moj-analytical-services.github.io/splink/) is the closest thing to a standard in probabilistic record linkage. It is Fellegi-Sunter with the parameters estimated from the data: `u`, how often a field agrees between records that are not the same, from random sampling; `m`, how often it agrees between records that are, by expectation maximisation over the blocked pairs; and a prior for how many true matches the corpus holds. It adjusts for term frequency, so agreeing on a rare value counts more than agreeing on a common one, with the rarity counted from the batch. It emits one probability per pair, and the caller picks a threshold.

It does inference better than arche does, and the benchmarks say so plainly. On every person and place dataset run here, Splink wins.

| Dataset | arche engine | Splink |
|---|---|---|
| Febrl 4, no identifier | 4,191 true, 42 false, recall 0.8382 | 4,768 true, 0 false, recall about 0.953 |
| Nigerian school register | 146 true of 200, 2 false of 400 | 190 true, 0 false |
| England schools link | 278 true, 32 false | 278 true, 0 false |
| `historical_50k` | precision 0.9803, recall 0.2872, 111 s | precision 0.9992, recall 0.5048, 20 s |
| Abt-Buy products, identity columns only | 741 true, 22 false, F1 0.797 | 732 true, 49 false, F1 0.780 |
| Abt-Buy products, title included | | F1 0.537 |

The product rows are the exception and the reason the last section of this page exists. Given only the columns the pack declares identity-bearing, Splink lands at arche's recall with twice the false merges. Given the title as well, which is the natural thing to do, it collapses to precision 0.41, because expectation maximisation cannot tell *same product* from *same brand, same kind of product, similar title*. Which fields carry identity is not something an estimator learns from titles. [Benchmarks](../reference/benchmarks.md) has every table with its caveats.

## The size floor, and the measurement behind it

A trained model learns from the batch in front of it, and a thin batch teaches it the wrong things. On a 1,200-record Nigerian register with nothing to learn from, Splink at its own decision boundary merged 368 of 400 known-different schools, because every name in the batch appeared exactly twice and nothing said *Community Primary School* is common. With 500 filler records added, that fell to 2. So there is a size below which the engine's shipped prior beats a trained model, and above which the trained model's precision and recall pull ahead. `AUTO_SPLINK_FLOOR` is where that line is drawn.

```python
from arche.resolve import AUTO_SPLINK_FLOOR

print(AUTO_SPLINK_FLOOR)
```

```text
1000
```

The floor is measured, not chosen. The sweep runs the synthetic supplier world at four sizes with the same generator and seed, arche's organisation pack against the published Splink recipe at its own boundary of 0.5, and reads false merges first, because a supplier that moved is the same supplier and two suppliers sharing a common name are not.

| Records | Engine false merges | Splink false merges |
|---|---|---|
| 444 | 2 | 5 |
| 1,215 | 39 | 47 |
| 3,081 | 456 | 49 |
| 6,144 | 917 | 103 |

At 444 and 1,215 records the two are level, and the engine is the one with no threshold to choose. By 3,081 the engine's precision has turned: 456 wrong merges against 49. The floor sits under that turn. It is a precision floor, not a runtime one. Runtime used to be the other reason (the engine took nine hours at 6,144 records) until its per-pair recomputation was memoised on 2026-09-19, and the same sweep now runs in 70 s, within three times Splink everywhere.

One thing to say plainly: the floor was measured on organisations, and no organisation recipe ships yet. So `auto` keeps the engine for organisations at every size and says so in the reason. The recipes that exist are for people, places and products.

## How `auto` decides

Splink is chosen only when every one of these holds: the batch is at or above the floor; the entity has a shipped recipe; the recipe is enabled for `auto`; Splink is installed (`arche-core[resolve]`); the records carry the recipe's columns; and no external candidate pairs were supplied. Otherwise arche's engine, with the first failing condition as the reason. Never `"derive"`: `auto` chooses between two measured configurations, not an inferred one.

```python
import random

random.seed(7)
given = ["Adesola", "Ibrahim", "Fatima", "Chukwuemeka", "Ngozi", "Musa", "Amina", "Kwame"]
surnames = ["Okonkwo", "Musa", "Abdullahi", "Okafor", "Adeyemi", "Bello", "Mensah", "Diallo"]

def people(n, prefix):
    return [{"id": f"{prefix}{i}", "name": f"{random.choice(given)} {random.choice(surnames)}",
             "phone": f"080{random.randint(10000000, 99999999)}"} for i in range(n)]

def products(n, prefix):
    return [{"id": f"{prefix}{i}", "name": f"Sony Turntable PSLX{i}H"} for i in range(n)]

for entity, a, b in [("person", people(500, "a"), people(500, "b")),
                     ("product_electronics", products(500, "a"), products(500, "b"))]:
    chosen = arche.reconcile(a, b, entity=entity)["backend"]
    print(chosen["records"], chosen["chosen"], "|", chosen["reason"].split(":")[0])
```

```text
1000 arche | records do not carry the recipe's columns
1000 arche | recipe product/identity-v1 exists but the engine won its benchmark; pass splink_settings=recipes.PRODUCT to use it deliberately
```

Both batches are at the floor and both stay on the engine, for different reasons. The person recipe reads `given_name` and `surname` as two columns, because Splink learns separate `m` and `u` for each and that split is where its Febrl recall comes from; a caller with one `name` blob stays on the engine at every size, and the full reason names the columns the recipe wanted. The product recipe exists and is not enabled for `auto`, because the engine won its benchmark; asking for it by name is the caller's decision.

Splink is installed here, so a `person` batch of a thousand records that does carry the recipe's columns would print `chosen: splink` with the recipe's name. Where Splink is not installed the reason says so instead, and the engine runs.

## What `result["backend"]` is, and where it is not

The choice is provenance of the run, not an input to any decision. The same pair scored by the engine is the same decision whether you asked for the engine or `auto` picked it, and the reason names the batch size, which an unrelated record would change. So the choice goes on the result and never into the pins that decision ids hash over. The scorer itself is already pinned: `engine`, and for Splink `backend` and `settings`.

```python
print(sorted(arche.reconcile(suppliers, registry, entity="organisation", backend="arche")))
```

```text
['blocking', 'count', 'matches', 'pins']
```

An explicit `backend="arche"` or `backend="splink"` made no choice, so there is no `backend` key on the result. Read it only when you left the choice to `auto`.

## The shipped recipes

A recipe is one hand-written Splink configuration per entity, with everything a run needs: the columns it reads, the training plan, a seeded `u` sample, the threshold it was benchmarked at, and the benchmark that set it. It is data the wheel ships, like a pack, and it is held to the same drift discipline: a CI gate re-runs the person recipe and fails the build if the result's pin does not name the recipe, whatever its precision did.

```python
from arche.resolve.recipes import PERSON, PLACE, PRODUCT

for recipe in (PERSON, PLACE, PRODUCT):
    print(recipe.name, "| auto:", recipe.auto, "| threshold:", recipe.threshold,
          "| review_margin:", recipe.review_margin)
    print("   needs", recipe.requires)
    print("   ", recipe.benchmark)
```

```text
person/febrl-v1 | auto: True | threshold: 0.99 | review_margin: 0.79
   needs ('given_name', 'surname', 'date_of_birth', 'street_number', 'address_1', 'postcode', 'state')
    datasets/names_dataops/bench_splink_febrl.py (no soc_sec_id)
place/name-coords-v1 | auto: True | threshold: 0.9 | review_margin: 0.4
   needs ('name', 'lat', 'lon')
    datasets/names_dataops/bench_splink_england_schools.py; bench_splink_nigeria.py
product/identity-v1 | auto: False | threshold: 0.5 | review_margin: 0.3
   needs ('name',)
    datasets/products_dataops/bench_splink_abt_buy.py (identity recipe)
```

| Recipe | What it is | Its benchmark |
|---|---|---|
| `PERSON` | Splink's own published Febrl 4 configuration with the identifier withheld and the `u` sample seeded | 4,761 true, 0 false at p >= 0.99, the same on every run |
| `PLACE` | name with term frequency, distance at 100 m, 500 m, 2 km and 10 km | England schools 278 true, 0 false at p >= 0.9; Nigerian register 190 true, 0 false |
| `PRODUCT` | the extracted model code and the brand, and nothing else | Abt-Buy 732 true, 49 false at p >= 0.5 |

The threshold is part of the recipe because a Splink probability has no portable scale. `PLACE` is at 0.9 and not 0.5 for the reason in the size-floor section: at 0.5 on a 1,200-record batch the same model merges 368 of 400 known-different schools, at 0.9 it merges 2. Records that do not carry a recipe's columns are refused by name before Splink sees a frame, because a column absent from every record would make Splink compare null against null and call that agreement.

Why recipes and not derivation: an earlier version inferred a Splink configuration from an arche pack, and on three datasets it was wrong in a different way on each (no date format, so the date trained nothing; uncosted blocking keys, so one column put 639 million pairs in a block; coordinates coerced to strings). Fixing those left the part that cannot be fixed by inference. A derived configuration orders pairs about as well as a hand-written one and cannot calibrate them, because calibration comes from a prior about how many true matches the corpus holds, and nothing in a list of records states it. The same derived run on Febrl 4 gives recall 0.8952 at p >= 0.5 and 0.5448 at p >= 0.99, either side of the engine's 0.8382, on the same edges in the same order. `splink_settings="derive"` still exists, opts in, and warns.

## What "a recipe withholds" means

The more important half of a recipe is which fields the estimator is not allowed to learn from. `PRODUCT` is the clearest case: it has a `prepare` step that runs arche's representation over each title before Splink sees a frame, and hands Splink the columns that come out.

```python
rows = [{"id": "a1", "name": "Sony Turntable - PSLX350H"},
        {"id": "b1", "name": "Sony PS-LX350H Turntable"}]
for row in PRODUCT.prepare(rows):
    print(row)
print(PRODUCT.columns)
```

```text
{'id': 'a1', 'code1': 'pslx350h', 'codes': ['pslx350h'], 'brand': 'sony', 'specs': []}
{'id': 'b1', 'code1': 'pslx350h', 'codes': ['pslx350h'], 'brand': 'sony', 'specs': []}
('code1', 'codes', 'brand', 'specs')
```

The title is gone. Two spellings of one model code normalise to the same `code1`, the brand is the first token, and a capacity or size would land in `specs`. That is all Splink gets. Given the title as well, expectation maximisation learns that similar titles are evidence of identity, which for products they are not: the learned weight for a shared code fell from +10.05 bits to +6.08, "no shared code" went from -4.13 bits to -0.09, neutral, and precision fell from 0.94 to 0.41 on the same data. Withholding the title was the whole difference between F1 0.537 and 0.785.

The pack's own guarantees stay outside the model for the same reason. A refutation that expectation maximisation learned was worth -4.86 bits in one configuration and -1.42 in another; a guarantee whose strength depends on what else was in the model is not a guarantee.

## Running Splink yourself

`backend="splink"` runs Splink regardless of size and requires `splink_settings=`: a shipped `Recipe`, or a `SettingsCreator` you wrote. A recipe brings its own threshold; your own settings need `threshold=` too, because the shipped 0.99 that used to stand in for one auto-merged nothing at all on one of the benchmark sets. Splink logs its training to the console as it goes.

<!-- docs-test: skip -->
```python
from arche.resolve.recipes import PLACE

random.seed(3)
towns = ["Karfi", "Gwale", "Nyeri", "Gyaranya", "Dawakin", "Kumbotso", "Ungogo", "Tofa", "Bichi",
         "Garko", "Wudil", "Kura", "Madobi", "Kiru", "Bebeji", "Rano", "Tudun Wada", "Doguwa", "Sumaila"]
kinds = ["Health Post", "Primary Health Centre", "General Hospital", "Dispensary", "Maternity", "Clinic"]

register, survey = [], []
for i in range(240):
    town, kind = random.choice(towns), random.choice(kinds)
    lat, lon = 11.5 + random.random(), 8.0 + random.random()
    register.append({"id": f"HFR-{i:03d}", "name": f"{town} {kind}", "lat": round(lat, 4), "lon": round(lon, 4)})
    if random.random() < 0.7:
        name = f"{town} {kind}".replace("Primary Health Centre", "PHC") if random.random() < 0.5 else f"{town} {kind}"
        survey.append({"id": f"OSM-{i:03d}", "name": name,
                       "lat": round(lat + random.uniform(-0.003, 0.003), 4),
                       "lon": round(lon + random.uniform(-0.003, 0.003), 4)})
for i in range(60):
    town, kind = random.choice(towns), random.choice(kinds)
    survey.append({"id": f"OSM-x{i:03d}", "name": f"{town} {kind}",
                   "lat": round(11.5 + random.random(), 4), "lon": round(8.0 + random.random(), 4)})

splink = arche.reconcile(register, survey, backend="splink", splink_settings=PLACE)
engine = arche.reconcile(register, survey, entity="place", backend="arche")
for label, run in (("splink", splink), ("engine", engine)):
    print(label, run["count"], "edges,", sum(e["decision"] == "match" for e in run["matches"]), "match")
edge = splink["matches"][0]
print(edge["evidence"], edge["decision_id"][:20])
print({k: splink["pins"][k] for k in ("engine", "backend", "settings", "training", "threshold", "gate")})
```

```text
splink 186 edges, 167 match
engine 866 edges, 182 match
{'name_level': 4, 'lat_lon_level': 3, 'match_probability': 0.9994} xwd:sha256:22073f884
{'engine': 'crosswalk.splink.v1', 'backend': 'splink', 'settings': 'recipe:place/name-coords-v1@sha256:c7b89bf4b53b38b7', 'training': 'recipe', 'threshold': 0.9, 'gate': False}
```

The result is the shape `reconcile` always returns, so a review queue, a report or a ledger reads it unchanged. Two things differ. The `evidence` on an edge is Splink's: the comparison level each field landed on and the match probability, not arche's per-field similarities. And the pins name a different engine. `crosswalk.splink.v1` pins the recipe or `caller` or `derived` under `settings`, the trained model's digest, the corpus digest, the blocking, the prior, the seed, and the Splink and DuckDB versions, because a trained scorer is a function of the data it saw and a version string would claim less than the truth. Two runs with different model digests were scored by different models and are not expected to agree.

The distinctive-signal gate is off by default on this backend. Splink has already priced name evidence, and recomputing arche's own name evidence to overrule it is two correlated rules that can be worse than either alone: on the Nigerian register the gate costs 44 true merges to prevent 2 and queues 393 of 400 pairs. `gate=True` turns it on, and turning it on is a decision to make with a measurement in hand.

To bring your own configuration, pass a `SettingsCreator` and a threshold. No pack is needed, because the settings already say what to compare and how; `splink_train=` takes a callable that receives the built `Linker` if you want a training plan other than Splink's documented default.

<!-- docs-test: fragment -->
```python
import splink.comparison_library as cl
from splink import SettingsCreator, block_on

settings = SettingsCreator(
    link_type="link_only",
    comparisons=[cl.NameComparison("name").configure(term_frequency_adjustments=True),
                 cl.DistanceInKMAtThresholds("lat", "lon", [0.5, 2, 10])],
    blocking_rules_to_generate_predictions=[block_on("name"), block_on("round(lat,1)", "round(lon,1)")],
)
result = arche.reconcile(register, survey, id_field="id", backend="splink",
                         splink_settings=settings, threshold=0.9)
```

Sweep the threshold on your own labels before trusting a number from it. `pins["settings"]` will read `caller`, so anyone reading the decision later knows the configuration was yours.

## Where to read next

| You want to | Read |
|---|---|
| every field on an edge and what its id hashes over | [The decision](the-decision.md) |
| the gates the engine applies and why | [Evidence, gates and distinctiveness](evidence.md) |
| every Splink comparison with its script and caveats | [Benchmarks](../reference/benchmarks.md) |
| a batch from two lists, step by step | [Resolve a batch](../guides/resolve-a-batch.md) |
| the `resolve` extra and what it installs | [Extras](../reference/extras.md) |
| every argument to `reconcile` | [Python API](../reference/python-api.md) |
