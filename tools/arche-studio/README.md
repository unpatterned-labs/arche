# arche studio

Compare two records, or work a review queue. Three files, no dependencies
beyond `arche-core` itself.

```bash
python tools/arche-studio/serve.py
```

It opens `http://127.0.0.1:8765` for you.

## The folder

```
tools/arche-studio/
├── serve.py      a local server, standard library only
├── index.html    the entire interface, one file, no CDN
└── README.md     this
```

That is the whole thing. There is no build step, no `pip install`, no
framework, and no network access. `index.html` is readable top to bottom.

This matters because the people who most need to look at a match decision are
often not the people who can install a Python package. A reviewer with a laptop
and a browser is the audience.

## Compare

Paste two records. Pick an entity pack. Get the decision, the evidence behind
it, and a plain sentence explaining why.

The fields are free-form, so this works for two bare names or for full records
with coordinates and identifiers. Add a field, name it whatever your data calls
it, and the pack decides what to do with it.

Worth trying first: two records both named `General Hospital`, entity `place`.
Byte-identical strings, and the engine holds them:

```
review   1.000
name              1.000
name_tftoken      1.000
name_type         1.000

Held for a human
The fields agree, but nothing that agreed is distinctive. The strongest
signal scored 0.564 against a floor of 0.750, so the agreement could be
coincidence. Common names do this.
```

Read that twice. **The score is 1.000.** Every comparator agrees perfectly,
because the two strings are identical. And the engine still refuses to merge
them, because `General` and `Hospital` are ordinary words and agreeing on
ordinary words is not evidence.

That is the whole argument of the project on one screen. Agreement is worth
what the rarity of the thing agreed on says it is worth, and a system that
cannot tell the difference will merge two hospitals in different states and
report a perfect score while doing it.

`Load an example` cycles through four pairs worth understanding: a Nigerian
facility upgraded to a new tier, two spellings of one Fula surname, a dropped
middle name, and two schools from the same academy chain.

## Review queue

Point it at an adjudication pack and walk it: filter to what needs a human, see
both records side by side with the same evidence panel, mark an outcome, give a
reason, save.

Packs live in `data/review_packs/`. Any CSV works. The tool guesses which
columns belong to which side from their prefixes, so a pack with `grid3_name`
and `hfr_name` renders without configuration.

Three things are deliberate:

**The original is never written to.** Saving produces a new `_reviewed.csv`
beside it, so the matcher output and its decision-ID manifest stay intact.

**A reviewer name is required.** An unattributed adjudication cannot be
audited, so the save is refused without one.

**The pack carries an integrity digest**, computed over its decision ids and
shown in the header. If someone edits the pack between matching and reviewing,
the digest moves.

## What it is not

Not a service. It binds to `127.0.0.1` and is meant to be run on the machine
that has the data. There is no authentication because there is no remote
access, and adding one without the other would be theatre.

It supersedes the earlier Streamlit `tools/review_log`, which needed a
dependency to do less.
