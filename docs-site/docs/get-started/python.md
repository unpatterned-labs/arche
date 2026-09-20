# From Python

Five verbs. Each one below is complete, runs offline on the base install, and prints what is shown. At the end you know which verb answers which question and what a receipt looks like in your own code.

```sh
pip install "arche-core[ledger]"
```

## What personal data is in this, and can I hand on a copy?

```python
import arche

note = "Patient Casey Example (NIN 12345678901) called from 0803 555 7890."

for d in arche.detect_pii(note, jurisdiction="NG", backend="basic"):
    print(d.category, (d.start, d.end), d.regulatory_citation)

safe = arche.deidentify(note, jurisdiction="NG", backend="basic")
print(safe.text)
print(safe.decision_id[:40])
```

```text
PII-2-NIN (27, 38) NDPA-2023 s.30, NIMC Act s.27
PII-3-PHONE (52, 65) NDPA-2023 s.30
Patient Casey Example (NIN [NIN]) called from PHONE_d3100c11.
red:sha256:31d8e1ac9880676a152f888490248
```

`detect_pii` returns spans, never values: offsets, a category, a confidence and the statute section each falls under. `deidentify` returns the copy the statute permits, and that copy is a decision with an id. `method="mask" | "token" | "drop"` overrides the rendering for every span; the citations stay the statute's. `jurisdiction=None` infers the country from the text and raises `JurisdictionRequiredError` when the evidence is thin.

## Are these two the same?

```python
a = "Adesola Okonkwo, NIN 12345678901, adesola@example.com"
b = "Adesola E. Okonkwo, NIN 12345678901, 124 Maple Street"

r = arche.compare(a, b, entity="person", jurisdiction="NG", backend="basic")
print(r.identity, r.action, "|", r.explanation)
print(r.factors)
print(r.decision_id[:40])
```

```text
same_entity merge | national ID match; name similarity 80%
{'name': 0.8, 'national_id': 1.0, 'name_tf': 0.7233}
dec:sha256:8912e7da95835995ea26b78045221
```

`identity` is one of `same_entity`, `review`, `different`. `action` is one of `merge`, `hold`, `no_op`, and it can be `hold` while identity is `same_entity`: a belief the engine holds but will not act on alone. `factors` is the per-field evidence; `name_tf` is the token overlap of the two names weighted by how rare each token is, and it is the gate, not the score, that decides whether agreeing on a name proves anything, which is why two *Ibrahim Musa* can share a name and still be two men. `compare` also takes two dicts with your own field names; [Compare two records](../guides/compare-two-records.md) covers the shape.

## Which of these are the same as those?

```python
suppliers = [
    {"id": "s1", "name": "Kijani Tea Exporters Ltd", "city": "Nairobi"},
    {"id": "s2", "name": "Zenith Bank Plc", "city": "Lagos"},
]
registry = [
    {"id": "r1", "name": "Kijani Tea Exporters Limited", "city": "Nairobi"},
    {"id": "r2", "name": "Kijani Coffee", "city": "Nairobi"},
]

result = arche.reconcile(suppliers, registry, entity="organisation")
for edge in result["matches"]:
    print(edge["a_id"], edge["b_id"], edge["decision"], edge["score"])
print(result["backend"])
```

```text
s1 r1 match 1.0
s1 r2 review 0.5798
{'floor': 1000, 'records': 4, 'chosen': 'arche', 'reason': '4 records is below the floor of 1000'}
```

Each list needs a stable `id`; the pack (`person`, `organisation`, `place`, `product_electronics`, `artist`) says which other fields it reads. `s1` and `r1` match: *Ltd* and *Limited* are one company. `s1` and `r2` are `review`: they share the rare word *Kijani* and nothing else, and that is a queue for a person, not a score to round up. Pairs below the review floor are not returned, and their absence is not a claim that they differ.

`result["backend"]` says who scored the pairs. With `arche-core[resolve]` installed and a thousand or more records, `backend="auto"` hands the scoring to Splink and keeps everything around the score; [Backends](../how-it-works/backends.md) has the measurement behind the floor.

## Where is this going?

```python
from arche.addr.request import MasterSheet

sheet = MasterSheet([
    {"id": "loc-001", "name": "123 Maple Street", "address": "123 Maple Street, Ikeja",
     "lat": 6.6000, "lon": 3.3500},
    {"id": "loc-124", "name": "124 Elim Street", "address": "124 Elim Street, Ikeja",
     "lat": 6.6010, "lon": 3.3510},
    {"id": "loc-124m", "name": "124 Elm Street", "address": "124 Elm Street, Ikeja",
     "lat": 6.6300, "lon": 3.3800},
    {"id": "poi-elim", "name": "Elim Pharmacy", "kind": "landmark",
     "lat": 6.6011, "lon": 3.3511},
])

req = arche.resolve_place_request(
    "Send my package tomorrow from 123 Maple Street to the blue gate behind "
    "Elim Pharmacy, 124 Elim Streat.",
    action="create_delivery", sources=[sheet])

print(req.origin.status, "|", req.destination.status)
print(req.destination.question)
print([c.display_name for c in req.destination.candidates])
print(req.status)
```

```text
verified | clarification_required
Is the destination 124 Elim Street, next to Elim Pharmacy?
['124 Elim Street', '124 Elm Street']
blocked_pending_destination_confirmation
```

The origin is a clean address in the sheet, so it is verified. The destination was written with a typo, *Streat*, and the sheet has an *Elm Street* one slip away, so it is one short question with the likely answer first: a typo-tolerant match is always confirmed, never verified. *Behind Elim Pharmacy* is evidence for *Elim Street* that *Elm Street* does not get, which is why it leads. The delivery is blocked until the destination is confirmed. A high-confidence endpoint passes through, a close contest becomes a question, weak evidence becomes a refusal with what was tried. The sheet is yours; a geocoder is an opt-in source beside it.

## Keep it, explain it, replay it

```python
ledger = arche.attach("duckdb:///:memory:")            # a file path keeps it

r = arche.compare(a, b, entity="person", jurisdiction="NG", backend="basic", store=ledger)
why = ledger.explain(r.decision_id)
print(why["supporting"], why["missing"])
print(ledger.replay(r.decision_id).reproduced)
```

```text
['national_id'] ['registration_id', 'phone', 'dob', 'address']
True
```

`store=` on any verb records the receipt with the inputs it was made from. `explain` says what supported the decision, what refuted it and what was missing; `replay` reads the inputs again with the engine installed now and reports whether the same id comes back, and if not, what moved. The ledger is a DuckDB file on your disk; nothing leaves the machine. [Keep, explain, replay](../guides/keep-and-replay.md) has the rest: cases still at review, entities the decisions have linked, adding evidence and deciding again.

## Where to read next

| You want to | Read |
|---|---|
| your own field names as the labels, one declaration for extraction and matching | [Extract to your schema](../guides/extract-to-your-schema.md) |
| PDFs in, linked entities out | [Resolve documents](../guides/resolve-documents.md) |
| a masked copy that still links to the original | [Find and mask](../guides/find-and-mask.md) |
| the fields on a receipt and what each means | [The decision](../how-it-works/the-decision.md) |
| a signed answer someone else can verify | [Attested answers](../how-it-works/attestation.md) |
