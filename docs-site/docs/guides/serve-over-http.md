# Serve over HTTP

`arche serve` is the same verbs with a socket in front of them: find the personal data, make the copy you can hand on, decide whether two records are the same thing, and read a decision back by its id. It exists for the three cases where `import arche` is not on the table: a container, a sidecar next to a service written in something else, and a tool that speaks HTTP.

```bash
pip install "arche-core[service]"
arche serve                     # http://127.0.0.1:8766, no ledger
arche serve --ledger decisions.duckdb
```

The ledger is what makes `/decision`, `/explain` and `/replay` answer; without one they return 503 and say so. `ARCHE_LEDGER` is read when `--ledger` is not given.

## The endpoints

| | |
|---|---|
| `POST /detect` | `{"text", "jurisdiction"?, "backend"?, "statute"?}` -- the spans, as offsets, categories, confidence and citations. **Never the value.** |
| `POST /deidentify` | as `/detect` plus `"method"?` (`statute`, `mask`, `token`, `drop`), `"salt"?`, `"store"?` -- the masked copy, its `decision_id`, the spans by category, and the `record` a `token` copy can be compared on |
| `POST /compare` | `{"a", "b", "entity"?, "jurisdiction"?, "backend"?, "store"?}` -- two dicts or two strings; the receipt |
| `GET /decision/{id}` | the stored decision, values masked; `?reveal=true` shows them |
| `GET /explain/{id}` | why, in the ledger's words |
| `GET /replay/{id}` | run it again from the stored inputs and say whether the same id comes out |
| `GET /livez`, `GET /capabilities` | up; version, whether a ledger and a model are present |

Defaults are the library's: `detect` and `deidentify` run `backend="auto"` (the rules, plus the model when `[detect2]` is installed), `compare` runs `basic`. A jurisdiction the text does not settle is a 400 with the same message the Python call raises, because a redaction under the wrong statute looks finished and is not. FastAPI publishes the OpenAPI document at `/docs`.

```bash
curl -s localhost:8766/deidentify -H 'content-type: application/json' \
  -d '{"text": "Adaeze Okonkwo, NIN 12345678901, +234 803 123 4567", "jurisdiction": "NG", "store": true}'
```

```json
{"text": "NAME_ef0f576a, NIN [NIN], PHONE_cb78f3fe",
 "decision_id": "red:sha256:b203c7b3...", "jurisdiction": "NG", "statute": "NDPA-2023",
 "backend": "auto", "model": "fastino/gliner2-privacy-filter-PII-multi", "method": "statute",
 "count": 3, "by_category": {"PII-1-NAME": 1, "PII-2-NIN": 1, "PII-3-PHONE": 1},
 "spans": [...], "record": {"name": "NAME_ef0f576a", "phone": "PHONE_cb78f3fe"}, "recorded": true}
```

That is the NDPA's rendering: the name and the phone are tokenised, so two notes about one person still compare on equal tokens (`record` is what `compare` takes), and the national identity number is masked outright. `model` names the proposer that ran because `[detect2]` was installed on that machine; without it the same call says `"backend": "basic", "model": null` and the lexicon and validators do the finding.

The `decision_id` re-derives from the same text and the same pins, so a second call with the same input returns the same id, and `/replay/{id}` later says whether today's detectors still find the same spans.

## Authentication

There is none. The service binds `127.0.0.1` and is meant for the machine that has the data, the same rule the studio follows. `--host 0.0.0.0` exists for a container whose port is published to something that already does identity -- Tailscale, Cloudflare Access, `oauth2-proxy` -- and for nothing else. Every request carries text the caller chose to send; nothing is logged beyond uvicorn's warning line, and nothing leaves the process unless `store` is set, in which case it goes to the ledger file you named.

## Attested answers

Give the service a key and every POST answer carries an `attestation`: a signature by this installation over the endpoint, a hash of the request, a hash of the rest of the answer, the caller and the decision ids. It is how a downstream auditor checks that what a client says arche said is what arche said.

```bash
arche attest keygen ~/.arche/signing.pem
arche serve --signing-key ~/.arche/signing.pem       # or ARCHE_SIGNING_KEY
```

`caller` is the `X-Arche-Caller` header when the auth proxy in front sets one, else the client address. `GET /capabilities` names the signer's did:key. The envelope and how to verify it are on [Attested answers](../reference/attestation.md).

## From Python

`arche._service.create_app(ledger=None)` returns the FastAPI application, for a test client or for mounting under your own app. It is the whole service; `arche serve` is `uvicorn.run` around it.
