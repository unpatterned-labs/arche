# Let an agent call arche

`arche-mcp` is an MCP server. It gives an agent ten tools for two jobs: **resolving entities** — are these two records the same thing, and what is the evidence — and **protecting data** — what may leave this boundary, and on whose authority.

```sh
uvx arche-mcp
```

That is the whole install. It speaks stdio, so point any MCP client at that command.

## The shape of the thing

An MCP tool is called **unattended**. No person reads the arguments, no person sees the result before it reaches a model. Three consequences run through everything below.

**The tool description is the documentation.** An agent reads that and nothing else, so the descriptions carry the caveats rather than deferring to a page like this one.

**A silent failure is worse here than anywhere.** A tool returning nothing looks like good news. Most of the design below is about making "I found nothing" distinguishable from "I could not look".

**No tool touches the filesystem.** An earlier version had one that read two caller-supplied paths and wrote a report to a third. MCP has no consent model for a filesystem write, so it is gone. Use the `arche compare` CLI, where a person sees the command before it runs.

## Two flows, not one

There are two things an agent comes here to do, and they share almost no tools.

**Resolve entities** — are these two records the same thing? Three calls.

**Protect data** — what may leave this boundary, and on whose authority? Four calls.

They compose: resolve a pair, then guard what you send onward about it. But they are separate, and an agent doing only one does not need the other.

## Flow A — entity resolution

```
capabilities()                          which entity packs exist
        │
describe_pack("person")                 which fields does it read?
        │                               └─ a field it does not name is IGNORED,
        │                                  silently. Map your columns here.
        │
compare_records(a, b, entity="person")  decisions, evidence, pins
```

What comes back is per-pair: `a_id`, `b_id`, `score`, `decision`, `distinctive_max`, `evidence`, and engine `pins` recording which comparator set and frequency table produced it.

**`review` is a decision, not a failure**, and it is the one worth understanding. Two records both called *General Hospital* score 1.000 and come back `review`, because `distinctive_max` is 0.564 against a floor of 0.750 — every field agreed and nothing that agreed was distinctive. An agent that treats `review` as `no_match` throws away the most interesting output; an agent that treats it as `match` merges two hospitals in different states.

Three limits worth knowing before you build on this.

**There is no dedupe entry point.** `compare_records(records, records)` self-links, and the result contains self-pairs (`x1 ~ x1`) and each real pair twice (`x1 ~ x2` and `x2 ~ x1`). Filter both yourself: drop `a_id == b_id`, then keep one ordering. arche resolves *between* lists; deduplicating *within* one is not a first-class operation yet.

**There is no clustering.** Results are pairwise edges. If A matches B and B matches C, nothing here tells you A, B and C are one entity — transitive closure over `reconcile` output does not exist.

**There is nowhere to put a `review` outcome.** `arche.review` in the library reads a pack, applies adjudicated outcomes and verifies them, and none of it is exposed as a tool. An agent can produce a review queue and cannot work one.

**Scores are batch-dependent.** `entity=` routes through `reconcile`, which self-calibrates a token-frequency table over the two lists being linked. The same pair can score differently in a different batch, because how ordinary a shared name is depends on the company it keeps. The `pins` record which table was used, so two results with different `tf` pins were never expected to agree.

## Flow B — protection

Four calls, in this order, and the first two are not optional if you want to trust the fourth.

```
capabilities()          what can this installation do at all?
        │
infer_jurisdiction()    which law governs THIS document?
        │               └─ policy_available: false?  stop, or pick a statute
        │
plan_protection()       what can be found here, and what cannot?
        │               └─ verdict: none?  a clean result would mean nothing
        │                  was looked for
        │
guarded_scan()          redact, with citations, fail-closed
```

### 1. `capabilities()`

What ships and what is installed. Cheap, pure, and the honest first call: several tools return empty results rather than errors when an optional extra is missing, and this is how you find that out without reading a traceback.

```json
{
  "arche_core_version": "0.6.0a1",
  "jurisdictions_inferable": ["DE", "EU", "GB", "KE", "NG", "US", "ZA"],
  "extras": {"detect": true, "splink": true, "doc": false}
}
```

`detect: false` means `detect_entities` will find pattern-shaped identifiers and **no personal names at all**.

### 2. `infer_jurisdiction(text)`

Which law governs the document, from evidence inside it.

This is a tool rather than a setting because a configured jurisdiction is the operator's guess applied to every document alike. That is right for a single-jurisdiction deployment and cannot work on a mixed stream.

```json
{
  "country": "NG", "confidence": 1.0, "margin": 1.0, "abstained": false,
  "evidence": [{"signal": "id.nin", "tier": "A", "count": 1, "weight": 1.0}],
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

Without that field the next call refuses and the refusal reads as a bug. With it, an unpoliced jurisdiction is a decision the agent makes rather than a wall it hits.

**Abstention is an answer.** `abstained: true` means nothing in the document said where it came from. Treat it as a question for a person, not a failure.

The evidence carries signal names and counts, never the matched text — a sample can be a registration number.

### 3. `plan_protection(jurisdiction=...)`

What this pipeline could and could not find, **before** you hand it anything.

```json
{
  "verdict": "partial",
  "uncovered": ["PII-2-NIN", "PII-2-TIN", "PII-5-CARD", "..."],
  "degraded_categories": ["PII-1-NAME", "PII-3-PHONE", "PII-4-LOCATION"],
  "calibration_mismatch": [
    {"detector": "names", "calibrated_for": ["AFRICA"],
     "note": "built on an African name lexicon; a name it has not seen is not detected, and outside Africa most are not seen"}
  ]
}
```

Three things to read, in order of sharpness.

`uncovered` — the statute governs these and nothing installed can find them.

`degraded_categories` — a detector exists, ran, and was built for somewhere else. This is the subtler one and it is usually the one that bites. For `GB`, the name, phone and location detectors are all African-calibrated: they report their categories as covered and then find nothing British.

`verdict` — **expect `partial`.** It is the normal answer, including for Nigeria, whose statute governs health, religion and biometric categories arche ships no detector for. `partial` is not a reason to stop. `none` is: it means a clean result would mean nothing was looked for, and `guarded_scan` refuses outright in that state.

### 4. `guarded_scan(text, ...)`

The flagship. Redacts personal data to deterministic hashed tokens, each with the statute section that required it.

```json
{
  "denied": false,
  "redacted_text": "[NAME:2c775a2c…] Okonkwo, NIN [NIN:8518cf0b…]",
  "fields": [{"category": "PII-2-NIN", "action": "mask",
              "token": "8518cf0b…", "citation": "NDPA-2023 s.30, NIMC Act s.27"}],
  "coverage": {"verdict": "partial", "degraded_categories": []},
  "offsets_match_original": false
}
```

**Five refusals, all deny by default:** no statute governs this jurisdiction; the provider is not allow-listed; a cross-border transfer has no declared basis; anything raised; or no installed detector can find a single category the statute governs.

**Read `coverage` even when `denied` is false.** That is the whole point of the block. A clean result from a pipeline with no detector for the locale looks identical to a clean document.

**The token is your correlation handle.** The same input value produces the same token across calls, so an agent can join an entity across documents and sessions without this server storing anything between calls. That is deliberately better than a session id: nothing to lose, nothing to expire, nothing held in memory.

`ARCHE_HASH_KEY` must be set or the tool refuses. It does not invent an ephemeral key, because tokens that silently stop correlating between runs while appearing to work is a worse failure than a clear refusal.

## Offsets

`detect_pii`, `detect_entities` and `extract_places` return offsets into the **original** text. `guarded_scan`'s `redacted_text` has different offsets, because replacement tokens are a different length from what they replace.

Slicing one with the other returns the wrong span, and a shifted window can expose an adjacent value. Every tool that returns offsets says which text they index; check the field rather than assuming.

## Configuration is a ceiling

```
ARCHE_JURISDICTION      ceiling jurisdiction; a call may not override it
ARCHE_STATUTE           ceiling statute id; a call may not override it
ARCHE_HASH_KEY          required for guarded_scan
ARCHE_ALLOWED_PROVIDERS comma-separated model-provider allow-list
ARCHE_TRANSFER_BASIS    declared cross-border transfer basis
```

Set, these are the strictest policy the server will operate under. A per-call argument may narrow and cannot widen.

That asymmetry is the point. Making jurisdiction an argument is what lets the inference flow work, and it also hands the choice of governing law to the agent — and an agent that can choose its statute can choose a weaker one. Pin the ceiling when a deployment handles one jurisdiction and an agent has no business choosing. Leave it unset for a mixed stream.

## On `compare_records` itself

The safest tool in the set: pure in, pure out, no filesystem, no state. Ids and numeric evidence come back, never record values.

<!-- docs-test: fragment -->
```python
compare_records(register, survey, entity="person")
```

Pass `entity=` for a shipped pack or `comparators=` to specify the comparison yourself. Not both — they say the same thing and one would silently win, so passing both is refused.

The `backend="splink"` scorer that `arche-core` 0.5.0a1 added is **not** reachable from here. `compare_records` uses arche's own engine. That is a gap rather than a decision.

## What it will not do

**Reveal.** No tool has a reveal option. Detections come back as offsets because the caller already holds the text; `guarded_scan` returns tokens.

**Touch the filesystem.** Nothing reads or writes a path.

**Remember anything.** Every handler is a pure function. There is no session, no document handle, no store. The stable token does the correlating instead.

**Run African ID detectors outside Africa.** Enforced, not defaulted: an eleven-digit German tax number is the same shape as a Nigerian NIN, and a confident mislabel in a signed audit log is worse than a miss.

## Not yet

HTTP and SSE transport, and authentication. It speaks stdio and expects to run on the machine holding the data.
