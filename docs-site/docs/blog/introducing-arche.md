# Introducing arche

*Know what's real. An open engine for messy, multilingual data — detect, resolve, protect, attest.*

!!! warning "Status: pre-beta (v0.3.0a1)"

    `arche-core` is on PyPI for research, prototyping, evaluation, benchmarking and contribution. APIs change between alpha releases. Complete your own legal, privacy and security review before using it with real personal data.

Somewhere in a royalty system right now, a statement line reads **Damini Ogulu** and a catalogue row reads **Burna Boy**. The matching software compared the two strings, found almost nothing in common, and concluded with complete statistical confidence that these are different people. The money didn't move. Nothing was broken. Every calculation was correct.

Change the stakes and it is the same bug. A mother brings her daughter to three clinics around Kano over two years; the registers say *Fatima Abdullahi*, *Fatuma Abdullahi*, *F. Abdulahi*. Three records, one child, a fragmented immunisation history.

arche exists for that gap. It finds the entities in a document or a system, works out which real-world thing each one refers to, protects them under the law that applies, and signs every decision so it can be defended later.

This post is the practical introduction. [The part intelligence doesn't make cheaper](the-part-intelligence-doesnt-make-cheaper.md) is the argument for why it should exist; [The same clinic, three spellings](reconciling-nigerias-health-facilities.md) is the measurement on real national data.

## Install

```bash
pip install arche-core
```

The base install is pure Python, runs offline, and pulls no machine-learning dependencies. Heavy capabilities are opt-in extras: `[detect]` for GLiNER neural NER, `[doc]` for docling document parsing, `[presidio]`, `[resolve]`, `[llm]`.

## Four verbs, one worked example

Everything below was run against v0.3.0a1 and the output is what it actually printed.

### detect

```python
from arche import Pipeline

text = "Fatima Abdullahi, NIN 12345678901, fatima@example.ng, phone 0803 555 7890."
result = Pipeline(jurisdiction="NG").process(text)

for d in result.detections:
    print(f"{d.category:16} {d.sensitivity_tier.value:9} {d.regulatory_citation}")
```

```text
PII-2-NIN        high      NDPA-2023 s.30, NIMC Act s.27
PII-1-NAME       moderate  NDPA-2023 s.30
PII-1-NAME       moderate  NDPA-2023 s.30
PII-1-NAME       moderate  NDPA-2023 s.30
PII-3-EMAIL      moderate  NDPA-2023 s.30
PII-3-PHONE      moderate  NDPA-2023 s.30
```

Every detection carries a category, a sensitivity tier, and **the statute section that classifies it**. Not a generic `PERSON` label — the specific rule someone will eventually ask you about. Swap `jurisdiction` for `"ZA"`, `"KE"`, `"GH"`, or a European code and the same call loads POPIA, Kenya DPA, Ghana DPA or GDPR instead.

### protect

```python
print(result.redacted_text)

for o in result.policy_outcomes:
    print(f"{o.category:16} -> {o.action:9} {o.statute_reference}")
```

```text
NAME_099000a2 NAME_e38a0fcd, NIN [NIN], EMAIL_8e418dd8, phone PHONE_d3100c11.

PII-2-NIN        -> mask      NDPA-2023 s.30, NIMC Act s.27
PII-1-NAME       -> tokenize  NDPA-2023 s.30
PII-3-EMAIL      -> tokenize  NDPA-2023 s.30
PII-3-PHONE      -> tokenize  NDPA-2023 s.30
```

Six closed actions — `mask`, `tokenize`, `drop`, `generalize`, `audit`, `retain` — chosen by the statute pack, not by you. `tokenize` produces a deterministic pseudonym, so the same email in two systems yields the same token and can still be joined on without ever being read.

### resolve

This is the half that matters most, and the half that surprises people.

```python
from arche import resolve
from arche.canonical import Reference

a = Reference.from_record({"name": "Fatima Abdullahi", "national_id": "12345678901"})
b = Reference.from_record({"name": "Fatuma Abdulahi",  "national_id": "12345678901"})

decision = resolve.pairwise(a, b)
print(decision.identity, decision.score)
```

```text
same_entity 1.0
```

Two spellings, one national ID, one person. Now the case that matters:

```python
a = Reference.from_record({"name": "Khalid Mehmood", "national_id": "AA1111111"})
b = Reference.from_record({"name": "Khalid Mehmood", "national_id": "BB2222222"})

decision = resolve.pairwise(a, b)
print(decision.identity, round(decision.score, 4), decision.factors)
```

```text
different 0.0843 {'name': 1.0, 'national_id': 0.0, 'name_tf': 1.0}
```

**Identical names, and the answer is `different`.** The name comparator scores a perfect 1.0 and it does not matter, because the identifiers contradict each other. Two men named Khalid Mehmood on the same sanctions programme are not one man, and the evidence says so field by field.

The third answer is the important one. `resolve.pairwise` returns `same_entity`, `different`, or **`review`** — and `review` is not an error state. A pair sharing an exact national ID can still come back `review` at a score of 0.9999, when the evidence is strong but not *distinctive*. A system whose only outputs are match and no-match will quietly pick one. This one stops and says a human is needed.

### attest

One thing first. Signing a decision requires that the decision was produced with an issuer key, and arche refuses otherwise:

```python
from arche.attest import attest
from arche.sign import generate_keypair

attest(decision, generate_keypair(), mode="jws")
```

```text
ValueError: refusing to attest a keyless decision: its reference_id/decision_id
are sha256 hashes of the person's attributes and can be brute-forced back to the
source records, so the signed artifact would NOT be PII-free.
```

That refusal is the design. A decision id derived from someone's attributes is not anonymous — given a candidate list you can hash your way back to the person. Keying it makes the id an HMAC instead, so it identifies the decision without leaking its subject. Pass an issuer key and it works:

```python
from arche.attest import attest, verify_attestation
from arche.sign import generate_keypair

ISSUER_KEY = b"replace-with-a-real-32-byte-secret!"   # >= 32 bytes

decision = resolve.pairwise(a, b, issuer_key=ISSUER_KEY)

kp = generate_keypair()
signed = attest(decision, kp, mode="jws")

v = verify_attestation(signed.compact, public_key=kp.public_key)
print(v.valid, v.trusted, v.reproducible)
```

```text
True True True
```

Three different questions. `valid` — does this signature match the key? `trusted` — did that key come from somewhere *I* control, rather than one the token named for itself? `reproducible` — can this decision be replayed from its evidence? Had a language model extracted the fields, `reproducible` would read `False`, and the signature would say so.

The decision also carries a content address over its evidence and the exact representation that produced it:

```python
print(decision.decision_id)
```

```text
dec:hmac-sha256:13fbac38e770b9410bd5fcd91c33...
```

Same inputs, same key, same id — tomorrow or in five years. That is what makes a merge defensible six months later, when somebody asks why two records became one.

## Where this has been measured

We reconciled Kano State's health facility list against OpenStreetMap — 685 records against 1,723, offline, in about twenty seconds:

| Outcome | Records | Share |
|---|---|---|
| Resolved automatically | 521 | 76.1% |
| Sent to human review | 111 | 16.2% |
| No plausible candidate | 53 | 7.7% |

And before any of that, a plain dictionary lookup on exact names already solved most of the list.

Read those numbers honestly: **most of a reconciliation needs no product at all.** The value is concentrated in the boundary between "safe to merge" and "a human needs to look at this". [The full write-up](reconciling-nigerias-health-facilities.md) has the method, its five stated limitations, and the case where it demonstrably gets a match wrong.

## Why African data first

arche was calibrated on African identity data, and that was a choice about difficulty rather than market.

It is the regime where every comfortable assumption fails at once. Names have no canonical spelling and cross colonial language boundaries — the same person is Mamadou Diallo in Dakar and Muhammad Jallow in Banjul. Identifier schemes are multiple and young. Addresses are landmarks and directions rather than street numbers. Coordinates disagree by kilometres.

A system that works there works on the easy cases by construction. The reverse is not true, which is why tools built on clean Western data fail quietly the moment they meet the majority of the world. The calibration was earned in Africa; it is not the limit of where it applies.

## What we compose with, and what we don't

Presidio has strong recognizers for Western PII. GLiNER does multilingual neural NER. Splink runs Fellegi-Sunter record linkage better than we do, at greater scale, with properly estimated parameters.

arche is not competing with any of them on their own ground. What none of them ships is **the input that ground requires**: whether `Diallo` agreeing with `Jallow` counts as agreement, whether agreeing on `Ibrahim` is worth as much as agreeing on `Gyaranya`, whether eleven digits are a national ID or a phone number with the leading zero eaten by a spreadsheet.

That layer is arche's contribution, and it ships as **data you can read, diff, cite and correct** — equivalence packs, frequency tables, identifier grammars, statute mappings — rather than weights you can only retrain. [Why arche, and when to use it](../tutorials/arche_vs_alternatives.md) makes the case in full, including a fifteen-line script that shows exactly which code paths touch Splink and which do not.

## What is not built

Stated up front so nobody discovers it later.

There is **no MCP server**. Agent-facing work today means the masked `to_dict(reveal=False)` projections and `Declaration.tool_def()`, wired into your own tool layer. Clustering is not implemented — the engine returns pairwise edges, because a merge that depends on other merges cannot be signed in isolation. `Pipeline(address_parsing=True)` is accepted and ignored. Unknown jurisdiction codes fail silently rather than raising.

The [roadmap](../concepts/roadmap.md) tracks all of it, with the prerequisite that gates each item.

## Start here

```bash
pip install arche-core
```

- [Quick start](../getting-started/quickstart.md) — first result in five minutes
- [How arche works](../concepts/how-it-works.md) — the pipeline end to end, for newcomers
- [Runnable notebooks](https://github.com/unpatterned-labs/arche/tree/main/examples/notebooks) — the facility reconciliation, resolving a person across documents, and a head-to-head against a frontier model
- [The place benchmark](../concepts/place-benchmark.md) — how we measure, and how to check whether two datasets you were told are independent actually are

Apache-2.0 for the code. The datasets are CC-BY-4.0, apart from the African name-equivalence lexicon, which is CC-BY-NC-SA-4.0 and [under review](https://github.com/unpatterned-labs/arche/blob/main/LICENSING.md).

Corrections are the most valuable contribution this project receives. If you know a naming convention, an identifier format, or an address grammar first-hand, that knowledge is the qualification that matters.
