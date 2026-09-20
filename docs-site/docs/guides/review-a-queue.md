# Review a queue

A batch result has pairs marked `review`, and those are questions for a person. At the end of this page you have a review pack a reviewer can open, an adjudication that binds each outcome to the decision it answers and that an auditor can re-check, a masked copy you can send onward, and a measurement of the run against pairs whose answer you already knew.

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

`arche compare a.csv b.csv --entity organisation` is the same command on two files of your own. It writes two things: `report.html`, every pair the engine matched or held for review with the fields that agreed, the fields that did not and the gate that decided, and a JSON sidecar of the decisions (`report.json` by default; `--json` names another path). Values are masked unless you pass `--reveal`, so the report can travel and the working copy is a deliberate choice.

## What a reviewer sees

`arche studio` is the local reading tool. It ships in the wheel, it is the standard library and nothing else, and it binds `127.0.0.1` with no authentication because there is no remote access.

```sh
arche studio                            # opens http://127.0.0.1:8765
arche studio --packs review_packs       # another pack directory
arche studio --ledger decisions.duckdb  # the Explain pane reads decisions by id
```

Review packs are read from `./data/review_packs` inside a checkout that has one and from `~/.arche/studio/review_packs` otherwise; `ARCHE_STUDIO_HOME` moves the whole thing and `--no-browser` keeps it from opening a tab. The reviewer's own state, the adjudications and the signing key, lives beside the packs under `_studio/`, never inside a pack.

Three panes draw one evidence panel. *Compare* takes two pasted records and a pack and shows the decision, the per-field evidence and the gate that produced it. *Review* opens a pack and walks it: both records side by side, the same evidence panel, an outcome, a reason, save. *Explain* takes a `dec:`, `xwd:` or `red:` id from a ledger and shows what supported it, what refuted it, what was missing, and a replay under the engine installed now; `http://127.0.0.1:8765/?explain=xwd:sha256:...` opens straight onto one, which is the link to put in a ticket.

The pair worth trying first in *Compare* is two records both named `General Hospital`, as `place`:

```text
review   1.000
name              1.000
name_tftoken      1.000
name_type         1.000

Held for a human
The fields agree, but nothing that agreed is distinctive. The strongest
signal scored 0.564 against a floor of 0.750.
```

The score is 1.000 and the engine still will not merge them. *General* and *Hospital* are ordinary words, and agreeing on ordinary words is not evidence. A matcher that cannot make that distinction merges two hospitals in different states and reports perfect confidence.

Saving never overwrites the matcher's output: it writes a `_reviewed.csv` beside the pack and a masked `_shared/` directory beside that, and names both in the confirmation. A reviewer name is required, because an unattributed adjudication cannot be audited. And a pack whose content changed since it was written is refused, because the manifest carries a digest over every column the matcher wrote.

## Turn a batch result into a pack

`review_pack` writes the two files the studio opens, and the same two files any spreadsheet or internal queue can work from. The studio is one way to adjudicate; the pack and the adjudication are the contract.

```python
import arche
from arche.report import review_pack

register = [
    {"id": "R-1", "name": "Amara Patel", "birth_date": "2016-06-28"},
    {"id": "R-2", "name": "Malik Okonkwo", "birth_date": "2017-08-18"},
    {"id": "R-3", "name": "Ibrahim Musa", "birth_date": "2015-01-09"},
    {"id": "R-4", "name": "Ibrahim Musa", "birth_date": "2016-04-22"},
]
survey = [
    {"id": "S-1", "name": "Amara Patel", "birth_date": "6/28/2016"},
    {"id": "S-2", "name": "Malik Okonkwo", "birth_date": "2017-08-18"},
    {"id": "S-3", "name": "Ibrahim Musa", "birth_date": "2015-11-09"},
]

result = arche.reconcile(register, survey, entity="person")
for edge in result["matches"]:
    print(edge["a_id"], edge["b_id"], edge["decision"], edge["score"], edge["evidence"])

manifest = review_pack(
    result, register, survey,
    out_dir="review_packs/register_x_survey",
    sides=("register", "survey"),
    entity="person",
    reveal=True,
)
print(manifest["rows"], manifest["decisions"], manifest["disclosure"])
print(manifest["pins"]["engine"], manifest["pins"]["tf"][:20])
```

```text
R-1 S-1 match 1.0 {'name': 1.0, 'name_tftoken': 1.0, 'birth_date': 1.0}
R-2 S-2 match 1.0 {'name': 1.0, 'name_tftoken': 1.0, 'birth_date': 1.0}
R-3 S-3 match 0.7833 {'name': 1.0, 'name_tftoken': 1.0, 'birth_date': 0.35}
R-4 S-3 review 0.6667 {'name': 1.0, 'name_tftoken': 1.0, 'birth_date': 0.0}
4 {'match': 3, 'review': 1} revealed (working copy)
crosswalk.v1 self-calibrated@sha2
```

Two register rows share the name *Ibrahim Musa*. One has a birthday a month's digit away from the survey's and matches at 0.7833; the other is a year apart and is held for a person. That held pair is the queue.

`sides=` gives the column prefixes and the panel headings. By default only `match` and `review` rows are written, because a queue of pairs the engine already rejected is not a queue; pass `decisions=("match", "review", "no_match")` to audit those too. The directory holds `pack.csv`, one row per decision with four blank review columns, and `manifest.json`, which records what was run and a digest of the decision ids.

```python
import csv
with open("review_packs/register_x_survey/pack.csv", encoding="utf-8", newline="") as fh:
    rows = list(csv.DictReader(fh))
print(list(rows[0]))
print(rows[0]["decision_id"][:24], rows[0]["decision"], rows[0]["register_name"], rows[0]["survey_name"])
```

```text
['decision_id', 'decision', 'score', 'distinctive_max', 'register_id', 'register_birth_date', 'register_name', 'survey_id', 'survey_birth_date', 'survey_name', 'evidence', 'review_outcome', 'reviewer', 'reviewed_at', 'reason']
xwd:sha256:66a9b253c63be match Amara Patel Amara Patel
```

`reveal=True` is normal here, and it is the opposite of the report's default on purpose. A pack is a file that gets copied around, so masked is the fail-safe, but nobody can judge whether two people are the same when both names are redacted. The thing to be deliberate about is where the file goes afterwards, and the manifest records which of the two you produced: `"disclosure": "revealed (working copy)"`. If your row ids are themselves identifiers, a national id or a BVN used as the join key, the masked export refuses rather than laundering them; add a surrogate id column.

Read the `tf` pin. `self-calibrated` means the frequency table was built from the two lists you passed, so the same two records compared inside a different batch can score differently and land on a different decision. The digest makes that visible: two packs whose `tf` digests differ were scored against different vocabularies and were never expected to agree. A pack built with a shipped table pins `shipped:place@sha256:...` instead, and that one does not move between runs.

## Apply the outcomes

The human part happens wherever suits you: the studio, a spreadsheet, a notebook, an internal queue. It ends as an outcomes file, one row per decision, with `outcome` one of `same_entity`, `different` or `unresolved` and a named `reviewer`. `arche review template` writes a value-free sheet with just the ids and the four blank columns; a pack exported with `reveal=True` and filled in directly is already an outcomes file, and `review_outcome` is accepted as an alias for `outcome`.

```python
from arche.review import apply_outcomes, effective_decision, read_pack, verify_adjudication

PACK = "review_packs/register_x_survey"
pack = read_pack(PACK)
outcomes = {"match": "same_entity", "review": "different"}
with open("outcomes.csv", "w", encoding="utf-8", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=["decision_id", "outcome", "reviewer", "reason"])
    w.writeheader()
    for row in pack.rows:
        w.writerow({"decision_id": row["decision_id"], "outcome": outcomes[row["decision"]],
                    "reviewer": "dee", "reason": "checked against the enrolment card"})

adjudication = apply_outcomes(PACK, "outcomes.csv")
print(adjudication["schema"], len(adjudication["ledger"]), adjudication["outcomes_sha256"][:16])
report = verify_adjudication(adjudication, PACK)
print(report["ok"], report["outcomes_match"], report["pack_matches"])

by_id = {entry["decision_id"]: entry["outcome"] for entry in adjudication["ledger"]}
for row in pack.rows:
    outcome = by_id[row["decision_id"]]
    print(row["register_id"], row["survey_id"], row["decision"], outcome, "->", effective_decision(row, outcome))
```

```text
arche.adjudication.v1 4 bc9c9ecc47856556
True True True
R-1 S-1 match same_entity -> match
R-2 S-2 match same_entity -> match
R-3 S-3 match same_entity -> match
R-4 S-3 review different -> no_match
```

The loop stands in for the reviewer; the outcomes here are what a person who checked the enrolment cards would write. `apply_outcomes` binds them to the pack: the adjudication carries a `ledger`, one row per decision with its outcome, reviewer and reason, and `outcomes_sha256` over that ledger, which says which decision got which outcome where a tally would only say how many of each. It also carries `source_pack_content_sha256`, so it is bound to the content of the pack and not to a filename. `verify_adjudication` re-checks both halves and they fail separately: an edited ledger gives `ledger-digest-mismatch`, and reading it beside the wrong pack gives `pack-mismatch`.

Two rules are enforced. Every outcome must name a reviewer. And a pack that does not match its manifest is refused, because an adjudication built on it would attest to a document nobody can identify; `require_clean_pack=False` (or `--allow-dirty-pack`) overrides that when you know why.

`effective_decision` is where the two vocabularies meet. `same_entity` is a claim about the world and `match` is a claim about what the system will do, so the mapping is written once: `review` plus `same_entity` is `match`, `review` plus `different` is `no_match`, and `match` plus `unresolved` is `review`. That last one matters: a reviewer who looked and could not decide has said something, and what they said is that this stays held. It must not read as unreviewed. `write_reviewed_csv` adds `effective_decision` beside `decision` rather than overwriting it, because what the matcher said is the thing being audited.

What none of this establishes is who reviewed. `reviewer` is a string somebody typed. The digests prove the artifact has not changed since it was made; they do not prove the names in it are real people. That is an identity problem, and an auth proxy in front of whatever tool does the reviewing is what solves it.

The same three steps from the command line, so they can be a pipeline stage:

```sh
arche review validate review_packs/register_x_survey
arche review apply    review_packs/register_x_survey outcomes.csv --out adjudication.json
arche review verify   adjudication.json review_packs/register_x_survey
```

```text
review_packs\register_x_survey\pack.csv  4 rows
content_sha256  dff07d016e246effd24306d9adb424e7930170384e586f6000a4477e4f45bcd2
OK
4 marked, 0 unmarked  {'different': 1, 'same_entity': 3}
outcomes_sha256  bc9c9ecc478565564fbb97e7ee5c9856e46b80f190d7425a42b16736eb95d8aa
-> adjudication.json
marked            4
outcomes_match    True
pack_matches      True
OK
```

`validate` answers one question, is this the pack the matcher wrote, and exits non-zero when it is not; `--json` gives a machine-readable report. `read_pack` also reads parquet (`arche-core[parquet]`), JSONL and JSON, and the formats agree on the digest, so an adjudication made against a parquet copy verifies against the CSV.

## Send it onward

The pack you reviewed has real names in it, because it had to. Everything downstream of a review, a summary for the programme team, a sample for a partner, an attachment on a ticket, is a copy of it leaving the machine.

```python
from arche.review import share_artifact

shared = share_artifact(PACK, "review_packs/register_x_survey_shared", adjudication=adjudication)
print(shared["disclosure"])
```

```text
masked (safe to share)
```

Or `arche review share review_packs/register_x_survey review_packs/register_x_survey_shared --adjudication adjudication.json`. Record values go through the same masking allowlist `review_pack` uses in its masked mode, so there is one implementation of *masked*. What survives is the decision machinery: `decision_id`, `decision`, `score`, `distinctive_max`, `evidence`, the outcomes, and the ids you join on. Reviewer reasons are dropped by default, because a reason is free text typed under time pressure and *same person, spoke to Amara's mother* names the person the rest of the row just masked; `include_reasons=True` keeps them when you know what is in them. It is a new artifact with its own `content_sha256` and a `source_pack_content_sha256` pointing back, so neither file pretends to be the other. If you sign anything, sign this one.

## Measure against pairs you already know

Adjudications are also labels. `same_entity` outcomes are positive pairs, `different` outcomes are hard negatives, and `unresolved` stays out of the labelled set. `evaluate` scores a batch result against them.

```python
from arche.resolve.metrics import evaluate

metrics = evaluate(
    result["matches"],
    gold=[("R-1", "S-1"), ("R-2", "S-2"), ("R-3", "S-3")],
    hard_negatives=[("R-4", "S-3")],
)
print(metrics)
```

```text
{'precision': 1.0, 'recall': 1.0, 'f1': 1.0, 'true_positives': 3, 'false_positives': 0, 'false_negatives': 0, 'matches': 3, 'review_queue': 1, 'surfaced_recall': 1.0, 'false_merge_rate': 0.0, 'false_merges': []}
```

Read the whole set, not one number. `precision` and `recall` count automatic matches only; `review_queue` is how many pairs were handed to a person, and `surfaced_recall` counts a true pair as found whether it was matched or queued, so conservative routing is not mistaken for an error-free system. `false_merges` lists the hard negatives the engine merged, because a generic name wrongly auto-matched is usually more costly than a record sent to review, and a count would hide which ones.

The labels have to be able to carry the claim. Claim precision only when every automatic match can be checked or the labelled set is a valid, predeclared sample. Claim recall only when the true-pair mapping is complete for the population: reviewing the queue alone cannot reveal a candidate that was never proposed. Record the dataset version, the matcher pins, the decision policy and every metric together, and re-run when any of them changes. A result that does not meet the false-merge or review-capacity limit agreed beforehand is a reason to stop the automatic action, not a number to round.

## Where to read next

| You want to | Read |
|---|---|
| where the `review` pairs came from, and what each number in an edge means | [Resolve a batch](resolve-a-batch.md) |
| what `review` means and why the score is not a probability | [Compare two records](compare-two-records.md) |
| the cases still open in a ledger, and adding evidence to close one | [Keep, explain, replay](keep-and-replay.md) |
| the fields on a receipt and what each means | [The decision](../how-it-works/the-decision.md) |
| a signed answer someone else can verify | [Attested answers](../how-it-works/attestation.md) |
| the measured runs, including the ones arche loses | [Benchmarks](../reference/benchmarks.md) |
