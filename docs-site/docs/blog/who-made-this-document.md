# Who made this document?

*Seven real PDFs, zero signatures, and why "verify this file" is the wrong question.*

---

I checked seven real PDFs on my laptop. Four invoices from unrelated companies, a bank statement, a payslip, a hosting invoice. Ordinary documents, the kind that arrive by email every week.

**None of them carries a digital signature.** No PAdES signature dictionary. No XMP packet. No C2PA content credential. Zero out of seven, and the check takes four lines:

```python
raw = open(path, "rb").read()
b"/Sig" in raw or b"adbe.pkcs7" in raw    # False, every time
```

That number is the whole problem with how document verification is usually discussed. The tooling starts at cryptographic signatures, and almost nothing in circulation has one.

---

## "Verify" is four different questions

When someone asks whether a document is real, they could mean any of these, and they have wildly different strengths.

| | The claim | How hard to fake |
|---|---|---|
| **0** | The file says who made it | Trivial. Anyone who can write a PDF can write any `author` they like. |
| **1** | The producer *family* is consistent with the claim | Easy, but you have to think about it |
| **2** | The structural fingerprint matches the claimed tool | Hard to fake by accident |
| **3** | It carries a valid cryptographic signature | Hard, in the good way |
| **4** | The signer resolves to a real, known organisation | Hard, and the only one that answers the actual question |

Most products pick rung 3 and call it verification. Rung 3 is genuinely strong and it applies to almost nothing you will ever receive.

---

## What rung 0 gives you, for free

Every PDF states what made it, and arche reads it:

```python
from arche.doc import parse

doc = parse("invoice.pdf")
doc.info.author              # 'Condor Flugdienst GmbH'
doc.info.producer.family     # 'enterprise-report'
```

Across the seven files:

```text
invoice_12_ak.pdf   author='Condor Flugdienst GmbH'   iText          enterprise-report
invoice_10.pdf                                        PDFlib         enterprise-report
invoice_27.pdf                                        Skia/Chromium  browser-print
Monzo statement                                       Skia/Chromium  browser-print
Invoice-PEDHCF.pdf                                    WeasyPrint     html-renderer
Paystatement.pdf                                      Telerik        enterprise-report
```

That is more useful than it looks. `Chromium` means a human pressed print in a browser. `WeasyPrint` means a server rendered HTML. `iText`, `PDFlib` and `Telerik` mean an enterprise reporting system emitted it.

So a bank statement whose producer says a human printed it from a browser is worth a second look. That is not proof of anything, but it is a question worth asking. It is rung 1, and it costs nothing.

**And every one of those fields is forgeable.** We put that sentence on every surface that touches this, because the failure mode is someone building an approval flow on `author`.

---

## Rung 2 is the interesting gap

Tools leave structural fingerprints beyond the metadata they declare: object ordering, cross-reference table style, how fonts are subsetted, whether streams are compressed and how. A PDF that *says* `Adobe Acrobat` but is laid out exactly the way `ReportLab` lays things out is telling you something the metadata is not.

That is real forensics, cheap to compute, and needs no manifest from anybody.

We have not built it, and the reason is the reason for most things we have not built: **we have not measured its false-positive rate.** Documents get re-saved, flattened, merged and passed through mail gateways, and each of those rewrites the structure without anything sinister happening. A provenance signal that cries wolf on every forwarded invoice is worse than no signal, because people learn to ignore it.

The gate is a labelled corpus with known producers, including deliberately re-saved files. Until that exists, building it would be guessing with extra steps.

---

## Two distinctions that matter more than the cryptography

**Integrity is not authenticity.** A valid signature proves the bytes have not changed since they were signed. It says nothing about whether the signer is who they claim to be. Those are different questions and the second one needs a trust anchor outside the file.

**Issued by is not belongs to.** A payslip is *issued by* an employer and *about* an employee. An invoice is issued by a vendor and about a customer. "Who does this document belong to" quietly asks both at once, and they have different failure costs. Getting the issuer wrong is a fraud problem, getting the subject wrong is a privacy problem.

We keep them apart. Provenance answers the first. The identity lane answers the second.

---

## The rung that is actually ours

Here is the reframe that made this tractable.

`author='Condor Flugdienst GmbH'` is not a fact. It is a **reference to an organisation**. A string that points at something in the world and may or may not be accurate. Deciding which real-world entity a reference denotes is precisely what this engine does, for people, places, publications and products.

So "who issued this document?" is an entity-resolution question wearing a security costume:

1. Extract the issuer reference. From metadata, or from the letterhead
2. Resolve it against a company registry
3. Report the verdict *with its evidence*, and abstain when the evidence is thin
4. Sign the decision so it can be re-checked

Every step there is something we already measure. Step 2 is a crosswalk against a registry, which is what the [places benchmark](../concepts/place-benchmark.md) and the [product lane](../tutorials/products.md) do. Step 3 is the gate that already refuses to merge `Dennis Aibuedefe Irorere` with `Dennis Irorere` on a common given name. Step 4 is `attest`.

That path is measurable with benchmarks we already run. Rung 3 is not, because we have no signed documents to test against.

---

## What we will and will not ship

**Shipped.** Metadata reading, producer classification, and the sentence *"metadata is a claim, not a verification"* everywhere it appears. And one quietly important thing: metadata is now **scanned and masked** like any other text, because a bank statement's `Title` carried an account fragment and a flight confirmation's `Subject` carried a real booking reference. If your pipeline redacts the body and ignores the header, it has been leaking.

**Typed, not built.** `ContentCredentials` ships as a type with an honest empty state. Its `ai_generated` field is deliberately **tri-state**: absence of a manifest yields *unknown*, never *human-authored*. That is the most dangerous possible reading of an empty field and we refuse it in the type system.

**Gated on evidence, not on a date.** We will read signatures and C2PA manifests when we hold five real documents that carry them. An untestable trust feature is worse than none, because it invites reliance it has not earned.

**Not shipping.** A boolean `verify()`. There is no rung at which a single true/false is honest, and a function with that name would be used as though there were.

---

## The same ladder is everywhere

None of this is really about PDFs. An API response, a database export, a CSV someone emailed you. Each has a self-declared origin, a structural signature, an optional cryptographic one, and an issuer who may or may not resolve to a real entity.

The document case is just where the question is easiest to see, because the file goes to the trouble of telling you who made it, and you get to decide whether to believe it.

*Related: [the document lane](../concepts/document-lane.md) · [three PDFs and a question](three-pdfs-and-a-question.md) · [re-verify a decision](../how-to/re-verify-a-decision.md)*
