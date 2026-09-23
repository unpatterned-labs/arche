# The decision

Every verb in arche hands back a decision with the same bones: a verdict, the evidence it rests on, the settings it was made under, and an id that anyone holding the same inputs can recompute. At the end of this page you can read every field on a `compare` receipt and a batch edge, know why the verdict comes in two fields, know what a `score` is and is not, and know what each id prefix hashes over.

```python
import arche
from pprint import pprint

a = {"name": "Adesola Okonkwo", "national_id": "12345678901", "email": "adesola@example.com"}
b = {"name": "Adesola E. Okonkwo", "national_id": "12345678901", "address": "124 Maple Street"}

r = arche.compare(a, b, entity="person", jurisdiction="NG")
pprint({k: v for k, v in vars(r).items() if k not in ("reference_a", "reference_b")}, width=100)
```

```text
{'action': 'merge',
 'basis': 'corroborated',
 'decision_id': 'dec:sha256:0e34aa91db0699c3f763655fe1e48c5ca6861ef28addc190957e3795fda6a92f',
 'entity_id': None,
 'explanation': 'national ID match; name similarity 80%',
 'factors': {'name': 0.8, 'name_tf': 0.7233, 'national_id': 1.0},
 'field_weights': {'name': {'bits': 3.6959, 'm': 0.92, 'sim': 0.8, 'u': 0.02},
                   'national_id': {'bits': 13.2863, 'm': 0.999, 'sim': 1.0, 'u': 1e-06}},
 'gate': {'clearing_signal': 'national_id', 'distinctive_cleared': True, 'floor': 0.75},
 'identity': 'same_entity',
 'jurisdiction': 'NG',
 'pins': {'comparator_lib': 'jellyfish@unknown',
          'engine': 'arche-core@0.9.0',
          'jurisdiction': 'NG',
          'receipt_schema': 1,
          'tf': 'default',
          'thresholds': {'distinctive_floor': 0.75, 'match': 0.85, 'review': 0.4}},
 'reference_id_a': 'ref:sha256:ead8f7d6a8b008b5faeb994d4d71bdfbaa538d2b6699d3e626ead2f9e1baf838',
 'reference_id_b': 'ref:sha256:e7b083811d74bbdbc2edd1aa8f495cd178d9874a096b0e0da3102d9a34e9bf88',
 'score': 1.0,
 'vetoes': {'id_conflict': False}}
```

That is a `Receipt`, the object every `compare` returns. The two reference objects are left out of the print because they carry the raw values; everything else is on the page below, field by field.

| Field | What it is |
|---|---|
| `identity` | What arche believes: `same_entity`, `review` or `different`. |
| `action` | What it recommends: `merge`, `hold` or `no_op`. |
| `basis` | The shape of the evidence the action rests on. |
| `score` | A ranking signal in `[0, 1]`. Not a probability. |
| `factors` | One number per field that was compared, in `[0, 1]`. |
| `field_weights` | On the person engine, the `m`, `u` and log-odds `bits` behind each factor. Empty on the pack engine. |
| `explanation` | One sentence a reviewer can read without knowing the engine. |
| `gate` | What decided: which distinctive signal cleared the floor, or that none did. |
| `vetoes` | Hard conflicts that override the score. |
| `reference_id_a`, `reference_id_b` | Content ids of the two records as arche read them. |
| `decision_id` | The reproducible address of this decision. |
| `entity_id` | A keyed pseudonym, present only with an `issuer_key` and a shared exact identifier. `None` here. |
| `reference_a`, `reference_b` | The two records as `Reference` objects, kept for rendering and never hashed. |
| `jurisdiction` | The priors and thresholds the person engine used. `default` on the pack engine. |
| `pins` | Everything the decision depends on besides the two records. |

## Two fields, on purpose

`identity` is the epistemic claim: given this evidence, are these one thing? `action` is the operational recommendation: what should a system do about it without asking anyone? Most of the time they agree, and the time they do not is the most useful thing on the receipt.

```python
c = {"name": "Ibrahim Musa", "phone": "0803 555 0111"}
d = {"name": "Ibrahim Musa", "phone": "0805 222 9999"}

for x, y in ((a, b), (c, d)):
    r = arche.compare(x, y, entity="person", jurisdiction="NG")
    print(r.identity, r.action, "|", r.factors["name_tf"], r.gate["clearing_signal"])
```

```text
same_entity merge | 0.7233 national_id
review no_op | 1.0 None
```

`same_entity` with `merge` is the ordinary case: the belief is held and nothing stops acting on it. `same_entity` with `hold` is the case worth the second field: a shared national id is distinctive enough to clear the gate alone, but with nothing else agreeing, `basis` is `single_identifier` and the recommendation is to wait. A system can link the two records on the belief and still route the pair to a person on the recommendation. [Compare two records](../guides/compare-two-records.md) shows that pair.

`review` means the evidence does not support a claim either way. On the person engine it comes with `no_op`; on the pack engine, which every entity other than `person` runs on, it comes with `hold`. Both mean the same thing to automation: stop here, a person decides. `different` always comes with `no_op`.

`basis` is `corroborated` when a second field backs the clearing signal, `single_identifier` when nothing does, and empty when there is no `same_entity` claim to base an action on. On the pack engine it names the pack, `pack:organisation`, with a note when the pair was never surfaced.

## What `score` is and is not

`score` orders pairs. It does not say how likely two records are to be the same thing, and two pairs can share a score and deserve different verdicts, as the batch example below shows. Two things follow. Do not threshold on it in your own code; the verdict already did that with more information than the score carries. And do not compare scores across engines: the person engine computes a Fellegi-Sunter log-odds sum from fixed per-jurisdiction `m` and `u` priors and squashes it into `[0, 1]`, while the pack engine takes a weighted mean of the per-field similarities. `0.8` from one does not mean what `0.8` from the other means, which is why `pins["engine"]` is on every receipt.

## `factors`, `gate` and `vetoes`

`factors` is one similarity per field the engine compared, in `[0, 1]`. A field only one record carries is absent, not zero. `name_tf` on the person engine is the rarity-weighted token overlap of the two names: identical names score `1.0` whether the name is rare or ordinary, which is why it cannot be read as "how common is this name" on its own.

`gate` is what decided, and it is the field to read when a verdict surprises you. The person engine reports `distinctive_cleared` and the `clearing_signal` that did it: an exact identifier, or `tftoken` when the names share a token that is itself distinctive, or `dob+name`. In the `Ibrahim Musa` pair above `name_tf` is `1.0` and the gate still did not clear, because the shared tokens are ordinary. The pack engine reports `distinctive_max`, the strongest distinctive agreement in the pair, against `distinctive_floor`, and a pair whose `distinctive_max` sits under the floor is `review` however high its score. [Evidence, gates and distinctiveness](evidence.md) is the whole story.

`vetoes` are hard conflicts. The person engine has one, `id_conflict`: two different values for the same national identifier make the pair `different` regardless of everything else.

```python
e = {"name": "Chukwuemeka Okafor", "national_id": "12345678901"}
f = {"name": "Emeka Okafor", "national_id": "99999999999"}

r = arche.compare(e, f, entity="person", jurisdiction="NG")
print(r.identity, r.action, "|", r.score, r.vetoes)
```

```text
different no_op | 0.044 {'id_conflict': True}
```

On the pack engine `vetoes` is empty. Its hard constraints (a `veto_km` on a geo comparator, a `refutes_below` on any comparator) show up as a `_conflict` key in `factors` and pull the verdict to `review`. A refutation is not outvoted by agreement elsewhere.

## The batch edge

`reconcile` answers the batch question and returns a batch result: `matches`, `count`, `pins`, `blocking` and `backend`. Each entry in `matches` is an edge, and an edge has one verdict field, `decision`, with two values.

```python
registry = [
    {"id": "r1", "name": "Gyaranya Health Post", "lat": 11.90, "lon": 8.50},
    {"id": "r2", "name": "General Hospital", "lat": 12.00, "lon": 8.50},
]
survey = [
    {"id": "s1", "name": "Gyaranya Health Post", "lat": 11.94, "lon": 8.50},
    {"id": "s2", "name": "General Hospital", "lat": 12.04, "lon": 8.50},
    {"id": "s3", "name": "Zenith Bank Plc", "lat": 6.45, "lon": 3.40},
]

result = arche.reconcile(registry, survey, entity="place", block=None)
print(sorted(result))
for edge in result["matches"]:
    pprint(edge, width=100)
print(result["count"], "of", len(registry) * len(survey), "pairs returned")
```

```text
['backend', 'blocking', 'count', 'matches', 'pins']
{'a_id': 'r1',
 'b_id': 's1',
 'decision': 'match',
 'decision_id': 'xwd:sha256:1d6e3c78e08679811fb5fb0e77781132780bbc8767306b9f1ec57a81aa0ea0aa',
 'distinctive_max': 0.86,
 'evidence': {'distance_km': 4.45,
              'geo': 0.227,
              'name': 1.0,
              'name_tftoken': 1.0,
              'name_type': 1.0},
 'score': 0.8454}
{'a_id': 'r2',
 'b_id': 's2',
 'decision': 'review',
 'decision_id': 'xwd:sha256:15018732c700ced588a40353045ae2dcb3e61ef7b81d9cea3782fe445b3a3b3d',
 'distinctive_max': 0.564,
 'evidence': {'distance_km': 4.45,
              'geo': 0.227,
              'name': 1.0,
              'name_tftoken': 1.0,
              'name_type': 1.0},
 'score': 0.8454}
2 of 6 pairs returned
```

| Field | What it is |
|---|---|
| `a_id`, `b_id` | The `id` of each record, or the column named by `id_field=`. |
| `decision` | `match`: cleared the threshold and every gate, eligible for whatever automatic action your workflow has agreed. `review`: surfaced, but a gate or a conflict withheld the automatic action. |
| `score` | The weighted mean of `evidence`. The two edges above share it exactly and get different verdicts. |
| `evidence` | The per-field similarities, the same thing `factors` is on a receipt, plus measurements such as `distance_km` and any `_conflict` keys. |
| `distinctive_max` | The gate value. `0.86` clears the floor of `0.75`; `0.564` does not, because *General* and *Hospital* are the two most ordinary words a facility name can carry. |
| `decision_id` | The edge's reproducible address. |

The same pins apply to every edge in the result, so they sit once at `result["pins"]` rather than on each edge. `result["backend"]` says which scorer ran and why; [Backends](backends.md) covers it.

Four of the six pairs are not there at all. A pair below the surfacing floor (`threshold - review_margin`, `0.55` by default) is simply not returned, and its absence is not a claim that the two records differ. The engine has said nothing about `r2` and `s3`; it has not said they are different things. A batch result has no `different` label, and a consuming system must not invent one from silence.

Do not translate between the two vocabularies. `match` on an edge and `same_entity` on a receipt come from the same engine and the same gate when the pack is the same, but a receipt also carries an `action`, and an edge does not. Keep the edge's `decision`, `evidence`, `decision_id` and the run's `pins` together in whatever you write downstream.

## When `compare` says `different`, and when it says nothing

On the pack engine, `compare` runs the pair as a batch of one with blocking off. A pair that reaches the surfacing floor comes back with the edge's verdict and the edge's own id. A pair that does not is a real answer, `different`, because the engine compared what it was given and nothing reached the floor.

```python
r = arche.compare({"name": "Karfi Agro Cooperative Ltd"}, {"name": "Zenith Bank Plc"}, entity="organisation")
print(r.identity, r.action, "|", r.basis, "|", r.gate)
print(r.decision_id[:16])
```

```text
different no_op | pack:organisation (below surfacing floor) | {'surfacing_floor': 0.55, 'surfaced': False, 'comparable_fields': ['name']}
dec:sha256:76293
```

There is a second silence that is not an answer. If neither record carries any field the pack reads, nothing was compared, and reporting that as `different` at score `0.0` would be a false claim. arche returns `review` instead and says why.

```python
r = arche.compare({"supplier": "Karfi Agro"}, {"supplier": "Karfi Agro"}, entity="organisation")
print(r.identity, r.action, "|", r.basis)
print(r.explanation)
```

```text
review hold | pack:organisation (no comparable fields)
neither record carries a field the organisation pack compares; nothing was compared, so this is not an answer either way (see arche.describe('organisation') for the fields it reads)
```

`gate["comparable_fields"]` is the list to check: it names the pack fields both records actually carried a value for. Empty means the fix is a column name, and [Extract to your schema](../guides/extract-to-your-schema.md) is how to declare yours.

## The id prefixes

Every decision id is `prefix:alg:hex`, a SHA-256 over the canonical JSON of what the decision depended on. Floats are rendered to four decimals before hashing so the id does not move with float representation, and there is no timestamp in it. Run the same call again and the same id comes back. The prefix says which verb issued it and therefore what was hashed.

```python
person = arche.compare(a, b, entity="person", jurisdiction="NG")
org = arche.compare({"name": "Touton Negoce SARL"}, {"name": "Touton Negoce"}, entity="organisation")
copy = arche.deidentify("Casey Example, NIN 12345678901.", jurisdiction="NG", backend="basic")

from arche.addr.request import MasterSheet
sheet = MasterSheet([{"id": "loc-1", "name": "123 Maple Street",
                      "address": "123 Maple Street, Ikeja", "lat": 6.60, "lon": 3.35}])
place = arche.resolve_place_request("Collect from 123 Maple Street.",
                                    action="create_delivery", sources=[sheet])

for label, the_id in [("compare, person", person.decision_id),
                      ("compare, any other pack", org.decision_id),
                      ("reconcile edge", result["matches"][0]["decision_id"]),
                      ("deidentify", copy.decision_id),
                      ("resolve_place_request", place.origin.decision_id)]:
    print(f"{label:24} {the_id[:24]}")
```

```text
compare, person          dec:sha256:0e34aa91db069
compare, any other pack  xwd:sha256:c63b43fa09585
reconcile edge           xwd:sha256:1d6e3c78e0867
deidentify               red:sha256:f8cdd9cfe01d2
resolve_place_request    plc:sha256:ac2ea94ee5932
```

| Prefix | Issued by | Hashes over |
|---|---|---|
| `dec:` | `compare` on the person engine, and `compare` on a pack when no edge was surfaced | the two `reference_id`s, `identity`, `factors`, `gate`, `vetoes`, `jurisdiction`, `pins` |
| `xwd:` | every edge in a batch result, and `compare` on a pack when the pair surfaced, because the receipt quotes the engine's own edge id rather than minting a second address for one decision | the edge (`a_id`, `b_id`, `score`, `decision`, `evidence`, `distinctive_max`) and the run's `pins`, under the schema name `arche.crosswalk_edge.v1` |
| `red:` | `deidentify`, on a `Deidentified` | the document hash, every span with its category, offsets, confidence, action and citation, and the pins (engine, backend, model, detectors, statute and version, jurisdiction, method). Never the text. |
| `plc:` | `resolve_place_request`, on each `Endpoint` | the mention as read (without its character span), every candidate with its id, confidence, evidence and source, the policy, the status, the question kind, and the pins |
| `ref:` | `Reference.from_record`, on `reference_id_a` and `reference_id_b` | the record's normalised attributes and its source system |

`alg` is `sha256` when no key was supplied. Pass `issuer_key=` to `compare` and the `ref:` and `dec:` ids become `hmac-sha256`, keyed to you: reproducible by the key holder and not brute-forceable back to an eleven-digit national id by anyone else. A keyless id over personal data is pseudonymous personal data, not anonymous.

## `reference_a` and `reference_b`

The two records as arche read them, after declaration mapping and normalisation, as `Reference` objects. They are on the receipt so a review screen can render the pair, and they are deliberately not in the hash: `decision_id` covers only the two `reference_id` strings.

```python
print(person.reference_id_a[:24], person.reference_id_b[:24])
print(person.reference_a)
print([attr.name for attr in person.reference_a.attributes])
```

```text
ref:sha256:ead8f7d6a8b00 ref:sha256:e7b083811d74b
Reference(id='', attributes=3, identity_attrs=2, source='')
['name', 'national_id', 'email']
```

The `repr` is value-free on purpose. The attribute values are there for code that needs them; nothing prints them by accident.

## `pins`, and when the engine pin moves

`pins` is everything the decision depended on that is not the two records: which engine, which comparator set, which frequency table, which thresholds. It is inside the hash, so a decision made under different settings is a different decision with a different id, even when the verdict is the same.

```python
again = arche.compare(a, b, entity="person", jurisdiction="NG")
print(again.decision_id == person.decision_id)
pprint(person.pins, width=100)
```

```text
True
{'comparator_lib': 'jellyfish@unknown',
 'engine': 'arche-core@0.9.0',
 'jurisdiction': 'NG',
 'receipt_schema': 1,
 'tf': 'default',
 'thresholds': {'distinctive_floor': 0.75, 'match': 0.85, 'review': 0.4}}
```

The person engine pins the package version, the string-similarity library, the jurisdiction whose priors it used, the thresholds, and `receipt_schema`, the version of the field vocabulary itself. A batch result pins differently:

```python
pprint(result["pins"], width=100)
```

```text
{'block': 'none',
 'comparators_sha256': '48e646d6895e9d1fb4d36c9f10925866574a374a5979529b2fde25829c418f1b',
 'distinctive_floor': 0.75,
 'engine': 'crosswalk.v1',
 'review_margin': 0.15,
 'tf': 'shipped:place@sha256:c94f20a1c2dfba18+phrases@sha256:ed19b623d77407d3',
 'threshold': 0.7}
```

`engine: crosswalk.v1` names the shape of the decision: how comparator similarities combine into `score`, what `evidence` contains, how the gate reaches a verdict, and which values `decision` can take. It deliberately does not cover the inputs to that shape, because those change independently and far more often, and each has its own pin.

| What changed | Which pin moves |
|---|---|
| a comparator added, removed or reweighted | `comparators_sha256` |
| a different blocking strategy | `block` |
| a threshold, margin or floor | the field itself |
| a frequency table rebuilt | `tf` |
| the scoring formula, the gate, a new verdict value, or a field in `evidence` changing meaning | `engine` |

The rule: `engine` bumps to `crosswalk.v2` when the same inputs would produce a different decision, or when a field on the edge means something new. A bug fix that makes the code match what the version already claimed is not a bump. A change to which pairs are offered is not a bump either, though it does change every `decision_id`, because `block` is hashed: same verdict, same score, different id, and that is correct, since the id addresses the decision as configured.

A bump has a cost. Ids issued under the old version stay valid, and anyone holding the old edge and the old pins recomputes the same id forever. They stop being reproducible by running the current code. Both halves are true at once, so a bump requires a changelog entry saying which decisions move and a note that old ids cannot be regenerated.

One gap to know about: `backend="splink"` does not pin `engine: crosswalk.v1`. It pins `crosswalk.splink.v1` with the trained model, the corpus, the blocking and the library versions, because a trained scorer is a function of the data it saw. Two engines, two provenance vocabularies, and no single field to compare across them. [Backends](backends.md) has the detail.

## Rules for anything downstream

1. Act automatically only on a `match` edge or a `same_entity` receipt whose `action` is `merge`, and only where your workflow has agreed that action in advance.
2. Treat `review` as a stop, never as a soft match. A consuming system must not promote it on its own.
3. Keep `evidence` (or `factors`), `decision_id` and `pins` together with whatever you did about the decision.
4. Do not read `score` as a probability, and do not compare it across engines.
5. Do not turn pairwise edges into entities unless your workflow has defined transitivity, conflict handling and review. [Keep, explain, replay](../guides/keep-and-replay.md) is arche's own answer to that.

## Where to read next

| You want to | Read |
|---|---|
| why identical strings can be `review`, and what a refutation does | [Evidence, gates and distinctiveness](evidence.md) |
| which scorer ran, and what changes when it is Splink | [Backends](backends.md) |
| to keep a receipt, explain it later, and replay it | [Keep, explain, replay](../guides/keep-and-replay.md) |
| a signed decision someone else can verify | [Attested answers](attestation.md) |
| every argument and return type | [Python API](../reference/python-api.md) |
