# Five minutes

Three commands, no data of your own, no model download. At the end you have seen a redaction with the statute attached, a verdict with its evidence, and a report you could hand to someone.

```sh
pip install arche-core
```

## 1. Redact a sentence under its statute

```sh
arche redact --text "Patient Casey Example (NIN 12345678901) called from 0803 555 7890." \
    --jurisdiction NG --backend basic
```

```text
2 span(s) under NDPA-2023 (NG, basic, statute)  decision_id red:sha256:ef519ebafc...
Patient Casey Example (NIN [NIN]) called from PHONE_d3100c11.
```

The statute chose each rendering: NDPA section 30 masks a national id and tokenises a phone. The name stayed because *Casey Example* is not in the lexicon and no model ran (`--backend auto` adds one when [`detect2`](install.md#extras) is installed). The `decision_id` is a content hash over the spans, their actions and the versions that decided them; run the command again and it comes back byte for byte.

Leave off `--jurisdiction` and arche refuses rather than guesses, because a redaction under the wrong law looks finished and is not. Point it at a file instead of `--text` and it reads `.txt`, `.md`, `.pdf` and `.docx`.

## 2. Are these two the same person?

```sh
arche compare --text "Adesola Okonkwo, NIN 12345678901, adesola@example.com" \
                     "Adesola E. Okonkwo, NIN 12345678901, 124 Maple Street" --json -
```

```json
{
  "identity": "same_entity",
  "action": "merge",
  "basis": "corroborated",
  "explanation": "national ID match; name similarity 80%",
  "score": 1.0,
  "factors": {"name": 0.8, "national_id": 1.0, "name_tf": 0.7233},
  "decision_id": "dec:sha256:8912e7da95835995ea26b78045221e321a0a8f03fba5c1fca25ab24c9c00dc02",
  "recorded": false
}
```

Two answers, on purpose. `identity` is what arche believes: the same person, because a shared national id is distinctive. `action` is what it recommends: `merge`, because the name corroborates the id. With the id alone and a conflicting email, the action would be `hold`: same belief, no recommendation to act on it yet. `recorded: false` says nothing was kept; add `--record` with `ARCHE_LEDGER` set and the receipt goes in a ledger.

## 3. A report you can hand to someone

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

Open `report.html`. Every pair the engine matched or held for review, with the fields that agreed, the fields that did not, and the gate that decided. Values are masked by default so the report can travel; `--reveal` makes the working copy. The same command takes two of your own files: `arche compare suppliers.csv registry.csv --entity organisation`.

## Where to read next

| You want to | Read |
|---|---|
| the same three things in Python, with the receipt in your code | [From Python](python.md) |
| what `review` means and what to do with it | [Compare two records](../guides/compare-two-records.md) |
| keep every decision and replay it next year | [Keep, explain, replay](../guides/keep-and-replay.md) |
| resolve two lists, not two texts | [Resolve a batch](../guides/resolve-a-batch.md) |
| run it as a service, or let an agent call it | [Serve over HTTP](../guides/serve-over-http.md), [Let an agent call arche](../guides/mcp-server.md) |
| the numbers behind the claims, including the runs where arche loses | [Benchmarks](../reference/benchmarks.md) |
