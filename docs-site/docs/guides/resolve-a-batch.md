# Resolve a batch

Two lists in, a batch result out: every pair the engine matched or held for review, with the evidence for each and an id you can keep. At the end of this page you can read every number in that result, know why a pair is `review` rather than `match`, and know which scorer ran and why.

```python
import arche

register = [
    {"id": "HFR-001", "name": "Karfi Primary Health Centre", "lat": 11.601, "lon": 8.402},
    {"id": "HFR-002", "name": "Central Hospital Kano", "lat": 12.002, "lon": 8.517},
    {"id": "HFR-003", "name": "Gwale General Hospital", "lat": 12.101, "lon": 8.601},
]
survey = [
    {"id": "OSM-77", "name": "Karfi PHC", "lat": 11.6015, "lon": 8.4025},
    {"id": "OSM-91", "name": "Gwale General Hospital", "lat": 12.1012, "lon": 8.6008},
    {"id": "OSM-12", "name": "Central Hospital", "lat": 12.0025, "lon": 8.5172},
]

result = arche.reconcile(register, survey, entity="place")
for edge in result["matches"]:
    print(edge["a_id"], edge["b_id"], edge["decision"], edge["score"])
print(result["count"], "edges;", result["backend"]["chosen"])
```

```text
HFR-003 OSM-91 match 0.9979
HFR-002 OSM-12 review 0.7935
HFR-001 OSM-77 review 0.6706
3 edges; arche
```

`reconcile` is the batch verb. It answers one narrow question, which of these records are the same thing as which of those, and returns the pairs it can say something about. One match, two for a person to look at, and three of the nine possible pairs it says nothing about at all. The rest of this page is what each of those means.

## Two lists in

Each list is a list of dicts. Every row needs a stable `id` (or name the column with `id_field=`); without one the engine falls back to the row's position, which is fine for a script and useless the moment the list is re-sorted. Use the same field names in both lists where you can, because the pack reads fields by name and a column it does not recognise is ignored without a warning.

A name alone is rarely enough. Give the pack the fields that can tell one entity from another: coordinates, an address and an administrative area for a place; a registration number, an address and a website for an organisation; a verified identifier, a date of birth, a phone or an email for a person; a brand and a model code or GTIN for a product. Use only fields you are permitted to process.

`reconcile` asks whether two records are the same entity. It is not the verb for related but distinct things, such as a supplier and its brand or a product family and one variant of it; those need different labels and different evidence.

## The pack choice

`entity=` names a comparator pack: which fields are read, how each is compared, and how much each counts. `describe_pack` says the same in JSON, and `ignores_everything_else` is there because it is true.

```python
from arche.resolve import describe_pack, describe_packs

print(sorted(describe_packs()))
pack = describe_pack("place")
print(pack["field_names"], pack["ignores_everything_else"])
for f in pack["fields"]:
    print(f["field"], f["kinds"], f["weight"])
```

```text
['artist', 'organisation', 'organization', 'person', 'place', 'product_electronics', 'product_grocery', 'product_home_goods']
['address', 'admin_path', 'lat', 'lon', 'name'] True
name ['placename', 'tftoken', 'type'] 4.0
address ['address'] 1.0
admin_path ['containment'] 1.0
lat + lon ['geo'] 1.0
```

Choose the pack by what the records are, not by what is nearest to hand. The pack decides which population rarity is measured against: `place`, `organisation` and `artist` read a shipped frequency table, so the engine knows that *General* and *Hospital* are ordinary words before it sees your data; `person` builds a table from the two lists you passed, and that self-calibrated table is named in the pins so two batches that scored the same pair differently say why. Pass `comparators=` instead of `entity=` to declare your own fields, or `decl=` for a declared schema; [Extract to your schema](extract-to-your-schema.md) covers the declaration.

## What an edge holds

```python
import json

print(json.dumps(result["matches"][0], indent=2))
print(sorted(result["pins"]))
print(result["blocking"]["candidate_pairs"], result["blocking"]["reduction_ratio"])
```

```text
{
  "a_id": "HFR-003",
  "b_id": "OSM-91",
  "score": 0.9979,
  "decision": "match",
  "evidence": {
    "name": 1.0,
    "name_tftoken": 1.0,
    "name_type": 1.0,
    "geo": 0.99,
    "distance_km": 0.03
  },
  "distinctive_max": 1.0,
  "decision_id": "xwd:sha256:753f1869e87016225468975c496018cbe24957c510b84c1de541913e28f7bee4"
}
['block', 'comparators_sha256', 'distinctive_floor', 'engine', 'review_margin', 'tf', 'threshold']
5 0.4444
```

| field | meaning |
|---|---|
| `a_id`, `b_id` | the two records' ids. An edge carries ids and numbers only, never a record value |
| `score` | the weighted mean of every comparator that applied, 0 to 1 |
| `decision` | `match` or `review`. Pairs below the review floor are not in the list |
| `evidence` | one entry per comparator that ran, keyed by field, with the kind suffixed when two comparators read one field (`name_tftoken`) |
| `distinctive_max` | the strongest distinctive signal seen, the number the gate below reads |
| `decision_id` | a content hash over the edge and the run's `pins` |

`evidence` is what the score was made from. `name` is place-name similarity with the type word set aside; `name_tftoken` is how rare the words the two names share are; `name_type` compares the facility tier as a category; `geo` decays with distance and `distance_km` says how far. A comparator whose field neither record carries skips silently rather than scoring zero, so a missing address does not drag a pair down.

`pins` are the run's provenance: the engine version, a digest of the comparator set, the thresholds and which frequency table was used. They are hashed into every `decision_id`, so the same edge from the same inputs under the same engine gives the same id, and an id that changed is a run that changed. `blocking` says how many pairs were scored and what fraction of the full cross product was skipped; with coordinates present, records are bucketed spatially and only neighbours are compared, which is why a big batch is fast.

## `review` is a queue

```python
queue = [e for e in result["matches"] if e["decision"] == "review"]
for edge in queue:
    print(edge["a_id"], edge["b_id"], edge["score"], edge["distinctive_max"], edge["evidence"])
```

```text
HFR-002 OSM-12 0.7935 0.636 {'name': 0.952, 'name_phrase': 'central hospital', 'name_phrase_rarity': 0.636, 'name_tftoken': 0.541, 'name_type': 1.0, 'geo': 0.98, 'distance_km': 0.06}
HFR-001 OSM-77 0.6706 0.837 {'name': 0.837, 'name_tftoken': 0.352, 'name_type': 1.0, 'geo': 0.974, 'distance_km': 0.08}
```

A pair lands at `review` for one of two reasons, and these two show one each.

The score bands come from two defaults, `threshold=0.7` and `review_margin=0.15`. A score at or above 0.70 is a `match` if the gate clears; a score from 0.55 up to 0.70 is `review`; below 0.55 the pair is dropped. `HFR-001` and `OSM-77` are the second case: *Karfi* is rare and the names are close, but *Primary Health Centre* against *PHC* leaves the name comparator at 0.837 and the shared-token evidence at 0.352, and the mean lands in the band.

The gate is the other reason. A score above the threshold only becomes `match` if some distinctive comparator reaches `distinctive_floor=0.75`, and `distinctive_max` says how close it came. `HFR-002` and `OSM-12` score 0.7935, well above the threshold, and stay at `review` because the strongest distinctive signal was 0.636: *Central Hospital* is an ordinary phrase, and agreeing on ordinary words is not evidence. Two different facilities at one coordinate score high on `geo`, and `geo` is not distinctive, so the gate is what stops a shared location from manufacturing a merge.

Treat the queue as work for a person, not as a score to round up or a rejection to throw away. [Review a queue](review-a-queue.md) turns it into a pack a reviewer can work and an adjudication an auditor can re-check.

## What absence means

Three of the nine possible pairs are not in the result. The engine scored five candidates (`blocking` said so), found two below the floor, and never compared the other four because blocking saw no reason to. None of that is a claim that those pairs are different entities. A batch result holds the pairs the engine can say something about; a pair it is silent on has not been decided either way, and a pipeline that reads absence as `no_match` is asserting something arche never said.

## Which scorer ran

```python
print(result["backend"])
engine = arche.reconcile(register, survey, entity="place", backend="arche")
print("backend" in engine, engine["pins"]["engine"])
```

```text
{'floor': 1000, 'records': 6, 'chosen': 'arche', 'reason': '6 records is below the floor of 1000'}
False crosswalk.v1
```

`backend` defaults to `"auto"`. Below `AUTO_SPLINK_FLOOR`, 1,000 records across the two lists, arche's own engine scores the pairs. At or above it, and only when `arche-core[resolve]` is installed, the entity has a shipped Splink recipe, and the records carry that recipe's columns, the scoring is handed to Splink and everything arche puts around a score (evidence, pins, the gate, the review band, the decision ids) stays. Otherwise the engine runs again, and `result["backend"]["reason"]` says which condition failed, in words. It sits on the result rather than in the pins because which scorer ran is already pinned into every id, while why it was chosen names the batch size and must not move an id.

The floor is measured, not chosen. On the supplier world the two scorers are level on false merges at 444 and 1,215 records, and by 3,081 the engine merges 456 wrong pairs to Splink's 49. It is a precision floor, not a runtime one: the engine runs that batch in under a minute. [Benchmarks](../reference/benchmarks.md#arche-using-splink-rather-than-against-it) has the runs, including the ones arche loses.

Today one recipe ships, `person/febrl-v1`, and it reads `given_name` and `surname` as two columns. A `person` caller with one `name` blob stays on the engine at every size and the reason says so. `backend="arche"` is the engine regardless of size, and the result then carries no `backend` key because nothing was chosen. `backend="splink"` is Splink regardless of size and needs `splink_settings=`.

## One list: `dedupe` and `find`

```python
one_list = register + [{"id": "HFR-001b", "name": "Karfi Primary Health Center", "lat": 11.6011, "lon": 8.4021}]
d = arche.dedupe(one_list, entity="place")
for edge in d["matches"]:
    print(edge["a_id"], edge["b_id"], edge["decision"], edge["score"])
for c in d["clusters"]:
    print(c)
```

```text
HFR-001 HFR-001b match 0.8665
{'members': ['HFR-001', 'HFR-001b'], 'size': 2, 'held_together_by': 'direct'}
{'members': ['HFR-002'], 'size': 1, 'held_together_by': 'direct'}
{'members': ['HFR-003'], 'size': 1, 'held_together_by': 'direct'}
```

`dedupe` is `reconcile` over one list, with the self-pairs and the mirrored edges removed, so every edge is one claim about two different records. It adds `clusters`, the transitive closure over `match` edges only: `review` never merges. Each cluster says how it is held together, `direct` when every pair of members was compared and matched, `transitive` when A matched B and B matched C but A and C were never judged, which is the case to look at first. Ids must be unique, and a duplicated id is refused rather than guessed at.

```python
f = arche.find({"id": "q", "name": "Gwale General Hospital", "lat": 12.101, "lon": 8.601}, survey, entity="place")
print(f["verdict"], f["match"]["b_id"] if f["match"] else None, f["reason"])
```

```text
found OSM-91 one candidate matched at 0.9979
```

`find` is one record against a list, and it returns a verdict rather than a ranking: `found` when one candidate matched and nothing else came close, `ambiguous` when two or more are within `ambiguity_margin` of each other (with `would_resolve` naming the field that would separate them), and `not_found` when nothing matched. `candidates` always carries what was compared, best first. Taking the top row of an ambiguous lookup is how a wrong supplier gets written into a master list, which is why the verdict is separate from the list.

## Keep the edges

```python
ledger = arche.attach("duckdb:///:memory:")
kept = arche.reconcile(register, survey, entity="place", store=ledger)
first = kept["matches"][0]["decision_id"]
print(first[:40])
why = ledger.explain(first)
print(sorted(why))
print(why.get("supporting"), why.get("missing"))
print(ledger.replay(first).reproduced)
```

```text
xwd:sha256:753f1869e87016225468975c49601
['action', 'basis', 'explanation', 'gate', 'identity', 'missing', 'refuting', 'shared', 'supporting']
['geo', 'name', 'name_tftoken', 'name_type'] ['national_id', 'registration_id', 'phone', 'email', 'dob', 'address']
True
```

`store=` on any batch verb records every edge and both lists in a ledger, so an edge can be looked up by its `decision_id`, explained, and replayed against the exact batch it was scored in. The return value is unchanged. A file path instead of `:memory:` keeps it on disk; nothing leaves the machine. [Keep, explain, replay](keep-and-replay.md) has the rest: the cases still at review, the entities the edges have linked, adding evidence and deciding again.

## From the command line

```sh
arche compare suppliers.csv registry.csv --entity organisation
```

The same call on two files, with an HTML report and a JSON sidecar of the decisions; values in the report are masked unless you pass `--reveal`. [Five minutes](../get-started/five-minutes.md) runs it on the built-in demo, and [Review a queue](review-a-queue.md) takes the report from there.

## Where to read next

| You want to | Read |
|---|---|
| work the `review` pairs and record what a person decided | [Review a queue](review-a-queue.md) |
| what `review` means, and why the score is not a probability | [Compare two records](compare-two-records.md) |
| your own field names as the labels, one declaration for extraction and matching | [Extract to your schema](extract-to-your-schema.md) |
| keep every edge and replay it next year | [Keep, explain, replay](keep-and-replay.md) |
| the full parameter list and `sign_edges` | [Backends](../how-it-works/backends.md) |
| the runs behind the size floor, including the ones arche loses | [Benchmarks](../reference/benchmarks.md) |
