# Compare two records, or work a review queue

`arche studio` is a small local tool with two jobs: decide whether two records
are the same thing, and walk an adjudication pack marking outcomes.

It is three files and the standard library. No `pip install`, no framework, no
network access.

```bash
python tools/arche-studio/serve.py
```

It opens `http://127.0.0.1:8765` for you.

## Compare

Paste two records, pick an entity pack, and get the decision with the evidence
behind it and a sentence saying why. The fields are free-form, so it works for
two bare names or for full records with coordinates and identifiers.

The pair worth trying first is two records both named `General Hospital`, as
`place`:

```text
review   1.000
name              1.000
name_tftoken      1.000
name_type         1.000

Held for a human
The fields agree, but nothing that agreed is distinctive. The strongest
signal scored 0.564 against a floor of 0.750.
```

The score is 1.000 and the engine still will not merge them. `General` and
`Hospital` are ordinary words, and agreeing on ordinary words is not evidence.
A matcher that cannot make that distinction merges two hospitals in different
states and reports perfect confidence.

`Load an example` cycles through four pairs: a Nigerian facility upgraded to a
new tier, two spellings of one Fula surname, a dropped middle name, and two
schools from the same academy chain.

## Review queue

Point it at an adjudication pack in `data/review_packs/` and work through it.
Filter to what needs a human, read both records side by side with the same
evidence panel, mark an outcome, give a reason, save.

Any CSV works. The tool infers which columns belong to which side from their
prefixes, so a pack with `grid3_name` and `hfr_name` renders without
configuration.

## What it will not let you do

**Overwrite the matcher's output.** Saving writes a new `_reviewed.csv` beside
the pack. The original and its decision-ID manifest stay intact.

**Save anonymously.** A reviewer name is required, because an unattributed
adjudication cannot be audited.

**Review a pack that changed underneath you.** The header shows an integrity
digest computed over the pack's decision ids. If the file was edited between
matching and reviewing, the digest moves.

## Scope

It binds to `127.0.0.1` and expects to run on the machine holding the data.
There is no authentication because there is no remote access.

It replaces an earlier Streamlit review app, which required a dependency to do
less.
