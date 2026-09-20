# HTTP API

The contract for `arche serve`: every route, its request body, the shape that comes back, and the status codes it can answer with. At the end of this page you can write a client without reading the source. [Serve over HTTP](../guides/serve-over-http.md) is the walkthrough with curl; this page does not repeat it.

```sh
pip install "arche-core[service]"
arche serve --port 8797
```

| Method and path | Body | Returns | Errors |
|---|---|---|---|
| `GET /livez` | | `ok`, `version`, `warm` | |
| `GET /capabilities` | | what this build can do and which endpoints exist | |
| `POST /detect` | `{"text", "jurisdiction"?, "backend"?, "statute"?}` | spans as offsets, category, confidence, citation, detector | 400 |
| `POST /deidentify` | as `/detect` plus `"method"?`, `"salt"?`, `"store"?` | the masked copy, its `decision_id`, the spans, the tokenised `record` | 400, 503 |
| `POST /compare` | `{"a", "b", "entity"?, "jurisdiction"?, "backend"?, "store"?}` | the receipt | 400, 503 |
| `POST /documents` | multipart `files` plus form fields `entity`?, `jurisdiction`?, `backend`?, `store`?, `reveal`? | one record per document, the decisions between them, the review pack | 400, 503 |
| `POST /places` | `{"text"}` | place mentions with their spatial role | 400 |
| `POST /extract` | `{"text", "entity_types"?, "backend"?}` | proposed entities | 400 |
| `GET /decision/{id}` | `?reveal=true` | the stored decision | 404, 503 |
| `GET /explain/{id}` | `?reveal=true` | supporting, refuting and missing fields | 404, 503 |
| `GET /replay/{id}` | | the decision made again, and what moved | 400, 404, 503 |

**Auth.** None. The service binds `127.0.0.1` and is for the machine that holds the data. To expose it further, put an auth proxy in front and have it set `X-Arche-Caller`; that header becomes `caller` in every attestation, and the client address is used when it is absent. [Docker and deploy](../get-started/docker.md) has the proxy arrangement.

**Status codes.** `400` carries the message the Python call would raise (a jurisdiction the text does not reveal, an unknown entity pack, a parser extra that is not installed, two uploads sharing a name). `404` is a decision id the ledger never saw. `503` is any ledger-backed call when no ledger is configured: `store: true` on a POST, or any of the three `GET` routes. `422` is FastAPI's own answer to a body that does not fit the model. The error body is always `{"detail": "..."}`.

**Values.** `/detect` never returns the text of a span. `/deidentify` returns the masked copy, which is the point of the call. `/documents` and the ledger routes mask record values unless `reveal` is true.

**Attestation.** With `--signing-key` or `ARCHE_SIGNING_KEY`, every POST response carries one more key, `attestation`: a JWS over the route name, a hash of the request body, a hash of the rest of the response, the caller and the decision ids. `arche attest verify` checks it; [Attestation](../how-it-works/attestation.md) says what it proves.

Every response below was captured from the 0.9.0 service with an in-memory ledger attached and the `detect` extra installed, which is why `model` is true; the calls themselves ran `backend: "basic"`.

## `GET /livez`

```json
{"ok": true, "version": "0.9.0", "warm": null}
```

`warm` is `null` without `--warm`, `false` while a warm start is loading, `true` when it has finished.

## `GET /capabilities`

```json
{
  "version": "0.9.0",
  "ledger": true,
  "model": true,
  "parsers": {"text": true, "pdf": true, "docx": true, "docling": false, "ocr": false},
  "warm": null,
  "attestation": null,
  "endpoints": ["/detect", "/deidentify", "/compare", "/documents", "/places", "/extract",
                "/decision/{id}", "/explain/{id}", "/replay/{id}", "/livez", "/capabilities"]
}
```

`ledger` says whether the three `GET` routes and `store: true` will work. `model` is whether the `detect` extra is installed. `attestation` is `{"signer": "did:key:..."}` when a signing key is loaded.

## `POST /detect`

Request:

```json
{"text": "Patient Casey Example (NIN 12345678901) called from 0803 555 7890.",
 "jurisdiction": "NG", "backend": "basic"}
```

Response:

```json
{
  "count": 2,
  "detections": [
    {"category": "PII-2-NIN", "start": 27, "end": 38, "confidence": 0.6,
     "citation": "NDPA-2023 s.30, NIMC Act s.27", "detector": "rule:ng_nin"},
    {"category": "PII-3-PHONE", "start": 52, "end": 65, "confidence": 0.9,
     "citation": "NDPA-2023 s.30", "detector": "rule:phone_libphonenumber"}
  ]
}
```

`backend` defaults to `auto` (the rules, plus the model when installed); `basic` is rules only. `jurisdiction` omitted means inferred from the text, and a 400 when it cannot be:

```json
{"detail": "the text does not say which jurisdiction governs it, and arche will not guess: a redaction under the wrong statute looks finished and is not. Pass jurisdiction=... -- packs exist for AT (GDPR), BE (GDPR), BG (GDPR), CY (GDPR), CZ (GDPR), DE (GDPR), DK (GDPR), EE (GDPR), ES (GDPR), EU (GDPR), FI (GDPR), FR (GDPR), GB (UK-GDPR), GH (GHANA-DPA), GR (GDPR), HR (GDPR), HU (GDPR), IE (GDPR), IS (GDPR), IT (GDPR), KE (KENYA-DPA), LI (GDPR), LT (GDPR), LU (GDPR), LV (GDPR), MT (GDPR), NG (NDPA-2023), NL (GDPR), NO (GDPR), PL (GDPR), PT (GDPR), RO (GDPR), SE (GDPR), SI (GDPR), SK (GDPR), ZA (POPIA) -- or statute=."}
```

## `POST /deidentify`

Request:

```json
{"text": "Patient Casey Example (NIN 12345678901) called from 0803 555 7890.",
 "jurisdiction": "NG", "backend": "basic", "method": "statute", "salt": "", "store": false}
```

Response:

```json
{
  "text": "Patient Casey Example (NIN [NIN]) called from PHONE_d3100c11.",
  "decision_id": "red:sha256:31d8e1ac9880676a152f8884902489200dfabd6c5c0950cdfe7eb6a75dacf89f",
  "jurisdiction": "NG",
  "statute": "NDPA-2023",
  "backend": "basic",
  "model": null,
  "method": "statute",
  "count": 2,
  "by_category": {"PII-2-NIN": 1, "PII-3-PHONE": 1},
  "spans": [
    {"category": "PII-2-NIN", "start": 27, "end": 38, "confidence": 0.6, "action": "mask",
     "citation": "NDPA-2023 s.30, NIMC Act s.27", "detector": "rule:ng_nin"},
    {"category": "PII-3-PHONE", "start": 52, "end": 65, "confidence": 0.9, "action": "tokenize",
     "citation": "NDPA-2023 s.30", "detector": "rule:phone_libphonenumber"}
  ],
  "record": {"phone": "PHONE_d3100c11"},
  "recorded": false
}
```

`method` is `statute` (the pack decides per category), `mask`, `token` or `drop`. `record` is the tokenised fields a masked copy can still be compared on. `store: true` records the decision in the ledger and answers 503 when there is none.

## `POST /compare`

Request, two dicts:

```json
{"a": {"name": "Touton Negoce SARL", "registration_id": "RC-88421"},
 "b": {"name": "Touton Negoce", "registration_id": "RC-88421"},
 "entity": "organisation", "store": true}
```

Response:

```json
{
  "identity": "same_entity",
  "action": "merge",
  "basis": "pack:organisation",
  "explanation": "agrees on name, name_tftoken, registration_id",
  "score": 1.0,
  "factors": {"name": 1.0, "name_tftoken": 1.0, "registration_id": 1.0},
  "decision_id": "xwd:sha256:c41d7cdea68bb66d97ad869f51b5cd3b8d66b26493a568831762d3646e219ca4",
  "pins": {
    "engine": "crosswalk.v1",
    "comparators_sha256": "36039316c08f4b6e5f9b1a061777090762b9554bc90545a5302fafd813d4cd05",
    "block": "none", "threshold": 0.7, "review_margin": 0.15, "distinctive_floor": 0.75,
    "tf": "shipped:organisation", "entity_pack": "organisation"
  },
  "recorded": true
}
```

Request, two strings; `backend` applies only here, and `jurisdiction` supplies the priors:

```json
{"a": "Adesola Okonkwo, NIN 12345678901", "b": "Adesola E. Okonkwo, NIN 12345678901",
 "entity": "person", "jurisdiction": "NG", "backend": "basic", "store": true}
```

```json
{
  "identity": "same_entity",
  "action": "merge",
  "basis": "corroborated",
  "explanation": "national ID match; name similarity 80%",
  "score": 1.0,
  "factors": {"name": 0.8, "national_id": 1.0, "name_tf": 0.7233},
  "decision_id": "dec:sha256:af8926e63cd1343257b449be8a17b700b927de7b86faf97b10312fc84850fda1",
  "pins": {
    "receipt_schema": 1,
    "engine": "arche-core@0.9.0",
    "comparator_lib": "jellyfish@unknown",
    "jurisdiction": "NG",
    "thresholds": {"match": 0.85, "review": 0.4, "distinctive_floor": 0.75},
    "tf": "default",
    "provenance": {
      "document_content_id_a": "doc:sha256:9e3c0f0d448f450d462ba2dd02c63cfdfedfba55ef53a658dc29cf063468e396",
      "document_content_id_b": "doc:sha256:96cf5006e8e9c065a56a60829cb2191ba6dc1e114898a6fb3a7e93dc19fd1bab",
      "backend": "basic"
    }
  },
  "recorded": true
}
```

`identity` is `same_entity`, `review` or `different`; `action` is `merge`, `hold` or `no_op`. The two engines do not share a score, which is why `pins.engine` is on every receipt. An unknown pack is a 400:

```json
{"detail": "no entity pack named 'nope'; have artist, organisation, organization, person, place, product_electronics, product_grocery, product_home_goods. Pass comparators= to reconcile(...) for a schema arche does not ship."}
```

## `POST /documents`

Multipart request: one or more `files` parts, plus optional form fields `entity` (default `person`), `jurisdiction` (default `auto`), `backend` (default `auto`), `store` (default `false`), `reveal` (default `false`). File names are the keys of the report, so two uploads with the same name are a 400 rather than one silently replacing the other.

```sh
curl -s -F "files=@a.txt" -F "files=@b.txt" -F entity=person -F jurisdiction=NG -F backend=basic \
     localhost:8797/documents
```

Response, for two short text files about one person:

```json
{
  "entity": "person",
  "jurisdiction": "NG",
  "jurisdictions": {
    "a.txt": {"country": "NG", "confidence": 1.0, "margin": 1.0, "runner_up": null, "abstained": false,
              "reason": "strongest signal id.nin, 100% of total evidence weight",
              "ruleset_version": "2026.08.1",
              "evidence": [{"signal": "id.nin", "tier": "A", "country": "NG", "count": 1,
                            "weight": 1.0, "source": "text", "sample": ""}]},
    "b.txt": {"country": "NG", "confidence": 1.0, "margin": 1.0, "runner_up": null, "abstained": false,
              "reason": "strongest signal id.nin, 100% of total evidence weight",
              "ruleset_version": "2026.08.1",
              "evidence": [{"signal": "id.nin", "tier": "A", "country": "NG", "count": 1,
                            "weight": 1.0, "source": "text", "sample": ""}]}
  },
  "documents": [
    {"document": "a.txt", "national_id": "1234*******", "name": "Ades***********",
     "detections": {"PII-2-NIN": 1, "PII-1-NAME": 2, "PII-4-LOCATION": 1}},
    {"document": "b.txt", "national_id": "1234*******", "phone": "0803*********", "name": "Ades**************",
     "detections": {"PII-2-NIN": 1, "PII-1-NAME": 2, "PII-3-PHONE": 1}}
  ],
  "decisions": [
    {"a": "a.txt", "b": "b.txt", "identity": "same_entity", "score": 1.0,
     "factors": {"name": 0.8, "national_id": 1.0, "name_tf": 0.7233},
     "decision_id": "dec:sha256:6632f7d56faedde2ae31adfe878aca7ace632826a0c68a9e9d48c8824ee399b6"}
  ],
  "unlinked": [],
  "review": {
    "entity": "person",
    "proposed_fields": [
      {"document": "a.txt", "field": "name", "value": "Ades***********", "source": "document",
       "confidence": 0.0, "span": null},
      {"document": "a.txt", "field": "national_id", "value": "1234*******", "source": "document",
       "confidence": 0.0, "span": null},
      {"document": "b.txt", "field": "name", "value": "Ades**************", "source": "document",
       "confidence": 0.0, "span": null},
      {"document": "b.txt", "field": "national_id", "value": "1234*******", "source": "document",
       "confidence": 0.0, "span": null},
      {"document": "b.txt", "field": "phone", "value": "0803*********", "source": "document",
       "confidence": 0.0, "span": null}
    ],
    "decisions": [
      {"a": "a.txt", "b": "b.txt", "identity": "same_entity", "score": 1.0,
       "factors": {"name": 0.8, "national_id": 1.0, "name_tf": 0.7233},
       "decision_id": "dec:sha256:6632f7d56faedde2ae31adfe878aca7ace632826a0c68a9e9d48c8824ee399b6"}
    ],
    "unlinked": [],
    "errors": {}
  },
  "errors": {},
  "recorded": false
}
```

Uploads go to a private temporary directory that is removed when the response is built; nothing is kept unless `store` is true. Plain text parses natively; PDF and DOCX need the `pdf` and `docx` extras, scanned pages the `doc-ocr` extra, and an absent parser is a 400 naming the extra. Two files called `a.txt`:

```json
{"detail": "two uploads share a name: a.txt; rename one, the report is keyed by file name"}
```

## `POST /places`

Request:

```json
{"text": "Send my package from 123 Maple Street to the blue gate behind Elim Pharmacy, 124 Elim Street."}
```

Response:

```json
{
  "count": 2,
  "mentions": [
    {"role": "origin", "start": 21, "end": 37, "cue": "from", "cue_start": 16, "cue_end": 20,
     "cue_rule": "from_origin", "confidence": 0.95, "evidence": ["span:parsed", "cue:adjacent"],
     "jurisdiction": "XX", "jurisdiction_confidence": 0.0, "has_address": true,
     "text": "123 Maple Street", "components": {"street_number": "123", "street": "Maple Street"}},
    {"role": "destination", "start": 55, "end": 92, "cue": "to", "cue_start": 38, "cue_end": 40,
     "cue_rule": "to_destination", "confidence": 0.7, "evidence": ["span:parsed", "cue:windowed"],
     "jurisdiction": "XX", "jurisdiction_confidence": 0.0, "has_address": true,
     "text": "behind Elim Pharmacy, 124 Elim Street",
     "components": {"street_number": "124", "street": "Elim Street",
                    "anchor": "behind Elim Pharmacy", "anchor_type": "commercial"}}
  ]
}
```

`role` is `origin`, `destination`, `location`, `via` or `unknown`. Offsets index the text as sent. Unlike the MCP tool of the same name, this route returns the mention text and components, because the caller sent the text.

## `POST /extract`

Request:

```json
{"text": "Adesola Okonkwo of Kijani Tea Exporters Ltd, Nairobi", "backend": "basic"}
```

Response:

```json
{
  "backend": "basic",
  "count": 1,
  "entities": [
    {"text": "Adesola Okonkwo", "entity_type": "PERSON", "confidence": 0.7, "start": 0, "end": 15,
     "source": "lexicon", "metadata": {}}
  ]
}
```

`entity_types` narrows what is proposed. `backend` defaults to `auto`; `basic` finds pattern-shaped identifiers and lexicon names and needs no model.

## `GET /decision/{id}`

```sh
curl -s "localhost:8797/decision/dec:sha256:af8926e63cd1343257b449be8a17b700b927de7b86faf97b10312fc84850fda1"
```

```json
{
  "decision_id": "dec:sha256:af8926e63cd1343257b449be8a17b700b927de7b86faf97b10312fc84850fda1",
  "verb": "compare",
  "identity": "same_entity",
  "action": "merge",
  "score": 1.0,
  "explanation": "national ID match; name similarity 80%",
  "factors": {"name": 0.8, "name_tf": 0.7233, "national_id": 1.0},
  "pins": {
    "comparator_lib": "jellyfish@unknown", "engine": "arche-core@0.9.0", "jurisdiction": "NG",
    "provenance": {"backend": "basic",
                   "document_content_id_a": "doc:sha256:9e3c0f0d448f450d462ba2dd02c63cfdfedfba55ef53a658dc29cf063468e396",
                   "document_content_id_b": "doc:sha256:96cf5006e8e9c065a56a60829cb2191ba6dc1e114898a6fb3a7e93dc19fd1bab"},
    "receipt_schema": 1, "tf": "default",
    "thresholds": {"distinctive_floor": 0.75, "match": 0.85, "review": 0.4}
  },
  "call": {"backend": "basic", "entity": "person", "jurisdiction": "NG"},
  "recorded_at": "2026-09-20T08:25:37+00:00",
  "supersedes": null,
  "superseded_by": null,
  "record_a": "rec:sha256:c5adbb97a01ce54397bd1996946f69d6d1e4587c589be6a982b928ea4534402a",
  "record_b": "rec:sha256:d7e3241b32ade95eeba9152e36cba23e17322122b7041996860f45afa799ffca"
}
```

`?reveal=true` adds the record values. An id the ledger never saw:

```json
{"detail": "\"no decision 'dec:sha256:0000' in this ledger\""}
```

## `GET /explain/{id}`

```json
{
  "identity": "same_entity",
  "action": "merge",
  "basis": "corroborated",
  "explanation": "national ID match; name similarity 80%",
  "supporting": ["national_id"],
  "refuting": [],
  "missing": ["registration_id", "phone", "email", "dob", "address"],
  "shared": {"national_id": "1234*******"},
  "gate": {"clearing_signal": "national_id", "distinctive_cleared": true, "floor": 0.75}
}
```

`shared` is the values both records carry, masked unless `?reveal=true`.

## `GET /replay/{id}`

```json
{
  "decision_id": "dec:sha256:af8926e63cd1343257b449be8a17b700b927de7b86faf97b10312fc84850fda1",
  "reproduced": true,
  "changed": {},
  "now": {
    "decision_id": "dec:sha256:af8926e63cd1343257b449be8a17b700b927de7b86faf97b10312fc84850fda1",
    "identity": "same_entity",
    "action": "merge",
    "score": 1.0,
    "factors": {"name": 0.8, "national_id": 1.0, "name_tf": 0.7233}
  }
}
```

`reproduced` is true when the engine installed now returns the same `decision_id` byte for byte; otherwise `changed` names every factor and pin that moved. A decision recorded with arguments the ledger could not store is a 400: it can be re-verified from its receipt but not re-run.

## No ledger

Any of `store: true`, `/decision`, `/explain` or `/replay` without `--ledger` or `ARCHE_LEDGER`:

```json
{"detail": "no ledger configured: pass --ledger FILE or set ARCHE_LEDGER"}
```

with status 503.

## From Python

<!-- docs-test: fragment -->
```python
from arche._service import create_app, serve, warm

app = create_app(ledger=None, signing_key=None, warm_start=None)   # a FastAPI app, for your own server
serve(host="127.0.0.1", port=8766, ledger=None, signing_key=None, warm_start=None)
warm(models=True, parsers=True)                                     # load everything now; an image build can call it
```

`create_app` raises with the install line when FastAPI is missing. `None` for `ledger`, `signing_key` and `warm_start` reads `ARCHE_LEDGER`, `ARCHE_SIGNING_KEY` and `ARCHE_WARM`.

## Where to read next

| You want to | Read |
|---|---|
| the walkthrough with curl, warm start, attestation | [Serve over HTTP](../guides/serve-over-http.md) |
| the same service behind an auth proxy | [Docker and deploy](../get-started/docker.md) |
| the fields on a receipt | [The decision](../how-it-works/the-decision.md) |
| the same verbs as MCP tools | [MCP tools](mcp-tools.md) |
| the same verbs from Python | [Python API](python-api.md) |
