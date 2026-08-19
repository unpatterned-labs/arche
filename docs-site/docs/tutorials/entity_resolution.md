# Entity resolution

*Two questions, two engines, and one answer type that most matchers refuse to give. What `pairwise`, `crosswalk` and `reconcile` return, what the numbers on them mean, and why "a human must look at this" is the output worth paying for.*

---

Entity resolution is the task of deciding which records refer to the same real-world thing. *Is `Adesola Okonkwo` in the core banking file the same person as `A. Okonkwo` in last night's branch intake? Is `Karfi PHC` in the ministry's list the clinic that OpenStreetMap calls `Karfi Health Post`?*

arche answers that question two different ways, because it is really two different questions, and the two have different combination laws. That split is the first thing to internalise, because the scores from the two engines are **not comparable** and are not meant to be.

| | `resolve.pairwise` | `resolve.crosswalk` |
|---|---|---|
| Question | Are these two the same? | Link two lists at scale |
| Input | Two `Reference`s, two `Result`s, or two strings | Two lists of dicts |
| Combination law | Fellegi-Sunter log-odds | Weighted arithmetic mean |
| Gate clears when | A genuinely **rare** shared name token exists | Any distinctive-*kind* comparator reaches the floor |
| Returns | One signable `CoReferenceDecision` | Edges with `decision_id` and evidence |
| Entities | `person` only | `person`, `place`, `artist`, or your own declaration |

Both share their primitives, comparators, normalisers, the token-frequency table, and the `DISTINCTIVE_FLOOR = 0.75` constant. What they do not share is the gate policy, and that is deliberate rather than historical; [Architecture](../api/architecture.md#1-and-2-two-resolution-gates-deliberately-not-merged) has the reasoning.

## `pairwise`: one decision, signable

The narrow question. Two references in, one decision out, and the decision is a content-addressed artefact you can sign and hand to somebody who was not there.

```python
from arche.canonical import Reference
from arche.resolve import pairwise

ISSUER_KEY = b"an issuer secret of at least 32b"

web = Reference.from_record({
    "id": "web-1", "full_name": "Adesola Okonkwo",
    "national_id": "12345678901", "phone": "0803 555 7890",
})
ussd = Reference.from_record({
    "id": "ussd-9", "full_name": "A. Okonkwo",
    "phone": "+234 803 555 7890",
})

d = pairwise(web, ussd, issuer_key=ISSUER_KEY)
print("identity   :", d.identity)
print("action     :", d.action, "/", d.basis)
print("score      :", d.score)
print("factors    :", d.factors)
print("gate       :", d.gate)
print("explanation:", d.explanation)
print("decision_id:", d.decision_id)
```

```text
identity   : same_entity
action     : merge / corroborated
score      : 1.0
factors    : {'name': 0.72, 'phone': 1.0, 'name_tf': 0.3751}
gate       : {'distinctive_cleared': True, 'clearing_signal': 'phone', 'floor': 0.75}
explanation: phone match
decision_id: dec:hmac-sha256:efb0671bb4ee6ce798294819f76d5647811821168ee511ea0de65fe494886e94
```

The decision has **two axes and they answer different questions.** `identity` is the epistemic claim, `same_entity`, `review`, or `different`. `action` is the operational recommendation, `merge`, `hold`, or `no_op`. A system can be confident that two records co-refer and still recommend against merging them automatically, and separating the two is what lets the second axis be tuned per deployment without touching the first.

The record fields are canonical attribute names, not arbitrary keys. `full_name` and `name` both feed the name comparator; `national_id`, `nin`, `bvn`, `ghana_card`, `sa_id`, `kenya_id`, `passport` and a dozen more all feed the identifier comparator. Deliberately absent from that list are non-person identifiers, `rc`, `tin`, `kra_pin`, because a company registration number must never enter person-identity matching. If your fields are named something else, [declare them](../how-to/declare-your-schema.md) rather than renaming your data.

### Abstention is the product

Here is the behaviour that separates arche from a threshold.

```python
from arche.canonical import Reference
from arche.resolve import pairwise

ISSUER_KEY = b"an issuer secret of at least 32b"

a = Reference.from_record({"id": "A1", "national_id": "12345678901"})
b = Reference.from_record({"id": "B7", "national_id": "12345678901"})

d = pairwise(a, b, issuer_key=ISSUER_KEY)
print("identity :", d.identity)
print("score    :", d.score)
print("gate     :", d.gate)
print("factors  :", d.factors)
print("entity_id:", d.entity_id)
```

```text
identity : review
score    : 0.9999
gate     : {'distinctive_cleared': True, 'clearing_signal': 'national_id', 'floor': 0.75}
factors  : {'national_id': 1.0}
entity_id: ent:hmac:UCpjYO0utXP-hRPyPUaLiCyVx7j34AAZu1cGdAofOkc
```

Two records carrying the **same eleven-digit national identifier**, a score of 0.9999, the distinctive gate cleared, and the answer is still `review`. Nothing here is broken. Exactly one field applied, so exactly one thing could have gone wrong: a transcription error, a shared ID in a registry with known duplicates, a form filled in with somebody else's number. `same_entity` requires the score, the gate, *and* at least two applied fields. Add anything that corroborates, a matching phone, a name over 0.7, an exact date of birth, or a second exact identifier, and the same pair merges.

A matcher that returned `match` here would be right most of the time and catastrophically wrong the rest, and it would give you no way to tell the two apart. The review queue is not a failure mode. It is where the value is: on the [Febrl4 person benchmark](person_resolution_at_scale.md) arche holds **precision 1.0 with zero false merges** at 0.877 auto-match recall, and the hardest twelve per cent of true pairs land in review rather than being guessed.

Note that `entity_id` is populated regardless. A shared exact identifier binds the two references to the same keyed pseudonym even when the decision abstains, the binding is a fact about the identifier, the decision is a claim about the people.

## `crosswalk`: two lists, at scale

The wide question. Blocking, then comparators, then a weighted mean, then the gate, then any vetoes, and out come edges.

```python
from arche.resolve import crosswalk

# Yesterday's branch intake against the core banking file.
branch = [
    {"id": "b1", "name": "Adesola Okonkwo", "phone": "0803 555 7890"},
    {"id": "b2", "name": "Chukwuemeka Okafor", "national_id": "22156789012"},
    {"id": "b3", "name": "Ibrahim Musa", "phone": "0805 111 2222"},
]
core = [
    {"id": "c1", "name": "A. Okonkwo", "phone": "+234 803 555 7890"},
    {"id": "c2", "name": "Emeka Okafor", "national_id": "22156789012"},
    {"id": "c3", "name": "Ibrahim Musa", "phone": "0809 333 4444"},
]

result = crosswalk(branch, core, entity="person", tf="default")

print("pins:", result["pins"])
for e in result["matches"]:
    print(f"{e['a_id']:4} -> {e['b_id']:4} {e['decision']:8} "
          f"score={e['score']:.3f}  {e['evidence']}")
```

```text
pins: {'engine': 'crosswalk.v1', 'comparators_sha256': 'b412742f3b961d45', 'block': 'union', 'threshold': 0.7, 'review_margin': 0.15, 'distinctive_floor': 0.75, 'tf': 'shipped:person'}
b2   -> c2   match    score=0.816  {'name': 1.0, 'name_tftoken': 0.356, 'national_id': 1.0}
b3   -> c3   match    score=0.727  {'name': 1.0, 'name_tftoken': 1.0, 'phone': 0.0}
b1   -> c1   review   score=0.671  {'name': 0.72, 'name_tftoken': 0.375, 'phone': 1.0}
```

Three things in that output repay reading. `Chukwuemeka Okafor` and `Emeka Okafor` score `name: 1.0` because the name lexicon knows Igbo prefix-elision, not because the strings resemble each other. `A. Okonkwo` lands in `review` despite an exact normalised phone match, because an initial plus a surname is not enough name evidence to release a merge on its own. And the `pins` dict is the reproducibility contract: the comparator hash, the thresholds, and where the frequency table came from all enter every edge's `decision_id`.

`tf="default"` loads the population-scale person name table shipped with arche, 50,591 tokens over 1,903,937 counts. Leave it out and `crosswalk` self-calibrates a table over the two lists you passed, which is the right default for a large reconciliation and actively misleading on a small one. In a three-row corpus every token is rare, including `Ibrahim`.

### The same pair, two engines, two answers

Look again at `b3 -> c3`: two records both named `Ibrahim Musa`, with **different phone numbers**, matched at 0.727. Now put that exact pair through `pairwise`.

```python
from arche.canonical import Reference
from arche.resolve import crosswalk, pairwise

ISSUER_KEY = b"an issuer secret of at least 32b"

a = {"id": "b3", "name": "Ibrahim Musa", "phone": "0805 111 2222"}
b = {"id": "c3", "name": "Ibrahim Musa", "phone": "0809 333 4444"}

edge = crosswalk([a], [b], entity="person", tf="default")["matches"][0]
print("crosswalk:", edge["decision"], round(edge["score"], 3), edge["evidence"])

ra = Reference.from_record({"id": "b3", "full_name": "Ibrahim Musa",
                            "phone": "0805 111 2222"})
rb = Reference.from_record({"id": "c3", "full_name": "Ibrahim Musa",
                            "phone": "0809 333 4444"})
d = pairwise(ra, rb, issuer_key=ISSUER_KEY)
print("pairwise :", d.identity, d.score, d.factors)
print("gate     :", d.gate)
```

```text
crosswalk: match 0.727 {'name': 1.0, 'name_tftoken': 1.0, 'phone': 0.0}
pairwise : review 0.8214 {'name': 1.0, 'phone': 0.0, 'name_tf': 1.0}
gate     : {'distinctive_cleared': False, 'clearing_signal': None, 'floor': 0.75}
```

Same two records, different verdicts, and the reason is written into the gate rather than hidden in a threshold. `crosswalk` clears its gate on any distinctive-kind comparator reaching the floor, and an identical name string does that. `pairwise` additionally requires the *shared token itself* to be rare in the population, and `ibrahim` sits at 0.5709 distinctiveness in the shipped table, nowhere near the 0.75 floor. So the pairwise gate stays shut and the pair goes to a human.

Neither is wrong. They are calibrated for different jobs: a list reconciliation that surfaces everything for review is unusable at 40,000 candidate pairs, and a signable claim about two named individuals must not rest on a common name. Choose the engine that matches the decision you are actually making, and do not compare the two scores.

## Places, and the constraint that can refuse

`crosswalk(..., entity="place")` swaps the comparator pack, and the place pack contains something the person pack does not: a **veto**. Distance is not a weighted signal there, it is a constraint.

```python
import csv
from collections import Counter

from arche.resolve import crosswalk

with open("data/GRID3_NGA_health_facilities_v2.csv", encoding="utf-8-sig") as fh:
    grid3 = [r for r in csv.DictReader(fh) if r["state"] == "Kano"]
with open("data/osm_kano.csv", encoding="utf-8-sig") as fh:
    osm = [r for r in csv.DictReader(fh) if r["name"].strip()]

A = [{"name": r["name"], "lat": r["lat"], "lon": r["lon"]} for r in osm]
B = [{"name": r["facility_name"], "lat": r["latitude"], "lon": r["longitude"]}
     for r in grid3]

result = crosswalk(A, B, entity="place")
print(Counter(e["decision"] for e in result["matches"]))
print("blocking:", result["blocking"])

vetoed = [e for e in result["matches"] if "geo_conflict_km" in e["evidence"]]
worst = max(vetoed, key=lambda e: e["score"])
print("names   :", A[worst["a_id"]]["name"], "<>", B[worst["b_id"]]["name"])
print("score   :", round(worst["score"], 3), "-> decision:", worst["decision"])
print("evidence:", worst["evidence"])
```

```text
Counter({'match': 564, 'review': 529})
blocking: {'candidate_pairs': 39701, 'reduction_ratio': 0.9664, 'strategies': {'h3': 37369, 'token': 2332, 'id': 0, 'coordless_a': 0, 'coordless_b': 0}}
names   : Kauyen Adam Health Post <> Kauyen Adam Health Post
score   : 0.805 -> decision: review
evidence: {'name': 1.0, 'name_tftoken': 1.0, 'name_type': 1.0, 'geo': 0.025, 'distance_km': 11.06, 'geo_conflict_km': 11.06}
```

Two byte-identical names, every name comparator at 1.0, a score of 0.805 comfortably over the 0.7 threshold, and the edge still lands in `review`, carrying the distance that put it there. Before v0.3.0a1 geography was scored at weight 1.0 against name and token-frequency's combined 4.0, so it could be outvoted, and it was: two Kano facilities sharing a common Hausa name merged 143 km apart while the geo comparator itself scored 0.000. No weight could produce the outcome above; only a constraint could.

Two properties of `veto_km: 10.0` are deliberate. It demotes to `review` and **never** to `no_match`, because distance says a human must look rather than that the answer is no. And records without usable coordinates are never vetoed, because you cannot refute a claim on evidence you do not have.

The threshold was set by a sweep against Local Government Area agreement, which moves from 78.4% to 88.1% between no veto and 10 km. [The place benchmark](../about/place-benchmark.md) reproduces that sweep and, this matters more than the number, shows why it is a **consistency check rather than validation**: OpenStreetMap's Kano health facilities share lineage with GRID3, with 59% of matched pairs sitting at exactly 0.00 km apart. No two independent surveys produce that. Do not cite 88.1% as accuracy, and read that page before choosing a validation source of your own.

## `reconcile`: the engine underneath

`crosswalk` is a convenience layer over `reconcile`, which takes explicit comparator specs and no entity pack. Reach for it when your schema is your own and you want to state the comparison rather than inherit it.

```python
from arche.resolve import TokenFrequencyTable, reconcile

specs = [
    {"field": "name", "kind": "name", "weight": 2.0},
    {"field": "name", "kind": "tftoken", "weight": 2.0},
    {"field": "national_id", "kind": "id", "weight": 3.0},
]

branch = [{"id": "b2", "name": "Chukwuemeka Okafor",
           "national_id": "22156789012"}]
core = [{"id": "c2", "name": "Emeka Okafor", "national_id": "22156789012"}]

result = reconcile(branch, core, specs, tf=TokenFrequencyTable.default(),
                   threshold=0.7)
for e in result["matches"]:
    print(e["decision"], round(e["score"], 3), e["evidence"])
```

```text
match 0.816 {'name': 1.0, 'name_tftoken': 0.356, 'national_id': 1.0}
```

`reconcile` will not guess a frequency table for you. Omit `tf=` with a `tftoken` comparator in the specs and it refuses rather than silently self-calibrating:

```text
ValueError: comparator kind 'tftoken' requires a TokenFrequencyTable passed as tf=;
build one with TokenFrequencyTable.from_corpus(...) or pass tf="default"
```

The comparator kinds are `name`, `placename`, `tftoken`, `id`, `phone`, `email`, `address`, `date`, `geo`, `type` and `containment`. A comparator that has nothing to say about a pair, a missing field on either side, no type token recognised, returns nothing and is dropped from the weighted mean rather than scored as a disagreement. `ENTITY_PACKS` holds the shipped packs for `person`, `place` and `artist`, and a pack is configuration over this same engine, never a fork of it.

## Signing an edge

Every crosswalk edge already carries a `decision_id` hashed over its evidence and the run's pins. `sign_edges` wraps that claim in a JWS.

```python
from arche.resolve import crosswalk
from arche.resolve.reconcile import sign_edges
from arche.sign import generate_keypair
from arche.sign.jws import verify

branch = [{"id": "b2", "name": "Chukwuemeka Okafor",
           "national_id": "22156789012"}]
core = [{"id": "c2", "name": "Emeka Okafor", "national_id": "22156789012"}]

result = crosswalk(branch, core, entity="person", tf="default")
key = generate_keypair()
signed = sign_edges(result, private_key=key.private_key, kid=key.did_key)

print("signed edges:", len(signed))
print("decision_id :", signed[0]["decision_id"])
res = verify(signed[0]["jws"], public_key=key.public_key)
print("valid:", res.valid, "| trusted:", res.trusted,
      "| key_source:", res.key_source)
print("payload keys:", sorted(res.payload))
```

```text
signed edges: 1
decision_id : xwd:sha256:ba8d2fafef445a4a3e8349617cf576ac923fd7511bcd21e1c570beba0379fd27
valid: True | trusted: True | key_source: pinned
payload keys: ['a_id', 'b_id', 'decision', 'decision_id', 'distinctive_max', 'evidence', 'pins', 'schema', 'score']
```

Edges carry ids and numeric evidence only, never raw values, so a signed edge is exactly as shareable as the crosswalk output it came from. Pass `public_key=` as above: without it `verify` reports `valid=True, trusted=False`, which is an integrity check and not an authentication. [Attest](../how-to/attest.md#valid-is-not-trusted) explains why that distinction is load-bearing.

## The v0.2 surface, and where Splink actually sits

`arche.resolve` still re-exports the older classical resolver, `resolve_entities`, `resolve_identity_records`, `ResolvedEntity`, so v0.2 code keeps working. It takes a flat list of extracted `Entity` objects and returns merged `ResolvedEntity` clusters. It is not the shipped surface, it is not signable, and it does not share the gate.

It is also the **only** thing in arche that touches Splink. `resolve_entities(entities, use_splink=True)` with at least ten entities and the `arche-core[resolve]` extra installed hands the work to a Splink + DuckDB linker; below ten, or without the extra, it falls back to rapidfuzz and union-find. Nothing else imports it. With splink 4.0.16 installed, `pairwise`, `crosswalk`, `reconcile`, `coref_references`, `TokenFrequencyTable` and the name lexicon all load **zero** splink modules; the legacy call loads eighty-four. If you read anywhere that arche's resolution engine is built on Splink, that is a description of this one legacy function. [Why arche, and when to use it](arche_vs_alternatives.md#the-splink-question-answered-plainly) has the measurement and what the honest relationship actually is.

## What this surface does not do

Stated so nobody plans around it.

- **`pairwise(entity="place")` raises.** `NotImplementedError: pairwise entity='place' is not available yet; person only. Use crosswalk(...) for place lists.` Signable decisions are person-shaped today.
- **No clustering or transitive closure.** `crosswalk` returns pairwise edges. Collective resolution, resolving A↔B and B↔C into one entity, with the contradictions that implies, is the open remainder and is post-beta.
- **No incremental or streaming resolution.** Both engines take their inputs whole.
- **No persistence.** Edges and decisions are Python objects and dicts; storing them is yours. `arche.graph.audit` is a separate SQLite log of detections, not a resolution store.
- **`orthography=` is not wired into `crosswalk`.** The Hausa pack is opt-in on `shared_name_distinctiveness` and `TokenFrequencyTable.weighted_token_sim` only, and the place pack does not set it.

## What's next

- Person resolution at scale, the same engine on Febrl4, scored against ground truth
- [Place resolution at scale](place_resolution_at_scale.md): the Nigerian facility crosswalk end to end
- [Read the crosswalk output](../how-to/read-crosswalk-output.md): every field on an edge, and what to do with it
- Declare your schema, when your field names are not arche's
- Architecture, which component is permitted to conclude anything
