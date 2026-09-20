# Serve over HTTP

`arche serve` is the same verbs with a socket in front of them: find the personal data, make the copy you can hand on, decide whether two records are the same thing, and read a decision back by its id. At the end of this page you have the service running, you have called every endpoint with curl and seen what comes back, and you know what it does not do (authenticate) and what to put in front of it.

```sh
pip install "arche-core[service]"
arche serve --port 8798
```

```text
  arche serve   ->  http://127.0.0.1:8798   (no authentication; keep it local or put an auth proxy in front)
  ledger        ->  none
  attestation   ->  none (arche attest keygen FILE; ARCHE_SIGNING_KEY)
  parsers       ->  text, pdf, docx
  warm start    ->  no (--warm or ARCHE_WARM=1)
```

It exists for the cases where `import arche` is not on the table: a container, a sidecar next to a service written in something else, and a tool that speaks HTTP. The default port is 8766. FastAPI publishes the OpenAPI document at `/docs`.

## The flags

| flag | what it does |
|---|---|
| `--host` | bind address, default `127.0.0.1`. See [Authentication](#authentication) before changing it |
| `--port` | port, default `8766` |
| `--ledger FILE` | the DuckDB file behind `/decision`, `/explain` and `/replay`, and where `store: true` records. Default `ARCHE_LEDGER`; without either those three answer 503 and say so |
| `--signing-key FILE` | a PEM from `arche attest keygen`; every POST answer then carries an attestation. Default `ARCHE_SIGNING_KEY` |
| `--warm` | load models and parsers at startup rather than on the first request. Also `ARCHE_WARM=1` |

## Is it up, and what can it do

```sh
curl -s localhost:8798/livez
curl -s localhost:8798/capabilities
```

```json
{"ok":true,"version":"0.9.0","warm":null}
{"version":"0.9.0","ledger":true,"model":true,"parsers":{"text":true,"pdf":true,"docx":true,"docling":false,"ocr":false},"warm":null,"attestation":null,"endpoints":["/detect","/deidentify","/compare","/documents","/places","/extract","/decision/{id}","/explain/{id}","/replay/{id}","/livez","/capabilities"]}
```

`/livez` is the health check. `warm` is `null` when the service was started without `--warm`, `false` while a warm start is loading and `true` once it has finished, which is the line a container health check should wait for. `/capabilities` says whether a ledger is attached, whether a model is installed (`detect2`), which parsers this build has, and who signs.

## The endpoints

| | request | answer |
|---|---|---|
| `POST /detect` | `{"text", "jurisdiction"?, "backend"?, "statute"?}` | the spans as offsets, category, confidence, citation and detector. Never the value |
| `POST /deidentify` | as `/detect` plus `"method"?` (`statute`, `mask`, `token`, `drop`), `"salt"?`, `"store"?` | the masked copy, its `decision_id`, the spans, and the `record` a tokenised copy can be compared on |
| `POST /compare` | `{"a", "b", "entity"?, "jurisdiction"?, "backend"?, "store"?}` | two dicts or two strings in; the receipt |
| `POST /documents` | multipart `files` plus form fields `entity`?, `jurisdiction`?, `backend`?, `store`?, `reveal`? | one resolved record per document, the decisions between them, the review pack, and per-file errors |
| `POST /places` | `{"text"}` | place mentions with their spatial role and the cue that decided it |
| `POST /extract` | `{"text", "entity_types"?, "backend"?}` | proposed entities of the types named |
| `GET /decision/{id}` | `?reveal=true` to show values | the stored decision, values masked |
| `GET /explain/{id}` | | what supported it, what refuted it, what was missing |
| `GET /replay/{id}` | | run it again from the stored inputs and say whether the same id comes out |
| `GET /livez`, `GET /capabilities` | | above |

Defaults are the library's: `detect` and `deidentify` run `backend="auto"` (the rules, plus the model when `detect2` is installed), `compare` runs `basic`. A 400 carries the same message the Python call raises.

## Find the personal data, and make the copy you can hand on

```sh
curl -s localhost:8798/detect -H 'content-type: application/json' \
  -d '{"text": "Patient Casey Example (NIN 12345678901) called from 0803 555 7890.", "jurisdiction": "NG", "backend": "basic"}'
```

```json
{"count":2,"detections":[{"category":"PII-2-NIN","start":27,"end":38,"confidence":0.6,"citation":"NDPA-2023 s.30, NIMC Act s.27","detector":"rule:ng_nin"},{"category":"PII-3-PHONE","start":52,"end":65,"confidence":0.9,"citation":"NDPA-2023 s.30","detector":"rule:phone_libphonenumber"}]}
```

Offsets, a category, a confidence and the statute section each span falls under. The value never leaves, because the caller already holds the text.

```sh
curl -s localhost:8798/deidentify -H 'content-type: application/json' \
  -d '{"text": "Adaeze Okonkwo, NIN 12345678901, +234 803 123 4567", "jurisdiction": "NG", "backend": "basic", "store": true}'
```

```json
{"text":"NAME_b9357aa3 NAME_925a28e1, NIN [NIN], PHONE_cb78f3fe",
 "decision_id":"red:sha256:5def6f98e1b678983c8aaa654e8c3f50ff887ccfbbf9889933e67475dc5ee39e",
 "jurisdiction":"NG","statute":"NDPA-2023","backend":"basic","model":null,"method":"statute",
 "count":4,"by_category":{"PII-1-NAME":2,"PII-2-NIN":1,"PII-3-PHONE":1},
 "spans":[{"category":"PII-2-NIN","start":20,"end":31,"confidence":0.6,"action":"mask","citation":"NDPA-2023 s.30, NIMC Act s.27","detector":"rule:ng_nin"}, "..."],
 "record":{"name":"NAME_b9357aa3 NAME_925a28e1","phone":"PHONE_cb78f3fe"},"recorded":true}
```

That is the NDPA's rendering: the name and the phone are tokenised, so two notes about one person still compare on equal tokens (`record` is what `/compare` takes), and the national identity number is masked outright. `model` is `null` because this call asked for `basic`; with `backend: "auto"` on a machine that has `detect2` it names the model that proposed spans. `recorded: true` says the receipt went into the ledger, because the service was started with `--ledger`; without one, `store: true` is a 503.

The `decision_id` re-derives from the same text and the same pins, so a second call with the same input returns the same id, and `/replay/{id}` later says whether today's detectors still find the same spans.

Leave off `jurisdiction` on text that does not settle it and the answer is a 400 rather than a guess, because a redaction under the wrong statute looks finished and is not:

```sh
curl -s localhost:8798/detect -H 'content-type: application/json' -d '{"text": "Casey called on Tuesday.", "backend": "basic"}'
```

```json
{"detail":"the text does not say which jurisdiction governs it, and arche will not guess: a redaction under the wrong statute looks finished and is not. Pass jurisdiction=... -- packs exist for AT (GDPR), BE (GDPR), ... NG (NDPA-2023), ... ZA (POPIA) -- or statute=."}
```

## Are these two the same?

```sh
curl -s localhost:8798/compare -H 'content-type: application/json' \
  -d '{"a": {"name": "Adesola Okonkwo", "national_id": "12345678901"}, "b": {"name": "Adesola E. Okonkwo", "national_id": "12345678901"}, "entity": "person", "store": true}'
```

```json
{"identity":"same_entity","action":"merge","basis":"corroborated","explanation":"national ID match; name similarity 80%",
 "score":1.0,"factors":{"name":0.8,"national_id":1.0,"name_tf":0.7233},
 "decision_id":"dec:sha256:345a8f6e1e4f99e8b41e9c846f48cafee00a75ea9c1f7be3586d51ee4bdd8a56",
 "pins":{"receipt_schema":1,"engine":"arche-core@0.9.0","comparator_lib":"jellyfish@unknown","jurisdiction":"default","thresholds":{"match":0.85,"review":0.4,"distinctive_floor":0.75},"tf":"default"},
 "recorded":true}
```

Two dicts with the pack's field names, or two strings about one person, in which case `backend` picks the extractor (`basic` offline, `auto` with a model). `identity` is what arche believes, `action` is what it recommends, and they can differ; [Compare two records](compare-two-records.md) explains the pair. This is the pairwise verb; two lists are the library's `reconcile` and the `arche compare` CLI, not an endpoint.

## Read a decision back

The three ledger endpoints answer only when the service has a ledger. They follow the CLI's masked default: a shared value comes back as `1234*******` until you ask with `?reveal=true`.

```sh
ID=dec:sha256:345a8f6e1e4f99e8b41e9c846f48cafee00a75ea9c1f7be3586d51ee4bdd8a56
curl -s localhost:8798/explain/$ID
curl -s localhost:8798/replay/$ID
```

```json
{"identity":"same_entity","action":"merge","basis":"corroborated","explanation":"national ID match; name similarity 80%","supporting":["national_id"],"refuting":[],"missing":["registration_id","phone","email","dob","address"],"shared":{"national_id":"1234*******"},"gate":{"clearing_signal":"national_id","distinctive_cleared":true,"floor":0.75}}
{"decision_id":"dec:sha256:345a8f6e...","reproduced":true,"changed":{},"now":{"decision_id":"dec:sha256:345a8f6e...","identity":"same_entity","action":"merge","score":1.0,"factors":{"name":0.8,"national_id":1.0,"name_tf":0.7233}}}
```

`/decision/{id}` returns the stored receipt with its pins, the call it was made by, when it was recorded, and the two records by content address. An id the ledger does not hold is a 404. Without a ledger all three are a 503 whose body says `no ledger configured: pass --ledger FILE or set ARCHE_LEDGER`. [Keep, explain, replay](keep-and-replay.md) has what the ledger holds and how the same questions are asked from Python and the CLI.

## Places and entities in free text

```sh
curl -s localhost:8798/places -H 'content-type: application/json' \
  -d '{"text": "Send my package tomorrow from 123 Maple Street to the blue gate behind Elim Pharmacy, Ikeja."}'
```

```json
{"count":2,"mentions":[
 {"role":"origin","start":30,"end":46,"cue":"from","cue_rule":"from_origin","confidence":0.95,"text":"123 Maple Street","components":{"street_number":"123","street":"Maple Street"}, "..."},
 {"role":"destination","start":64,"end":91,"cue":"to","cue_rule":"to_destination","confidence":0.7,"text":"behind Elim Pharmacy, Ikeja","components":{"anchor":"behind Elim Pharmacy","anchor_type":"commercial","city":"Ikeja"}, "..."}]}
```

Each mention carries its role (`origin`, `destination`, `via`, `location`, or `unknown` when the cues conflict), the cue that decided it and where that cue sits in the text. `/extract` takes `entity_types` and proposes entities of those types; with `backend: "basic"` and no model it answers `{"backend":"basic","count":0,"entities":[]}`, and an empty list from a build with no model is not a claim that the text held nothing. Check `/capabilities` first.

## Documents

```sh
curl -s localhost:8798/documents -F files=@invoice.pdf -F files=@purchase_order.pdf \
     -F entity=organisation -F jurisdiction=NG
```

Each file is parsed (plain text natively, PDF and DOCX through their extras, everything else through docling, scanned pages through RapidOCR when `doc-ocr` is installed), then detected under its jurisdiction, mined for names and places, and resolved against the other files in the same request. The answer has `jurisdictions` (what each file said about where it came from), `documents` (one record per file, values masked unless `reveal=true`), `decisions` between them, `unlinked`, a `review` pack, and `errors` keyed by file name, so a file that yielded no identity attributes is named rather than silently absent. Two uploads with one name are refused, because the report is keyed by file name. A parser this build does not have is a 400 naming the extra, not a report that says the documents contained nothing. `store=true` records the decisions in the ledger. [Resolve documents](resolve-documents.md) is the same verb from Python.

## Warm start

Every model and parser loads on first use, which on a fresh process is a slow first request: two GLiNER models and docling's layout models are a thirty-second wait. `--warm` (or `ARCHE_WARM=1`) loads them at startup instead, and `/livez` answers `"warm": true` once that has finished. `arche._service.warm()` is the same function, public so an image build can call it and ship the weights. `packages/arche-core/Dockerfile` does exactly that, every parser and both models inside and nothing fetched at runtime, and the build fails if a model does not load. It is the image to put an auth proxy in front of.

## Authentication

There is none. The service binds `127.0.0.1` and is meant for the machine that has the data, the same rule the studio follows. `--host 0.0.0.0` exists for a container whose port is published to something that already does identity, and for nothing else. Every request carries text the caller chose to send; nothing is logged beyond uvicorn's warning line, and nothing leaves the process unless `store` is set, in which case it goes to the ledger file you named.

[`deploy/compose.yaml`](https://github.com/unpatterned-labs/arche/tree/main/deploy) is the arrangement to copy: this service and the MCP server behind one Caddy proxy that authenticates, sets `X-Arche-Caller`, and is the only published port. The basic-auth block works on day one and the Caddyfile says how to replace it with your identity provider. [Docker and deploy](../get-started/docker.md) walks through it.

## Attested answers

Give the service a key and every POST answer carries an `attestation`: a signature by this installation over the endpoint, a hash of the request, a hash of the rest of the answer, the caller and the decision ids. It is how a downstream auditor checks that what a client says arche said is what arche said.

```sh
arche attest keygen ~/.arche/signing.pem
arche serve --port 8798 --signing-key ~/.arche/signing.pem       # or ARCHE_SIGNING_KEY
curl -s localhost:8798/compare -H 'content-type: application/json' -H 'X-Arche-Caller: dee' \
  -d '{"a": {"name": "Adesola Okonkwo", "national_id": "12345678901"}, "b": {"name": "Adesola E. Okonkwo", "national_id": "12345678901"}}'
```

```json
{"identity":"same_entity","action":"merge", "...": "...",
 "attestation":{"schema":"arche.attestation.v1","tool":"compare",
  "inputs_sha256":"a8cc8d8836bce1dd3d05fa09476f43c1b85921f5db80e2f090aac2ece2354660",
  "response_sha256":"54f1d6a2bf0eea22232b0eec8ebad1e26c74a7ce43b6531d6d68c2445b479273",
  "caller":"dee",
  "decision_ids":["dec:sha256:345a8f6e1e4f99e8b41e9c846f48cafee00a75ea9c1f7be3586d51ee4bdd8a56"],
  "issued_at":"2026-09-20T06:16:02+00:00","engine":"arche-core@0.9.0",
  "signer":"did:key:z6MknWTRQ21jnkP9Y5hZZxHhg4NCgTapTuBhzxZ95azf7z9V",
  "jws":"eyJhbGciOiJFZERTQSIs..."}}
```

`caller` is the `X-Arche-Caller` header when the auth proxy in front sets one, else the client address. `GET /capabilities` names the signer's did:key. The envelope and how to verify it are on [Attested answers](../how-it-works/attestation.md).

## From Python

`arche._service.create_app(ledger=None, signing_key=None, warm_start=None)` returns the FastAPI application, for a test client or for mounting under your own app. It is the whole service; `arche serve` is `uvicorn.run` around it.

## Where to read next

| You want to | Read |
|---|---|
| the same verbs as MCP tools, for an agent runtime | [Let an agent call arche](mcp-server.md) |
| the container, the compose file and the proxy | [Docker and deploy](../get-started/docker.md) |
| the redaction verbs behind `/detect` and `/deidentify` | [Find and mask](find-and-mask.md) |
| what the ledger holds and how to replay from it | [Keep, explain, replay](keep-and-replay.md) |
| PDFs in, linked entities out, from Python | [Resolve documents](resolve-documents.md) |
| the signed envelope and how to check it | [Attested answers](../how-it-works/attestation.md) |
