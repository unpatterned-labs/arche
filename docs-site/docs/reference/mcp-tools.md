# MCP tools

Every tool `arche mcp` registers: its arguments with their types, what it returns, and what it never returns. At the end of this page you can read an agent's transcript and know what each call could and could not have told it. [Let an agent call arche](../guides/mcp-server.md) is the walkthrough; this page is the contract.

Every example below calls the tool's handler directly in Python, which is the same function the server registers, minus the environment. The handlers take the environment's values as arguments (`key`, `statute`, `allowed_providers`, `transfer_basis`, `ledger`), so a page can show a refusal without setting a variable.

```python
from arche.mcp import handlers

caps = handlers.capabilities()
print(caps["entity_packs"])
print(caps["jurisdictions_inferable"])
print(sorted(caps["extras"]))
```

```text
['artist', 'organisation', 'organization', 'person', 'place', 'product_electronics', 'product_grocery', 'product_home_goods']
['DE', 'EU', 'GB', 'KE', 'NG', 'US', 'ZA']
['detect', 'doc', 'splink']
```

| Tool | Arguments | Returns | Never returns |
|---|---|---|---|
| `capabilities` | | statutes, inferable jurisdictions, entity packs, installed extras, signer, ledger tools | |
| `infer_jurisdiction` | `text` | `country`, `confidence`, `margin`, `abstained`, `evidence`, `statute_id`, `policy_available` | the matched text behind a signal |
| `plan_protection` | `jurisdiction?`, `statute?` | `verdict`, `governed`, `covered`, `uncovered`, `degraded_categories` | |
| `describe_pack` | `entity` | the fields a pack reads, each with kinds, weight and notes | |
| `detect_pii` | `text`, `jurisdiction?` | spans as offsets, category, confidence, citation, tier; `coverage` | the value of a span |
| `detect_entities` | `text`, `entity_types?` | typed offset spans; `ner_backend_installed` | the entity text |
| `guarded_scan` | `text`, `jurisdiction?`, `provider?`, `crosses_border?` | `denied` with a reason, or `redacted_text`, `fields` with hashed tokens, `coverage` | a raw value; offsets into the original |
| `compare_records` | `list_a`, `list_b`, `entity?`, `comparators?`, `backend?`, `threshold?`, `id_field?` | `matches` with ids, score, decision, evidence, `decision_id`; `pins`, `blocking`, `backend` | record values |
| `why_unresolved` | `record_a`, `record_b`, `entity?` | `decision`, `why`, `fields_present`, `would_resolve`, `will_not_help` | a promise of `no_match` |
| `check_name_equivalence` | `name_a`, `name_b` | `decision`, `score`, `bands` | |
| `extract_places` | `text` | roles, offsets, cues, confidence, component names; `pack` | the address text or components |
| `decision` | `decision_id` | the receipt, its pins, the two records by label and field names, `entity_id` | record values |
| `explain` | `decision_id` | `supporting`, `refuting`, `missing`, `shared` (names) | values |
| `replay` | `decision_id` | `reproduced`, `then`, `now`, `changed` | values |
| `entities` | `entity_type?` | entities with records by label, shared and conflicting field names, `held_together_by`, `weak_links` | values |
| `path` | `record_a`, `record_b` | `same_entity`, `hops`, the decisions between, `note` | values |
| `cases` | `entity_type?` | pairs at `review` with `would_resolve` | values |
| `resolve` | `record`, `entity_type` | `verdict`, the entity, `candidates`, `entity_evidence`, `would_resolve`, new decisions | values out of the ledger |
| `observe` | `record_id`, `evidence` | field names, the superseding decisions, `open_cases` | the evidence back |

The first eleven are always registered. The last eight appear only when `ARCHE_LEDGER` is set, so a client of an unconfigured server never sees a tool that can only fail. No tool has a reveal option, touches the filesystem, or keeps state between calls; the ledger file is the operator's, and the agent gets ids, labels, field names and numbers out of it.

## Environment

| Variable | What it does |
|---|---|
| `ARCHE_JURISDICTION` | ceiling jurisdiction; a call may not override it |
| `ARCHE_STATUTE` | ceiling statute id; a call may not override it |
| `ARCHE_HASH_KEY` | required for `guarded_scan`; no key, no tokens |
| `ARCHE_ALLOWED_PROVIDERS` | comma-separated model-provider allow-list |
| `ARCHE_TRANSFER_BASIS` | declared cross-border transfer basis |
| `ARCHE_LEDGER` | `duckdb:///FILE` (or a path): record decisions there and register the eight ledger tools |
| `ARCHE_SIGNING_KEY` | PEM from `arche attest keygen`: every answer then carries a signed `attestation` |

The ceiling rule: `ARCHE_JURISDICTION` and `ARCHE_STATUTE`, when set, are the policy every call runs under, and a `jurisdiction` argument is ignored in their favour. Unset, the argument decides, which is what a mixed document stream needs: `infer_jurisdiction`, then `plan_protection`, then `guarded_scan`. An agent that can choose its statute can choose a weaker one, so pin the ceiling when a deployment handles one jurisdiction.

With `ARCHE_SIGNING_KEY`, every tool's answer carries one more key, `attestation`: a JWS over the tool name, a hash of the arguments, a hash of the answer and the decision ids in it. stdio has no caller identity, so `caller` is `null`. [Attestation](../how-it-works/attestation.md) says what it proves.

## `capabilities`

No arguments. Returns `arche_core_version`, `statutes_available`, `jurisdictions_with_a_statute`, `jurisdictions_inferable`, `entity_packs`, `extras` (`detect`, `splink`, `doc`, each true only when the module actually imports), `attestation` (`{"signer": "did:key:..."}` or `null`) and `ledger` (`configured`, and the `tools` it added). Call it first: several tools return empty results rather than errors when an extra is missing, and this is how to tell the two apart. The example at the top of the page is its output.

## `infer_jurisdiction`

| Argument | Type |
|---|---|
| `text` | `str` |

```python
note = "Patient Casey Example (NIN 12345678901) called from 0803 555 7890."

j = handlers.infer_jurisdiction(note)
print(j["country"], j["confidence"], j["abstained"], j["statute_id"], j["policy_available"])
print(j["evidence"])
```

```text
NG 1.0 False NDPA-2023 True
[{'signal': 'id.nin', 'tier': 'A', 'country': 'NG', 'count': 1, 'weight': 1.0, 'source': 'text'}]
```

Also `margin`, `runner_up`, `reason`, `ruleset_version`, `policy_reason` and `policy_alternatives`. `abstained: true` means nothing in the text said where it came from. `policy_available: false` means a country was inferred and no statute pack covers it (the United States, for one); `policy_alternatives` names what can be passed explicitly. Evidence carries the signal name and count, never the matched text, because a sample can be a registration identifier.

## `plan_protection`

| Argument | Type | Default |
|---|---|---|
| `jurisdiction` | `str \| None` | `None`, or the ceiling |
| `statute` | `str \| None` | `None`, or the ceiling |

```python
plan = handlers.plan_protection(jurisdiction="NG")
print(plan["verdict"], plan["statute_id"], len(plan["governed"]), len(plan["covered"]))
print(plan["uncovered"][:4], plan["degraded_categories"])
```

```text
partial NDPA-2023 27 14
['PII-5-BANK_ACCOUNT', 'PII-5-CARD', 'PII-5-MPESA_REF', 'PII-6-BIOMETRIC'] []
```

`verdict` is `full`, `partial`, `none` or `no-statute`. `partial` is the normal answer and not a reason to stop on its own; `degraded_categories` (a detector exists and was built for somewhere else) is the sharper signal, and `none` means a clean result would mean nothing was looked for. Also `detector_packages`, `detectable_categories`, `calibration_mismatch` and `note`.

## `describe_pack`

| Argument | Type |
|---|---|
| `entity` | one of the `entity_packs` from `capabilities` |

```python
pack = handlers.describe_pack("place")
print(pack["field_names"], pack["ignores_everything_else"])
print([(f["field"], f["kinds"], f["weight"]) for f in pack["fields"]])
```

```text
['address', 'admin_path', 'lat', 'lon', 'name'] True
[('name', ['placename', 'tftoken', 'type'], 4.0), ('address', ['address'], 1.0), ('admin_path', ['containment'], 1.0), ('lat + lon', ['geo'], 1.0)]
```

Each field also carries `notes` (what each kind does, in words), `refutes`, and for coordinates `geo` with `decay_km` and `veto_km`. A field the pack does not name is ignored, not rejected: no error, no effect on the score. Call this before `compare_records` to map your columns.

## `detect_pii`

| Argument | Type | Default |
|---|---|---|
| `text` | `str` | |
| `jurisdiction` | `str \| None` | `None`, or the ceiling |

```python
d = handlers.detect_pii(note, jurisdiction="NG")
print(d["count"], d["coverage"]["verdict"])
for span in d["detections"]:
    print(span)
```

```text
2 partial
{'category': 'PII-2-NIN', 'start': 27, 'end': 38, 'confidence': 0.6, 'citation': 'NDPA-2023 s.30, NIMC Act s.27', 'tier': 'high'}
{'category': 'PII-3-PHONE', 'start': 52, 'end': 65, 'confidence': 0.9, 'citation': 'NDPA-2023 s.30', 'tier': 'moderate'}
```

Offsets index the original text; the caller holds it and slices. `coverage` is the same block `plan_protection` returns, because `count: 0` on its own does not say whether the document is clean or nothing installed could read it.

## `detect_entities`

| Argument | Type | Default |
|---|---|---|
| `text` | `str` | |
| `entity_types` | `list[str] \| None` | `None` |

```python
e = handlers.detect_entities("Adesola Okonkwo of Kijani Tea Exporters Ltd, Nairobi")
print(e["count"], e["ner_backend_installed"])
print(e["entities"])
```

```text
1 True
[{'type': 'PERSON', 'start': 0, 'end': 15, 'confidence': 0.7, 'source': 'lexicon'}]
```

Without the `detect` extra this finds pattern-shaped identifiers and lexicon names and no model-proposed people, organisations or places; `ner_backend_installed` says which it was, so check it before reading an empty result as clean. `source` names where each span came from.

## `guarded_scan`

| Argument | Type | Default |
|---|---|---|
| `text` | `str` | |
| `jurisdiction` | `str \| None` | `None`, or the ceiling |
| `provider` | `str \| None` | `None` |
| `crosses_border` | `bool` | `False` |

The handler also takes `key`, `statute`, `allowed_providers` and `transfer_basis`, which the server fills from the environment.

```python
g = handlers.guarded_scan(note, key="", jurisdiction="NG")
print(g["denied"], "|", g["reason"])

g = handlers.guarded_scan(note, key="demo-key", jurisdiction="NG")
print(g["denied"], g["offsets_match_original"], g["coverage"]["verdict"])
print(g["redacted_text"])
print([(f["category"], f["action"], f["tier"], f["token"][:12]) for f in g["fields"]])

g = handlers.guarded_scan(note, key="demo-key", jurisdiction="NG",
                          provider="openai", allowed_providers=["anthropic"])
print(g["denied"], "|", g["reason"])
```

```text
True | no hash key configured, so tokens could not be stable and the guard refuses rather than inventing one (set ARCHE_HASH_KEY)
False False partial
Patient Casey Example (NIN [NIN:de11776532b6f1b0]) called from [PHONE:53bb10448ce546a9].
[('PII-2-NIN', 'mask', 'high', 'de11776532b6'), ('PII-3-PHONE', 'tokenize', 'moderate', '53bb10448ce5')]
True | provider 'openai' is not in the allow-list ['anthropic']
```

Five refusals, all deny by default: no hash key, no statute for the jurisdiction, a provider outside the allow-list, a cross-border transfer with no declared basis, and no installed detector for anything the statute governs. A refusal is `{"denied": true, "reason", "citation", "coverage"?}`. An answer carries `redacted_text`, `fields` (each `category`, `action`, `token`, `citation`, `tier`), `metadata`, `coverage` and `offsets_match_original: false`: the tokens are a different length from what they replaced, so offsets from `detect_pii` do not index `redacted_text`. The same value gives the same token across calls under the same key, which is how an entity is correlated across documents without the server storing anything.

## `compare_records`

| Argument | Type | Default |
|---|---|---|
| `list_a`, `list_b` | `list[dict]` | |
| `entity` | one of the `entity_packs`, or `None` | `None` |
| `comparators` | `list[dict] \| None` | `None` |
| `backend` | `str \| None` | `None` (arche's own scorer); `"splink"` derives a Splink configuration from the pack |
| `threshold` | `float` | `0.7` |
| `id_field` | `str` | `"id"` |

Pass `entity` or `comparators`, not both and not neither. The handler also takes `ledger`, which the server fills from `ARCHE_LEDGER`; with one, every edge is recorded.

```python
import arche

ledger = arche.attach("duckdb:///:memory:")
suppliers = [{"id": "s1", "name": "Kijani Tea Exporters Ltd", "city": "Nairobi"},
             {"id": "s2", "name": "Central Cooperative Society", "city": "Nakuru"}]
registry = [{"id": "r1", "name": "Kijani Tea Exporters Limited", "city": "Nairobi"},
            {"id": "r2", "name": "Central Cooperative Society", "city": "Nakuru"}]

res = handlers.compare_records(suppliers, registry, entity="organisation", ledger=ledger)
for m in res["matches"]:
    print(m["a_id"], m["b_id"], m["decision"], m["score"], m["distinctive_max"], m["decision_id"][:24])
print(res["count"], res["backend"]["chosen"], sorted(res["pins"]))
```

```text
s1 r1 match 1.0 0.86 xwd:sha256:a96f6fd332e6d
s2 r2 review 1.0 0.594 xwd:sha256:81709217510d8
2 arche ['block', 'comparators_sha256', 'distinctive_floor', 'engine', 'review_margin', 'tf', 'threshold']
```

Each edge is `a_id`, `b_id`, `score`, `decision` (`match` or `review`), `evidence` (one number per field), `distinctive_max` and `decision_id`. `review` is a real answer: the records agree and nothing they agree on is distinctive enough to assert a match, which is the second pair here. Pairs below the review floor are not returned. `pins` records which engine and which frequency table decided; `blocking` says how many candidate pairs were scored.

## `why_unresolved`

| Argument | Type | Default |
|---|---|---|
| `record_a`, `record_b` | `dict` | |
| `entity` | one of the `entity_packs` | `"place"` |

```python
w = handlers.why_unresolved({"name": "Central Cooperative Society", "city": "Nakuru"},
                            {"name": "Central Cooperative Society", "city": "Nakuru"},
                            entity="organisation")
print(w["decision"], "|", w["why"])
print([(f["field"], f["effect"]) for f in w["would_resolve"]])
print([f["field"] for f in w["will_not_help"]])
```

```text
review | the records agree, and what they agree on is ordinary in this pack's reference population (distinctive_max 0.594 < floor 0.75). Agreement on a common token is not evidence of identity
[('registration_id', 'decisive_for'), ('entity_class', 'can_prevent_match'), ('address', 'independent_signal'), ('lat + lon', 'independent_signal')]
['name']
```

Effects, strongest first: `hard_constraint` (can cap the decision at `review` on its own), `decisive_for` (an exact identifier; agreement settles it), `can_prevent_match` (disagreement holds it), `independent_signal` (adds evidence without deciding alone). Read `will_not_help` before retrying: a cleaner rendering of a field that already agrees cannot raise its rarity. When the pair was never surfaced as a candidate, `decision` is `not_surfaced` and the lists are empty. Nothing here promises `no_match`.

## `check_name_equivalence`

| Argument | Type |
|---|---|
| `name_a`, `name_b` | `str` |

```python
print(handlers.check_name_equivalence("Fatima Abdullahi", "Fatuma Abdulahi"))
print(handlers.check_name_equivalence("Fatima Abdullahi", "Grace Mwangi"))
```

```text
{'decision': 'match', 'score': 0.9053, 'bands': {'match': 0.85, 'review': 0.7}}
{'decision': 'no_match', 'score': 0.5097, 'bands': {'match': 0.85, 'review': 0.7}}
```

`decision` is `match` at or above `0.85`, `review` at or above `0.7`, `no_match` below. A band rather than a boolean, so "close and not close enough" has a name.

## `extract_places`

| Argument | Type |
|---|---|
| `text` | `str` |

```python
p = handlers.extract_places("Send my package from 123 Maple Street to the blue gate behind Elim Pharmacy, 124 Elim Street.")
print(p["count"], p["offsets_match_original"], p["pack"])
for m in p["places"]:
    print(m["role"], (m["start"], m["end"]), m["cue"], m["cue_rule"], m["confidence"], m["components_present"])
```

```text
2 True arche.place_roles@v1:sha256:52ff7520cad60a44
origin (21, 37) from from_origin 0.95 ['street', 'street_number']
destination (55, 92) to to_destination 0.7 ['anchor', 'anchor_type', 'street', 'street_number']
```

`role` is `origin`, `destination`, `location`, `via` or `unknown`; absent or conflicting cues come back `unknown` at floor confidence rather than guessed. Each mention also carries `cue_start`, `cue_end`, `evidence`, `jurisdiction`, `jurisdiction_confidence` and `has_address`. An address is personal data, so the address text and its components never come back, only their names; the HTTP route of the same name returns them, because there the caller sent the text.

## `decision`

Registered with `ARCHE_LEDGER`. The handler takes the ledger as its first argument.

| Argument | Type |
|---|---|
| `decision_id` | `str` |

```python
did = res["matches"][0]["decision_id"]
dec = handlers.ledger_decision(ledger, did)
print(dec["verb"], dec["identity"], dec["action"], dec["score"])
print([(r["label"], r["fields"], r["from_text"]) for r in dec["records"]])
print(dec["entity_id"].startswith("ent_"), dec["supersedes"], dec["superseded_by"])
```

```text
reconcile match merge 1.0
[('s1', ['city', 'id', 'name'], False), ('r1', ['city', 'id', 'name'], False)]
True None None
```

Also `decision_id`, `explanation`, `factors`, `pins`, `record_a`, `record_b` (content addresses of the form `rec:sha256:`), `recorded_at`. `records` gives each record's `record_id`, `label` (the caller's id, or the address), `entity_type` and the names of its fields.

## `explain`

| Argument | Type |
|---|---|
| `decision_id` | `str` |

```python
why = handlers.ledger_explain(ledger, did)
print(why["supporting"], why["refuting"], why["missing"], why["shared"])
```

```text
['name', 'name_tftoken', 'name_type'] [] ['national_id', 'registration_id', 'phone', 'email', 'dob', 'address'] []
```

`shared` is the names of the fields both records carry with the same value, sorted; the CLI and HTTP forms can show the values with `reveal`, this one cannot. Also `identity`, `action`, `basis`, `explanation`, `gate` and `decision_id`.

## `replay`

| Argument | Type |
|---|---|
| `decision_id` | `str` |

```python
rp = handlers.ledger_replay(ledger, did)
print(rp["reproduced"], rp["changed"])
print(rp["then"])
print(rp["now"]["decision_id"] == did)
```

```text
True {}
{'identity': 'match', 'action': 'merge', 'score': 1.0, 'engine': 'crosswalk.v1'}
True
```

`then` and `now` each carry `identity`, `action`, `score` and `engine`; `now` adds the new `decision_id`. `reproduced` is true when it is the same id byte for byte; otherwise `changed` names every factor and pin that moved.

## `entities`

| Argument | Type | Default |
|---|---|---|
| `entity_type` | `str \| None` | `None` |

```python
ents = handlers.ledger_entities(ledger)
print(ents["count"])
for ent in ents["entities"]:
    print([r["label"] for r in ent["records"]], ent["held_together_by"],
          ent["shared_fields"], ent["conflicting_fields"], ent["weak_links"], ent["decisions"])
```

```text
1
['s1', 'r1'] direct ['city'] ['name'] [] 1
```

Largest entity first. Each has `entity_id`, `entity_type`, `records` (by `record_id` and `label`), `shared_fields` and `conflicting_fields` (names only: `Ltd` and `Limited` are a conflict on `name` even though the pack matched them), `held_together_by` (`direct` or `transitive`), `weak_links` (the records that hold a transitive entity together), `bridges` and the number of `decisions`. The pair at `review` is not an entity: `review` never merges.

## `path`

| Argument | Type |
|---|---|
| `record_a`, `record_b` | `str`, the `record_id` from `decision`, `entities` or `cases` |

```python
chain = handlers.ledger_path(ledger, dec["record_a"], dec["record_b"])
print(chain["same_entity"], chain["hops"], "|", chain["note"])
print([(s["from"], s["to"], s["identity"]) for s in chain["decisions"]])
```

```text
True 1 | one decision: the two were compared and matched directly
[('s1', 'r1', 'match')]
```

Each step is a decision with `from` and `to` labels. More than one hop means the two were never compared and the records between them were; an empty chain means they are not one entity. The argument is the `rec:sha256:` address, not the caller's label.

## `cases`

| Argument | Type | Default |
|---|---|---|
| `entity_type` | `str \| None` | `None` |

```python
cases = handlers.ledger_cases(ledger)
print(cases["count"])
case = cases["cases"][0]
print(case["a"]["label"], case["b"]["label"], case["score"], "|", case["explanation"])
print(case["supporting"], case["refuting"], case["would_resolve"])
```

```text
1
s2 r2 1.0 | review: agrees on name, name_tftoken, name_type
['name', 'name_tftoken', 'name_type'] [] ['registration_id', 'entity_class', 'address', 'lat + lon']
```

Each case carries its `decision_id`, `a` and `b` (`record_id` and `label`), `score`, `explanation`, `supporting`, `refuting` and `would_resolve`: the fields that would settle it. Fetch one of those from wherever you can and hand it to `observe`.

## `resolve`

| Argument | Type |
|---|---|
| `record` | `dict`, non-empty |
| `entity_type` | one of the `entity_packs` |

```python
r = handlers.ledger_resolve(ledger, {"name": "Kijani Tea Exporters", "city": "Nairobi"},
                            entity_type="organisation")
print(r["verdict"], "|", r["note"])
print([x["label"] for x in r["entity"]["records"]])
print([(v["identity"], v["matched"], v["members"]) for v in r["candidates"].values()])
print(r["entity_evidence"]["identity"], r["conflicting_fields"], r["would_resolve"])
```

```text
found | matched 2 member(s) of one entity
['s1', 'r1', '0']
[('match', 2, 2)]
review [] []
```

The record is compared with every stored record of its type, grouped by entity, and decided at the entity level: `found` (linked, and now a member), `review` (the nearest pairs opened as cases), `ambiguous` (members of two entities matched; link withheld), `conflict` (contradicts an identifier the entity shares; withheld), `not_found` (stored on its own). `candidates` is keyed by entity id with `identity`, `score`, `matched`, `review` and `members`; `entity_evidence` compares the record with the entity's merged profile; `decisions` lists every new receipt. A record without an id is labelled by its position, `0` here.

## `observe`

| Argument | Type |
|---|---|
| `record_id` | `str`, the `record_id` from `cases` or `decision` |
| `evidence` | `dict` of field: value, non-empty |

```python
first = handlers.ledger_observe(ledger, case["a"]["record_id"], {"registration_id": "CS-1188"})
print(first["fields"], [(d["identity"], d["action"], d["supersedes"] == case["decision_id"]) for d in first["decisions"]], first["open_cases"])

second = handlers.ledger_observe(ledger, case["b"]["record_id"], {"registration_id": "CS-1188"})
print(second["fields"], [(d["identity"], d["action"], d["factors"]) for d in second["decisions"]], second["open_cases"])
print(handlers.ledger_cases(ledger)["count"])
```

```text
['registration_id'] [('review', 'hold', True)] 1
['registration_id'] [('same_entity', 'merge', {'name': 1.0, 'name_tftoken': 1.0, 'name_type': 1.0, 'registration_id': 1.0})] 0
0
```

The values go into the operator's ledger file; the reply carries `fields` (names), the new `decisions` (each naming what it `supersedes`; nothing is overwritten) and `open_cases`. One side carrying a registration id is still `review`, because the other side has nothing to agree with; once both carry it the pair is `same_entity` and the queue is empty.

## Where to read next

| You want to | Read |
|---|---|
| run the server, see the tools from a script, the Inspector and a chat client | [Let an agent call arche](../guides/mcp-server.md) |
| the same eight ledger operations from Python | [Keep, explain, replay](../guides/keep-and-replay.md) |
| the same verbs over plain HTTP | [HTTP API](http-api.md) |
| what the signed `attestation` proves | [Attestation](../how-it-works/attestation.md) |
| the server behind an auth proxy | [Docker and deploy](../get-started/docker.md) |
