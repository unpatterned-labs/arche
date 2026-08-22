# arche-mcp

An MCP server for [arche](https://github.com/unpatterned-labs/arche). Gives an agent ten tools: work out which law governs a document, find out what this installation can and cannot detect, redact personal data to stable tokens with the statute section that required it, and reconcile two record lists.

```sh
uvx arche-mcp
```

Speaks stdio. Point any MCP client at that command.

Full guide: **[Let an agent call arche](https://arche.unpatterned.org/guides/mcp-server/)**.

## The tools

| tool | answers |
| --- | --- |
| `capabilities` | what this installation can actually do |
| `infer_jurisdiction` | which law governs this document, and is there a pack for it |
| `plan_protection` | what could this pipeline find, and what could it not |
| `describe_pack` | which record fields an entity pack reads |
| `detect_pii` | personal data as offsets, with citations |
| `detect_entities` | named entities as typed offsets |
| `guarded_scan` | redact to hashed IDs, fail-closed |
| `compare_records` | reconcile two record lists |
| `check_name_equivalence` | are these two names the same person's |
| `extract_places` | place mentions with their spatial role |

## Four calls, in order

```
capabilities()          what can this installation do at all?
infer_jurisdiction()    which law governs THIS document?
plan_protection()       what can be found here, and what cannot?
guarded_scan()          redact, with citations, fail-closed
```

The first two are not optional if you want to trust the fourth. `infer_jurisdiction` returns `policy_available`, because a country can be inferred with full confidence and still have no statute pack — sometimes because none ships, sometimes because no such law exists. `plan_protection` says which categories nothing installed can find, and separately which have a detector built for somewhere else.

## Three things that are deliberate

**Silence is never safety.** A tool returning nothing looks like good news. `detect_pii` and `guarded_scan` both carry a coverage block, because `count: 0` from a pipeline with no detector for the locale is indistinguishable from a clean document.

**Nothing touches the filesystem.** An earlier version had a tool that read two caller-supplied paths and wrote a report to a third. MCP has no consent model for a filesystem write. Use the `arche compare` CLI, where a person sees the command before it runs.

**Nothing is remembered.** Every handler is a pure function — no session, no document handle, no store. The hashed token does the correlating instead: the same input value produces the same token across calls, so an agent can join an entity across documents without this server holding anything.

## See it work, without an agent

```sh
uv run python packages/arche-mcp/demo.py
```

Calls the same functions the tools call, in the order an agent would, and prints what comes back. No MCP client, no model, no API key, nothing to go wrong in front of a room.

It runs one referral note through the flow twice, Nigerian and British, because the difference is the argument:

```
--- Nigeria ---
  infer_jurisdiction  -> NG (confidence 1.0, from: id.nin, registrar.cac, phone.ng)
                         statute NDPA-2023, policy_available=True
  guarded_scan        -> 6 fields removed
                         Referral: Dr [NAME:0aba5577] Okonkwo, NIN [NIN:de117765], at ...
                           PII-2-NIN        mask      NDPA-2023 s.30, NIMC Act s.27
                           PII-4-LOCATION   retain    NDPA-2023 s.31 (legitimate interests)

--- Britain ---
  infer_jurisdiction  -> GB (confidence 1.0, from: postcode.uk)
  plan_protection     -> partial
                         6 categories with no detector at all
                         3 with a detector built elsewhere: PII-1-NAME, PII-3-PHONE, PII-4-LOCATION
  guarded_scan        -> 0 fields removed
```

Same tool, same code. Nigeria gets a redaction with the section that required it. Britain gets nothing removed **and says so** — three of the detectors that ran were built for African data, so a clean result there does not mean the document was clean.

Watch `PII-4-LOCATION retain` in the Nigerian run. A statute that permits keeping something is doing as much work as one that removes it, and a redactor that only ever deletes has not read the law.

## Wire it to a client

Claude Desktop, `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "arche": {
      "command": "uvx",
      "args": ["arche-mcp"],
      "env": {
        "ARCHE_HASH_KEY": "a-long-random-string-you-keep"
      }
    }
  }
}
```

`ARCHE_HASH_KEY` is required or `guarded_scan` refuses. It is what makes tokens stable across calls, so the same person gets the same token in every document. Keep it; changing it changes every token.

Add `"ARCHE_JURISDICTION": "NG"` to pin the server to one jurisdiction. Leave it out for a mixed stream, and let `infer_jurisdiction` decide per document.

Running from a checkout instead of PyPI:

```json
{"command": "uv",
 "args": ["run", "--directory", "/path/to/arche", "arche-mcp"]}
```

## Configuration

```
ARCHE_JURISDICTION      ceiling jurisdiction; a call may not override it
ARCHE_STATUTE           ceiling statute id; a call may not override it
ARCHE_HASH_KEY          required for guarded_scan
ARCHE_ALLOWED_PROVIDERS comma-separated model-provider allow-list
ARCHE_TRANSFER_BASIS    declared cross-border transfer basis
```

A ceiling, not a default: a per-call argument may narrow it and cannot widen it. Unset, the caller chooses, which is the mixed-document-stream case.

## Install extras

`arche-mcp[detect]` adds a NER backend. Without it `detect_entities` finds pattern-shaped identifiers and no personal names at all — check `capabilities()["extras"]["detect"]` before reading an empty result as clean.

## Not yet

HTTP and SSE transport, and authentication. It speaks stdio and expects to run on the machine holding the data.

## Licence

Apache-2.0.
