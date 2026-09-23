# Let an agent call arche

`arche mcp` is an MCP server. It gives an agent eleven tools for two jobs: resolving entities (are these two records the same thing, and what is the evidence) and protecting data (what may leave this boundary, and on whose authority). At the end of this page you have it running, you have seen it answer three ways, and you know which tool an agent should call first and why.

```sh
pip install "arche-core[mcp]"
arche mcp
```

That is the whole install. It speaks stdio by default, so point any MCP client at that command; `uvx --from "arche-core[mcp]" arche mcp` runs it with no install at all, and the container image serves it with `docker run -i --rm -e ARCHE_HASH_KEY ghcr.io/unpatterned-labs/arche-core mcp`. Until 0.9.0 this was a separate package, `arche-mcp`; it is part of `arche-core` now, and the `arche-mcp` command still exists for configs written against the old name.

## The shape of the thing

An MCP tool is called unattended. No person reads the arguments, no person sees the result before it reaches a model. Three consequences run through everything below.

**The tool description is the documentation.** An agent reads that and nothing else, so the descriptions in `arche.mcp.server` are long and carry the caveats rather than deferring to a page like this one.

**A silent failure is worse here than anywhere.** A tool returning nothing looks like good news. Most of the design below is about making "I found nothing" distinguishable from "I could not look".

**No tool touches the filesystem.** An earlier version had one that read two caller-supplied paths and wrote a report to a third. MCP has no consent model for a filesystem write, so it is gone. Use the `arche compare` CLI, where a person sees the command before it runs.

## The tools

| tool | what it answers |
|---|---|
| `capabilities` | what this installation can do: statutes, inferable jurisdictions, entity packs, installed extras. Call it first |
| `infer_jurisdiction` | which law governs this document, from evidence inside it, and whether a statute pack covers the answer |
| `plan_protection` | which categories the statute governs that nothing installed can find, before you hand anything over |
| `detect_pii` | personal data as offset spans with category and citation, plus a `coverage` block |
| `detect_entities` | people, places and organisations as typed offset spans; needs the `detect` extra, and says so |
| `guarded_scan` | the redacted copy, tokens with citations, fail-closed |
| `describe_pack` | which record fields an entity pack reads and how much each counts |
| `compare_records` | two record lists in, edges with scores and evidence out |
| `why_unresolved` | why a pair came back `review`, and which field would settle it |
| `check_name_equivalence` | are two names the same person's, with African name variation and transliteration |
| `extract_places` | place mentions in free text with their spatial role and the cue that decided it |

With `ARCHE_LEDGER` set, eight more appear: `decision`, `explain`, `replay`, `entities`, `path`, `cases`, `observe` and `resolve`. Without it the server is stateless and a client never sees tools that can only fail.

## Three ways to see it

| | proves | needs |
|---|---|---|
| the script | the engine works, and says why | nothing |
| the Inspector | the real protocol, driven by you | `npx` |
| chat | a model choosing tools on its own | an API key |

An MCP server has no interface. It is a tool provider speaking JSON-RPC over stdio: nothing to open, no port to visit. The interface is always the client, which is why the script looks scripted (there is no client, so the script stands in for one) and why chat is the only one that shows tool selection.

### The script

```sh
uv run python examples/mcp_demo.py
```

No client, no model, no key, about fifteen seconds. It calls the same functions the tools call, in the order an agent would, and runs one referral note through the flow twice:

```text
--- Nigeria -------------------------------------------------------------
  infer_jurisdiction  -> NG (confidence 1.0, from: id.nin, registrar.cac, phone.ng)
                         statute NDPA-2023, policy_available=True

  plan_protection     -> partial
                         13 categories with no detector at all

  guarded_scan        -> 7 fields removed
                           PII-1-NAME       tokenize  NDPA-2023 s.30
                           PII-2-NIN        mask      NDPA-2023 s.30, NIMC Act s.27

--- Britain -------------------------------------------------------------
  infer_jurisdiction  -> GB (confidence 1.0, from: postcode.uk)
                         statute UK-GDPR, policy_available=True

  plan_protection     -> partial
                         6 categories with no detector at all
                         3 with a detector built elsewhere: PII-1-NAME, PII-3-PHONE, PII-4-LOCATION

  guarded_scan        -> 3 fields removed
                           PII-1-NAME       tokenize  UK GDPR Art 4(1) (personal data)
```

The British run is the one to point at. Same tool, same code, and it says that three of the detectors that ran were built for African data. Anyone can build a redactor that removes things; the useful one tells you when it could not look.

### The Inspector

The official MCP client, as a web UI or a one-shot CLI, nothing installed permanently. `mcp-demo.json` ships in the repository root:

```json
{
  "mcpServers": {
    "arche": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/arche", "arche", "mcp"],
      "env": { "ARCHE_HASH_KEY": "change-me-to-a-long-random-string" }
    }
  }
}
```

Change `--directory` to your checkout and set a hash key. Then:

```sh
npx @modelcontextprotocol/inspector --config mcp-demo.json --server arche
```

That opens a browser: every tool with its schema, a form to fill in, and the raw response. One-shot from a terminal instead:

```sh
npx @modelcontextprotocol/inspector --cli --config mcp-demo.json --server arche \
  --method tools/list

npx @modelcontextprotocol/inspector --cli --config mcp-demo.json --server arche \
  --method tools/call --tool-name infer_jurisdiction \
  --tool-arg "text=NIN 12345678901, RC 1234567, Karfi Health Post, Kano"
```

Use the config-file form. Passing the command inline (`--cli uv run arche mcp --method tools/list`) does not work: everything after the command is forwarded to the server, so `--method` reaches `arche mcp` instead of the Inspector and the connection closes.

### Chat, with a model choosing

```sh
uv run python examples/mcp_chat.py
uv run python examples/mcp_chat.py "is this safe to send? NIN 12345678901, Kano"
```

This starts the real server as a subprocess, speaks the protocol to it, hands the tool schemas to a model, and lets the model decide. Nothing in the script picks the order. It needs `OPENAI_API_KEY`, reads `.env` in the repository root (gitignored) and will not prompt for a key or fall back to one; `ARCHE_CHAT_MODEL` overrides the model (default `gpt-4o-mini`). Every tool call prints before it runs and its result after, so the transcript is the demo:

```text
you> Is this safe to send to a model? Dr Adaeze Okonkwo, NIN 12345678901, Kano

  [tool] infer_jurisdiction({"text": "Dr Adaeze Okonkwo, NIN 12345678901, ..."})
      { "country": "NG", "confidence": 1.0, "statute_id": "NDPA-2023",
        "policy_available": true, ... }

  [tool] plan_protection({"jurisdiction": "NG"})
      { "verdict": "partial", "uncovered": ["PII-2-BVN", "PII-2-NIN", ...] }

  [tool] guarded_scan({"text": "...", "jurisdiction": "NG"})
      { "denied": false,
        "redacted_text": "Dr [NAME:0aba5577] Okonkwo, NIN [NIN:de117765], ...",
        "fields": [ { "category": "PII-2-NIN", "action": "mask",
                      "citation": "NDPA-2023 s.30, NIMC Act s.27" } ] }

arche> The document is governed by NDPA-2023. Not safe to send unredacted...
```

The model was not told to call those three in that order. It read the tool descriptions and worked it out. Try `"are General Hospital and General Hospital the same place?"` for the resolution half; the answer is `review`, and the model will tell you why.

### A real client

The same config, dropped into Claude Desktop's `claude_desktop_config.json`, then restart it. Without a checkout, `"command": "uvx", "args": ["--from", "arche-core[mcp]", "arche", "mcp"]`; or the container, `"command": "docker", "args": ["run", "-i", "--rm", "-e", "ARCHE_HASH_KEY", "ghcr.io/unpatterned-labs/arche-core", "mcp"]`.

## Over the network

```sh
arche mcp --transport streamable-http --host 0.0.0.0 --port 8765
```

The same tools at `http://HOST:8765/mcp` (`--path` changes it) for a client that is not on this machine. The server has no authentication of its own: it binds `127.0.0.1` unless told otherwise, and over HTTP anyone who can reach the port can call every tool. The compose file in [`deploy/`](https://github.com/unpatterned-labs/arche/tree/main/deploy) is the arrangement to copy: this server and `arche serve` behind one Caddy proxy that authenticates and sets `X-Arche-Caller`. The MCP transport does not read that header yet, so attested answers over HTTP carry `caller: null`, as they do over stdio.

## Two flows, not one

There are two things an agent comes here to do, and they share almost no tools. Resolve entities: are these two records the same thing? Protect data: what may leave this boundary, and on whose authority? They compose, resolve a pair and then guard what you send onward about it, but an agent doing only one does not need the other.

## Flow A: entity resolution

```text
capabilities()                          which entity packs exist
        |
describe_pack("place")                  which fields does it read?
        |                               a field it does not name is IGNORED,
        |                               silently. Map your columns here.
        |
compare_records(a, b, entity="place")   edges, evidence, pins
        |
why_unresolved(a, b, entity="place")    for each `review`: what would settle it
```

Every tool here is a thin wrapper over `arche.mcp.handlers`, so what a tool returns can be seen without a client:

```python
from arche.mcp import handlers

a = {"id": "a", "name": "General Hospital"}
b = {"id": "b", "name": "General Hospital"}
edge = handlers.compare_records([a], [b], entity="place")["matches"][0]
print(edge["decision"], edge["score"], edge["distinctive_max"], edge["evidence"])

why = handlers.why_unresolved(a, b, entity="place")
print(why["why"])
print([(w["field"], w["effect"]) for w in why["would_resolve"]])
print([w["field"] for w in why["will_not_help"]])
```

```text
review 1.0 0.564 {'name': 1.0, 'name_tftoken': 1.0, 'name_type': 1.0}
the records agree, and what they agree on is ordinary in this pack's reference population (distinctive_max 0.564 < floor 0.75). Agreement on a common token is not evidence of identity
[('lat + lon', 'hard_constraint'), ('address', 'independent_signal'), ('admin_path', 'independent_signal')]
['name']
```

What comes back from `compare_records` is per pair: `a_id`, `b_id`, `score`, `decision`, `distinctive_max`, `evidence`, and engine `pins` recording which comparator set and frequency table produced it. Ids and numbers only, never a record value. [Resolve a batch](resolve-a-batch.md) explains each field.

**`review` is a decision, not a failure**, and it is the one worth understanding. Two records both called *General Hospital* score 1.000 and come back `review`, because `distinctive_max` is 0.564 against a floor of 0.750: every field agreed and nothing that agreed was distinctive. An agent that treats `review` as `no_match` throws away the most interesting output; an agent that treats it as `match` merges two hospitals in different states. `why_unresolved` turns the refusal into a next action: the fields the pack could read and did not receive, ranked by what supplying them achieves, and the fields already present that cannot help however much they agree. Read `will_not_help` before retrying; a cleaner rendering of *General Hospital* is still *General Hospital*.

**Choose the pack by what the records are.** The pack decides which population rarity is measured against, so the same pair is `review` under `place` and `match` under `organisation`, and only one of those is the right question. `describe_pack` says which fields your choice reads.

Three limits worth knowing before you build on this.

**There is no dedupe tool.** `compare_records(records, records)` self-links, and the result contains self-pairs and each real pair twice. Drop `a_id == b_id`, then keep one ordering. The library's `dedupe` does this; the tool does not yet.

**Nothing is remembered unless the operator sets `ARCHE_LEDGER`.** Without it, results are edges and the server keeps no state. With it, one DuckDB file the operator names, `compare_records` records every edge and the eight [ledger](keep-and-replay.md) tools read them back. So A~B and B~C do tell an agent that A, B and C are one entity (`entities`), and why (`path`), and a `review` has somewhere to go (`cases`, fetch a field, `observe`). None of the eight returns a record value. [Keep, explain, replay](keep-and-replay.md) walks the whole loop.

**Scores are batch-dependent.** `entity=` routes through `reconcile`, which for the `person` pack calibrates a token-frequency table over the two lists being linked. The same pair can score differently in a different batch, because how ordinary a shared name is depends on the company it keeps. The `pins` record which table was used, so two results with different `tf` pins were never expected to agree.

`backend="splink"` on `compare_records` hands the scoring to Splink with a configuration derived from the pack, which warns that it is best-effort; the [size floor](resolve-a-batch.md#which-scorer-ran) that `backend="auto"` applies in the library is not applied here.

## Flow B: protection

Four calls, in this order, and the first two are not optional if you want to trust the fourth.

```text
capabilities()          what can this installation do at all?
        |
infer_jurisdiction()    which law governs THIS document?
        |               policy_available: false?  stop, or pick a statute
        |
plan_protection()       what can be found here, and what cannot?
        |               verdict: none?  a clean result would mean nothing
        |               was looked for
        |
guarded_scan()          redact, with citations, fail-closed
```

### 1. `capabilities()`

What ships and what is installed. Cheap, pure, and the honest first call: several tools return empty results rather than errors when an optional extra is missing, and this is how you find that out without reading a traceback.

```json
{
  "arche_core_version": "0.9.0",
  "jurisdictions_inferable": ["DE", "EU", "GB", "KE", "NG", "US", "ZA"],
  "entity_packs": ["artist", "organisation", "organization", "person", "place",
                   "product_electronics", "product_grocery", "product_home_goods"],
  "extras": {"detect": true, "splink": true, "doc": false},
  "ledger": {"configured": false, "tools": []}
}
```

`detect: false` means `detect_entities` will find pattern-shaped identifiers and no personal names at all.

### 2. `infer_jurisdiction(text)`

Which law governs the document, from evidence inside it. This is a tool rather than a setting because a configured jurisdiction is the operator's guess applied to every document alike; that is right for a single-jurisdiction deployment and cannot work on a mixed stream.

```json
{
  "country": "NG", "confidence": 1.0, "margin": 1.0, "abstained": false,
  "evidence": [{"signal": "id.nin", "tier": "A", "country": "NG", "count": 1, "weight": 1.0, "source": "text"},
               {"signal": "registrar.cac", "tier": "A", "country": "NG", "count": 1, "weight": 1.0, "source": "text"}],
  "statute_id": "NDPA-2023", "policy_available": true
}
```

**Read `policy_available` before going further.** A country can be inferred with full confidence and have no pack:

```json
{
  "country": "US", "confidence": 1.0, "abstained": false,
  "statute_id": null, "policy_available": false,
  "policy_reason": "the United States has no omnibus federal privacy statute, so there is no single pack to apply. This is a fact about US law rather than a gap in arche",
  "policy_alternatives": ["HIPAA-SAFE-HARBOR", "BASELINE"]
}
```

Without that field the next call refuses and the refusal reads as a bug. With it, an unpoliced jurisdiction is a decision the agent makes rather than a wall it hits. **Abstention is an answer**: `abstained: true` means nothing in the document said where it came from. Treat it as a question for a person, not a failure. The evidence carries signal names and counts, never the matched text, because a sample can be a registration number.

### 3. `plan_protection(jurisdiction=...)`

What this pipeline could and could not find, before you hand it anything. For `GB`:

```json
{
  "verdict": "partial",
  "uncovered": ["PII-2-DRIVERS_LICENCE", "PII-2-NIN", "PII-2-RC", "PII-2-TIN", "PII-5-BANK_ACCOUNT", "PII-5-CARD"],
  "degraded_categories": ["PII-1-NAME", "PII-3-PHONE", "PII-4-LOCATION"],
  "calibration_mismatch": [
    {"detector": "names", "calibrated_for": ["AFRICA"], "categories": ["PII-1-NAME"],
     "note": "built on an African name lexicon; a name it has not seen is not detected, and outside Africa most are not seen"}
  ]
}
```

Three things to read, in order of sharpness. `uncovered`: the statute governs these and nothing installed can find them. `degraded_categories`: a detector exists, ran, and was built for somewhere else. This is the subtler one and it is usually the one that bites: for `GB`, the name, phone and location detectors are all African-calibrated, so they report their categories as covered and then find few British ones. `verdict`: expect `partial`. It is the normal answer, including for Nigeria, whose statute governs health, religion and biometric categories arche ships no detector for. `partial` is not a reason to stop. `none` is: it means a clean result would mean nothing was looked for, and `guarded_scan` refuses outright in that state.

### 4. `guarded_scan(text, ...)`

Redacts personal data to deterministic hashed tokens, each with the statute section that required it.

```json
{
  "denied": false,
  "redacted_text": "[NAME:ff3a81b1f0469783] [NAME:7407c82e2f1d98c6], NIN [NIN:8b888b97a3474d11]",
  "fields": [{"category": "PII-2-NIN", "action": "mask", "token": "8b888b97...",
              "citation": "NDPA-2023 s.30, NIMC Act s.27", "tier": "high"}],
  "coverage": {"verdict": "partial", "statute_id": "NDPA-2023", "degraded_categories": []},
  "offsets_match_original": false
}
```

**Five refusals, all deny by default:** no statute governs this jurisdiction; the provider is not allow-listed; a cross-border transfer has no declared basis; anything raised; or no installed detector can find a single category the statute governs.

**Read `coverage` even when `denied` is false.** That is the whole point of the block. A clean result from a pipeline with no detector for the locale looks identical to a clean document.

**The token is your correlation handle.** The same input value produces the same token across calls, so an agent can join an entity across documents and sessions without this server storing anything between calls. That is better than a session id: nothing to lose, nothing to expire, nothing held in memory. `ARCHE_HASH_KEY` must be set or the tool refuses, with `denied: true` and a reason naming the variable. It does not invent an ephemeral key, because tokens that silently stop correlating between runs while appearing to work is a worse failure than a clear refusal.

## Offsets

`detect_pii`, `detect_entities` and `extract_places` return offsets into the original text. `guarded_scan`'s `redacted_text` has different offsets, because replacement tokens are a different length from what they replace. Slicing one with the other returns the wrong span, and a shifted window can expose an adjacent value. Every tool that returns offsets says which text they index; check the field rather than assuming.

## Configuration is a ceiling

```text
ARCHE_HASH_KEY          required for guarded_scan; no key, no tokens
ARCHE_JURISDICTION      ceiling jurisdiction; a call may not override it
ARCHE_STATUTE           ceiling statute id; a call may not override it
ARCHE_ALLOWED_PROVIDERS comma-separated model-provider allow-list
ARCHE_TRANSFER_BASIS    declared cross-border transfer basis
ARCHE_LEDGER            duckdb:///FILE (or a path): remember decisions there
ARCHE_SIGNING_KEY       PEM from `arche attest keygen`: every answer carries an attestation
```

`ARCHE_HASH_KEY` is what makes tokens stable across calls, so the same person gets the same token in every document. Keep it. Changing it changes every token, and correlation across previously processed documents is lost.

The jurisdiction and statute settings are a ceiling, not a default. Set, they are the strictest policy the server will operate under; a per-call argument may narrow and cannot widen. That asymmetry is the point. Making jurisdiction an argument is what lets the inference flow work, and it also hands the choice of governing law to the agent, and an agent that can choose its statute can choose a weaker one. Pin the ceiling when a deployment handles one jurisdiction and an agent has no business choosing. Leave it unset for a mixed stream and let `infer_jurisdiction` decide per document.

## What it will not do

**Reveal.** No tool has a reveal option. Detections come back as offsets because the caller already holds the text; `guarded_scan` returns tokens.

**Touch the filesystem.** Nothing reads or writes a path.

**Remember anything on its own.** Every handler is a pure function; there is no session and no document handle. Memory exists only as the ledger file an operator named in `ARCHE_LEDGER`, and the agent gets ids, labels, field names and numbers out of it, never a value. The stable token from `guarded_scan` does the cross-document correlating either way.

**Run African ID detectors outside Africa.** Enforced, not defaulted: an eleven-digit German tax number is the same shape as a Nigerian NIN, and a confident mislabel in a signed audit log is worse than a miss.

## Attested answers

With `ARCHE_SIGNING_KEY` set to a PEM from `arche attest keygen`, every tool's answer carries an `attestation`: a JWS by this installation over the tool name, a hash of the arguments, a hash of the answer and the decision ids in it. `capabilities` names the signer. stdio has no caller identity, so `caller` is `null`; the point is the binding of question to answer, which lets an auditor check an agent's transcript against what arche signed. See [Attested answers](../how-it-works/attestation.md).

## When it does not work

**`Connection closed` from the Inspector.** Almost always the inline-command form. Use `--config`.

**`guarded_scan` returns `denied: true` about a hash key.** `ARCHE_HASH_KEY` is unset. It refuses rather than generating an ephemeral one.

**`uv` prints a `VIRTUAL_ENV` mismatch warning.** Harmless. It goes to stderr, so it does not corrupt the JSON-RPC stream on stdout. Worth knowing because if it went to stdout every client would disconnect.

**`detect_entities` returns nothing.** Check `capabilities()["extras"]["detect"]`. Without a NER backend it finds pattern-shaped identifiers and no personal names at all, and returns an empty list rather than erroring. Install `arche-core[detect]`.

**Empty results generally.** Read the `coverage` block before believing them. A pipeline with no detector for the locale returns a clean-looking result that means nothing was looked for.

**The ledger tools are missing.** They are registered only when `ARCHE_LEDGER` was set before the server started; `capabilities()["ledger"]` says whether it was.

## Where to read next

| You want to | Read |
|---|---|
| the same verbs with a socket in front, for a client that speaks HTTP | [Serve over HTTP](serve-over-http.md) |
| every number in a `compare_records` edge, and the size floor | [Resolve a batch](resolve-a-batch.md) |
| what the eight ledger tools read, and the loop from `cases` to `observe` | [Keep, explain, replay](keep-and-replay.md) |
| the redaction verbs the protection tools wrap | [Find and mask](find-and-mask.md) |
| the container and the proxy that gives it authentication | [Docker and deploy](../get-started/docker.md) |
| the signed envelope on every answer | [Attested answers](../how-it-works/attestation.md) |
