# Command line

Every `arche` subcommand with its options as `--help` prints them, and one sentence on when you reach for it. At the end of this page you know which command does what and which ones need a ledger.

```sh
arche compare --demo
```

```text
compared 10 x 112 records (entity pack: artist)
  matched: 18   review: 1
  report:    report.html   [masked: safe to share]
  decisions: report.json
  (values masked by default; add --reveal for a working copy)
```

| Command | What it does | Needs |
|---|---|---|
| `version`, `list`, `datasets` | what is installed, what it can do, which datasets are here | |
| `compare` | two record files, or two texts, and a shareable report | |
| `redact` | a copy of a file or a text with the personal data removed | |
| `resolve-documents` | document fields out, candidates compared, cases opened | `pdf` and `docx` extras for those formats, `doc` and `doc-ocr` for layout and scanned pages |
| `studio` | the local reading tool: compare two records, work a review queue | |
| `serve` | the same verbs over HTTP, on this machine | `service` extra |
| `mcp` | the MCP server for an agent runtime | `mcp` extra |
| `decision`, `explain`, `replay`, `entities`, `cases`, `path`, `resolve`, `observe` | read and extend a ledger | `--store FILE` or `ARCHE_LEDGER` |
| `review` | validate, apply, share and verify a review pack | |
| `schema` | validate a declaration, generate tool definitions from it | |
| `attest` | make a signing key, verify an attested answer | |

Values are masked by default in every command that prints a record; `--reveal` shows them. On the ledger commands `--json` makes the output machine-readable and `--out PATH` writes it to a file; on `compare` and `redact`, `--json PATH` names the sidecar and `-` sends it to stdout. The ledger commands default to `$ARCHE_LEDGER` when `--store` is not given.

## Orientation

### `arche version`

```text
usage: arche version [-h] [--json]

options:
  -h, --help  show this help message and exit
  --json      machine-readable version metadata
```

Prints `arche 0.9.0`; with `--json`, the package, version and where the number came from.

### `arche list`

```text
usage: arche list [-h] [--json]

options:
  -h, --help  show this help message and exit
  --json      machine-readable command catalog
```

The command catalogue with one line each, which is this page in short.

### `arche datasets`

```text
usage: arche datasets [-h] [--available] [--json]

options:
  -h, --help   show this help message and exit
  --available  show only datasets present in this source checkout
  --json       machine-readable dataset catalog
```

The benchmark and review datasets arche knows, with their truth coverage; `--available` restricts it to the ones on disk in a source checkout.

```sh
arche datasets
```

```text
leipzig-abt-buy                    complete    available   product linkage and false-merge measurement
leipzig-dblp-acm                   complete    available   bibliographic linkage and false-merge measurement
nigeria-facilities-review-pack     unlabelled  available   human adjudication; not eligible for method qualification
parrish-person-review-pack         unlabelled  available   human adjudication; not eligible for method qualification
```

## The verbs

### `arche compare`

```text
usage: arche compare [-h] [--text] [--jurisdiction JURISDICTION]
                     [--backend BACKEND] [--store STORE] [--record]
                     [--entity ENTITY] [--schema DECL.YAML] [--out OUT]
                     [--json JSON] [--reveal] [--brand-color #HEX]
                     [--block {auto,none}] [--demo]
                     [a] [b]

positional arguments:
  a                     left file (.csv or .json), or a text with --text
  b                     right file (.csv or .json), or a text with --text

options:
  --text                A and B are two pieces of text about one person;
                        answer the pairwise question
  --jurisdiction JURISDICTION
                        with --text: priors (default NG)
  --backend BACKEND     with --text: extractor, basic (default, offline) or
                        auto
  --store STORE         record every decision in this ledger file
  --record              with --text: record in the ARCHE_LEDGER file
  --entity ENTITY       entity pack: person, place, artist (default person)
  --schema DECL.YAML    a declaration file: YOUR fields + role annotations
                        (overrides --entity)
  --out OUT             HTML report path (default report.html)
  --json JSON           decisions sidecar path (default <out>.json); with
                        --text, a path or - for stdout
  --reveal              show record values in the report (default: masked)
  --brand-color #HEX    theme the report accent with your color (hex only,
                        e.g. #0f766e)
  --block {auto,none}   candidate blocking (default auto; none = all pairs)
  --demo                run on the built-in artist demo, no data needed
```

Two files in, an HTML report and a JSON sidecar of decisions out; with `--text`, two pieces of text about one person and the receipt on stdout. `--demo` runs the shipped artist set and needs no data.

```sh
arche compare --text "Adesola Okonkwo, NIN 12345678901" "Adesola E. Okonkwo, NIN 12345678901" --json -
```

```text
{
  "identity": "same_entity",
  "action": "merge",
  "basis": "corroborated",
  "explanation": "national ID match; name similarity 80%",
  "score": 1.0,
  "factors": {
    "name": 0.8,
    "national_id": 1.0,
    "name_tf": 0.7233
  },
  "decision_id": "dec:sha256:af8926e63cd1343257b449be8a17b700b927de7b86faf97b10312fc84850fda1",
  "recorded": false
}
```

### `arche redact`

```text
usage: arche redact [-h] [--text] [--jurisdiction JURISDICTION]
                    [--backend BACKEND] [--method {statute,mask,token,drop}]
                    [--salt SALT] [--out OUT] [--json JSON] [--store STORE]
                    [--record]
                    [source]

positional arguments:
  source                a .txt/.md/.pdf/.docx file, or the text itself with
                        --text

options:
  --text                SOURCE is the text, not a path
  --jurisdiction JURISDICTION
                        NG, ZA, KE, GH, GB, ... (default: inferred from the
                        text; refuses if it cannot)
  --backend BACKEND     basic (rules only), auto (default; adds GLiNER2-PII
                        when installed), gliner2-pii
  --method {statute,mask,token,drop}
                        statute (default: the pack decides per category),
                        mask, token or drop
  --salt SALT           key the tokens so two deployments never mint the same
                        one
  --out OUT             write the masked text here (default: stdout)
  --json JSON           write the value-free span report here, or - for stdout
  --store STORE         record the decision in this ledger file
  --record              record in the ARCHE_LEDGER file
```

A file or a text in, the copy the statute permits out, with the decision id on stderr. It refuses when it cannot tell which jurisdiction governs the text; pass `--jurisdiction`.

```sh
arche redact --text "Patient Casey Example (NIN 12345678901) called from 0803 555 7890." --jurisdiction NG --backend basic
```

```text
2 span(s) under NDPA-2023 (NG, basic, statute)  decision_id red:sha256:31d8e1ac9880676a152f8884902489200dfabd6c5c0950cdfe7eb6a75dacf89f
Patient Casey Example (NIN [NIN]) called from PHONE_d3100c11.
```

### `arche resolve-documents`

```text
usage: arche resolve-documents [-h] [--candidates CANDIDATES]
                               [--entity ENTITY] [--jurisdiction JURISDICTION]
                               [--max-candidate-pairs MAX_CANDIDATE_PAIRS]
                               [--extraction-backend {auto,basic,regex}]
                               [--progress] [--verbose] [--reveal]
                               [--store STORE] [--out OUT]
                               source

positional arguments:
  source                document path, directory, or glob owned by the caller

options:
  --candidates CANDIDATES
                        caller-owned JSON or CSV candidate records with
                        entity_id or id
  --entity ENTITY       entity pack (default person)
  --jurisdiction JURISDICTION
                        declared jurisdiction or auto (default)
  --max-candidate-pairs MAX_CANDIDATE_PAIRS
                        hard candidate comparison cap (default 1000)
  --extraction-backend {auto,basic,regex}
                        field extraction backend (default basic; auto may load
                        local models)
  --progress            emit progress while parsing instead of JSON only
  --verbose             show parser diagnostics while resolving
  --reveal              include document field values in output
  --store STORE         record every verdict and its records in this local
                        DuckDB ledger
  --out OUT             write JSON review artifact instead of stdout
```

A folder of documents in, one record per document and the decisions between them out as a JSON review artifact; `--candidates` resolves each document against your own list instead of against the others. [Resolve documents](../guides/resolve-documents.md) is the walkthrough.

## The servers

### `arche studio`

```text
usage: arche studio [-h] [--port PORT] [--packs PACKS] [--no-browser]
                    [--ledger LEDGER]

options:
  --port PORT      listen on 127.0.0.1:PORT (default 8765)
  --packs PACKS    review pack directory
  --no-browser     do not open a browser tab
  --ledger LEDGER  ledger file the Explain pane reads (default: $ARCHE_LEDGER)
```

The local reading tool: compare two records in a browser, work a review queue from a pack directory, and read a ledger's explanations. It binds `127.0.0.1` and is for the machine that holds the data. [Review a queue](../guides/review-a-queue.md) uses it.

### `arche serve`

```text
usage: arche serve [-h] [--host HOST] [--port PORT] [--ledger LEDGER]
                   [--signing-key SIGNING_KEY] [--warm]

options:
  --host HOST           bind address (default 127.0.0.1)
  --port PORT           port (default 8766)
  --ledger LEDGER       ledger file for the decision endpoints (default:
                        $ARCHE_LEDGER)
  --signing-key SIGNING_KEY
                        PEM from `arche attest keygen`; answers then carry an
                        attestation (default: $ARCHE_SIGNING_KEY)
  --warm                load models and parsers at startup, not on the first
                        request (also ARCHE_WARM=1)
```

The same verbs over HTTP with no authentication of its own, for a container or a tool that speaks HTTP and not Python. [HTTP API](http-api.md) is the contract and [Serve over HTTP](../guides/serve-over-http.md) the walkthrough.

### `arche mcp`

```text
usage: arche mcp [-h] [--transport {stdio,streamable-http}] [--host HOST]
                 [--port PORT] [--path PATH]

options:
  --transport {stdio,streamable-http}
                        stdio for a local agent runtime (default); streamable-
                        http for a client over the network
  --host HOST           bind address for streamable-http (default 127.0.0.1)
  --port PORT           port for streamable-http (default 8765)
  --path PATH           URL path for streamable-http
```

The MCP server, stdio by default for an agent runtime on the same machine. Its configuration is environment variables, listed in [MCP tools](mcp-tools.md); [Let an agent call arche](../guides/mcp-server.md) is the walkthrough.

## The ledger

Every command here reads the DuckDB file named by `--store` or `$ARCHE_LEDGER`. Decision ids come from `compare --store`, `redact --store`, `resolve-documents --store`, or the `store=` argument in Python. [Keep, explain, replay](../guides/keep-and-replay.md) shows the same eight operations from Python.

### `arche decision`

```text
usage: arche decision [-h] [--store STORE] [--json] [--out OUT] [--reveal]
                      decision_id

options:
  --store STORE  ledger file (default: $ARCHE_LEDGER)
  --json         machine-readable output
  --out OUT      write JSON to this path
  --reveal       show record values (masked by default)
```

The receipt as it was recorded: verdict, factors, pins, the two records by their labels and the entity it now belongs to.

### `arche explain`

```text
usage: arche explain [-h] [--store STORE] [--json] [--out OUT] [--reveal]
                     decision_id

options:
  --store STORE  ledger file (default: $ARCHE_LEDGER)
  --json         machine-readable output
  --out OUT      write JSON to this path
  --reveal       show record values (masked by default)
```

What supported the decision, what refuted it and what was missing, field by field.

### `arche replay`

```text
usage: arche replay [-h] [--store STORE] [--json] [--out OUT] decision_id

options:
  --store STORE  ledger file (default: $ARCHE_LEDGER)
  --json         machine-readable output
  --out OUT      write JSON to this path
```

Make the decision again with the engine installed now and report whether the same id comes back, and if not, what moved.

### `arche entities`

```text
usage: arche entities [-h] [--store STORE] [--json] [--out OUT] [--reveal]
                      [--type TYPE]

options:
  --store STORE  ledger file (default: $ARCHE_LEDGER)
  --json         machine-readable output
  --out OUT      write JSON to this path
  --reveal       show record values (masked by default)
  --type TYPE    only this entity type
```

What the ledger's decisions have linked together, largest entity first, with whether each is held together directly or transitively.

### `arche cases`

```text
usage: arche cases [-h] [--store STORE] [--json] [--out OUT] [--type TYPE]

options:
  --store STORE  ledger file (default: $ARCHE_LEDGER)
  --json         machine-readable output
  --out OUT      write JSON to this path
  --type TYPE    only this entity type
```

The pairs still at `review`, and for each the fields that would settle it.

### `arche path`

```text
usage: arche path [-h] [--store STORE] [--json] [--out OUT] [--reveal]
                  record_a record_b

options:
  --store STORE  ledger file (default: $ARCHE_LEDGER)
  --json         machine-readable output
  --out OUT      write JSON to this path
  --reveal       show record values (masked by default)
```

Why two records are one entity: the chain of decisions between them. Record ids are the `rec:sha256:` addresses `decision`, `entities` and `cases` print.

### `arche resolve`

```text
usage: arche resolve [-h] [--text TEXT] [--record RECORD] [--type TYPE]
                     [--jurisdiction JURISDICTION] [--backend BACKEND]
                     [--store STORE] [--json] [--out OUT] [--reveal]

options:
  --text TEXT           the record as a piece of text (person pack)
  --record RECORD       the record as a JSON object, or @file.json
  --type TYPE           entity pack (default person)
  --jurisdiction JURISDICTION
                        with --text: priors (default NG)
  --backend BACKEND     with --text: extractor (default basic)
  --store STORE         ledger file (default: $ARCHE_LEDGER)
  --json                machine-readable output
  --out OUT             write JSON to this path
  --reveal              show record values (masked by default)
```

A new record, as JSON or as text, against the entities the ledger already holds: `found`, `review`, `ambiguous`, `conflict` or `not_found`.

### `arche observe`

```text
usage: arche observe [-h] --evidence EVIDENCE [--store STORE] [--json]
                     [--out OUT] [--reveal]
                     record_id

positional arguments:
  record_id            record id (from `arche cases` or `arche decision`)

options:
  --evidence EVIDENCE  JSON object of field: value, or @file.json
  --store STORE        ledger file (default: $ARCHE_LEDGER)
  --json               machine-readable output
  --out OUT            write JSON to this path
  --reveal             show record values (masked by default)
```

Add evidence about a record, a registration id from a registry for instance, and decide every open pair about it again. New receipts name the decision they supersede; nothing is overwritten.

## Review, schema and attest

### `arche review`

```text
usage: arche review [-h] {validate,apply,template,share,verify} ...

positional arguments:
  {validate,apply,template,share,verify}
    validate            is this the pack the matcher wrote?
    apply               bind a file of outcomes to a pack
    template            write a value-free outcome sheet for human review
    share               write the masked copy of a pack, safe to send onward
    verify              re-check an adjudication against its pack
```

The review pack lifecycle: `template` writes the sheet a reviewer fills in, `apply` binds their outcomes to the pack as an adjudication, `share` writes the masked copy, and `validate` and `verify` check that a pack or an adjudication is still the one that was written. [Review a queue](../guides/review-a-queue.md) is the walkthrough.

```text
usage: arche review validate [-h] [--json] pack
usage: arche review template [-h] pack out
usage: arche review apply [-h] [--out OUT] [--csv PATH] [--allow-dirty-pack]
                          pack outcomes
usage: arche review share [-h] [--adjudication PATH] [--include-reasons]
                          [--id-column COL]
                          pack out
usage: arche review verify [-h] [--json] adjudication [pack]

  pack                 pack.csv, or the directory holding it
  outcomes             csv, jsonl or json of decision_id/outcome/reviewer
  --out OUT            where to write the adjudication (default
                       adjudication.json)
  --csv PATH           also write the pack with its review columns filled in
  --allow-dirty-pack   adjudicate a pack that does not match its manifest
  --adjudication PATH  an adjudication.json whose outcomes to carry across
  --include-reasons    keep the reviewers' free-text reasons (they are not
                       masked, and can name the person the row does not)
  --id-column COL      column(s) to keep unmasked as the join key; repeatable.
                       Default is each side's `_id`.
```

### `arche schema`

```text
usage: arche schema [-h] {validate,gen} ...

positional arguments:
  {validate,gen}
    validate      validate a declaration file
    gen           generate an extraction schema / tool-def / comparator pack

usage: arche schema validate [-h] decl
usage: arche schema gen [-h]
                        [--format {json-schema,anthropic,openai,comparators}]
                        decl
```

`validate` checks a declaration YAML; `gen` prints the same declaration as a JSON schema, an Anthropic or OpenAI tool definition, or the comparator pack it implies. [Extract to your schema](../guides/extract-to-your-schema.md) is the walkthrough.

### `arche attest`

```text
usage: arche attest [-h] {keygen,verify} ...

positional arguments:
  {keygen,verify}
    keygen         write an Ed25519 key and print its did:key
    verify         re-check an attestation envelope

usage: arche attest keygen [-h] [--force] out

  out         where to write the PEM (keep it; 0600 where the OS allows)
  --force     replace an existing file

usage: arche attest verify [-h] [--inputs INPUTS] [--response RESPONSE]
                           [--public-key PUBLIC_KEY] [--json]
                           envelope

  envelope              the envelope JSON, or a whole service response
                        carrying one
  --inputs INPUTS       JSON file of the inputs, to check their hash
  --response RESPONSE   JSON file of the response, to check its hash
  --public-key PUBLIC_KEY
                        the signer's did:key or public PEM; without it the
                        result is valid, not trusted
  --json                machine-readable report
```

`keygen` writes the PEM that `arche serve --signing-key` and `ARCHE_SIGNING_KEY` read, so every answer carries an attestation; `verify` re-checks one envelope, and with `--public-key` says whether it is trusted as well as valid. [Attestation](../how-it-works/attestation.md) explains what the envelope proves.

## Where to read next

| You want to | Read |
|---|---|
| the same verbs from Python | [Python API](python-api.md) |
| the endpoints behind `arche serve` | [HTTP API](http-api.md) |
| the tools behind `arche mcp` | [MCP tools](mcp-tools.md) |
| which extra each command needs | [Extras](extras.md) |
| the image that runs any of these | [Docker and deploy](../get-started/docker.md) |
