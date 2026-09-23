# Places and roles

At the end of this page you can parse an address into its parts, read a sentence like *pick up from X and deliver to Y* and get each place back with the role it plays and the word that decided it, and see how the `place` pack tells two records about one facility apart from two facilities that share a name. Everything here runs offline on the base install.

```python
import arche

text = ("Pick up the parcel from 7B Allen Avenue, Ikeja, Lagos and deliver to "
        "12 Adeola Odeku Street, Victoria Island.")
for m in arche.extract_places(text):
    print(m.role.ljust(12), m.text.ljust(40), "| cue:", m.cue, "| rule:", m.cue_rule, "|", m.confidence, m.evidence)
```

```text
origin       7B Allen Avenue, Ikeja, Lagos            | cue: from | rule: from_origin | 0.95 ('span:parsed', 'cue:adjacent')
destination  12 Adeola Odeku Street, Victoria Island  | cue: deliver to | rule: deliver_destination | 0.95 ('span:parsed', 'cue:adjacent')
```

Two addresses, two roles, and the cue for each. Swapping them is the one catastrophic failure a delivery has: the rider goes to the pickup with the package. So the role is never a guess. It is licensed by a word in the sentence, the word is returned, and when there is no such word the answer is `unknown`.

## Parsing an address

`parse_address` finds the first address-shaped span in a text and breaks it into components. `parse_addresses` returns every non-overlapping span, longest first, which is what the role labeller reads.

```python
from arche.addr import parse_address, parse_addresses, extract_anchor, normalize_landmark

addr = parse_address("7B Allen Avenue, Ikeja, Lagos, Nigeria")
print(addr.raw, addr.span)
print(addr.components)
print(addr.country_inferred, addr.country_confidence)

za = parse_address("Unit 5B, 22 Riebeek Street, Cape Town, 8001")
print(za.components.plot, "|", za.components.street_number, za.components.street, "|", za.components.city, za.components.postal_code, "|", za.country_inferred)
```

```text
7B Allen Avenue, Ikeja, Lagos, Nigeria (0, 38)
AddressComponents(plot=None, street_number='7B', street='Allen Avenue', anchor=None, anchor_type=None, neighborhood='Ikeja', area=None, city='Lagos', region=None, country='NG', postal_code=None)
NG 0.95
Unit 5B | 22 Riebeek Street | Cape Town 8001 | ZA
```

An `Address` is the raw substring, its `span` in the source, the `components`, the country the parser inferred with a confidence, and a `confidence` for the parse itself. The parser handles number-prefixed, plot-prefixed and unit-prefixed street addresses, P.O. boxes, four-digit South African and six-digit Nigerian postal codes, and UK postcodes. The country comes from the components: a named country, a postal code shape, or a city in the shipped gazetteer of about 104 African cities. It never defaults silently; a text with no address in it returns `None`.

The case that breaks most parsers is the one most of Africa lives at: an address with no street, anchored to a landmark.

```python
lm = parse_address("behind the Total filling station, Madina Junction, Accra")
print(lm.components.anchor, "|", lm.components.anchor_type, "|", lm.components.neighborhood, "|", lm.components.city, lm.country_inferred)
print(extract_anchor("behind the Total filling station, Madina Junction"))
print(normalize_landmark("nyuma ya Total filling station"))
print(parse_address("call me on the usual number"))
```

```text
behind the Total filling station | commercial | Madina Junction | Accra GH
('behind the Total filling station', 'commercial')
Total filling station
None
```

The anchor is a component of its own, typed as `commercial`, `religious` or `infrastructure`, because *behind the Total filling station* is not a broken street address. It is a rich place description with a landmark, a relation and an implied containment, and thousands of people can confirm it. What it lacked was a system willing to represent it. Relation words come from `addr/address_tokens.yaml` in English, Pidgin, Hausa, Yoruba, Igbo, Swahili, French and Portuguese, so *nyuma ya* normalises the same way *behind the* does. Extending the vocabulary is a data contribution, not a code change.

## A place mention, with its role

`extract_places` finds place spans in free text and labels each with a spatial role: `origin`, `destination`, `via`, `location`, or `unknown`. The academic name is spatial role labelling; `origin`, `destination` and `via` are the `source`, `goal` and `midPoint` of an ISO-Space movement link, `location` is the ground of a static relation, and `unknown` mirrors the standard's own explicit undefined value. The role is spatial and has nothing to do with the declaration-layer field roles in `arche.declare`.

Each `PlaceMention` carries the `text` and its `span`, the `cue` and its `cue_span` with the invariant that `text[cue_span] == cue`, the pack rule that fired (`cue_rule`), an ordinal `confidence`, an `evidence` tuple that says how the span was found and how the cue was attached, the parsed `address`, and a jurisdiction inferred per mention.

```python
m = arche.extract_places("The workshop is behind the central mosque, Ungwan Rimi, Kaduna")[0]
print(m.role, "|", m.text, "| cue:", m.cue, m.cue_span, "|", m.confidence, m.evidence)
```

```text
location | behind the central mosque, Ungwan Rimi, Kaduna | cue: behind (16, 22) | 0.95 ('span:parsed', 'cue:adjacent')
```

An informal address is first class. Here the cue lives inside the span, because *behind* is both the relation that anchors the landmark and the word that makes this a `location`. Pidgin, Hausa and Swahili cues (`carry am go`, `zuwa`, `kwenda`) ship in the vocabulary beside the English ones.

Confidence is a label from a nine-cell table, not a probability, and nothing in arche multiplies it. One axis is how the span was found: parsed as an address (`span:parsed`), matched in the gazetteer (`span:gazetteer`), or licensed by a cue and not otherwise verified. The other is how the cue was attached: directly adjacent (`cue:adjacent`), within a window (`cue:windowed`), or absent. Adjacent cue on a parsed span is `0.95`; a windowed cue on a gazetteer hit is `0.55`; an absent or conflicting cue forces `unknown` at the floor of `0.25` whatever the span looked like.

```python
for s in ("The consignment was picked up at and delivered to 7B Allen Avenue, Ikeja.",
          "Don't deliver to 31 Ribadu Road, Kano anymore.",
          "The invoice lists 7B Allen Avenue, Ikeja as the billing address."):
    for m in arche.extract_places(s):
        print(m.role, "|", m.text, "|", m.cue, "|", m.confidence, m.evidence)
```

```text
unknown | 7B Allen Avenue, Ikeja | delivered to | 0.25 ('span:parsed', 'cue_conflict:deliver_destination|pickup_origin')
unknown | 31 Ribadu Road, Kano | deliver to | 0.25 ('span:parsed', 'cue:negated')
unknown | 7B Allen Avenue, Ikeja | None | 0.25 ('span:parsed', 'cue:absent')
```

Three ways to abstain, each named in the evidence. Two cues of equal priority pulling in opposite directions is a conflict, and the extractor does not pick one. A negation directly before the cue cancels the role: the sentence names an address whose role it explicitly withdraws, so the cue is still reported and the role is not. A mention with no cue at all is a place the sentence does not move anything to or from. The refusal is the feature: an agent that asks has a better day than one that swaps pickup and drop-off.

The cue vocabulary is `addr/place_roles.yaml`, data rather than code, and it carries a content-hash pin so a result can name the exact vocabulary that produced it.

```python
from arche.addr import load_role_pack

pack = load_role_pack()
print(pack.pin)
print(len(pack.vocabulary()), sorted(pack.vocabulary())[:6])
print(arche.extract_places(text)[0].to_dict(reveal=False))
```

```text
arche.place_roles@v1:sha256:52ff7520cad60a44
157 ['&', 'across from', 'across the street from', 'address is', 'adjacent to', 'after']
{'role': 'origin', 'start': 24, 'end': 53, 'cue': 'from', 'cue_start': 19, 'cue_end': 23, 'cue_rule': 'from_origin', 'confidence': 0.95, 'evidence': ['span:parsed', 'cue:adjacent'], 'jurisdiction': 'NG', 'jurisdiction_confidence': 0.85, 'has_address': True, 'components_present': ['city', 'country', 'neighborhood', 'street', 'street_number']}
```

`to_dict(reveal=False)` is the shape to hand across a trust boundary: offsets, the role, the cue and rule, the confidence, and the names of the components present, never the address text or a component value. The caller already holds the text and can slice the offsets itself. `to_dict()` with no argument reveals everything, so pass `reveal=False` explicitly when the output leaves your process. `pack.vocabulary()` is the closed set of phrases a cue can be reported as, for when a caller's output has to be constrained to a fixed vocabulary.

## Grading any extractor

The durable asset is not the cue engine; it is the labelled set and the scorer, both shipped in the wheel. `load_gold` returns 54 sentences (UK and Nigerian, formal, informal and Pidgin, adversarial items whose right answer is `unknown`, and negatives). `grade_places` scores any extractor against them, and takes plain dicts as well as `PlaceMention`s, so a model's JSON grades against the identical set with no adapter.

```python
from arche.addr import grade_places, load_gold

gold = load_gold()
grade = grade_places(gold, {s.id: arche.extract_places(s.text) for s in gold})
print(len(gold), grade.span_f1, grade.cue_accuracy)
print({role: round(v["f1"], 2) for role, v in grade.per_role.items() if v.get("f1") is not None})
print(grade.abstentions)
```

```text
54 0.9922 1.0
{'origin': 0.97, 'destination': 0.98, 'location': 1.0, 'via': 1.0}
{'correct_unknown': 6, 'over_guess': 1, 'missed_by_abstention': 0}
```

The scoring is refusal-aware. Predicting `unknown` where the gold committed is a non-answer: a false negative and a `missed_by_abstention`, never a false positive. Predicting a role where the gold is `unknown` is an `over_guess` and a false positive, because that is the failure this evaluation exists to price. Empty denominators return `None`, never a fake zero. The one over-guess above is the attributive trap: *the invoice from our Lagos office* has a movement-shaped cue and no movement, the known blind spot of cue-based labelling, and it stays in the set on purpose.

This is a 54-sentence probe, not a citable benchmark: per-role intervals at this size are wide. Cross-sentence references, anaphora and roles no cue can decide are out of scope for the deterministic extractor by design; those are where it abstains, and where a model routed through `arche.llm.extract_places_llm` may earn its keep, with each proposed role kept only when its cue can be found in the source, adjacent to the span, and consistent with the pack.

## Comparing two places

A place is not a point. Coordinates for the same real facility routinely disagree, because one team measured at the gate, one at the borehole, one from a desk with a gazetteer. The name, the type and the named things that contain it drift far more slowly. The `place` pack is that observation written down as comparators.

```python
from arche.resolve import ENTITY_PACKS

for comparator in ENTITY_PACKS["place"]:
    print(comparator)
```

```text
{'field': 'name', 'kind': 'placename', 'weight': 2.0}
{'field': 'name', 'kind': 'tftoken', 'weight': 2.0}
{'field': 'name', 'kind': 'type', 'domain': 'health_facility', 'weight': 0.0}
{'kind': 'geo', 'lat': 'lat', 'lon': 'lon', 'weight': 1.0, 'decay_km': 3.0, 'veto_km': 10.0}
{'kind': 'containment', 'field': 'admin_path', 'weight': 1.0}
{'field': 'address', 'kind': 'address', 'weight': 1.0}
```

`placename` is plain string similarity after the type word is set aside, so *General Hospital* and *General Clinic* are not near-matches for sharing *General*. `tftoken` is how rare the shared words are in the pack's reference population: agreeing on *Central* is not evidence, agreeing on *Gyaranya* is. `type` reads the facility tier through a synonym vocabulary (`type_tokens.yaml`) that knows *primary health centre*, *PHC* and *health centre* are one tier and *dispensary* is another, and it scores the tier as a category at weight zero: it is there to agree or refute, not to add. `geo` is haversine distance under an exponential decay with `decay_km` of 3, so it supports and never decides on its own; `veto_km` of 10 is a hard constraint that sends a pair to `review`, never to `different`, because being too strict costs a human glance while being too loose costs a clinic its allocation. `containment` compares the named admin hierarchy when records carry one, and `address` an address when there is one.

```python
p = {"name": "Karfi Health Post", "lat": 11.9960, "lon": 8.5170}
q = {"name": "Karfi Primary Health Centre", "lat": 11.9782, "lon": 8.5093}

r = arche.compare(p, q, entity="place")
print(r.identity, r.action, "|", r.explanation)
print(r.factors)
```

```text
review hold | agrees on distance_km, name; disagrees on name_type
{'name': 0.834, 'name_tftoken': 0.505, 'name_type': 0.0, 'geo': 0.489, 'distance_km': 2.15}
```

Two rows from two Nigerian registries, and every signal arguing with the others: the names nearly agree, the tiers differ, and 2.15 km is not GPS jitter. The answer is `review`, and it is right. The facility was upgraded; the health post became a PHC, the name changed with the tier, and the two coordinates were captured years apart by different field teams. One place, two references, and the disagreement is history, not noise. No amount of extra signal in the data would have said so; a person who knew the district did.

```python
a = {"name": "Kano Central Primary Health Centre", "lat": 12.0022, "lon": 8.5920}
b = {"name": "Kano Central PHC", "lat": 12.0024, "lon": 8.5918}
r = arche.compare(a, b, entity="place")
print(r.identity, r.action, "|", r.explanation, r.factors)

g = {"name": "Fatima Hospital", "lat": 12.0, "lon": 8.5}
h = {"name": "Fatouma Hospital", "lat": 12.0, "lon": 8.5}
print(arche.compare(g, h, entity="place").factors["name"], arche.compare({"name": "Fatima Musa"}, {"name": "Fatouma Musa"}, entity="person").factors["name"])

far = arche.compare({"name": "Gyaranya Dispensary", "lat": 12.0, "lon": 8.5},
                    {"name": "Gyaranya Dispensary", "lat": 12.9, "lon": 9.6}, entity="place")
print(far.identity, far.action, "|", far.factors["geo"], far.factors["distance_km"], "|", far.explanation)
```

```text
same_entity merge | agrees on geo, name, name_type {'name': 0.894, 'name_tftoken': 0.457, 'name_type': 1.0, 'geo': 0.99, 'distance_km': 0.03}
0.922 1.0
review hold | 0.0 155.82 | agrees on distance_km, geo_conflict_km, name, name_tftoken, name_type; disagrees on geo
```

Three things the pack knows. *PHC* and *Primary Health Centre* are one tier, so the first pair agrees on the part that matters and thirty metres is the same building. *Fatima* and *Fatouma* are one person under the `person` pack's equivalence lexicon and score `1.0` there; the `place` pack never consults that lexicon, because two hospitals named after two different women are plausibly two hospitals, and the strings alone earn `0.922`. And a rare name at 155 km is not a merge: as a scored signal geo was outvoted four to one by name and rarity, and two facilities sharing a common Hausa name merged 143 km apart, which is why the veto exists. It was set at 10 km after a sweep on GRID3 against OpenStreetMap for Kano, scored on LGA agreement, where 10 km gave up 2 same-LGA matches to remove 13 cross-LGA ones and left nothing matched beyond it. Records with no coordinates are never vetoed; absent evidence refutes nothing.

[Evidence, gates and distinctiveness](evidence.md) is why a score of `1.0` can still be `review`, and [Compare two records](../guides/compare-two-records.md) has the receipt.

## From a sentence to a verified endpoint

`resolve_place_request` builds on both halves of this page. It reads the sentence with `extract_places` for the roles, then reads the relation (*behind*), the reference (*Elim Pharmacy*), the access hint (*the blue gate*) and the target address, typo-tolerantly. It turns each mention into candidates against sources you own (a `MasterSheet` of your own locations; a geocoder is opt-in beside it) and applies a declared policy: a high-confidence endpoint is `verified`, a close contest becomes one short question, weak evidence is `refused` with what was tried, and the action is blocked until every endpoint it needs is verified. Each endpoint carries a `plc:` decision id. [Resolve a delivery address](../guides/resolve-a-delivery-address.md) walks through it.

## Where to read next

| You want to | Read |
|---|---|
| a sentence to a verified endpoint, one question, or a refusal | [Resolve a delivery address](../guides/resolve-a-delivery-address.md) |
| two records and the receipt, for any pack | [Compare two records](../guides/compare-two-records.md) |
| why an identical ordinary name is `review` and what geography can carry | [Evidence, gates and distinctiveness](evidence.md) |
| two facility registers, not two records | [Resolve a batch](../guides/resolve-a-batch.md) |
| the whole Python surface | [Python API](../reference/python-api.md) |
