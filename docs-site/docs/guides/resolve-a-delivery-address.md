# Resolve a delivery address

At the end of this page a sentence like *send it to the blue gate behind Elim Pharmacy, 124 Elim Streat* comes back as a verified endpoint, one short question, or an honest refusal, checked against a list of places you own, with a receipt for each endpoint.

```python
import arche
from arche.addr.request import MasterSheet

sheet = MasterSheet([
    {"id": "loc-001", "name": "123 Maple Street", "address": "123 Maple Street, Ikeja",
     "lat": 6.6000, "lon": 3.3500},
    {"id": "loc-124", "name": "124 Elim Street", "address": "124 Elim Street, Ikeja",
     "lat": 6.6010, "lon": 3.3510},
    {"id": "loc-124m", "name": "124 Elm Street", "address": "124 Elm Street, Ikeja",
     "lat": 6.6300, "lon": 3.3800},
    {"id": "loc-012", "name": "12 Awolowo Way", "address": "12 Awolowo Way, Ikeja",
     "lat": 6.6100, "lon": 3.3600},
    {"id": "loc-030", "name": "30 Awolowo Way", "address": "30 Awolowo Way, Ikeja",
     "lat": 6.6102, "lon": 3.3604},
    {"id": "loc-045", "name": "45 Awolowo Way", "address": "45 Awolowo Way, Ikeja",
     "lat": 6.6105, "lon": 3.3609},
    {"id": "poi-elim", "name": "Elim Pharmacy", "kind": "landmark",
     "lat": 6.6011, "lon": 3.3511, "front_bearing": 0},
])

text = ("Send my package tomorrow from 123 Maple Street to the blue gate behind "
        "Elim Pharmacy, 124 Elim Streat.")

req = arche.resolve_place_request(text, action="create_delivery", sources=[sheet])
print(req.status)
print(req.origin.status, "|", req.origin.chosen.display_name, req.origin.chosen.evidence)
print(req.destination.status, "|", req.destination.question)
for c in req.destination.candidates:
    print(" ", c.confidence, c.display_name, c.evidence)
```

```text
blocked_pending_destination_confirmation
verified | 123 Maple Street ('street-number match', 'street match')
clarification_required | Is the destination 124 Elim Street, next to Elim Pharmacy?
  1.0 124 Elim Street ('street-number match', 'typo-tolerant street match', 'nearby landmark match', 'relation geometry agrees')
  0.7 124 Elm Street ('street-number match', 'typo-tolerant street match')
```

The origin is a clean address that the sheet holds, so it is verified. The destination was written with a typo, and the sheet has an *Elm Street* one slip away, so it is one question, with the likely answer first and the evidence for each candidate listed. The delivery is `blocked_pending_destination_confirmation` until someone answers. Nothing here guesses: an endpoint the text does not mention is `missing`, and a landmark the sources cannot place is `refused` with what was tried.

## What arche read

The sentence is read before anything is looked up. Each endpoint is a `SpatialMention`: its role in the action, the address, and the informal parts an address form has no field for.

```python
from arche.addr.request import spatial_mentions

for m in spatial_mentions(text):
    print(m.action_role, "|", m.relation_kind, m.reference_text, "|", m.access_hint, "|", m.street_number, m.street, m.street_suffix_known)
```

```text
origin | None None | None | 123 Maple Street True
destination | behind Elim Pharmacy | blue gate | 124 Elim Streat False
```

`relation_kind` and `reference_text` are the landmark clause, *behind Elim Pharmacy*. `access_hint` is the thing a courier needs at the door, *blue gate*, kept as written. `street_suffix_known` is `False` because *Streat* is not a suffix arche knows, which is what marks the mention as a typo rather than a street it has never heard of. The reading is deterministic and offline; no model runs. `POST /places` and the `extract_places` MCP tool return the same mentions.

## The four outcomes

A high-confidence endpoint passes through:

```python
r = arche.resolve_place_request("Deliver the parcel from 12 Awolowo Way to 124 Elim Street.",
                                action="create_delivery", sources=[sheet])
print(r.status, "|", r.destination.status, r.destination.chosen.display_name)
```

```text
ready | verified 124 Elim Street
```

A street with no number is a missing field, not a contest between three of a dozen doors:

```python
r = arche.resolve_place_request("Pick up the goods from 123 Maple Street to Awolowo Way.",
                                action="create_delivery", sources=[sheet])
print(r.destination.status, r.destination.question_kind, "|", r.destination.question)
```

```text
clarification_required number | Which number on Awolowo Way is the destination?
```

`question_kind` is `confirm` (*is it this one?*) or `number` (*which number?*), so an application can render a yes/no or a number field rather than parse the sentence.

Weak evidence is a refusal, with the candidates that were considered, which here is none:

```python
r = arche.resolve_place_request("Send it from 123 Maple Street to 77 Marina Road.",
                                action="create_delivery", sources=[sheet])
print(r.destination.status, r.destination.candidates, "|", r.status)
```

```text
refused () | blocked_destination_refused
```

And a landmark alone proposes the doors near it, at a confidence that asks rather than verifies:

```python
r = arche.resolve_place_request("Send it from 123 Maple Street to behind Elim Pharmacy.",
                                action="create_delivery", sources=[sheet])
print(r.destination.status, "|", r.destination.question)
for c in r.destination.candidates:
    print(" ", round(c.confidence, 2), c.display_name, c.evidence)
```

```text
clarification_required | Is the destination 124 Elim Street, next to Elim Pharmacy?
  0.73 124 Elim Street ('nearby landmark match', 'relation geometry agrees')
  0.58 123 Maple Street ('nearby landmark match', 'relation geometry agrees')
```

Informal addresses are made of this. The landmark row in the sheet carries `front_bearing`, the compass direction its front faces, so *behind* is used and not only read: a door on the far side gets `relation geometry agrees`, a door in front would get `relation geometry disagrees`. Without a bearing the relation proves proximity only, and a written address always outranks a relation that disagrees with it.

## The policy, and what its numbers were measured on

```python
from arche.addr.request import Policy

print(Policy())
```

```text
Policy(verified_at=0.85, clarify_margin=0.15, minimum=0.4, require=('origin', 'destination'), candidates_shown=3, confirm_typo_matches=True)
```

`verified_at=0.85`: the top candidate at or above it is verified. `clarify_margin=0.15`: two candidates within it of each other are a question. `minimum=0.40`: a top candidate below it is a refusal. `require=("origin", "destination")`: the endpoints the action is blocked on. `confirm_typo_matches=True`: an endpoint reached through a typo-tolerant match is a question even when it clears `verified_at`, which is why the first example asked. Turn the rule off and the same sentence verifies:

```python
r = arche.resolve_place_request(text, action="create_delivery", sources=[sheet],
                                policy=Policy(confirm_typo_matches=False))
print(r.destination.status, r.destination.chosen.display_name)
```

```text
verified 124 Elim Street
```

Whether that is a good trade is a measurement, not an opinion. On the synthetic `places_v1` world (a sheet with confusable street pairs, a thousand requests, every endpoint labelled with how the sentence rendered it), the default policy verifies the wrong door `0.000` of the time; with the typo rule off and `verified_at` at 0.7, it verifies eight points more automatically and sends 34 parcels per 1,000 to the wrong door. The defaults are safe, not tight. [Benchmarks](../reference/benchmarks.md) has the table.

`confidence` is a weighted agreement over named evidence, number, street, a landmark nearby, the relation's geometry, in `[0, 1]`. It orders candidates and drives the policy; it is not a calibrated probability, and the policy thresholds are the place to be conservative.

## The time window

```python
import datetime as dt

r = arche.resolve_place_request(text, action="create_delivery", sources=[sheet],
                                now=dt.date(2026, 9, 20))
print(r.time_window.to_dict())
```

```text
{'date': '2026-09-21', 'confidence': 'high', 'phrase': 'tomorrow'}
```

*Tomorrow*, *on Friday*, *next Tuesday* resolve against `now`; a sentence with no phrase has no date, and arche does not assume today.

## Sources

`MasterSheet` is the caller's own list: a customer's saved locations, a facility register, a sheet someone maintains. Fields read: `id`, `name` (or `display_name`), `address` as free text or `street_number` and `street`, `lat` and `lon`, and for a landmark `kind: landmark` and optionally `front_bearing`. Any object with a `name` and a `candidates(mention)` method is a source; `Nominatim` is one, opt-in, one request a second under OpenStreetMap's policy, and empty under `ARCHE_OFFLINE=1`. Sources combine: `sources=[sheet, Nominatim()]` checks your own list first and the geocoder beside it, one entry per place id, best confidence wins.

A verified-address layer that answers with an id a regulator or a courier can be handed is the third kind of source, and it does not live in this repository. What this repository owes it is the protocol staying stable.

## The receipt

Every endpoint carries a `decision_id` with its own prefix, `plc:`, hashed over the reading, the candidates shown, the policy, the status and the pinned sources. A `MasterSheet` pins as a content hash of its rows, so a sheet that gained a row gives a different id even when the status did not move. A live geocoder pins as `live` and is unreplayable by declaration.

```python
ledger = arche.attach("duckdb:///:memory:")

r = arche.resolve_place_request(text, action="create_delivery", sources=[sheet],
                                store=ledger, now=dt.date(2026, 9, 20))
why = ledger.explain(r.destination.decision_id)
print(why["identity"], "|", why["why"])
print([c["place_id"] for c in why["candidates"]])
print(ledger.replay(r.destination.decision_id).reproduced)
print(r.destination.decision_id[:36], r.destination.pins["sources"][0][:20])
```

```text
clarification_required | Is the destination 124 Elim Street, next to Elim Pharmacy?
['loc-124', 'loc-124m']
True
plc:sha256:c3f78a31704b86645881273e0 sheet:sha256:09fbe64
```

With `store=`, each endpoint is recorded as a decision with verb `place`; `explain` returns the reading, the candidates and the question, and `replay` rebuilds the sheet from the receipt, reads the sentence again and says whether the same id comes back. [Keep, explain, replay](keep-and-replay.md) covers the ledger.

## Where to read next

| You want to | Read |
|---|---|
| the place mentions without a source, over HTTP or from an agent | [Serve over HTTP](serve-over-http.md), [Let an agent call arche](mcp-server.md) |
| how the `place` pack compares two facility records | [Compare two records](compare-two-records.md) |
| the policy's numbers against the synthetic world, and the runs that found the defects | [Benchmarks](../reference/benchmarks.md) |
| every field on an endpoint | [The decision](../how-it-works/the-decision.md) |
