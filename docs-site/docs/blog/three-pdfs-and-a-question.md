# Three PDFs and a question

*What document intelligence actually has to get right, and the part everyone skips.*

---

A bank statement, an invoice, a payslip. Three PDFs on a laptop, from three companies that have never heard of each other. Different layouts, different spellings of the same name, no shared identifier anywhere.

Are they the same person?

Every extraction tool on the market will happily pull fields out of those three files. Almost none of them will answer the question, and the gap between those two things is the whole subject of this post.

---

## A fortnight of documents, and the two things nobody checked

If that sounds abstract, it is the most ordinary experience there is. Try renting a flat.

You send three months of bank statements. Two payslips. A photo of your passport. A utility bill as proof of address, which is a strange sentence when you think about it, because the bill proves the electricity company believes you live there and nothing more. An employer reference. A credit check that pulls yet another version of your name and address from somewhere you have never seen.

Six documents, five of them about you, one of them about you and your electricity. A person at the agency looks at the pile, decides it hangs together, and you get the flat.

Now list what was actually verified.

| What you sent | What was really checked | What was not |
|---|---|---|
| **Bank statement** | someone read the address off it | whether the PDF had been edited |
| **Payslip** | someone read the figure | whether that employer exists |
| **Passport photo** | it resembled you | whether it is about the same person as the payslip |
| **Utility bill** | the address matched the statement | who actually issued it |
| **Employer reference** | it was on letterhead | anything at all |
| **All six together** | the pile looked complete | **whether they are one person** |

The right-hand column is the entire subject of this post. And the bottom row is the one that should worry you, because it is the only question the pile was assembled to answer, and nothing in the process addressed it.

## Two questions, and extraction answers neither

Everything in that column reduces to two questions, and they fail in different ways.

**Who is this about?** `Dennis Irorere` on the payslip, `D. A. Irorere` on the bank statement, `Dennis Aibuedefe Irorere` on the passport. A human glances at those and moves on. A system has to decide, and deciding is not reading. Getting it wrong in the generous direction merges a stranger into your file. Getting it wrong in the strict direction means your own payslip does not count as yours, and you are asked for more documents, which is the polite version of being told you do not exist.

**Where did it come from?** Every one of those files is a PDF, and a PDF is a document format rather than a claim anybody signed. Changing a number in one takes less skill than making the coffee. The agency's defence is that the layout looked right, which is a defence against carelessness and not against anyone trying.

Both failures are quiet. Nothing crashes. The merge is confident and the forgery is neat, and either one surfaces months later as a problem that gets called something else.

And notice what happens next: you do this again for the next agency, from scratch, because none of that checking travelled with you. **Six documents, verified by eye, then discarded, then repeated.** The reason we keep doing the ritual is that nobody can hand the next party a checkable answer, so everybody re-derives an uncheckable one.

## The part that got easier, and the part that did not

Reading a PDF used to be the hard bit. It isn't any more. Layout models are good, table extraction works, and a dozen services will turn a scanned invoice into clean markdown for fractions of a cent.

So extraction stopped being the moat, and what it produces turns out to be the easy half of the problem. A field is a *reference*. A string that points at something in the world. `Dennis Irorere`. `123 Sherlorne Place`. `dennis@gmail.com`. Three references, and no statement yet about whether they point at one person.

The hard half is what the field industry calls entity resolution: deciding which references denote the same real-world thing. It is old, it is unglamorous, and it is where document pipelines quietly go wrong, because the failure mode isn't a crash, it's a confident merge nobody notices for six months.

Here is what our three PDFs actually produce:

```text
EXTRACTED RECORDS
document                    name                       organisation
--------------------------------------------------------------------
Monzo_bank_statement.pdf    Dennis A. Irorere   Monzo Bank Limited
Invoice-PEDHCF-00012.pdf    Dennis Irorere             Netlify, Inc.
Paystatement_2025-12.pdf    Dennis Irorere             Amsterheed Ltd
```

One document carries a middle name and two do not. That is the single most ordinary fact in identity data. It is also about to decide everything.

---

## The result that should bother you

```text
document a                  document b                  verdict        score
-----------------------------------------------------------------------------
Monzo_bank_statement.pdf    Invoice-PEDHCF-00012.pdf    review        0.9656
Monzo_bank_statement.pdf    Paystatement_2025-12.pdf    review        0.9974
Invoice-PEDHCF-00012.pdf    Paystatement_2025-12.pdf    same_entity   0.9903
```

**The highest-scoring pair is not a match.** `0.9974` is a review. `0.9903`. Lower. Is a merge. The ordering by score is the inverse of the ordering by verdict.

If you have ever tuned a threshold, that should make you uncomfortable, because it means the threshold was never the interesting part.

What separates them is one number the score does not show:

```text
pair                                          score   name_tf   verdict
Monzo / Invoice                              0.9656   0.6393   review
Monzo / Paystatement                         0.9974   0.6393   review
Invoice / Paystatement                       0.9903   1.0000   same_entity
```

`name_tf` is name similarity **weighted by how rare the shared tokens are**. The Monzo pairs sit at 0.6393 because `Dennis Aibuedefe Irorere` and `Dennis Irorere` do not share enough uncommon material. A merge needs agreement on something *rare*, and a shared given name is not it.

This is the same rule that stops two records called `General Hospital` merging because they have the same name, and the same one that stops two different people called `Ibrahim Musa` becoming one person. It is not a heuristic bolted on for this example; it is the shipped constant, and we have measured what happens when you lower it. The person case breaks first.

**A score is not a decision.** Most pipelines conflate the two, and that is why they merge things.

---

## What "review" is for

Two of three pairs came back `review`. It is tempting to read that as failure.

It is the opposite. The engine found both pairs, surfaced both, scored both above 0.96, and then declined to spend a merge it could not justify. A human looks at two edges instead of auditing a database later.

We measure this properly rather than reporting the flattering number. On the Leipzig Geographic Settlements benchmark. 3,054 records, four independent sources, complete ground truth. The place matcher reports:

| | |
|---|---|
| precision | 0.9862 |
| recall at auto-match | 0.7135 |
| **surfaced recall** | **0.9654** |

Recall of 0.71 looks mediocre until you notice surfaced recall is 0.97: the missing pairs are in the queue, not lost. Reporting only auto-match recall understates a system that deliberately abstains. Reporting only precision hides what it costs. So we report both, always, plus the size of the queue a human has to work.

---

## Three things a document tells you before you read it

Here is a thing almost every pipeline throws away.

```python
from arche.doc import parse

doc = parse("invoice.pdf")
doc.info.author            # 'Condor Flugdienst GmbH'
doc.info.producer.family   # 'enterprise-report'
```

Across seven real PDFs on one laptop:

```text
invoice_12_ak.pdf   author='Condor Flugdienst GmbH'   iText          enterprise-report
invoice_27.pdf                                        Skia/Chromium  browser-print
Invoice-PEDHCF.pdf                                    WeasyPrint     html-renderer
Monzo_statement     10 pages                          Skia/Chromium  browser-print
```

Three things fall out, and none of them needed a model.

**The issuer arrives for free.** `author='Condor Flugdienst GmbH'` is a high-confidence organisation sitting in the file header. The exact field an NER model is otherwise guessing at from body text, available more reliably and at zero cost.

**The producer is provenance.** `Chromium` means a human printed this from a browser. `WeasyPrint` means a server rendered it from HTML. `iText`, `Crystal Reports`, `PDFlib` mean an enterprise reporting system emitted it. Those imply very different degrees of trust in the contents, and you get it without any cryptographic manifest.

**Metadata is personal data.** A bank statement's `Title` carried an account fragment and a date range. A flight confirmation's `Subject` carried a real booking reference. If your pipeline redacts the body and ignores the header, you have been leaking for as long as you have been running.

A caveat we put on every surface that touches this: **metadata is a claim, not a verification.** `producer` and `author` are trivially forged by anyone who can write a PDF. Read it as what the file says about itself.

---

## The thing we got wrong, and why it is in this post

We ran the Nigerian detector set over a British bank statement. It reported **36 tax identification numbers**.

Every one was wrong. They were Bolt ride references, Viator transaction IDs, and a direct-debit reference. Ten-digit numbers, which is exactly what a Nigerian TIN looks like.

Three things were true at once, and separating them is the useful part:

1. **The detector was doing its job.** Without context there is no way to tell those apart on shape alone.
2. **The confidence said so.** Every one landed at 0.55, not 0.95. The number was not decoration.
3. **None of them reached the identity record.** Detection and resolution are separate boundaries. A detector may over-fire, for redaction, over-firing is the safe direction. Without that noise ever becoming evidence about who someone is.

That third point is the design. If those 22 distinct values had been mapped into the record as identifiers, a shared Bolt reference would have looked like a shared ID, and two strangers who both took an Uber would have become one person.

It also taught us something we did not expect. The obvious fix is to detect the right jurisdiction. So we measured what that would do:

```text
jurisdiction="NG"   36 false detections, and the email IS masked
jurisdiction="GB"    0 false detections, and the email is NOT masked
```

There was no UK pack. Detecting the correct jurisdiction would have taken the headline error count from 36 to zero **by switching protection off entirely**. That is the most flattering possible reading of your own data, and we nearly shipped it. What shipped instead was a conservative floor that applies when no pack covers a jurisdiction, and whose every citation says, in words, that it is not law.

---

## What we think document intelligence is

Extraction is table stakes. Buy it, borrow it, or run it locally. It is not where the risk lives.

The risk lives in the three questions after extraction:

- **Which real-world thing does this reference denote?** Not "are these strings
similar". Similar is not the same. `Rosetta` and `Roulette` are one edit apart and are not the same name.
- **What is the evidence, and what would refute it?** A merge you cannot explain
is a merge you cannot defend. Every verdict carries its factors and a content hash you can recompute months later.
- **What did the system decline to decide?** A tool that never abstains is not
confident, it is unfalsifiable.

That is the whole pitch, and it is why the answer to *"are these three PDFs the same person?"* is **one confirmed match and two cases for a human** rather than a tidy yes.

---

## Back to the flat

Run the fortnight again with the two questions answered rather than assumed.

The six documents still arrive. Each one now carries what produced it: the hash of the exact bytes, the parser and its version, the rendering that every quoted span points into. The decision that they describe one person carries its evidence, the rule that produced it, and an identifier a stranger can recompute. Where the evidence is thin, the answer is `review` rather than a confident guess, and the reviewer sees which field was thin.

Nothing there stops a determined forger, and it is worth being plain about that. What it changes is that the next agency does not start from zero. You can hand them a decision they can check instead of a pile they must squint at, and the checking is arithmetic rather than an impression of a letterhead.

That is a smaller claim than "verified documents" and it is the one that survives contact with what actually exists.

## Try it

```bash
pip install arche-core[doc]
```

```python
from arche import resolve_documents

report = resolve_documents("statements/*.pdf")
print(report.table())
```

No API key, no account, nothing leaves your machine.

Everything in this post is reproducible. The benchmarks run from `data/scripts/benchmark_leipzig.py`, and the three-PDF walkthrough is [notebook 02](https://github.com/unpatterned-labs/arche/blob/main/examples/notebooks/02_same_person_across_documents.ipynb), with every layer opened up one cell at a time in [notebook 08](https://github.com/unpatterned-labs/arche/blob/main/examples/notebooks/08_inside_the_one_call.ipynb).

If you find a number here that a re-run does not reproduce, that is a bug and we want the issue.

*Related: [Similar is not the same](similar-is-not-the-same.md) · [The part intelligence doesn't make cheaper](the-part-intelligence-doesnt-make-cheaper.md)*
