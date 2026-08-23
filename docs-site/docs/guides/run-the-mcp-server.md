# Run the arche MCP server

Three ways to see arche through MCP, in increasing order of what they prove and what they need.

| | proves | needs |
| --- | --- | --- |
| **1. The script** | the engine works, and says why | nothing |
| **2. The Inspector** | the real protocol, driven by you | `npx` |
| **3. Chat** | a model choosing tools on its own | an API key |

Pick by what you are trying to show. For a talk where nothing may go wrong, use 1. To poke at a tool with your own arguments, use 2. To demonstrate what MCP actually is, use 3.

A thing worth understanding before any of them: **an MCP server has no interface.** It is a tool provider speaking JSON-RPC over stdio. There is nothing to open, no port to visit. The interface is always the client, which is why option 1 looks scripted (there is no client, so the script stands in for one) and why option 3 is the only one that shows tool *selection*.

## 1. The script

```sh
uv run python packages/arche-mcp/demo.py
```

No client, no model, no key, about fifteen seconds. It calls the same functions the tools call, in the order an agent would.

It runs one referral note through the flow **twice**, and the difference is the whole point:

```
--- Nigeria ---
  infer_jurisdiction  -> NG (confidence 1.0, from: id.nin, registrar.cac, phone.ng)
                         statute NDPA-2023, policy_available=True
  guarded_scan        -> 6 fields removed
                           PII-2-NIN        mask      NDPA-2023 s.30, NIMC Act s.27
                           PII-4-LOCATION   retain    NDPA-2023 s.31 (legitimate interests)

--- Britain ---
  infer_jurisdiction  -> GB (confidence 1.0, from: postcode.uk)
  plan_protection     -> partial
                         3 with a detector built elsewhere: PII-1-NAME, PII-3-PHONE, PII-4-LOCATION
  guarded_scan        -> 0 fields removed
```

Two lines to point at. `PII-4-LOCATION retain` — a statute *permitting* something is doing as much work as one removing it. And Britain's `0 fields removed` next to its coverage line — anyone can build a redactor that removes things; almost nobody ships one that tells you when it could not look.

## 2. The Inspector

The official MCP client, as a web UI or a one-shot CLI. Nothing to install permanently.

`mcp-demo.json` ships in the repo root:

```json
{
  "mcpServers": {
    "arche": {
      "command": "uv",
      "args": ["run", "--directory", "C:/Users/Dee/arche/arche", "arche-mcp"],
      "env": { "ARCHE_HASH_KEY": "change-me-to-a-long-random-string" }
    }
  }
}
```

Change the `--directory` to your checkout and set a hash key. Then:

```sh
npx @modelcontextprotocol/inspector --config mcp-demo.json --server arche
```

That opens a browser: every tool listed with its schema, a form to fill in, and the raw response. Click `infer_jurisdiction`, paste a document, watch the evidence come back.

One-shot from a terminal instead:

```sh
npx @modelcontextprotocol/inspector --cli --config mcp-demo.json --server arche \
  --method tools/list

npx @modelcontextprotocol/inspector --cli --config mcp-demo.json --server arche \
  --method tools/call --tool-name infer_jurisdiction \
  --tool-arg "text=NIN 12345678901, RC 1234567, Karfi Health Post, Kano"
```

**Use the config-file form.** Passing the command inline (`--cli uv run arche-mcp --method tools/list`) does not work: everything after the command is forwarded to the server, so `--method` reaches `arche-mcp` instead of the Inspector and the connection closes.

## 3. Chat, with a model choosing

```sh
uv run python packages/arche-mcp/chat.py
uv run python packages/arche-mcp/chat.py "is this safe to send? NIN 12345678901, Kano"
```

This starts the real server as a subprocess, speaks the protocol to it, hands the tool schemas to a model, and lets the model decide. Nothing in the script picks the order.

Needs `OPENAI_API_KEY`. It reads `.env` in the repo root, which is gitignored, and will not prompt for a key or fall back to one. Override the model with `ARCHE_CHAT_MODEL` (default `gpt-4o-mini`).

Every tool call prints before it runs and its result after, so the transcript is the demo:

```
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

The model was not told to call those three, in that order. It read the tool descriptions and worked it out, which is the property worth demonstrating. It is also why the descriptions in `server.py` are long: **for an MCP server the tool description is the documentation**, because it is the only thing the model reads.

Try `"are General Hospital and General Hospital the same place?"` for the resolution half. The answer is `review`, and the model will tell you why.

## 4. A real client

Same config, dropped into Claude Desktop's `claude_desktop_config.json`, then restart it:

```json
{
  "mcpServers": {
    "arche": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/arche", "arche-mcp"],
      "env": { "ARCHE_HASH_KEY": "a-long-random-string-you-keep" }
    }
  }
}
```

Once `arche-mcp` is published this becomes `"command": "uvx", "args": ["arche-mcp"]` and needs no checkout at all.

## Configuration

```
ARCHE_HASH_KEY          required for guarded_scan; no key, no tokens
ARCHE_JURISDICTION      ceiling jurisdiction; a call may not override it
ARCHE_STATUTE           ceiling statute id; a call may not override it
ARCHE_ALLOWED_PROVIDERS comma-separated model-provider allow-list
ARCHE_TRANSFER_BASIS    declared cross-border transfer basis
```

`ARCHE_HASH_KEY` is what makes tokens stable across calls, so the same person gets the same token in every document. Keep it. Changing it changes every token, and correlation across previously-processed documents is lost.

The jurisdiction and statute settings are a **ceiling, not a default**: a per-call argument may narrow them and cannot widen them. Set them when a deployment handles one jurisdiction and an agent has no business choosing. Leave them unset for a mixed stream, and let `infer_jurisdiction` decide per document.

## When it does not work

**`Connection closed` from the Inspector.** Almost always the inline-command form. Use `--config`.

**`guarded_scan` returns `denied: true` about a hash key.** `ARCHE_HASH_KEY` is unset. It refuses rather than generating an ephemeral one, because tokens that silently stop correlating between runs while appearing to work is a worse failure than a clear refusal.

**`uv` prints a `VIRTUAL_ENV` mismatch warning.** Harmless. It goes to stderr, so it does not corrupt the JSON-RPC stream on stdout. Worth knowing because if it went to stdout every client would disconnect.

**`detect_entities` returns nothing.** Check `capabilities()["extras"]["detect"]`. Without a NER backend it finds pattern-shaped identifiers and no personal names at all, and returns an empty list rather than erroring. Install `arche-mcp[detect]`.

**Empty results generally.** Read the `coverage` block before believing them. A pipeline with no detector for the locale returns a clean-looking result that means nothing was looked for.
