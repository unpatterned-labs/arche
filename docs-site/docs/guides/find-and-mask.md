# Find and mask personal data

By the end of this page you can take a piece of text, list the personal data in it with the statute section that governs each span, and hand on a masked copy that is itself a decision with an id. Everything here runs offline on the base install with `backend="basic"`.

```python
import arche

note = "Patient Casey Example (NIN 12345678901) called from 0803 555 7890."

for d in arche.detect_pii(note, jurisdiction="NG", backend="basic"):
    print(d.category, (d.start, d.end), round(d.confidence, 2), d.regulatory_citation)

safe = arche.deidentify(note, jurisdiction="NG", backend="basic")
print(safe.text)
```

```text
PII-2-NIN (27, 38) 0.6 NDPA-2023 s.30, NIMC Act s.27
PII-3-PHONE (52, 65) 0.9 NDPA-2023 s.30
Patient Casey Example (NIN [NIN]) called from PHONE_d3100c11.
```

Two verbs over one detection run. `detect_pii` says what personal data the text holds and which section of which statute makes it personal data. `deidentify` returns the copy that statute permits.

## What a detection carries

A detection is a span in your own text: offsets, a category, a confidence and a citation. The value is on it, because the text is yours; what is never on it is a `repr` that prints the value, so a detection in a log is not a leak. The citation is the reason the span counts. NDPA-2023 s.30 is the section that makes an 11-digit NIMC number personal data, and it travels with the detection into whatever you do next.

`Casey Example` is not found here. The `basic` backend reads names from a lexicon of 13,342 African given and family names, and *Casey* is not one of them. That is what `backend="auto"` is for: with `arche-core[detect2]` installed, GLiNER2-PII proposes the names and prose addresses the lexicon cannot, and the same validators and the same statute decide over what it proposed. Without the extra, `auto` runs the rules and says so once. `backend="basic"` is the rules alone and never loads a model, which is why every example on this page names it.

## What a masked copy carries

```python
print(safe.count, "spans |", safe.statute, "|", safe.method, "|", safe.decision_id[:32])
print(safe.pins["jurisdiction_source"], safe.pins["backend"], safe.pins["model"])
```

```text
2 spans | NDPA-2023 | statute | red:sha256:31d8e1ac9880676a152f8
given basic None
```

The copy is a `Deidentified`: the masked `text`, the `detections`, what was done to each, and a `decision_id` that is a content hash over the spans, their actions, the citations and the pins. The `pins` say what ran: the engine version, the backend, the model if one was loaded (`None` here), the statute and its version, and whether the jurisdiction was `given` or `inferred`.

The statute chose two different renderings: the national id is masked, the phone is tokenised. That is `method="statute"`, the default. It is a method rather than the absence of one: a data protection act says what may be kept in a pseudonymous form and what may not. The other three methods apply one rendering to every governed span; the citations stay the statute's.

```python
for method in ("mask", "token", "drop"):
    print(method.ljust(6), arche.deidentify(note, jurisdiction="NG", backend="basic", method=method).text)
```

```text
mask   Patient Casey Example (NIN [NIN]) called from [PHONE].
token  Patient Casey Example (NIN NIN_7bad73b5) called from PHONE_d3100c11.
drop   Patient Casey Example (NIN ) called from .
```

## Let the text say where it is from, or refuse

Leave `jurisdiction` out and it is inferred from the text's own evidence: a postcode, a registrar, a currency, a company-form suffix. When the evidence is thin the call refuses, and the refusal names the packs it has.

```python
from arche.protect import JurisdictionRequiredError

inferred = arche.deidentify("Monzo Bank Limited, London EC2A 2AG. Contact jane.smith@monzo.com.",
                            backend="basic")
print(inferred.statute, inferred.pins["jurisdiction_source"], inferred.pins["jurisdiction_confidence"])
try:
    arche.deidentify("call me on the usual number", backend="basic")
except JurisdictionRequiredError as exc:
    print(type(exc).__name__, "|", str(exc)[:88])
```

```text
UK-GDPR inferred 1.0
JurisdictionRequiredError | the text does not say which jurisdiction governs it, and arche will not guess: a redacti
```

`JurisdictionRequiredError` is a `ValueError`, so an existing `except ValueError` catches it too. A redaction under the wrong statute looks finished and is not, which is why the guess is refused rather than made quietly. A jurisdiction no pack covers, which is most of the world, gets arche's baseline floor: a conservative default whose every citation says it is not the law of any country.

## Compare two masked copies

The tokens are keyed digests: the same value under the same `salt` gives the same token, in every note, on every day. So two masked copies of one person can still be compared. Not by reading the masked text, which the extractor cannot, but by their tokens as a record.

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

`same_entity`, on a national id neither record holds. The evidence names the field and the receipt is signable like any other. Three things make this honest rather than clever, and the next fence checks two of them.

```python
other = arche.deidentify(a, jurisdiction="NG", backend="basic", method="token", salt="other-key")
print(other.record()["national_id"] == ma.record()["national_id"], other.decision_id == ma.decision_id)
print(arche.deidentify(a, jurisdiction="NG", backend="basic").record())
```

```text
False True
{'name': 'NAME_f71c6342 NAME_925a28e1', 'email': 'EMAIL_3f6caee6'}
```

First, the salt is a key: under a different salt the same NIN gets a different token, so two deployments never mint the same token for the same value and cannot be joined by accident. Second, the `decision_id` does not depend on the salt, because what was found and what was done to it are the same under any key. Third, `record()` only carries spans that were tokenised. A masked `[NIN]` or a dropped span contributes nothing, and under `method="statute"` NDPA masks the id, so the record from the default method has a name and an email and no `national_id`. The record says so by omission, and `method="token"` is the one that makes a copy linkable.

## Keep the redaction

```python
ledger = arche.attach("duckdb:///:memory:")            # a path keeps it
kept = arche.deidentify(note, jurisdiction="NG", backend="basic", store=ledger)

why = ledger.explain(kept.decision_id)
print(why["by_category"], why["citations"])
print(why["spans"][0])
print(ledger.replay(kept.decision_id).reproduced)
print(len(ledger.entities()))
```

```text
{'PII-2-NIN': 1, 'PII-3-PHONE': 1} ['NDPA-2023 s.30', 'NDPA-2023 s.30, NIMC Act s.27']
{'action': 'mask', 'category': 'PII-2-NIN', 'citation': 'NDPA-2023 s.30, NIMC Act s.27', 'confidence': 0.6, 'detector': 'rule:ng_nin', 'end': 38, 'start': 27}
True
0
```

The redaction sits in the same ledger as the matches, under the same verbs. `explain` gives the spans by category with their citations and never a value. `replay` runs the detectors again over the stored text under the engine installed now and reports whether the same spans would be found, and when they would not, which pin or factor moved. A redaction links nothing: it is a decision about one document, so `ledger.entities()` is still empty. [Keep, explain, replay](keep-and-replay.md) has the rest of the ledger.

## From the shell

```bash
arche redact note.txt --jurisdiction NG --out note.redacted.txt --json note.spans.json
arche redact --text "Patient Casey Example (NIN 12345678901)" --jurisdiction NG --method mask
```

The masked text is the output, so it can be piped; the span report is the sidecar, and it never carries a value. `--backend auto` uses the model when installed; `--salt` keys the tokens; `--store FILE.duckdb` or `--record` (with `ARCHE_LEDGER`) keeps the decision. The source can be a `.txt`, `.md`, `.pdf` or `.docx` file, or the text itself with `--text`.

## Where to read next

| You want to | Read |
|---|---|
| the model backend and what each extra adds | [Extras](../reference/extras.md) |
| the ledger: look up, explain, replay, entities, cases | [Keep, explain, replay](keep-and-replay.md) |
| the fields on a receipt and what each means | [The decision](../how-it-works/the-decision.md) |
| a masked report over whole documents | [Resolve documents](resolve-documents.md) |
| the same verbs from an agent | [The MCP server](mcp-server.md) |
