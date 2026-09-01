# Compare two records, or work a review queue

`arche studio` is a small local tool with two jobs: decide whether two records are the same thing, and walk an adjudication pack marking outcomes.

It is a handful of files and the standard library. No `pip install`, no framework, no network access.

```bash
python tools/arche-studio/serve.py
```

It opens `http://127.0.0.1:8765` for you.

## Compare

Paste two records, pick an entity pack, and get the decision with the evidence behind it and a sentence saying why. The fields are free-form, so it works for two bare names or for full records with coordinates and identifiers.

The pair worth trying first is two records both named `General Hospital`, as `place`:

```text
review   1.000
name              1.000
name_tftoken      1.000
name_type         1.000

Held for a human
The fields agree, but nothing that agreed is distinctive. The strongest
signal scored 0.564 against a floor of 0.750.
```

The score is 1.000 and the engine still will not merge them. `General` and `Hospital` are ordinary words, and agreeing on ordinary words is not evidence. A matcher that cannot make that distinction merges two hospitals in different states and reports perfect confidence.

`Load an example` cycles through four pairs: a Nigerian facility upgraded to a new tier, two spellings of one Fula surname, a dropped middle name, and two schools from the same academy chain.

## Review queue

Point it at an adjudication pack in `data/review_packs/` and work through it. Filter to what needs a human, read both records side by side with the same evidence panel, mark an outcome, give a reason, save.

Any CSV works. The tool infers which columns belong to which side from their prefixes, so a pack with `grid3_name` and `hfr_name` renders without configuration.

## Export a match result as a pack

`review_pack` turns any `reconcile` result into the two files the studio opens.

```python
from arche.report import review_pack
from arche.resolve import reconcile

register = [{"id": "1", "name": "Amara Patel", "birth_date": "2016-06-28"},
            {"id": "2", "name": "Malik Okonkwo", "birth_date": "2017-08-18"}]
survey   = [{"id": "1", "name": "Amara Patel", "birth_date": "6/28/2016"},
            {"id": "2", "name": "Malik Okonkwo", "birth_date": "2017-08-18"}]

result = reconcile(register, survey, entity="person", id_field="id")

review_pack(
    result, register, survey,
    out_dir="data/review_packs/register_x_survey",
    sides=("register", "survey"),   # column prefixes, and the panel headings
    entity="person",
    reveal=True,                    # see below before you copy this
)
```

That writes:

```
data/review_packs/register_x_survey/
  pack.csv        one row per decision, four blank review columns
  manifest.json   what was run, and a digest of the decision ids
```

Start the studio and the pack is in the picker:

```sh
python tools/arche-studio/serve.py
```

The CSV columns are `decision_id`, `decision`, `score`, `distinctive_max`, then each side under its own prefix, then `evidence` as JSON, then the four columns a reviewer fills. `distance_km` is added when the evidence carries one.

By default only `match` and `review` rows are written. A queue of pairs the engine already rejected is not a queue. Pass `decisions=("match", "review", "no_match")` when you want to audit those too.

### Masked by default, and why you will usually override it

A pack is a file that gets copied around, so it follows the same fail-safe as `crosswalk_report`, its HTML sibling: values pass through the masking allowlist, and record ids that look like national identifiers are refused outright rather than laundered.

A masked pack is also close to useless for the thing a pack is *for*. Nobody can judge whether two people are the same when both names are redacted. So `reveal=True` is normal here, and the thing to be deliberate about is where the file goes afterwards. `data/review_packs/` is the intended home, and the manifest records which of the two you produced:

```json
"disclosure": "revealed (working copy)"
```

If your row ids are themselves sensitive, a national ID or a BVN used as the join key, the export refuses in masked mode. Add a surrogate id column rather than revealing to get past it.

### The manifest is the reproducibility record

This is the manifest the call above writes, not an illustration of one:

```json
{
  "schema": "arche.review_pack.v1",
  "entity": "person",
  "rows": 2,
  "decisions": {"match": 2},
  "pins": {
    "engine": "crosswalk.v1",
    "comparators_sha256": "8d1e03d23fa6b8a649dca0eac9e0ce6909683f7a89ecf7dadb9de89f44e1f334",
    "block": "union",
    "threshold": 0.7,
    "review_margin": 0.15,
    "distinctive_floor": 0.75,
    "tf": "self-calibrated@sha256:739ea1e68c3da830cabfa450277923b43e261aeaaf03903a48358c2e852c8acc"
  },
  "content_sha256": "...",
  "decision_ids_sha256": "..."
}
```

`pins` says which engine, which comparator set, and which token-frequency table produced the decisions, so a pack reviewed months later still says what it was. `content_sha256` covers every column the matcher wrote, so an edited name or a flipped decision moves it, and it is recomputable from the CSV alone with `arche.report.pack_content_digest`. `decision_ids_sha256` sits beside it and covers membership only: it notices a row added or dropped and nothing inside a row, which is why both are there.

**Read the `tf` line.** `self-calibrated` means the frequency table was built from the two lists you passed, so it describes *this* pair of lists and nothing else. Rarity decides how much a shared name is worth, so the same two records compared inside a different batch can score differently and can land on a different decision. That is what self-calibration is for, and the digest is there so it is visible rather than implied: two packs whose `tf` digests differ were scored against different vocabularies and were never expected to agree.

A pack built with a shipped table pins `shipped:place@sha256:...` instead, and that one does not move between runs.

## Work a pack without the studio

The studio is one way to adjudicate a pack. It is not the supported way, because it lives in this repository and `pip install arche-core` does not give you it. What the library gives you is the artifact protocol: read a pack, check it is the one the matcher wrote, apply outcomes you arrived at however you liked, and get something an auditor can re-check.

The human part happens wherever suits you. A spreadsheet, a notebook, an internal queue, the studio. None of those need to be arche.

```sh
arche review validate data/review_packs/register_x_survey
arche review apply    data/review_packs/register_x_survey outcomes.csv --out adjudication.json
arche review verify   adjudication.json data/review_packs/register_x_survey
```

`validate` answers one question: is this the pack the matcher wrote? It checks the content digest, the row count against the manifest, and that every `decision_id` is present and unique. It exits non-zero when the answer is no, so it works as a pipeline step, and `--json` gives a machine-readable report.

### The outcomes file

CSV, JSONL or JSON, one row per decision:

```
decision_id,outcome,reviewer,reason
xwd:sha256:ab12...,same_entity,dee,same school, tier renamed
xwd:sha256:cd34...,different,dee,different LGA
```

`outcome` must be `same_entity`, `different` or `unresolved`. `reason` and `reviewed_at` are optional. Extra columns are ignored rather than rejected, because a reviewer's own spreadsheet will have some.

**A pack you exported with `reveal=True` and filled in directly is already an outcomes file.** Its four review columns are this schema, and `review_outcome` is accepted as an alias for `outcome`, so there is nothing to rename.

Two rules are enforced rather than suggested. Every outcome must name a reviewer, because an unattributed adjudication cannot be audited. And by default a pack that does not match its manifest is refused, because an adjudication built on it would attest to a document nobody can identify. `--allow-dirty-pack` overrides that when you know why.

### The adjudication

```python
import csv

from arche.review import apply_outcomes, read_pack, verify_adjudication

PACK = "data/review_packs/register_x_survey"

# Stand-in for the human part: whatever you use to decide, it ends as this file.
pack = read_pack(PACK)
with open("outcomes.csv", "w", encoding="utf-8", newline="") as fh:
    writer = csv.DictWriter(fh, fieldnames=["decision_id", "outcome", "reviewer"])
    writer.writeheader()
    for decision_id in pack.decision_ids:
        writer.writerow({"decision_id": decision_id,
                         "outcome": "same_entity", "reviewer": "dee"})

adjudication = apply_outcomes(PACK, "outcomes.csv")
report = verify_adjudication(adjudication, PACK)
assert report["ok"] and report["outcomes_match"] and report["pack_matches"]
```

The artifact carries a `ledger`, one row per decision with its outcome, reviewer and reason, and `outcomes_sha256` over that ledger. That digest is the binding: it says which decision got which outcome, where a tally of outcomes would only say how many of each.

It also carries `source_pack_content_sha256`, so it is bound to the content of the pack it was made against and not to a filename. `verify_adjudication` re-checks both halves and they fail separately: an edited ledger gives `ledger-digest-mismatch`, and reading it beside the wrong pack gives `pack-mismatch`.

**What none of this establishes is who reviewed.** `reviewer` is a string somebody typed. The digests prove the artifact has not changed since it was made; they do not prove the names in it are real people. That is an identity problem, and an auth proxy in front of whatever tool does the reviewing is what solves it.

### A pack does not have to be a CSV

`review_pack` writes one, because CSV is what a reviewer can open in anything.
`read_pack` also reads parquet, JSONL and JSON, so a pipeline that ends in
parquet does not have to convert before it can be reviewed:

<!-- docs-test: fragment -->
```python
from arche.review import read_pack

pack = read_pack("data/decisions.parquet")     # or .jsonl, .json, .csv
```

Point it at a directory and it looks for `pack.csv` first, then the others, then
any single readable file — so a directory holding `decisions.parquet` works
without renaming anything.

**The formats agree on the digest**, which is the property that makes this safe
rather than merely possible. The same pack written three ways produces one
`content_sha256`, so an adjudication made against the parquet copy verifies
against the CSV copy. That requires narrowing the typed formats to the untyped
one on read: a parquet `1.0` and a CSV `"1.0"` have to hash identically, and
evidence written as a nested JSON object has to hash the same as evidence
written as a JSON string. Types are lost, deliberately — a pack is a document to
be read and adjudicated, not a frame to compute on.

Parquet needs `pip install arche-core[parquet]`. The other formats are standard
library. A format with no reader is refused rather than sniffed: a pack is
re-read months later, and a file whose format was guessed is a file whose
reading cannot be reproduced.

### What the pair now stands as

An adjudication and the matcher's own answer are two different columns, and
until you combine them nothing tells you where a pair actually landed:

```python
from arche.review import effective_decision

effective_decision({"decision": "review"}, "same_entity")   # -> "match"
effective_decision({"decision": "review"}, "different")     # -> "no_match"
effective_decision({"decision": "match"}, "unresolved")     # -> "review"
```

The vocabularies stay separate on purpose. `same_entity` is a claim about the
world and `match` is a claim about what the system will do, so the mapping is
written down once rather than re-derived wherever a result is displayed.

Note the third line. *Cannot tell* is a **finding**, not the absence of one: a
reviewer who looked and could not decide has said something, and what they said
is that this stays held. It must not read as unreviewed.

`write_reviewed_csv` adds `effective_decision` beside `decision` rather than
overwriting it. Both are worth keeping — what the matcher said is the thing
being audited, and destroying it to record the audit would be self-defeating.

### Sending it onward

The pack you just reviewed has real names in it, because it had to. That makes it a local document, and everything downstream of a review — a summary for the programme team, a sample for a partner, an attachment on a ticket — is a copy of it leaving the machine.

`share_artifact` derives the other file:

```python
from arche.review import share_artifact

manifest = share_artifact(
    PACK, "data/review_packs/register_x_survey_shared",
    adjudication=adjudication,      # carries the outcomes across
)
assert manifest["disclosure"] == "masked (safe to share)"
```

Or without writing Python:

```sh
arche review share data/review_packs/register_x_survey \
    data/review_packs/register_x_survey_shared \
    --adjudication adjudication.json
```

Record values go through the same masking allowlist `review_pack` uses in its masked mode, so there is one implementation of *masked* rather than two that can drift apart. What survives is the decision machinery — `decision_id`, `decision`, `score`, `distinctive_max`, `evidence`, and the ids you join on. A score is not somebody's data, and a reader cannot see what the matcher did without it.

The studio writes this file on every save, beside the reviewed copy, and names both in the confirmation. That is deliberate: a redaction step you have to remember is a redaction step that does not happen.

Three things are worth knowing before you rely on it.

**Reviewer reasons are dropped.** A reason is free text somebody typed under time pressure, and *same person, spoke to Amara's mother* names the person the rest of the row just masked. Running a detector over free text would catch most of those and miss the rest quietly, which is the worse failure. Pass `include_reasons=True` when you know what is in them.

**The ids are not masked, and they are yours to check.** They have to survive or the file joins to nothing. If your join key is itself an identifier — a BVN, a national ID — the export refuses rather than laundering it, the same refusal `review_pack` makes. Name a surrogate column instead:

```python
share_artifact(PACK, "out", id_columns=["register_ref", "survey_ref"])
```

**It is a new artifact, not an edited one.** It carries its own `content_sha256` over its own rows, and `source_pack_content_sha256` pointing back at the pack it came from. Masking in place would leave the original manifest describing a file that no longer exists; this way the pair is linked and neither one pretends to be the other. If you sign anything, sign this one — the digest worth attesting is the one over the thing you actually sent.

## What it will not let you do

**Overwrite the matcher's output.** Saving writes a new `_reviewed.csv` beside the pack, and a masked `_shared/` directory beside that. The original and its manifest stay intact.

**Save anonymously.** A reviewer name is required, because an unattributed adjudication cannot be audited.

**Review a pack that changed underneath you.** The manifest carries `content_sha256` over every column the matcher wrote, so a name edited or a decision flipped between matching and reviewing moves it. The short digest in the header covers the decision ids only, which catches a row added or dropped and not an edit inside one.

## Scope

It binds to `127.0.0.1` and expects to run on the machine holding the data. There is no authentication because there is no remote access.

It replaces an earlier Streamlit review app, which required a dependency to do less.
