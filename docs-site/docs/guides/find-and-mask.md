# Find and mask

Two verbs over one detection run: `detect_pii` says what personal data a text holds and which section of which statute governs each span; `deidentify` returns the copy the statute permits, and the copy is a decision with an id. Everything on this page runs offline on the base install with `backend="basic"`.

## Find

```python
import arche

note = "Patient Casey Example (NIN 12345678901) called from 0803 555 7890."

for d in arche.detect_pii(note, jurisdiction="NG", backend="basic"):
    print(d.category, (d.start, d.end), round(d.confidence, 2), d.regulatory_citation)
```

```text
PII-2-NIN (27, 38) 0.6 NDPA-2023 s.30, NIMC Act s.27
PII-3-PHONE (52, 65) 0.9 NDPA-2023 s.30
```

A detection is a span in *your* text, so the value is on it; what is never on it is a `repr` that prints the value. The citation is the reason the span counts: NDPA-2023 s.30 is the section that makes an 11-digit NIMC number personal data, and it travels with the detection into whatever you do next.

`Casey Example` is not found here. The `basic` backend reads names from a lexicon of 13,342 African given and family names, and *Casey* is not one of them. That is what `backend="auto"` is for: with `arche-core[detect2]` installed, GLiNER2-PII proposes the names and prose addresses the lexicon cannot, and the same validators and the same statute decide over what it proposed. Without the extra, `auto` runs the rules and says so once.

## Mask

```python
safe = arche.deidentify(note, jurisdiction="NG", backend="basic")
print(safe.text)
print(safe.count, "spans |", safe.statute, "|", safe.method, "|", safe.decision_id[:32])
```

```text
Patient Casey Example (NIN [NIN]) called from PHONE_d3100c11.
2 spans | NDPA-2023 | statute | red:sha256:8f7ce784d66831a26668f3
```

The statute chose two different renderings: the national id is masked, the phone is tokenised. That is `method="statute"`, the default, and it is a method rather than the absence of one -- a data protection act says what may be kept in a pseudonymous form and what may not. The other three apply one rendering to every governed span; the citations stay the statute's.

```python
for method in ("mask", "token", "drop"):
    print(method.ljust(6), arche.deidentify(note, jurisdiction="NG", backend="basic", method=method).text)
```

```text
mask   Patient Casey Example (NIN [NIN]) called from [PHONE].
token  Patient Casey Example (NIN NIN_7bad73b5) called from PHONE_d3100c11.
drop   Patient Casey Example (NIN ) called from .
```

## The jurisdiction is never guessed silently

Leave `jurisdiction` out and it is inferred from the text's own evidence -- a postcode, a registrar, a currency, a company-form suffix. When the evidence is thin the call refuses, and the refusal names the packs it has.

```python
print(arche.deidentify("Monzo Bank Limited, London EC2A 2AG. Contact jane.smith@monzo.com.",
                       backend="basic").statute)
try:
    arche.deidentify("call me on the usual number", backend="basic")
except ValueError as exc:
    print(type(exc).__name__)
```

```text
UK-GDPR
JurisdictionRequiredError
```

A jurisdiction no pack covers -- most of the world -- gets arche's baseline floor, a conservative default whose every citation says it is not the law of any country. The `pins` on the result record whether the jurisdiction was `given` or `inferred`, and at what confidence.

## A tokenised copy still links

The tokens are keyed digests: the same value under the same `salt` gives the same token, in every note, on every day. So two masked copies of one person can still be compared -- not by reading the masked text, which the extractor cannot, but by their tokens as a record.

```python
a = "Adesola Okonkwo, NIN 12345678901, adesola@example.com, 123 Maple Street"
b = "Adesola E. Okonkwo, NIN 12345678901, adesola@gmail.com, 231 Elim Street"

ma = arche.deidentify(a, jurisdiction="NG", backend="basic", method="token", salt="clinic-2026")
mb = arche.deidentify(b, jurisdiction="NG", backend="basic", method="token", salt="clinic-2026")
print(ma.text)
print(ma.record())

receipt = arche.compare(ma.record(), mb.record(), entity="person", jurisdiction="NG")
print(receipt.identity, receipt.action, receipt.factors)
```

```text
NAME_66ea6caf NAME_c21aa630, NIN NIN_45aa5c4f, EMAIL_eb52e647, ADDRESS_29972278
{'national_id': 'NIN_45aa5c4f', 'name': 'NAME_66ea6caf NAME_c21aa630', 'email': 'EMAIL_eb52e647', 'address': 'ADDRESS_29972278'}
same_entity merge {'name': 1.0, 'national_id': 1.0, 'email': 0.0, 'address': 0.825, 'name_tf': 1.0}
```

`same_entity`, on a national id neither record holds. The evidence names the field and the receipt is signable like any other. Three things make this honest rather than clever: `record()` only carries spans that were *tokenised*, so a masked `[NIN]` or a dropped span contributes nothing (`method="statute"` under NDPA masks the id, and the record says so by omission); the salt is a key, so two deployments never mint the same token for the same value and cannot be joined by accident; and the `decision_id` of the redaction does not depend on the salt, because what was found and what was done to it are the same under any key.

## Keep it

```python
ledger = arche.attach("duckdb:///:memory:")            # a path keeps it
kept = arche.deidentify(note, jurisdiction="NG", backend="basic", store=ledger)

why = ledger.explain(kept.decision_id)
print(why["by_category"], why["citations"])
print(why["spans"][0])
print(ledger.replay(kept.decision_id).reproduced)
```

```text
{'PII-2-NIN': 1, 'PII-3-PHONE': 1} ['NDPA-2023 s.30', 'NDPA-2023 s.30, NIMC Act s.27']
{'action': 'mask', 'category': 'PII-2-NIN', 'citation': 'NDPA-2023 s.30, NIMC Act s.27', 'confidence': 0.6, 'detector': 'rule:ng_nin', 'end': 38, 'start': 27}
True
```

The redaction sits in the same ledger as the matches, under the same verbs. `explain` gives the spans by category with their citations and never a value; `replay` runs the detectors again over the stored text under the engine installed now and reports whether the same spans would be found -- and when they would not, which pin or factor moved. A redaction links nothing: it is a decision about one document, and `ledger.entities()` does not change.

## From the shell

```bash
arche redact note.txt --jurisdiction NG --out note.redacted.txt --json note.spans.json
arche redact --text "Patient Casey Example (NIN 12345678901)" --jurisdiction NG --method mask
```

The masked text is the output, so it can be piped; the span report is the sidecar, and it never carries a value. `--backend auto` uses the model when installed; `--store FILE.duckdb` or `--record` (with `ARCHE_LEDGER`) keeps the decision.
