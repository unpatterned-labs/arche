# Evidence, gates and distinctiveness

Two records can agree on every field they carry and still not be a match. At the end of this page you know why: what the frequency table measures, what `name_tf` and `name_tftoken` are, where the floor of `0.75` sits and what `distinctive_max` is measured against, why a conflicting field is not outvoted, what geography can and cannot carry, and how arche reads a name written two ways.

```python
import arche

a = [{"id": "a1", "name": "General Hospital"}]
b = [{"id": "b1", "name": "General Hospital"}]

for entity in ("place", "organisation"):
    edge = arche.reconcile(a, b, entity=entity)["matches"][0]
    print(f"{entity:13}", edge["decision"], edge["score"], edge["distinctive_max"])
```

```text
place         review 1.0 0.564
organisation  match 1.0 0.862
```

Same two strings, same score of `1.0`, two verdicts. Nothing about the pair changed between the runs. What changed is the population the pair was measured against, and that is the whole subject of this page.

## Agreement and distinctiveness are two questions

Every candidate pair passes two independent tests, and it has to clear both to be `match`.

| Gate | Question | Field |
|---|---|---|
| Agreement | Do these records say the same things? | `score` |
| Distinctiveness | Is what they agree on rare enough to identify anything? | `distinctive_max` |

`score` is a weighted mean of per-field similarities. `distinctive_max` is not a similarity at all: it asks how much information the agreement carries. Two clinics both called *General Hospital* agree completely, and so do two people both called *Mohammed Ibrahim*. In neither case does the agreement say they are the same thing, because almost nothing was said; thousands of other records share those words. Two facilities both called *Karfi Health Post* also agree completely, and *Karfi* is a settlement name few places carry, so that agreement is close to conclusive.

Similarity cannot tell these cases apart. Both score `1.0`. The difference is in how many other records use the same words, which is a fact about the population, not about the pair. That is why arche ships frequency tables.

## The frequency table

A frequency table is a count of tokens over a population. Distinctiveness of a token is its rarity, scaled so that five decades of frequency fill the range:

```
distinctiveness(token) = -log10(relative frequency) / 5     clamped to [0, 1]
```

A token that is one in 100,000 or rarer scores about `1.0`. A token that is most of the corpus scores about `0.0`. `TokenFrequencyTable` is the object, and `default(domain=...)` loads a shipped one.

```python
from arche.resolve import TokenFrequencyTable, describe_pack

for domain in ("place", "organisation"):
    tf = TokenFrequencyTable.default(domain=domain)
    print(domain, [(t, round(tf.distinctiveness(t), 3)) for t in ("general", "hospital", "karfi")])
```

```text
place [('general', 0.564), ('hospital', 0.351), ('karfi', 0.927)]
organisation [('general', 0.594), ('hospital', 0.862), ('karfi', 0.86)]
```

That is the opening example explained. The place table is built from facility registers and settlement gazetteers, where *hospital* is one token in 57, the most ordinary word a facility name can contain. The organisation table is built from GLEIF legal-entity records, where the ordinary words are *limited* and *ltd* and *hospital* appears eleven times in 223,842, one in 20,349. Under `place`, the strongest distinctive agreement on *General Hospital* is *general* at `0.564`, under the floor, so `review`. Under `organisation` it is *hospital* at `0.862`, over the floor, so `match`.

Read that second number carefully, because it is the honest limitation. *Hospital* is not rare in the world. It is rare in a registry of entities that participate in financial markets, because hospitals do not generally register Legal Entity Identifiers. The organisation table's `0.862` is a true statement about GLEIF and a misleading one about hospitals. A frequency table cannot tell "rare" from "absent from my sampling frame", and no gate downstream can recover the difference. So choosing an entity pack is choosing which population rarity is measured against. Pick the pack that matches what your records are. Picking a different one does not get a better answer, it gets a different question, and if it turns a `review` into a `match` you have routed around the refusal rather than resolved it.

```python
for entity in ("place", "organisation", "artist", "person"):
    print(f"{entity:13}", describe_pack(entity)["frequency_table"])
```

```text
place         place
organisation  organisation
artist        artist
person        None
```

| Pack | Population it measures against |
|---|---|
| `place` | shipped place table: 1,248,172 records, 40 strata, 20 countries |
| `organisation` / `organization` | shipped GLEIF organisation table: 41,387 tokens |
| `artist` | shipped MusicBrainz artist table: 95,306 tokens |
| `person` | self-calibrated over the two lists being compared, unless `tf="default"` |

The last row is the one to know about, and it has its own section below.

## `name_tf` and `name_tftoken`

Two factors carry the table into a decision, and both are easy to misread.

`name_tftoken` is on every edge from the pack engine, from the `tftoken` comparator. It is the token overlap of the two names, weighted by distinctiveness: agreeing on a rare token counts far more than agreeing on an ordinary one. It is a ratio, so two identical names score `1.0` whether the name is rare or ordinary. `name_tf` on a `compare` receipt for a person is the same measure from the person engine.

Neither is the gate. Both are similarities, and a similarity of `1.0` on *General Hospital* says only that the two strings match. The gate is a separate number: `distinctive_max` on the pack engine, and on the person engine the `clearing_signal`, which reads `tftoken` only when the two names share a token that is itself distinctive.

```python
c = {"name": "Ibrahim Musa", "phone": "0803 555 0111"}
d = {"name": "Ibrahim Musa", "phone": "0805 222 9999"}
e = {"name": "Adesola Okonkwo", "phone": "0803 555 0111"}
f = {"name": "Adesola Okonkwo", "phone": "0805 222 9999"}

for x, y in ((c, d), (e, f)):
    r = arche.compare(x, y, entity="person", jurisdiction="NG")
    print(r.identity, r.action, "|", r.factors, "|", r.gate["clearing_signal"])
```

```text
review no_op | {'name': 1.0, 'phone': 0.0, 'name_tf': 1.0} | None
review no_op | {'name': 1.0, 'phone': 0.0, 'name_tf': 1.0} | tftoken
```

Same factors, to the digit. Both pairs are `review`, for two different reasons that only the gate shows. *Ibrahim Musa* shares no distinctive token, so nothing cleared and there is no identity claim to make. *Adesola Okonkwo* cleared the gate on the name, and the disagreeing phone kept the score below the match threshold. A reviewer looking at the second pair has a real question; a reviewer looking at the first has two men with a common name.

## The floor, and what `distinctive_max` is measured against

`distinctive_max` is the strongest agreement among the pair's distinctive comparators, priced by the table the pack uses. The floor is `0.75`, `DISTINCTIVE_FLOOR` in `arche.resolve._gate`, and it is pinned on every result as `distinctive_floor`. A pair that clears the score threshold but sits under the floor is demoted from `match` to `review`.

```python
registry = [
    {"id": "r1", "name": "Karfi Health Post", "lat": 11.60, "lon": 8.40},
    {"id": "r2", "name": "General Hospital", "lat": 12.00, "lon": 8.50},
]
survey = [
    {"id": "s1", "name": "Karfi Health Post", "lat": 11.64, "lon": 8.40},
    {"id": "s2", "name": "General Hospital", "lat": 12.04, "lon": 8.50},
]

result = arche.reconcile(registry, survey, entity="place", block=None)
for edge in result["matches"]:
    print(edge["a_id"], edge["b_id"], edge["decision"], edge["score"], edge["distinctive_max"])
print(result["pins"]["distinctive_floor"])
```

```text
r1 s1 match 0.8454 0.927
r2 s2 review 0.8454 0.564
0.75
```

Identical scores, because the two pairs agree on the same fields to the same degree. `Karfi` at `0.927` clears the floor; `general` at `0.564` does not. Nothing is discarded by the demotion: the edge is still returned, still carries its evidence, and is still there for a reviewer. Only the automatic action is withheld.

The gate governs name-like signals, where a shared token can be coincidence. It does not apply to identifiers: an agreeing `national_id` or `registration_id` is strong on its own terms and clears the gate by itself.

## People: self-calibrated unless you say otherwise

The `person` pack ships no population table by default. With no table, the population is whatever you passed in, so a comparison of two records cannot know that *Mohammed* is common, and every token in it looks maximally rare.

```python
p = [{"id": "p1", "name": "Mohammed Ibrahim"}]
q = [{"id": "p2", "name": "Mohammed Ibrahim"}]

alone = arche.reconcile(p, q, entity="person")
table = arche.reconcile(p, q, entity="person", tf="default")
for run in (alone, table):
    edge = run["matches"][0]
    print(edge["decision"], edge["distinctive_max"], "|", run["pins"]["tf"])
```

```text
match 1.0 | self-calibrated@sha256:df2ee5c0dd8a0cdd3d44c792351a2ae85bb78b3f0484511bafc604c2b02346a5
review 0.683 | shipped:person
```

Both runs are internally consistent; the first has no population to consult. A person table does ship, 50,591 tokens built from the 2010 US Census surname file and an African names lexicon, and `tf="default"` loads it. It is not wired in by default because the only benchmark so far argues against changing that: on the current data, self-calibration scores F1 `0.637` against the shipped table's `0.577`, trading precision for recall. If you are resolving people at population scale, pass `tf="default"`. If you are comparing two curated lists where every name is already known to be distinct, the self-calibrated default is defensible. Either way the run pins which one it used.

A self-calibrated table is built from the two lists, so the same pair scored in two different batches can get two different rarities and two different decisions. The digest in the pin is what makes that visible rather than silent.

## Reading the `tf` pin

Every result names the exact table that priced it.

```python
print(result["pins"]["tf"])
print(arche.reconcile(a, b, entity="organisation")["pins"]["tf"])
```

```text
shipped:place@sha256:c94f20a1c2dfba18+phrases@sha256:ed19b623d77407d3
shipped:organisation
```

| Pin | Meaning |
|---|---|
| `shipped:place@sha256:...+phrases@sha256:...` | a shipped table identified by content hash, with its phrase table |
| `shipped:organisation` | a shipped table with no version stamp |
| `self-calibrated@sha256:...` | built from the two lists in this run, identified by its content |
| `provided@sha256:...` | a table you passed as `tf=` |

Two runs that pin different `tf` values were scored against different vocabularies and are not expected to agree; comparing their decisions is a category error, not a discrepancy to investigate. The pin is hashed into `decision_id`, so a table change shows up as a changed id even when the verdict did not move.

## Refutation: a conflict is not outvoted

Agreement is weighed. Disagreement on a field declared to refute is not weighed against it; it pulls the pair to `review` on its own, however much else agrees. In the pack engine that is `refutes_below` on a comparator, and it shows in `factors` as a `_conflict` key.

```python
site = {"name": "Nyeri Hill Factory", "entity_class": "SITE", "lat": -0.42, "lon": 36.95}
operator = {"name": "Nyeri Hill Tea Factory Co Ltd", "entity_class": "OPERATOR", "lat": -0.42, "lon": 36.95}

r = arche.compare(site, operator, entity="organisation")
print(r.identity, r.action, "|", r.gate["distinctive_max"], "|", r.explanation)
print(r.factors)
r = arche.compare(site, dict(operator, entity_class="SITE"), entity="organisation")
print(r.identity, r.action, "|", r.explanation)
```

```text
review hold | 0.86 | agrees on geo, name, name_type; disagrees on distance_km, entity_class, entity_class_conflict
{'name': 0.954, 'name_tftoken': 0.795, 'name_type': 1.0, 'entity_class': 0.0, 'entity_class_conflict': 0.0, 'geo': 1.0, 'distance_km': 0.0}
same_entity merge | agrees on entity_class, geo, name, name_type; disagrees on distance_km
```

A site and the company that operates it share a name and a coordinate, so every string and spatial signal points the wrong way at once, and `distinctive_max` of `0.86` clears the floor. The one field that knows they are different parties refutes the pair. `entity_class` carries weight `0.0` in the `organisation` pack: it can never push a pair up, only hold one back. Change the class to agree and the same pair merges. Merging a plot and the party accountable for it would destroy the one link a due-diligence chain exists to establish, which is why this is a refutation and not a weight.

The `person` pack does not declare a refutation by default. A date of birth is exactly the asymmetric signal refutation was built for, and on the one labelled set it was measured on it scored slightly worse, so it is opt-in: copy the pack and set `refutes_below` on the date.

```python
import copy
from arche.resolve import ENTITY_PACKS

pack = copy.deepcopy(ENTITY_PACKS["person"])
for spec in pack:
    if spec["field"] == "birth_date":
        spec["refutes_below"] = 0.5

p1 = [{"id": "p1", "name": "Adesola Okonkwo", "birth_date": "1990-04-12", "phone": "0803 555 0111"}]
p2 = [{"id": "p2", "name": "Adesola Okonkwo", "birth_date": "1987-11-30", "phone": "0803 555 0111"}]

shipped = arche.reconcile(p1, p2, entity="person", block=None)["matches"][0]
refuting = arche.reconcile(p1, p2, comparators=pack, block=None)["matches"][0]
print(shipped["decision"], shipped["score"], shipped["evidence"])
print(refuting["decision"], refuting["score"], refuting["evidence"])
```

```text
match 0.7333 {'name': 1.0, 'name_tftoken': 1.0, 'birth_date': 0.0, 'phone': 1.0}
review 0.7333 {'name': 1.0, 'name_tftoken': 1.0, 'birth_date': 0.0, 'birth_date_conflict': 0.0, 'phone': 1.0}
```

The score is the same in both runs. Under the shipped pack the disagreeing birthday is outvoted by the name and the phone; under the refuting pack it is not, and the pair goes to a person. On the person engine that `compare` uses, the equivalent is the `id_conflict` veto: two different national identifiers make a pair `different` outright, and [The decision](the-decision.md) shows it.

## Geography supports; it does not carry

The `place` pack gives the coordinate a weight of `1.0` against `4.0` for the name, a decay of 3 km, and a veto at 10 km. So a coordinate can lift a well-evidenced pair over the line and can refute one, and it cannot carry an ordinary name across the gate by itself.

```python
karfi = {"name": "Karfi Health Post", "lat": 11.60, "lon": 8.40}
general = {"name": "General Hospital", "lat": 12.00, "lon": 8.50}

pairs = [
    ("ordinary name, 30 m apart", general, dict(general, lat=12.0002, lon=8.5001)),
    ("rare name, 4 km apart", karfi, dict(karfi, lat=11.64)),
    ("rare name, 16 km apart", karfi, dict(karfi, lon=8.55)),
]
for label, x, y in pairs:
    r = arche.compare(x, y, entity="place")
    print(f"{label:26} {r.identity:12} {r.action:6} geo={r.factors['geo']} "
          f"km={r.factors['distance_km']} conflict={'geo_conflict_km' in r.factors}")
```

```text
ordinary name, 30 m apart  review       hold   geo=0.992 km=0.02 conflict=False
rare name, 4 km apart      same_entity  merge  geo=0.227 km=4.45 conflict=False
rare name, 16 km apart     review       hold   geo=0.004 km=16.34 conflict=True
```

Two *General Hospital* records thirty metres apart are `review`: the coordinate agrees almost perfectly and the name is ordinary, and a shared location cannot auto-merge two records without a distinctive signal clearing the floor. Two *Karfi Health Post* records four kilometres apart are a merge: the name carried it and the coordinate, weak at that distance, did not stop it. Sixteen kilometres apart, the same rare name is `review`, because the veto fired: `geo_conflict_km` is in the factors and a geographic impossibility is a refutation like any other. Read `geo` as the verdict on the coordinate and `distance_km` as the measurement it was made from.

The veto was measured before it shipped. As a scored signal, geography was outvoted four to one by name and token frequency, and two facilities sharing a common Hausa name merged 143 km apart with `geo` at `0.000`. A hard constraint was the answer. On GRID3 against OpenStreetMap for Kano (685 by 1,723 records), scored against local-government-area agreement, no veto gave 497 same-area matches against 137 across an area line with 72 matches more than 10 km apart; a 10 km veto gave 495 against 67, with none.

## Names across scripts and variants

*Mamadou*, *Muhammad*, *Mohammed* and *Muhammadu* are one name written in Fulani, Arabic, English and Hausa conventions, and character similarity alone puts some of those pairs under any threshold a matcher would use. arche's name comparator reads a lexicon of naming equivalence groups, 114 of them in six files covering West African, East African, Southern African, North African, pan-Islamic and colonial-era cross-linguistic names, alongside character-level similarity, so a name written two ways scores as one name. `compare_names` is the comparator itself; it returns the similarity and the `u` probability the person engine weighs it with.

```python
from arche.resolve import compare_names

for x, y in [("Fatima Abdullahi", "Fatoumata Abdoulaye"),
             ("Mamadou Diallo", "Muhammad Jallow"),
             ("Chukwuemeka Okafor", "Emeka Okafor"),
             ("Pierre Kamga", "Peter Kamga"),
             ("Janet Okafor", "David Mensah")]:
    similarity, u = compare_names(x, y)
    print(f"{x:20} {y:20} {similarity:.3f}")
```

```text
Fatima Abdullahi     Fatoumata Abdoulaye  0.943
Mamadou Diallo       Muhammad Jallow      0.921
Chukwuemeka Okafor   Emeka Okafor         1.000
Pierre Kamga         Peter Kamga          1.000
Janet Okafor         David Mensah         0.472
```

Arabic to Mandinka and to French West African spellings, a Fulani surname spelled by country, a Yoruba and an Igbo prefix elision, a colonial-era given name, and a negative. Compare full names rather than isolated given names: *Oluwaseun* against *Seun* alone falls short, and the elision is recovered when the surrounding tokens agree, because the surname anchors the comparison. The equivalence data lives in `datasets/name_equivalences/` as YAML, one `canonical` name and its `variants` per group, and contributions are welcome.

You do not call the comparator yourself in ordinary use. It is what the `name` comparator does inside `compare` and inside the `person` pack:

```python
r = arche.compare({"name": "Fatima Abdullahi", "phone": "0803 555 0111"},
                  {"name": "Fatoumata Abdoulaye", "phone": "0803 555 0111"},
                  entity="person", jurisdiction="NG")
print(r.identity, r.action, "|", r.explanation)
```

```text
same_entity merge | phone match; name similarity 94%
```

The `place` pack deliberately does not consult the person lexicon: *Fatima Hospital* and *Fatouma Hospital* are plausibly two facilities named after two different people.

## What the gate does not do

- It does not reject the pair. `review` is a returned edge with full evidence, not a silence and not a `different`.
- It does not fire on disagreement. Conflicting values are handled by refutation and by hard constraints such as `veto_km`, independently of `distinctive_max`. When a verdict surprises you, check both: the gate value and any `_conflict` key in the evidence.
- It does not apply to identifiers. The distinctiveness gate governs name-like signals; an agreeing exact identifier clears it on its own.

## Where to read next

| You want to | Read |
|---|---|
| every field on a receipt and an edge, and what the ids hash | [The decision](the-decision.md) |
| which scorer ran, and what Splink does differently with frequency | [Backends](backends.md) |
| two records in front of you, with the verdict explained | [Compare two records](../guides/compare-two-records.md) |
| the measured effect of the gate and the veto on labelled data | [Benchmarks](../reference/benchmarks.md) |
| to bring your own frequency table or comparators | [Python API](../reference/python-api.md) |
