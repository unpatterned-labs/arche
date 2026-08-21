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

`review_pack` turns any `crosswalk` result into the two files the studio opens.

```python
from arche.report import review_pack
from arche.resolve import crosswalk

register = [{"id": "1", "name": "Amara Patel", "birth_date": "2016-06-28"},
            {"id": "2", "name": "Malik Okonkwo", "birth_date": "2017-08-18"}]
survey   = [{"id": "1", "name": "Amara Patel", "birth_date": "6/28/2016"},
            {"id": "2", "name": "Malik Okonkwo", "birth_date": "2017-08-18"}]

result = crosswalk(register, survey, entity="person", id_field="id")

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
  "decision_ids_sha256": "..."
}
```

`pins` says which engine, which comparator set, and which token-frequency table produced the decisions, so a pack reviewed months later still says what it was. `decision_ids_sha256` is what the studio's integrity digest is checked against.

**Read the `tf` line.** `self-calibrated` means the frequency table was built from the two lists you passed, so it describes *this* pair of lists and nothing else. Rarity decides how much a shared name is worth, so the same two records compared inside a different batch can score differently and can land on a different decision. That is what self-calibration is for, and the digest is there so it is visible rather than implied: two packs whose `tf` digests differ were scored against different vocabularies and were never expected to agree.

A pack built with a shipped table pins `shipped:place@sha256:...` instead, and that one does not move between runs.

## What it will not let you do

**Overwrite the matcher's output.** Saving writes a new `_reviewed.csv` beside the pack. The original and its decision-ID manifest stay intact.

**Save anonymously.** A reviewer name is required, because an unattributed adjudication cannot be audited.

**Review a pack that changed underneath you.** The header shows an integrity digest computed over the pack's decision ids. If the file was edited between matching and reviewing, the digest moves.

## Scope

It binds to `127.0.0.1` and expects to run on the machine holding the data. There is no authentication because there is no remote access.

It replaces an earlier Streamlit review app, which required a dependency to do less.
