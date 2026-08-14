# Zero to hero: documents

Four invoices in a folder. By the end of this page you will have gone from files on disk to typed records, to verdicts about who they refer to, to a signed decision you can re-check next year — and you will have seen the engine get one of them wrong, which is the part worth staying for.

Everything below is real output from `data/doc_bench/`, four invoices from four unrelated companies. Values are masked because that is the default.

```bash
pip install arche-core[doc]
```

---

## 1. Files in

```python
from arche import resolve_documents

report = resolve_documents("data/doc_bench/*.pdf")
print(report.table())
```

```text
EXTRACTED RECORDS
document           name              email                  phone       organisation
------------------------------------------------------------------------------------
invoice_10.pdf     ANDR********      —                      86-0******  Sher****************
invoice_12_ak.pdf  MRS ************  andr*****************  7263****    Cond****************
invoice_27.pdf     —                 —                      91-2******  Meri****************
invoice_6_ak.pdf   Andr********      erik*****************  —           RIDG****************

RESOLUTION
document a              document b              verdict        score
---------------------------------------------------------------------
invoice_10.pdf          invoice_12_ak.pdf      review        0.7500
invoice_10.pdf          invoice_27.pdf         different     0.0000
invoice_10.pdf          invoice_6_ak.pdf       same_entity   0.9816
invoice_12_ak.pdf       invoice_27.pdf         different     0.0574
invoice_12_ak.pdf       invoice_6_ak.pdf       different     0.3914
invoice_27.pdf          invoice_6_ak.pdf       review        0.5031
```

No regular expressions, no field mapping, no schema. Progress prints to stderr while it runs, so a slow job never looks like a hang.

**One confirmed match, two queued for a human, three ruled out.** Now look at whether it was right.

---

## 2. The one it got wrong

Three of these four invoices are billed to the same person. The engine found one of those pairs, queued another, and ruled the third out entirely.

```python
for d in report.decisions:
    print(d["a"], d["b"], d["identity"], d["score"], d["factors"])
```

```text
invoice_10  vs invoice_6_ak    same_entity  0.9816   name=1.0  name_tf=1.0000
invoice_10  vs invoice_12_ak   review       0.7500   name=0.8  name_tf=0.6713
invoice_12_ak vs invoice_6_ak  different    0.3914   name=0.8  name_tf=0.6713
```

Every pair involving `invoice_12_ak` sits at `name_tf` **0.6713**, under the 0.75 gate. The cause is one word: that invoice writes the customer's name with an **honorific prefix** and the other two do not.

That is the third time this shape has appeared in arche, and it is worth naming because you will hit it too:

| Lane | One source adds | The other does not |
|---|---|---|
| places | a trailing region — `Petra (Jordan)` vs `Petra` | |
| products | a leading publisher — `vivendi-universal games inc swat 4` vs `swat 4` | |
| people | a leading honorific — `MRS <name>` vs `<name>` | |

In each case the extra token is not part of the identity, and in each case it does two kinds of damage at once: it dilutes agreement between records of the same thing, and it manufactures agreement between different things that share the affix.

The engine did not merge on a name it could not justify, which is correct behaviour on the evidence it had. It also did not find a match that a human would. **Both of those are true**, and a tutorial that showed you only the 0.9816 would be selling you something.

---

## 3. Each document, on its own terms

```python
from arche.doc import parse

doc = parse("data/doc_bench/invoice_6_ak.pdf")
doc.info.producer.family   # 'enterprise-report'
doc.info.author            # the issuing company, straight from the PDF header
doc.info.page_count        # 1
```

The producer tells you how a file came to exist — `browser-print` means a human printed it, `html-renderer` means a server rendered it, `enterprise-report` means a reporting system emitted it. Different provenance, different trust, no cryptographic manifest required.

Treat every one of those fields as a **claim by the file**. `producer` and `author` are trivially forged by anyone who can write a PDF.

---

## 4. Which rules apply, without you typing a country

```python
for doc, j in report.jurisdictions.items():
    print(doc, j["country"] or "ABSTAIN", j["reason"])
```

```text
invoice_12_ak.pdf  DE        strongest signal registrar.handelsregister, 79% of evidence
invoice_10.pdf     ABSTAIN   US leads but only on weak or corroborating evidence
invoice_27.pdf     ABSTAIN   US leads but only on weak or corroborating evidence
invoice_6_ak.pdf   ABSTAIN   US leads but only on weak or corroborating evidence
```

One document names its own jurisdiction — a German commercial register entry is close to conclusive. **Three abstain**, because a currency symbol and a timestamp are not enough to choose a legal regime, and guessing would be worse than declining.

An explicit `jurisdiction=` always wins, and any disagreement with the document's own evidence is recorded in `report.jurisdiction_conflicts` rather than left silent.

---

## 5. A typed record instead of a dict

```python
from pydantic import BaseModel, Field
from arche.doc import parse, extract

class Invoice(BaseModel):
    email: str = Field(description="contact email")
    customer: str = Field(description="the person billed")

result = extract(Invoice, document=parse("data/doc_bench/invoice_6_ak.pdf"))
```

```text
result.data                       Invoice(email='erik…', customer='Andr…')
result.fields["email"].source     'detector'      span (368, 391)
result.fields["customer"].source  'extractor'
result.unresolved                 []
```

`result.data` is a **validated instance**, not `dict[str, object]`. And every field says where it came from: `email` was found by a structure-validated detector and carries a span you can index back into the text; `customer` was recognised by a model and carries a confidence.

That distinction is the point. A value a detector validated and a value a model guessed are not equally trustworthy, and `unresolved` names what could not be filled rather than inventing it.

---

## 6. Out, in whatever shape you need

```python
report.to_csv("invoices.csv")     # utf-8-sig, so Excel opens it correctly
report.to_json()                  # records, verdicts, timing, errors
header, rows = report.to_rows()   # the primitive everything else sits on
```

```text
document,jurisdiction,producer_family,address,email,name,national_id,organisation,phone,detections,parse_seconds
invoice_10.pdf,,enterprise-report,5151**********,,ANDR********,0832***,Sher**********,86-0******,PII-…
invoice_12_ak.pdf,DE,enterprise-report,Regi**********,andr**********,MRS ******,,Cond**********,7263…
```

`to_rows()` is deliberately public: pandas, Google Sheets, BigQuery and Excel are each three lines of your own code on top of it, with no dependency and no authentication for this library to own.

```python
import pandas
header, rows = report.to_rows()
pandas.DataFrame(rows, columns=header)
```

**Masking is the default on every path.** `reveal=True` when you need real values, and that choice is explicit rather than a flag you forgot.

---

## 7. Something you can check next year

```python
report.decisions[0]["decision_id"]
# 'dec:sha256:6905b79403b22a17dc471dd2d054882a30ba314c7230e3af9845b27a6d146238'
```

A content hash over the evidence and the pinned inputs. No timestamp, no randomness — anyone holding the same inputs recomputes the same id. That is what makes a verdict checkable later rather than merely stored, and it is why the inputs that *change* a decision are named in the pins.

---

## What you have, and what you do not

**You have** four files turned into typed records, verdicts with the evidence behind them, jurisdictions proposed from the documents themselves, and a decision you can re-verify.

**You do not have** a system that found every true match. It missed one, for a reason it showed you rather than hid. When that happens the fixes are ordinary and in that order: check what the extractor put in the `name` field, look at `name_tf` to see whether the shared tokens were rare enough to earn a merge, and work the review queue — which exists precisely because the alternative is a merge nobody can defend.

If a number on this page does not reproduce on your machine, that is a bug and we want the issue.

*Next: [the document lane](../concepts/document-lane.md) for what decides what · [matching products](products.md) for the same engine on catalogues.*
