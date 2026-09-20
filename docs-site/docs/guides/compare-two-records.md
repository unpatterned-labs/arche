# Compare two records

At the end of this page you can put two records in front of arche, read the verdict and the two fields it comes in, see what each number in the evidence means, and know why an identical pair can come back `review`.

```python
import arche

a = {"name": "Touton Negoce SARL", "registration_id": "RC-88421"}
b = {"name": "Touton Negoce", "registration_id": "RC-88421"}

r = arche.compare(a, b, entity="organisation")
print(r.identity, r.action, "|", r.explanation)
print(r.factors)
print(r.gate)
```

```text
same_entity merge | agrees on name, name_tftoken, registration_id
{'name': 1.0, 'name_tftoken': 1.0, 'registration_id': 1.0}
{'distinctive_max': 1.0, 'distinctive_floor': 0.75}
```

A company number is the one exact identity signal most supplier files carry, and it settles the pair without the names having to agree on a format. `compare` takes two dicts with your own field names, or two texts with `jurisdiction=` and `backend=` so the fields can be read out of them first. The pack (`person`, `organisation`, `place`, `product_electronics`, `artist`) says which fields it reads and what each is worth; [Extract to your schema](extract-to-your-schema.md) is how you name your own.

## Two fields, on purpose

`identity` is what arche believes: `same_entity`, `review` or `different`. `action` is what it recommends: `merge`, `hold` or `no_op`. They can disagree, and when they do it is the most useful thing on the receipt.

```python
c = "NIN 12345678901, adesola@example.com"
d = "NIN 12345678901, okonkwo.a@gmail.com"

r = arche.compare(c, d, entity="person", jurisdiction="NG", backend="basic")
print(r.identity, r.action, "|", r.basis, "|", r.explanation)
print(r.factors)
```

```text
same_entity hold | single_identifier | national ID match
{'national_id': 1.0, 'email': 0.0}
```

The belief is `same_entity`: a shared national id is distinctive enough to clear the gate alone. The recommendation is `hold`: one identifier, nothing corroborating it, and an email that disagrees. `basis` names the shape of the evidence, `single_identifier` here and `corroborated` when a second field agrees. A system can link the two records on the belief and still route the pair to a person on the recommendation, which is what keeping the fields apart is for.

## What the numbers mean

`factors` is one number per field the pack compared, in `[0, 1]`. A field that neither record carries is absent from `factors`; a field one side carries and the other does not is absent too. `score` is the weighted agreement over those fields, and it is a ranking signal, not a probability: two records can score `1.0` and not be the same thing.

`gate` is what decided. `distinctive_max` is the strongest *distinctive* agreement in the pair, and `distinctive_floor` is the line it has to clear. That is the number to look at when a verdict surprises you.

```python
x = {"name": "Central Cooperative Society"}
y = {"name": "Central Cooperative Society"}

r = arche.compare(x, y, entity="organisation")
print(r.identity, r.action, "|", r.explanation)
print(r.score, r.gate)
```

```text
review hold | agrees on name, name_tftoken, name_type
1.0 {'distinctive_max': 0.594, 'distinctive_floor': 0.75}
```

Byte-identical strings, a score of `1.0`, and still not a merge. The names agree; the frequency table knows that agreeing on *Central* and *Cooperative Society* is not evidence of identity, because every district has one. `distinctive_max` is `0.594` against a floor of `0.75`, so the gate does not clear and the answer is `review`: look at this one. Before the frequency table shipped, this pair merged at `1.0`.

The same rule in the other direction: two people with the same ordinary name and nothing else in common.

```python
e = "Ibrahim Musa, 0803 555 0111, ibrahim@example.com"
f = "Ibrahim Musa, 0805 222 9999, imusa@work.ng"

r = arche.compare(e, f, entity="person", jurisdiction="NG", backend="basic")
print(r.identity, r.action, "|", r.explanation)
print(r.factors)
```

```text
different no_op | name similarity 100%
{'name': 1.0, 'phone': 0.0, 'email': 0.0, 'name_tf': 1.0}
```

`name_tf` is the token overlap of the two names weighted by how rare each token is, and two identical names score `1.0` whether the name is rare or ordinary; the gate is what asks whether the shared tokens are distinctive, and *Ibrahim Musa* is not. A full-name match on a common name, with the phone and the email both disagreeing, is two men. [Evidence, gates and distinctiveness](../how-it-works/evidence.md) has the measure.

## When a supporting signal cannot carry the pair

Geography, address and containment can lift a well-evidenced pair over the line. None of them can carry a weak or refuted name across it.

```python
site = {"name": "Nyeri Hill Factory", "entity_class": "SITE", "lat": -0.42, "lon": 36.95}
operator = {"name": "Nyeri Hill Tea Factory Co Ltd", "entity_class": "OPERATOR", "lat": -0.42, "lon": 36.95}

r = arche.compare(site, operator, entity="organisation")
print(r.identity, r.action, "|", r.explanation)
print(r.factors["name"], r.factors["geo"], r.factors["distance_km"], r.factors["entity_class"])
```

```text
review hold | agrees on geo, name, name_type; disagrees on distance_km, entity_class, entity_class_conflict
0.954 1.0 0.0 0.0
```

This is the largest false-merge risk in supply-chain data. A site and the company that operates it share a name and a coordinate, so every string and spatial signal points the wrong way at once. The one field that knows they are different parties, `entity_class`, refutes the pair, and a refutation is not outvoted by agreement elsewhere. Merging them would destroy the link between a plot and the party accountable for it, which is the only thing a due-diligence chain exists to establish.

## Places

The `place` pack reads a name and a coordinate, and knows which words are ordinary in a facility name.

```python
p = {"name": "Kano Central Primary Health Centre", "lat": 12.0022, "lon": 8.5920}
q = {"name": "Kano Central PHC", "lat": 12.0024, "lon": 8.5918}

r = arche.compare(p, q, entity="place")
print(r.identity, r.action, "|", r.explanation)
print(r.factors)
```

```text
same_entity merge | agrees on geo, name, name_type
{'name': 0.894, 'name_tftoken': 0.457, 'name_type': 1.0, 'geo': 0.99, 'distance_km': 0.03}
```

*PHC* and *Primary Health Centre* are one type, so the names agree on the part that matters, and thirty metres apart is the same building. The coordinate cuts the other way too:

```python
g = {"name": "General Hospital", "lat": 12.0, "lon": 8.5}
h = {"name": "General Hospital", "lat": 9.06, "lon": 7.49}

r = arche.compare(g, h, entity="place")
print(r.identity, r.action, "|", r.factors["distance_km"], "km |", r.explanation)
```

```text
review hold | 345.05 km | agrees on distance_km, geo_conflict_km, name, name_tftoken, name_type; disagrees on geo
```

Identical names, 345 km apart. The name is ordinary and the geography refutes it, so this is not a merge, and it is not `different` either, because two records that agree on everything they carry except a coordinate deserve a look rather than a verdict. Read `geo` as the verdict on the coordinate; `distance_km` and `geo_conflict_km` are the measurements it was made from.

## The receipt

Every `compare` returns a `Receipt`. `decision_id` is a content hash over the rounded evidence and the pinned versions: run the same call again and you get the same id, byte for byte. `pins` names the pack, the frequency table, the comparator set, the floors and the engine that decided. `reference_a` and `reference_b` are the records as arche read them, with the raw values replaced by their references.

```python
print(r.decision_id[:32])
print(sorted(r.pins))
```

```text
xwd:sha256:0c15336a080c4babc7eaf
['block', 'comparators_sha256', 'distinctive_floor', 'engine', 'entity_pack', 'review_margin', 'tf', 'threshold']
```

Add `store=` and the same call records the receipt with the inputs it was made from; [Keep, explain, replay](keep-and-replay.md) is what you can do with it after that. [The decision](../how-it-works/the-decision.md) lists every field.

## Where to read next

| You want to | Read |
|---|---|
| two lists, not two records | [Resolve a batch](resolve-a-batch.md) |
| your own field names as the ones the pack reads | [Extract to your schema](extract-to-your-schema.md) |
| why `review` is the answer, in the engine's own terms | [Evidence, gates and distinctiveness](../how-it-works/evidence.md) |
| the verdicts on a hundred real pairs, with the ones arche got wrong | [Benchmarks](../reference/benchmarks.md) |
