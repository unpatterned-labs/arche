# The document lane

A file on disk becomes a signed decision. This page is about what does the deciding, because that is the part that determines whether you can defend the answer.

It is deliberately **not** a five-stage pipeline diagram. Boxes and arrows suggest every stage is the same kind of thing, and they are not: some layers *propose*, one layer *decides*, and confusing the two is how a pattern-matched coincidence ends up treated as proof.

---

## Proposers and deciders

**Proposers** read evidence and offer it. They are allowed to be wrong, and they are allowed to over-fire, because nothing they say is binding.

| Proposer | Offers | How wrong it is allowed to be |
|---|---|---|
| `doc.parse` | text, tables, markdown | A scan with no text layer yields nothing, and that is an outcome, not an error |
| `doc.read_metadata` | title, author, producer, dates | Every field is a **claim by the file** — `producer` and `author` are trivially forged |
| `jurisdictions.infer` | a country, or an abstention | Abstains on thin or conflicting evidence; an explicit `jurisdiction=` always wins |
| `detect` | spans with categories and confidence | May over-fire freely — for redaction, over-firing is the safe direction |
| `extract` | names, organisations, places | Recognition, with a confidence attached, never validation |

**Deciders** act on what the proposers offered, and their output is what you are held to.

| Decider | Decides |
|---|---|
| the statute engine | what happens to each detected category, with a citation |
| the resolution gate | whether two records may merge, or must go to a human |
| `attest` | the content hash and signature over the decision |

The whole design follows from one rule: **a proposer's confidence is never sufficient for a decider's action.**

---

## What that buys, concretely

Run the Nigerian detector set over a British bank statement and it reports **36 tax identification numbers**. Every one is a Bolt ride reference or a Viator transaction ID — ten-digit numbers, which is what a Nigerian TIN looks like.

Three things are true at once, and the lane keeps them apart:

1. **The detector was right to fire.** Without context there is no way to tell those apart on shape.
2. **Its confidence said 0.55**, not 0.95. The number is not decoration.
3. **None of them became identity evidence.** The record builder consumes only the identifier categories it maps to canonical fields, and `TIN` is not one of them.

If detection and resolution were one stage, those 22 distinct values would be sitting in the record as national identifiers, and two strangers who both took a taxi would have become one person.

---

## Where the boundaries actually are

There are three, and each exists because crossing it caused a real bug.

**Between detection and identity.** A detector may over-fire; identity evidence must be earned. Detected categories reach a record only through an explicit mapping, so a noisy detector cannot quietly become a matching signal.

**Between a score and a decision.** Two documents in this repo score **0.9974** and are not merged, while a pair scoring **0.9903** is. The gate requires agreement on something *rare*, and `Dennis A. Irorere` against `Dennis Irorere` does not clear it. A score says how consistent two records look; a decision says whether anyone has earned a merge.

**Between inference and law.** `jurisdictions.infer` proposes a country from postcodes, registrars, currency and company forms. It cannot establish that a country's law *applies* to your processing — that turns on establishment, on where your data subjects are, and on sector. Selecting a jurisdiction chooses a **policy template**; it does not perform a legal analysis.

---

## The trap that shaped the design

Inference looks like an obvious win until you measure it. Before a UK statute pack existed:

```text
jurisdiction="NG"    36 false TIN detections, and the email IS masked
jurisdiction="GB"     0 false detections,     and the email is NOT masked
```

"Correcting" the jurisdiction would have taken the headline error count from 36 to zero **by switching protection off**, because a Pipeline with no statute returns text unredacted.

So inference could not ship alone. It shipped with a baseline floor that applies when an *inferred* jurisdiction has no pack — a conservative default whose every citation reads, in words, that it is not law. The measured result is 36 → 0 **and** the document still redacted.

That ordering is the point: a number that improves because a feature stopped working is not an improvement.

---

## Abstention is an output

Four of the seven real PDFs in this repo produce no jurisdiction at all. Two of three document pairs come back `review` rather than a merge. On the place benchmark, auto-match recall is 0.71 while *surfaced* recall is 0.97 — the missing pairs are queued, not lost.

None of that is failure. A system that always answers cannot be wrong in any detectable way, and a review queue is the mechanism that converts an unjustifiable merge into a human glance. What matters is that the queue is small enough to work and that every item in it says why it is there.

---

## Reading a decision afterwards

Every verdict carries the factors that produced it and a `decision_id` — a content hash over the evidence and the pinned inputs, with no timestamp and no randomness. Anyone holding the same inputs recomputes the same id.

That is what makes a decision checkable months later rather than merely stored, and it is why the inputs that *change* a decision — the frequency tables, the jurisdiction, the ruleset version — are named in the pins. An unpinned scoring input makes a `decision_id` claim a reproducibility it does not have.

---

*Next: [zero to hero with documents](../tutorials/zero-to-hero-documents.md) — the whole lane on four real invoices, in one page. Or [the architecture](architecture.md) for how the layers are wired.*
