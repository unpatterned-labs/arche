# Ask an organisation for everything it holds on you

*A **Data Subject Access Request**, or DSAR, is the legal right to demand a copy of every piece of personal data an organisation holds about you, and to be told what it is doing with it. This page generates that letter: the correct statute section for the jurisdiction, the deadline the law gives the recipient, and an Ed25519 signature the receiving data protection officer can check offline.*

---

The right exists in every jurisdiction arche ships a statute pack for. Nigeria's NDPA-2023 grants it at section 34, South Africa's POPIA at section 23, Kenya's DPA at section 26(a), Ghana's DPA at section 35. On paper a citizen simply asks and the organisation has thirty days, twenty-one in Ghana, to answer.

In practice almost nobody asks, and the reason is bureaucratic rather than legal. Exercising the right means identifying which organisations hold your data, finding each one's data protection officer, drafting a request that cites the correct section of the correct statute, sending it through a channel that counts, tracking the response, and escalating to the regulator when it never arrives. Six steps, each of which quietly assumes you are a lawyer.

`arche.workflow.DSARWorkflow` does steps three and four. It drafts the letter with the right citation and the right deadline, and it signs the draft so the recipient can verify the request came from the holder of a particular key and has not been altered since. You review it and you send it. **It never sends anything itself**, see [dispatch, and why it is draft-only](#dispatch-and-why-it-is-draft-only) at the bottom of the page.

## The workflow

```python
from arche.sign import generate_keypair
from arche.workflow import DSAROrganization, DSARRequestor, DSARWorkflow

# Citizen-held key: generate once, store locally. arche never holds it.
citizen_key = generate_keypair()

workflow = DSARWorkflow(
    jurisdiction="NG",                       # resolves NDPA-2023
    requestor=DSARRequestor(
        name="Adesola Okonkwo",
        identifier_label="NIN",
        identifier_value="12345678901",
        email="adesola@example.com",
        phone="+234 803 555 7890",
    ),
    request_type="access",                   # see request types below
    targets=[
        DSAROrganization(name="Sterling Bank Limited",
                         dpo_email="dpo@sterlingbank.ng"),
        DSAROrganization(name="MTN Nigeria Communications",
                         dpo_email="dpo@mtn.ng"),
    ],
)

result = workflow.run(citizen_key)

for draft in result.drafts:
    print(draft.citation)               # the statute section cited
    print(draft.deadline)               # when the clock runs out
    print(draft.letter_text)            # ready to email
    print(draft.signed_envelope)        # JWS, for the DPO to verify
```

One draft comes back per target. `DSARResult` carries `drafts`, `jurisdiction`, `statute`, `request_type`, `dispatch_mode`, `sent_at` and `tracking`; each `DSARDraft` carries `target`, `citation`, `statute_short`, `deadline`, `letter_text` and `signed_envelope`.

## Request types

Five request types, matching the vocabulary the NDPA, POPIA, Kenya DPA and Ghana DPA share with the GDPR.

| Request type | What it asks for |
|---|---|
| `access` | A copy of all personal data held about the requestor |
| `rectification` | Correction of inaccurate or incomplete data |
| `erasure` | Deletion of personal data ("right to be forgotten") |
| `portability` | Personal data in a structured, machine-readable format |
| `objection` | Cessation of processing for specified purposes |

## The citation is chosen for you

Two axes decide which section appears in the letter: the jurisdiction and the request type. Both come from the statute YAML in `arche/policy/statutes/`, not from a table in this page.

```python
from arche.sign import generate_keypair
from arche.workflow import DSAROrganization, DSARRequestor, DSARWorkflow

citizen_key = generate_keypair()


def draft(jurisdiction, request_type="access"):
    result = DSARWorkflow(
        jurisdiction=jurisdiction,
        requestor=DSARRequestor(name="Adesola Okonkwo", identifier_label="NIN",
                                identifier_value="12345678901",
                                email="adesola@example.com"),
        request_type=request_type,
        targets=[DSAROrganization(name="Acme Ltd", dpo_email="dpo@acme.test")],
    ).run(citizen_key)
    return result, result.drafts[0]


for jurisdiction in ("NG", "ZA", "KE", "GH"):
    result, d = draft(jurisdiction)
    print(f"{jurisdiction}  {result.statute:12} {d.citation}")

print()
for request_type in ("access", "rectification", "erasure", "portability",
                     "objection"):
    _, d = draft("NG", request_type)
    print(f"  {request_type:15} {d.citation}")
```

```text
NG  NDPA-2023    NDPA-2023 s.34 (Right of Access)
ZA  POPIA        POPIA s.23 (Access to personal information)
KE  KENYA-DPA    Kenya DPA s.26(a) (Right of Access)
GH  GHANA-DPA    Ghana DPA s.35 (Access to personal data)

  access          NDPA-2023 s.34 (Right of Access)
  rectification   NDPA-2023 s.35 (Right to Rectification)
  erasure         NDPA-2023 s.36 (Right to Erasure)
  portability     NDPA-2023 s.38 (Right to Data Portability)
  objection       NDPA-2023 s.37 (Right to Object)
```

## The deadline is the statute's, unless you shorten it

| Jurisdiction | Statutory deadline |
|---|---|
| NDPA-2023 (Nigeria) | 30 days |
| POPIA (South Africa) | 30 days |
| Kenya DPA | 30 days |
| Ghana DPA | 21 days |

`draft.deadline` is a timezone-aware datetime computed from the statute pack and stamped into the signed envelope's `expires_at`. Pass `deadline_days=` to shorten it, there is no reason to lengthen it, since the statute already sets the maximum.

```python
DSARWorkflow(
    jurisdiction="NG",
    deadline_days=14,                  # shorter than the 30-day NDPA default
    # ...
)
```

## What a draft looks like

Real output from `result.drafts[0].letter_text`, run on the date in the first line. Only the date and the version string change between runs.

```text
2026-08-09

Data Protection Officer
Sterling Bank Limited
[Address on file]

Subject: Data Subject Access Request under Nigeria Data Protection Act 2023 (NDPA-2023)

Dear Data Protection Officer,

I, Adesola Okonkwo, identified by NIN (12345678901),
hereby exercise my right under NDPA-2023 s.34 (Right of Access) to access to all personal data that you hold concerning me.

Identity verification details:
  Full name:     Adesola Okonkwo
  NIN: 12345678901
  Email:         adesola@example.com
  Phone:         +234 803 555 7890



You are required to respond to this request within 30 days of
receipt, as provided by Nigeria Data Protection Act 2023 (NDPA-2023). Please confirm receipt within
7 working days and provide an estimated response date.

If you fail to respond within the statutory window, or if I am not
satisfied with your response, I reserve the right to lodge a complaint
with the Nigeria Data Protection Commission (NDPC).

Yours faithfully,

Adesola Okonkwo
adesola@example.com

---
This letter was generated by arche-core v0.3.0a1 (NDPA / POPIA /
Kenya DPA / Ghana DPA compliant DSAR drafting workflow). The accompanying
signed envelope (arche+envelope/v1, Ed25519 over canonical JSON) provides
cryptographic provenance and tamper evidence.
```

The ragged line breaks and the misaligned `NIN:` row are the template's, not a transcription slip. The letter is a draft you edit before sending, and tidying the template is outstanding work rather than a feature.

## What the signature proves, and what it does not

The envelope beside each draft is a JWS over canonical JSON. A data protection officer who receives one can check it without contacting anybody.

```python
from arche.sign import VerifyExtractWorkflow

# The DPO has the letter and the envelope, and nothing else.
untrusted = VerifyExtractWorkflow(
    require_purpose=f"dsar_{result.request_type}",
    require_jurisdiction=result.jurisdiction,
).process(result.drafts[0].signed_envelope)

# The DPO has previously been given the citizen's public key, out of band.
pinned = VerifyExtractWorkflow(
    public_key=citizen_key.public_key,
    require_purpose=f"dsar_{result.request_type}",
    require_jurisdiction=result.jurisdiction,
).process(result.drafts[0].signed_envelope)

for label, v in (("no key", untrusted), ("pinned key", pinned)):
    print(f"{label:11} valid={v.signature_valid!s:5} "
          f"trusted={v.signature_trusted!s:5} key_source={v.key_source}")

print("issuer     :", pinned.issuer_did)
print("deadline   :", pinned.envelope.expires_at)
```

```text
no key      valid=True  trusted=False key_source=self-asserted
pinned key  valid=True  trusted=True  key_source=pinned
```

Read those two rows carefully, because the difference is the whole security model. **`valid` says the signature matches the key that was resolved. `trusted` says that key came from somewhere the verifier controls.** With no key supplied, the verifier falls back to the `did:key` the token names about itself, which any impostor can also do, with their own keypair and a matching `kid`. That check proves the letter has not been altered since it was signed. It proves nothing at all about who signed it. [Attest](../how-to/attest.md#valid-is-not-trusted) has the forged-token demonstration.

Altering the letter breaks the envelope outright:

```python
from arche.sign import VerifyExtractWorkflow

tampered = result.drafts[0].signed_envelope[:-4] + "AAAA"
VerifyExtractWorkflow().process(tampered)
```

```text
SignatureVerificationError: Ed25519 signature verification failed
```

So what a DPO actually learns from a verified envelope is: the request was signed by the holder of this specific key, at this timestamp, for this purpose and this jurisdiction, with this deadline, and neither the letter nor its metadata has changed since. Whether that key belongs to Adesola Okonkwo is an identity question the signature does not answer, and the letter's identity-verification block is where the organisation's own checks begin.

## Dispatch, and why it is draft-only

`dispatch_mode` accepts exactly one value, `"draft_only"`, and it is the default. The workflow writes the letter; you read it and you send it.

That is a deliberate constraint rather than an unfinished feature. A workflow that emailed statutory demands on a citizen's behalf would be one miscited section or one wrong DPO address away from doing real damage in that citizen's name, and the person carrying the consequence is not the person who wrote the code. Autonomous dispatch would need consent mechanics, a delivery audit trail, and a bounce-and-escalation path that none of this ships today.

The organisation side is also absent: arche drafts requests, it does not help a controller answer them. That is a different product with different obligations, and it is on the roadmap rather than in this release.

## What's next

- [Sign, share, extract](sign_share_extract.md): the envelope primitives this workflow composes
- Attest: the signature on the decision, why `trusted` is the field to check
- [API overview](../api/index.md): the public workflow surface
