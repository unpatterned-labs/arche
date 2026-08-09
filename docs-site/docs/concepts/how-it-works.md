# How arche works

*One record, all four verbs, start to finish. Written for a reader who has never done entity resolution.*

---

Two clinics in Kano file a monthly return with the same health ministry. One of them writes a patient's name **Fatima Abdullahi**. The other writes **Fatuma Abdulahi**. Both record the same eleven-digit National Identification Number. A person glancing at the pair says "same woman, spelled twice" without effort. A database says nothing at all, because the strings do not match. And a system that simply merged every pair sharing a number would, sooner or later, merge two different people because somebody mistyped a digit.

arche lives in the space between those answers. It describes itself in four verbs — **detect · resolve · protect · attest** — and this page runs that one record through all four, in order, with the real output of every step printed underneath it. Nothing below is pseudocode; every block was executed to produce the text that follows it.

<div class="flow" markdown>
<div class="flow__step" markdown>
<span class="flow__n">01</span>
<span class="flow__verb">detect</span>
<span class="flow__what">Find the personal data in the text, and **name the law that classifies it**.</span>
</div>
<div class="flow__step" markdown>
<span class="flow__n">02</span>
<span class="flow__verb">protect</span>
<span class="flow__what">Apply the action that law requires, **before the text goes anywhere else**.</span>
</div>
<div class="flow__step" markdown>
<span class="flow__n">03</span>
<span class="flow__verb">resolve</span>
<span class="flow__what">Decide whether two records are the same person, **and show the evidence**.</span>
</div>
<div class="flow__step" markdown>
<span class="flow__n">04</span>
<span class="flow__verb">attest</span>
<span class="flow__what">Sign the decision, **so someone who was not there can check it**.</span>
</div>
</div>

---

## 1 and 2. Detect and protect

These are two verbs and one function call, which is the honest way to present them: arche will not hand you a list of discovered identifiers without also telling you what the applicable statute says to do with them.

```python
from arche import Pipeline

result = Pipeline(jurisdiction="NG").process(
    "Fatima Abdullahi, NIN 12345678901, phone 0803 555 7890."
)

for d in result.detections:
    print(f"{d.category:12} {d.sensitivity_tier.value:9} {d.regulatory_citation}")

print()
print(result.redacted_text)
print([(o.category, o.action) for o in result.policy_outcomes])
```

```text
PII-2-NIN    high      NDPA-2023 s.30, NIMC Act s.27
PII-1-NAME   moderate  NDPA-2023 s.30
PII-1-NAME   moderate  NDPA-2023 s.30
PII-3-PHONE  moderate  NDPA-2023 s.30

NAME_099000a2 NAME_e38a0fcd, NIN [NIN], phone PHONE_d3100c11.
[('PII-2-NIN', 'mask'), ('PII-1-NAME', 'tokenize'), ('PII-1-NAME', 'tokenize'), ('PII-3-PHONE', 'tokenize')]
```

Read the first three columns as a sentence. `PII-2-NIN` is a label from the Pan-African PII Taxonomy, a published list of categories rather than a name we invented at the call site. `high` is a sensitivity tier. **`NDPA-2023 s.30, NIMC Act s.27` is the part most detection libraries do not have**: the section of the Nigeria Data Protection Act, and of the NIMC Act that governs the National Identification Number specifically, under which that field is being treated. `Pipeline(jurisdiction="NG")` loaded the Nigerian statute pack; passing `"ZA"` would have loaded POPIA and produced different sections and, where the two laws differ, different actions.

The redacted line shows two of the six actions a statute may choose. The NIN was **masked** — replaced by a category placeholder, `[NIN]`, and gone for good. The name and the phone were **tokenized** — replaced by a deterministic, non-reversible token. The difference matters more than it looks: the same phone number produces the same `PHONE_d3100c11` in every document you process with the same salt, so you can still count how many returns mention one patient without ever holding their number. A mask throws that link away; a token keeps the link and drops the value. Which one a field gets is the statute's call, not the detector's.

Now the second clinic's line, through the same pipeline:

```python
from arche import Pipeline

pipeline = Pipeline(jurisdiction="NG")

for line in ("Fatima Abdullahi, NIN 12345678901.",
             "Fatuma Abdulahi, NIN 12345678901."):
    print(pipeline.process(line).redacted_text)
```

```text
NAME_099000a2 NAME_e38a0fcd, NIN [NIN].
Fatuma NAME_ae1ee794, NIN [NIN].
```

**"Fatuma" came through in the clear.** Name detection on the base wheel is a lexicon of African given names and surnames, and this spelling is not in it. That is not a bug to be embarrassed about so much as the first thing a newcomer needs to internalise: protection can only act on what detection proposed, so the coverage of the detectors *is* the strength of the guarantee. The full inventory of what is and is not detected today is on [the lifecycle page](lifecycle.md), and it is worth reading before you deploy anything.

---

## 3. Resolve

Resolution asks a different question from detection. Not "what is in this text" but "are these two records about the same person". arche's answer comes back as a decision plus the numbers that produced it.

```python
from arche.canonical import Reference
from arche.resolve import pairwise

ISSUER_KEY = b"an issuer secret of at least 32b"

a = Reference.from_record({"id": "lagos-001", "full_name": "Fatima Abdullahi",
                           "national_id": "12345678901"})
b = Reference.from_record({"id": "kano-774", "full_name": "Fatuma Abdulahi",
                           "national_id": "12345678901"})

decision = pairwise(a, b, issuer_key=ISSUER_KEY)
print("identity :", decision.identity)
print("action   :", decision.action)
print("score    :", decision.score)
print("factors  :", decision.factors)
print("gate     :", decision.gate)
```

```text
identity : same_entity
action   : merge
score    : 1.0
factors  : {'name': 0.9053, 'national_id': 1.0, 'name_tf': 0.0}
gate     : {'distinctive_cleared': True, 'clearing_signal': 'national_id', 'floor': 0.75}
```

A `Reference` is one record's worth of claims about one thing, and `from_record` turns an ordinary dictionary into one. The `factors` are the per-field evidence: the two names are 0.905 similar, the two national IDs are identical, and `name_tf` — a measure of how *distinctive* the words the names share are, weighted against how common those words are in the population — is **0.0**, because "Fatima Abdullahi" and "Fatuma Abdulahi" share no token at all once you compare them literally. The shared identifier is carrying this decision on its own, and the `gate` says so out loud: `clearing_signal: national_id`.

Three outcomes are possible on the `identity` axis: `same_entity`, `different`, and `review`. The third one is the point of the product.

```python
from arche.canonical import Reference
from arche.resolve import pairwise

ISSUER_KEY = b"an issuer secret of at least 32b"

# The same NIN, and nothing else to go on.
c = Reference.from_record({"id": "ussd-9", "national_id": "12345678901"})
d = Reference.from_record({"id": "ussd-4", "national_id": "12345678901"})

thin = pairwise(c, d, issuer_key=ISSUER_KEY)
print("identity :", thin.identity)
print("action   :", thin.action)
print("score    :", thin.score)
print("factors  :", thin.factors)
print("gate     :", thin.gate)
```

```text
identity : review
action   : no_op
score    : 0.9999
factors  : {'national_id': 1.0}
gate     : {'distinctive_cleared': True, 'clearing_signal': 'national_id', 'floor': 0.75}
```

Look at that carefully, because it surprises almost everyone. The two records share an exact national ID. The score is **0.9999**. The distinctive-signal gate **cleared**. And arche still refuses to say they are the same person. `same_entity` requires three things at once — the score, a distinctive signal, and *at least two fields that actually agreed* — and here only one field was ever compared, so the third condition fails and the decision lands in `review` with a recommended action of `no_op`. One number is not a person. If that identifier was mistyped, or belongs to a shared household account, or was reused by a registry, there is nothing in these two records that would catch it.

Abstention is a feature that costs something, and it is worth being clear about the trade: arche will hand you pairs a naive join would have merged silently, and a human has to look at them. In exchange, a merge that does come back carries evidence you can read, and a wrong merge is the expensive failure — it fuses two people's records, and unpicking that afterwards is very much harder than glancing at a queue.

---

## 4. Attest

The last verb turns a decision into something a third party can check.

```python
from arche.attest import attest, verify_attestation
from arche.canonical import Reference
from arche.resolve import pairwise
from arche.sign import generate_keypair

ISSUER_KEY = b"an issuer secret of at least 32b"
signing_key = generate_keypair()

a = Reference.from_record({"id": "lagos-001", "full_name": "Fatima Abdullahi",
                           "national_id": "12345678901"})
b = Reference.from_record({"id": "kano-774", "full_name": "Fatuma Abdulahi",
                           "national_id": "12345678901"})

signed = attest(pairwise(a, b, issuer_key=ISSUER_KEY), signing_key)

checked = verify_attestation(signed.compact, public_key=signing_key.public_key)
print("valid       :", checked.valid)
print("trusted     :", checked.trusted)
print("key_source  :", checked.key_source)
print("decision    :", checked.claims["decision"])
print("reproducible:", checked.claims["reproducible"])
print("raw names in the attestation:",
      "Fatima" in signed.compact or "Abdullahi" in signed.compact)
```

```text
valid       : True
trusted     : True
key_source  : pinned
decision    : same_entity
reproducible: True
raw names in the attestation: False
```

Four fields in that output are doing separate jobs, and conflating any two of them is how people end up trusting something they should not.

**`valid` says the signature matches the key that was used to check it. `trusted` says that key came from somewhere the caller controls** — here, a `public_key` passed in explicitly, which is why `key_source` reads `pinned`. Had we verified without passing a key, arche would have fallen back to the key the token names *about itself*, and an impostor who signs their own forgery names their own key too. That token would come back `valid=True, trusted=False`. Check `trusted`, never `valid`, whenever the signature is meant to prove *who* signed. [The attest page](attest.md) shows the forged case side by side with the genuine one.

**`reproducible: True` is a claim about replay**, and it is derived from what actually fed the decision rather than from the signing format. The engine's own path is deterministic, so this decision replays byte for byte. Had the two records been extracted by a hosted language model, the extraction step could not be replayed by a stranger, and the attestation would say `reproducible: False` instead of quietly implying otherwise.

**And no raw name is in the artefact.** An attestation carries the decision, the numeric evidence, the gate, and content-addressed identifiers — not the person. That is what makes it shareable with a regulator, an auditor, or a counterparty who has no business seeing the underlying records.

---

## What you have at the end

One paragraph, because this is the whole claim. You started with a line of text and finished with: a list of the personal data it contained, each tagged with the statute section that governs it; a copy of the text safe to pass on, with the identifiers masked or tokenised according to that statute; a decision about whether two records are the same person, with the per-field evidence and the gate that permitted it; and a signature over that decision that a stranger can verify offline, containing no personal data at all.

---

## What this page did not show

It showed one pair. Real work is usually two *lists* — `resolve.crosswalk` links them at scale, and for places it enforces a geographic veto that demotes a pair to `review` when the coordinates are too far apart no matter how well the names match. It used arche's built-in field names; a [declaration](../how-to/declare-your-schema.md) lets you keep your own schema and state what your fields mean. It said nothing about sending data to a third party, which is what `arche.guard.EgressGuard` exists to refuse by default.

It also showed detection working. Detection is where arche's coverage is most uneven, and this page deliberately left the inventory to a page that can be exhaustive about it.

- [The identity lifecycle](lifecycle.md) — verb by verb: what ships, what is gated, and what does not exist. The page to read before you rely on any of the above.
- [Architecture](architecture.md) — how the code is layered, and which components are permitted to conclude anything.
- [Attest: the signature on the decision](attest.md) — what a signature does and does not prove.
- [A representation engine, not an inference engine](representation-engine.md) — why `name_tf` was 0.0, and why that is the interesting number.
- [Entity resolution tutorial](../tutorials/entity_resolution.md) — the same ideas with your hands on the keyboard.
