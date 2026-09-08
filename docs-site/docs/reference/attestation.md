# Attested answers

When an agent asks arche a question and acts on the answer, the record of that action is usually the agent's own transcript: *arche said these two were the same*. Nothing in a transcript stops the agent, or whoever edits the transcript later, from saying arche said something else. An attestation is the answer's own receipt -- a signature by the arche installation over what was asked, what was answered, and which decision ids the answer carried -- so a downstream auditor can check that *what the agent says arche said* is what arche said.

It is one function over `arche.sign`, and it rides on the two surfaces an agent uses: `arche serve` and the MCP server. Both attest every answer once they have a key, and neither does anything at all without one.

## The envelope

```json
{
  "schema": "arche.attestation.v1",
  "tool": "compare",
  "inputs_sha256": "9f3c…",
  "response_sha256": "1b7e…",
  "caller": "svc:billing",
  "decision_ids": ["dec:sha256:8b5b…"],
  "issued_at": "2026-09-08T10:12:44+00:00",
  "engine": "arche-core@0.9.0",
  "signer": "did:key:z6Mk…",
  "jws": "eyJhbGciOiJFZERTQSIsImtpZCI6…"
}
```

| Field | What it binds |
|---|---|
| `tool` | the verb that answered: an endpoint name over HTTP, a tool name over MCP |
| `inputs_sha256` | sha256 of the canonical JSON of the arguments as arche received them -- the whole request model over HTTP, defaults included; the bound arguments over MCP |
| `response_sha256` | sha256 of the canonical JSON of the answer, without the `attestation` field itself |
| `caller` | what the transport knew: the `X-Arche-Caller` header an auth proxy sets, else the client address; `null` on stdio MCP |
| `decision_ids` | every arche id in the answer (`dec:`, `xwd:`, `red:`, `rec:`, `ent:`), sorted |
| `signer` | the installation's `did:key`; also the JWS `kid` |
| `jws` | Ed25519 JWS (compact, `typ: arche+jws`) over every field above |

The plain fields repeat what the JWS signs, for a reader without a verifier. Only the JWS is evidence: a verifier reads the signed body and reports a plain field that disagrees with it as a problem.

Canonical JSON is `arche.ids.canonical_json` -- sorted keys, compact, floats at four places -- so an answer re-serialised by a different client still hashes the same. Nothing in the envelope is a value: it is as shareable as a decision id, and the inputs and the answer stay with whoever holds them.

## Verifying

```python
from arche.attest import attest, verify_attestation
from arche.sign import generate_keypair

key = generate_keypair()                     # arche attest keygen, in a service
inputs = {"a": {"name": "Adaeze Okonkwo"}, "b": {"name": "Adaeze Okonkwo"}}
response = {"identity": "same_entity", "decision_id": "dec:sha256:" + "ab" * 32}

envelope = attest("compare", inputs, response, keypair=key)

check = verify_attestation(envelope, inputs=inputs, response=response,
                           public_key=key.did_key)
assert check.ok and check.trusted
assert check.decision_ids == ["dec:sha256:" + "ab" * 32]

edited = {**response, "identity": "different"}
assert verify_attestation(envelope, response=edited, public_key=key.did_key).ok is False

unpinned = verify_attestation(envelope)      # no key supplied
assert unpinned.valid and not unpinned.trusted
```

Three answers, kept apart because they fail apart:

- **`valid`** -- the signature holds over the signed body. Nothing changed since signing.
- **`trusted`** -- and the key came from the verifier (`public_key=` as a did:key or an Ed25519 key, or a `resolver=`), not from the token's own `kid`. A self-asserted key is never trusted: anyone can sign anything with a key they made and name it in the header. This is the same rule `arche.sign.verify` applies everywhere.
- **`inputs_match` / `response_match`** -- `None` when that side was not supplied, else whether it hashes to what was signed. `ok` is `valid` with every supplied side matching. It does not require `trusted`, because integrity and attribution are different questions and the verifier decides which one they are asking.

From a shell, `arche attest verify ENVELOPE.json --inputs in.json --response out.json --public-key did:key:z6Mk…` prints the same report; a whole service response can be passed in place of the envelope. The exit code is 0 only when `ok`.

## Turning it on

```bash
arche attest keygen ~/.arche/signing.pem     # prints the did:key to publish
export ARCHE_SIGNING_KEY=~/.arche/signing.pem
arche serve                                  # every POST answer carries `attestation`
arche-mcp                                    # every tool answer does too
```

`capabilities` -- the endpoint and the MCP tool -- names the signer, which is how a client learns which did:key to pin. The key is never generated on the fly: a key that exists for one process and vanishes signs envelopes nobody can attribute, and a signature nobody can attribute is a checksum with extra steps. Replacing a key (`keygen --force`) means envelopes signed with the old one stop verifying against the new did:key; publish both while the old ones matter.

## What it does not prove

`caller` is a claim the signer makes from what the transport told it. Behind an auth proxy that sets `X-Arche-Caller`, it is as good as the proxy; without one, it is a client address, and on stdio it is nothing. The signature proves arche made this answer to this question; it does not prove who asked, and it does not prove the answer was right -- that is what the decision id is for, and `explain` and `replay` are the tools for that question.
