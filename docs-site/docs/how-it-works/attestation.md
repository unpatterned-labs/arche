# Attested answers

At the end of this page you know what an attestation is, how to turn it on for `arche serve` and `arche mcp`, how someone who does not trust you checks one, why a signature that is `valid` is not yet `trusted`, and how attesting an answer differs from signing a decision.

```python
import arche
from arche.attest import attest, verify_attestation
from arche.sign import generate_keypair

key = generate_keypair()                       # in a service: arche attest keygen
a = {"name": "Touton Negoce SARL", "registration_id": "RC-88421"}
b = {"name": "Touton Negoce", "registration_id": "RC-88421"}
receipt = arche.compare(a, b, entity="organisation")

inputs = {"a": a, "b": b, "entity": "organisation"}
response = {"identity": receipt.identity, "action": receipt.action, "decision_id": receipt.decision_id}
envelope = attest("compare", inputs, response, keypair=key, caller="svc:billing")
for field in ("schema", "tool", "caller", "decision_ids", "engine"):
    print(field.ljust(13), envelope[field])
print("signer       ", envelope["signer"][:12] + "...", "| jws", envelope["jws"][:20] + "...")

check = verify_attestation(envelope, inputs=inputs, response=response, public_key=key.did_key)
print(check.ok, check.valid, check.trusted, check.inputs_match, check.response_match, check.problems)
```

```text
schema        arche.attestation.v1
tool          compare
caller        svc:billing
decision_ids  ['xwd:sha256:c41d7cdea68bb66d97ad869f51b5cd3b8d66b26493a568831762d3646e219ca4']
engine        arche-core@0.9.0
signer        did:key:z6Mk... | jws eyJhbGciOiJFZERTQSIs...
True True True True True []
```

When an agent asks arche a question and acts on the answer, the record of that action is usually the agent's own transcript: *arche said these two were the same*. Nothing in a transcript stops the agent, or whoever edits it later, from saying arche said something else. An attestation is the answer's own receipt: a signature by the arche installation over what was asked, what was answered, and which decision ids the answer carried, so that an auditor can check that what the agent says arche said is what arche said.

## What is in the envelope

The envelope is a JWS, Ed25519 in compact form with `typ: arche+jws`, over a small body. The plain fields repeat what the JWS signs, for a reader without a verifier; only the JWS is evidence.

| Field | What it binds |
|---|---|
| `tool` | the verb that answered: an endpoint name over HTTP, a tool name over MCP |
| `inputs_sha256` | sha256 of the canonical JSON of the arguments as arche received them: the whole request model over HTTP, defaults included; the bound arguments over MCP |
| `response_sha256` | sha256 of the canonical JSON of the answer, without the `attestation` field itself |
| `caller` | what the transport knew: the `X-Arche-Caller` header an auth proxy sets, else the client address; `null` over MCP |
| `decision_ids` | every arche id in the answer (`dec:`, `xwd:`, `red:`, `rec:`, `ent:`), sorted and unique, wherever in the answer they sat |
| `issued_at` | when, to the second, UTC |
| `engine` | `arche-core@<version>` |
| `signer` | the installation's `did:key`, also the JWS `kid` |

Canonical JSON is `arche.ids.canonical_json`: sorted keys, compact, floats at four places, so an answer re-serialised by a different client still hashes the same. Nothing in the envelope is a value. It is as shareable as a decision id, and the inputs and the answer stay with whoever holds them.

## Turning it on

```sh
arche attest keygen signing.pem
```

```text
key       signing.pem
did:key   did:key:z6MkuC77gNPr5EWz3fGeJGgKSSYMpdZGniWfAv3867mVgHhR
publish the did:key; set ARCHE_SIGNING_KEY to the path for arche serve and arche mcp
```

One key per installation, kept. `keygen` refuses to overwrite an existing file without `--force`, because envelopes signed with the old key stop verifying against the new `did:key`; publish both while the old ones matter. The key is never generated on the fly: a key that exists for one process and vanishes signs envelopes nobody can attribute, and a signature nobody can attribute is a checksum with extra steps. With no key set, neither surface attests anything, and `capabilities` says so.

```sh
export ARCHE_SIGNING_KEY=signing.pem
arche serve                     # or: arche serve --signing-key signing.pem
arche mcp                       # reads the same variable
```

Every POST answer from `arche serve` then carries an `attestation` object beside its other fields, and every MCP tool answer does too. `GET /capabilities` and the `capabilities` tool name the signer, which is how a client learns which `did:key` to pin.

```sh
curl -s -X POST http://127.0.0.1:8766/compare -H "Content-Type: application/json" -H "X-Arche-Caller: svc:billing" \
  -d '{"a": {"name": "Touton Negoce SARL", "registration_id": "RC-88421"}, "b": {"name": "Touton Negoce", "registration_id": "RC-88421"}, "entity": "organisation"}' > response.json
```

`response.json` is the receipt with an `attestation` object beside it. Abbreviated, the fields that matter:

```text
identity      same_entity
action        merge
decision_id   xwd:sha256:c41d7cdea68bb66d97ad869f51b5cd3b8d66b26493a568831762d3646e219ca4
attestation   tool=compare  caller=svc:billing  decision_ids=[xwd:sha256:c41d...]  signer=did:key:z6MkuC77...
```

## Who asked: the `caller` field

`caller` is a claim the signer makes from what the transport told it. Over HTTP it is the `X-Arche-Caller` header when an auth proxy in front of `arche serve` sets one, and the client address otherwise. Over MCP it is `null`, on stdio and on `--transport streamable-http` alike: the MCP layer has no caller identity of its own, and rather than sign a guess arche signs nothing. The signature proves arche made this answer to this question. It does not prove who asked, and behind a proxy it is exactly as good as the proxy.

## Checking one

```python
edited = {**response, "identity": "different"}
bad = verify_attestation(envelope, response=edited, public_key=key.did_key)
print(bad.ok, bad.valid, bad.response_match, bad.problems)

unpinned = verify_attestation(envelope)
print(unpinned.ok, unpinned.valid, unpinned.trusted)

other = generate_keypair()
wrong_key = verify_attestation(envelope, public_key=other.did_key)
print(wrong_key.valid, wrong_key.trusted, wrong_key.problems)

tampered = {**envelope, "tool": "deidentify"}
print(verify_attestation(tampered, public_key=key.did_key).problems)
```

```text
False True False ['the response supplied does not hash to what was signed']
True True False
False False ['signature: Ed25519 signature verification failed']
["envelope field 'tool' differs from what was signed"]
```

An `AttestationCheck` answers three questions, kept apart because they fail apart.

`valid` is whether the signature holds over the signed body. Nothing changed since signing. An envelope whose plain fields disagree with the signed body is reported as a problem and is not valid, because the signed body is the claim and the plain copy is a convenience.

`trusted` is `valid` and the key came from the verifier: `public_key=` as a `did:key` string or an Ed25519 key, or a `resolver=`. With neither, the key is decoded from the token's own `kid`, and the result is valid, not trusted. A self-asserted key is never trusted: anyone can sign anything with a key they made and name it in the header, and the signature verifies perfectly. `arche.sign.verify` applies the same rule everywhere. Check `trusted`, not `valid`, whenever the signature is meant to prove who signed.

`inputs_match` and `response_match` are `None` when that side was not supplied, else whether it hashes to what was signed. `ok` is `valid` with every supplied side matching. It does not require `trusted`, because integrity and attribution are different questions and the verifier decides which one it is asking.

The same check from a shell. A whole service response can be passed in place of the envelope, and the exit code is 0 only when `ok`.

```sh
arche attest verify response.json --public-key did:key:z6MkuC77gNPr5EWz3fGeJGgKSSYMpdZGniWfAv3867mVgHhR
```

```text
tool            compare
signer          did:key:z6MkuC77gNPr5EWz3fGeJGgKSSYMpdZGniWfAv3867mVgHhR
valid           True
trusted         True
decision        xwd:sha256:c41d7cdea68bb66d97ad869f51b5cd3b8d66b26493a568831762d3646e219ca4
OK
```

```sh
arche attest verify envelope.json --inputs in.json --response out.json
```

```text
tool            compare
signer          did:key:z6MkuC77gNPr5EWz3fGeJGgKSSYMpdZGniWfAv3867mVgHhR
valid           True
trusted         False   (no key pinned: integrity shown, authorship not)
inputs_match    True
response_match  True
decision        xwd:sha256:c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4
OK
```

`--public-key` takes the `did:key` or a public PEM. Verifying needs no network, no PKI and no resolver: the `did:key` contains the public key, so a field tablet with no connectivity can check that an envelope was not altered. Deciding that the envelope came from the installation it names is a key-distribution problem, and the answer to it is the `did:key` you obtained out of band and pinned.

## Attesting an answer is not signing a decision

Both use `arche.sign`, the Ed25519 and `did:key` primitives, and both produce a JWS you check with the same `valid` and `trusted` rule. They sign different claims.

`arche.sign` signs what the engine decided. `sign_edges` in `arche.resolve.reconcile` signs each edge of a batch result with the run's pins under the `arche.crosswalk_edge.v1` schema, the same claim its `decision_id` hashes, so a verifier can recompute the id from the signed payload and confirm nothing moved. `SignWorkflow` signs a document's detection set and policy outcomes as an `ArcheSignedDocument`, for a party who will verify it and extract identity claims from it. Both carry ids and numbers, never a value.

```python
from arche.resolve.reconcile import sign_edges
from arche.sign import verify

result = arche.reconcile(
    [{"id": "s1", "name": "Kijani Tea Exporters Ltd", "city": "Nairobi"}],
    [{"id": "r1", "name": "Kijani Tea Exporters Limited", "city": "Nairobi"}],
    entity="organisation")
signed = sign_edges(result, private_key=key.private_key, kid=key.did_key)
edge = verify(signed[0]["jws"], public_key=key.public_key)
print(len(signed), edge.valid, edge.trusted, edge.key_source, "|", edge.payload["schema"], edge.payload["decision"], sorted(edge.payload["pins"])[:4])
```

```text
1 True True pinned | arche.crosswalk_edge.v1 match ['block', 'comparators_sha256', 'distinctive_floor', 'engine']
```

`arche.attest` signs what the service said. The claim is *this installation, asked this, answered this, and the answer carried these decision ids*. It rides on the two surfaces an agent uses and it does not know or care whether the decision inside was right. That is what the decision id is for: `explain` says what supported it and `replay` says whether the same id comes back today, and [Keep, explain, replay](../guides/keep-and-replay.md) is where to take that question. A signed decision says the engine reached this from this evidence under these pins. An attested answer says the transcript is faithful. An audit of an agent's actions needs the second; an audit of the engine's judgement needs the first.

## Where to read next

| You want to | Read |
|---|---|
| the HTTP surface the attestation rides on | [Serve over HTTP](../guides/serve-over-http.md) |
| the MCP tools, and what `capabilities` reports | [The MCP server](../guides/mcp-server.md) |
| the decision id, the pins, and what a receipt carries | [The decision](the-decision.md) |
| explain and replay a decision an attestation names | [Keep, explain, replay](../guides/keep-and-replay.md) |
| every endpoint and field | [HTTP API](../reference/http-api.md) |
