# Re-verify a decision

Anyone can produce a match. The question that decides whether a match is usable is a different one: **six months from now, can someone who does not trust you check it?**

This page is the operational answer. It covers the three kinds of decision arche produces — crosswalk edges, person decisions, and document-derived decisions — and ends with the checklist for the person on the other side, who has been handed a signed artifact and has to decide what it is worth.

For the *semantics* of the signature, read [Attest](../concepts/attest.md); for the wider question of what "verify a document" even means, read [Who made this document?](../blog/who-made-this-document.md). This page is the how.

---

## Re-running is not re-verifying

The distinction the rest of this page rests on:

**Re-run** means: you have the inputs and the software, you execute it again, and you get an answer. If the answer differs you learn that something changed, but not what.

**Re-verify** means: you have an artifact and you can establish, independently, that it is the artifact it claims to be — produced from those exact inputs, by that version of that engine, under those thresholds.

The mechanism is that every decision has a **reproducible address**: `decision_id`, a hash over the rounded evidence and the pinned versions. No timestamp, no raw float, no run counter. Same inputs, same id, byte for byte. Change any input that mattered — a score, a threshold, a parser version — and the id moves.

That gives you a property that plain determinism does not: **you cannot quietly change what a decision was made from and keep its identity.**

---

## Path 1 — Crosswalk edges (the fully open case)

Reconciliation output is the strongest case, because crosswalk edges carry ids and numeric evidence only — never raw attribute values — so their ids are **keyless** content hashes. Anyone holding the artifact can recompute them. No secret required.

```python
from arche.resolve.reconcile import reconcile, sign_edges
from arche.sign import generate_keypair

res = reconcile(a, b, comparators=[{"field": "name", "kind": "name"},
                                   {"field": "city", "kind": "text"}])

for e in res["matches"]:
    print(e["a_id"], e["b_id"], e["decision"], e["score"], e["decision_id"])
```

```text
a1 b1  match   0.8     xwd:sha256:829f1e0d388f9e99a41f71bf1bed72beb23d3550d7b1b697fdc0b95e9211e294
a2 b2  match   0.8     xwd:sha256:5640afb3cc530517c835619bb3260a3e833bec050102386600108d25c271824f
a2 b1  review  0.6711  xwd:sha256:9b79d32c82cf545f64d438ca3a885ebb74f60f47ef301d1ca02335213e021b83
```

Sign the edges you want to stand behind:

```python
kp = generate_keypair()
signed = sign_edges(res, private_key=kp.private_key, kid=kp.did_key)
```

### What the recipient does

They have the JWS and your public key, and nothing else. Two independent checks:

```python
from arche.ids import content_hash
from arche.sign import verify as jws_verify

r = jws_verify(signed[0]["jws"], public_key=issuer_public_key)
print(r.valid, r.trusted, r.key_source)      # True True pinned

payload = r.payload
body = {k: v for k, v in payload.items() if k != "decision_id"}
pins, schema = body.pop("pins"), body.pop("schema")
recomputed = content_hash({"schema": schema, **body, "pins": pins}, prefix="xwd")

print(recomputed == payload["decision_id"])  # True
```

The first check — the signature — establishes **who** and **unaltered since signing**. The second — recomputing the id from the payload with the id removed — establishes that the id is the honest address of *this* evidence, and not an id lifted from some other, more favourable decision.

Both fail on tampering, and they fail differently, which is the useful part:

| What was tampered with | Signature | Recomputed id |
|---|---|---|
| Nothing | `valid=True` | matches |
| A score, inside the signed payload | `valid=False` | — |
| A score, then re-signed with the attacker's key | `valid=True`, **`trusted=False`** | **mismatch** |

That middle row is why `sign_edges` puts the evidence *and* its address under one signature. An attacker who controls their own keypair can always produce a valid signature over whatever they like; what they cannot do is make the arithmetic agree.

---

## Path 2 — Person decisions (the keyed case)

Person decisions are different, and the difference is not cosmetic. `reference_id` and `decision_id` are derived from the person's attributes. As a plain hash, a short attribute space is **brute-forceable**: an attacker who suspects the record is for a given name and phone number can confirm it by hashing candidates until one matches.

So the ids are keyed with an issuer HMAC key, and the shape of the id says which you have:

```text
keyless : dec:sha256:24f73e888f83fdbfe1d9705842a2b5bcb0c300d9ed6d2bd13d21db43d7283758
keyed   : dec:hmac-sha256:35217f13aa6a0ca8da56d6de029f8a0f95d333158ab4b4b25261ddcfa648fdbb
```

`attest()` refuses to sign a keyless decision, rather than trusting you to notice:

```text
refusing to attest a keyless decision: its reference_id/decision_id are sha256
hashes of the person's attributes and can be brute-forced back to the source
records, so the signed artifact would NOT be PII-free.
```

The key-holder gets full replay — either by re-running, or by recomputing the id from the evidence alone:

```python
from arche.ids import decision_id as compute_decision_id

rec = compute_decision_id(
    reference_id_a=d.reference_id_a, reference_id_b=d.reference_id_b,
    decision=d.identity, factors=d.factors, gate=d.gate, vetoes=d.vetoes,
    jurisdiction=d.jurisdiction, pins=d.pins, key=ISSUER_KEY,
)
rec == d.decision_id      # True — and False with any other key
```

### State this plainly: a third party cannot recompute a keyed id

This is the honest limit of the person lane, and the reason it gets its own heading rather than a footnote.

The privacy property and the open-verification property are **in tension**, and arche resolves that tension in favour of privacy. Keying the id is what stops a stranger brute-forcing it back to a named human. The same keying is what stops that stranger recomputing it. You cannot have both from one number.

So for a person decision, an outside verifier gets:

- **the signature** — who issued it, and that nothing has been altered since
- **the full numeric evidence** — every factor, the gate, the vetoes, the thresholds
- **`reproducible`** — whether everything that fed the decision could itself be replayed
- **not** the ability to independently recompute the id

```python
r = verify_attestation(signed.compact, public_key=issuer_public_key)
# valid=True  trusted=True  key_source=pinned  reproducible=True
```

```text
decision       = same_entity
action         = merge
basis          = corroborated
score          = 1.0
jurisdiction   = NG
factors        = {'email': 1.0, 'name': 0.9636, 'name_tf': 0.2801, 'phone': 1.0}
gate           = {"clearing_signal": "phone", "distinctive_cleared": true, "floor": 0.75}
```

A verifier can read that `phone` was the clearing signal, that the floor was `0.75`, and that `name` alone at `0.9636` would not have cleared it. That is a reviewable decision even though the id is opaque — they are checking your reasoning, not just your arithmetic.

And the artifact is genuinely free of the underlying values:

```text
'Amara'              present: False
'Nwosu'              present: False
'amara@example.com'  present: False
'2348012345678'      present: False
```

---

## Path 3 — Document decisions

A decision derived from a document has a failure mode the other two do not: the record was not given to the engine, it was **extracted**, and extraction is version-dependent. A parser upgrade changes the text, which changes the record, which changes the verdict.

A signature over such a decision, with the extraction unrecorded, is worth very little — it proves the verdict was not altered while saying nothing about where the verdict came from. **A signed wrong merge with opaque extraction provenance is worse than an unsigned heuristic**, because it lends institutional legitimacy to something the reader cannot inspect.

So every parse records what produced it, and those facts enter the pins **before** `decision_id` is computed:

```python
report = resolve_documents("data/doc_bench/*.pdf")
report.provenance["invoice_10.pdf"]
```

```text
parser           docling
parser_version   2.110.0
artifact_sha256  4650ea6b8501217404b46a07f8b4acff3f49b025d9b8cc8931c1e17083f6bb3e
text_sha256      5312d158b979a187ad5f141294c52c16af704e8d94582f2a2e25cdf4f9af84ce
ocr              None
```

Each field earns its place by what breaks without it. `artifact_sha256` because a filename is not an identity — two files called `invoice.pdf` are not the same document, and the same file renamed is. `parser_version` because a decision that does not name its parser cannot explain why it differs from the same decision made last year. `text_sha256` because every cited span indexes into *that* rendering, and a citation without it silently points at the wrong characters after any re-parse — which is worse than pointing at nothing. `ocr` because it changes the text for identical bytes.

Because these are inside the hash, the id moves when any of them moves: upgrade docling, re-run, get the same verdict — and be able to tell that it was **not the same decision**.

### The check the recipient actually runs

`artifact_sha256` is a full, untruncated SHA-256 in lowercase hex, specifically so that the standard tool agrees with it. Whoever received the PDF runs:

```console
$ sha256sum invoice_10.pdf
4650ea6b8501217404b46a07f8b4acff3f49b025d9b8cc8931c1e17083f6bb3e *invoice_10.pdf
```

and compares it, by eye, to the string in the report. Same file, or not the file. No arche installation required to perform this check — `shasum -a 256` and PowerShell's `Get-FileHash` do just as well.

---

## You have been sent a signed decision. Now what?

In order, because each step is worthless if the one above it failed:

**1. Does the signature verify, and against whose key?** `valid` and `trusted` are different questions and the gap between them is where impostors live. `valid=True, trusted=False` means the artifact is internally consistent and signed by *somebody* — the key came from the token's own `kid`, which the signer chose for themselves. Anyone can sign a claim with their own keypair. Check `key_source`: `pinned` (you supplied the key), `resolver` (your own resolver found it), or `self-asserted` (it named itself).

```python
r = verify_attestation(compact, public_key=the_key_you_already_trusted)
if not r.trusted:
    ...   # you have verified a signature, not an issuer
```

**2. Is the id the honest address of this evidence?** For crosswalk edges, recompute it. For keyed person decisions you cannot, and should rely on step 1 instead — knowing that is the point of this page.

**3. Does it claim to be reproducible?** `reproducible` is not decoration. It is `False` when something that fed the decision could not itself be replayed — a hosted model's extraction, for instance. The decision maths still replays; the extraction does not, and the artifact says so rather than letting you assume otherwise.

**4. For a document decision, is this the file?** Hash it and compare, as above.

**5. Read the evidence, not just the verdict.** `gate` names the clearing signal and the floor. `vetoes` records what was blocked and why. `factors` gives every component score. A merge at `0.76` against a floor of `0.75` is a different fact from a merge at `1.0`, and both say `same_entity`.

---

## Where the guarantee stops

Worth stating explicitly, because a verification page that only lists what works is a sales page.

**A signature is not a truth claim.** It says a named key asserted this decision and it has not been altered. It does not say the decision is correct. arche can reproducibly, verifiably, signedly merge two records that are not the same person.

**Reproducibility is not correctness either.** A pinned wrong threshold reproduces perfectly.

**Keyed ids are pseudonymous, not anonymous.** Under NDPA, POPIA and GDPR an HMAC pseudonym derived from personal data is still personal data. It resists brute force; it is not exempt from the regime.

**Provenance records what happened, not whether it should have.** `artifact_sha256` proves you read that file. It says nothing about whether the file was genuine — that is [a different ladder entirely](../blog/who-made-this-document.md), and arche sits on a lower rung of it than most people assume when they hear the word "verify".

---

## See also

- [Attest: the signature on the decision](../concepts/attest.md) — `valid` vs `trusted`, what is signed, selective disclosure
- [Who made this document?](../blog/who-made-this-document.md) — the provenance ladder, and which rung is ours
- [The document lane](../concepts/document-lane.md) — proposers and deciders
- [Verify a merge against an external source](verify-with-external-sources.md) — corroborating a decision against third-party data
