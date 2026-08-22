# arche studio

Compare two records, read spatial roles out of a document, or work a review
queue. A handful of files, no Python dependencies beyond `arche-core` itself.

```bash
python tools/arche-studio/serve.py
```

It opens `http://127.0.0.1:8765` for you.

## The folder

```
tools/arche-studio/
├── serve.py      a local server, standard library only
├── index.html    the entire interface, one file
├── state.py      append-only adjudication store (SQLite)
├── keyring.py    this installation's signing key
└── README.md     this
```

That is the whole thing. No build step, no `pip install`, no framework.
`index.html` is readable top to bottom.

It makes exactly one external request: two typefaces from Google Fonts. An
earlier version made none, and that was worth giving up for a page that reads
like a page. Offline it falls back to a local serif stack and stays fully
usable; only the typography changes. For a hard air gap, download Source Serif
4 and JetBrains Mono and swap the `<link>` for a `@font-face` block.

This matters because the people who most need to look at a match decision are
often not the people who can install a Python package. A reviewer with a laptop
and a browser is the audience.

## Compare

Paste two records. Pick an entity pack. Get the decision, the evidence behind
it, and a plain sentence explaining why.

The fields are free-form, so this works for two bare names or for full records
with coordinates and identifiers. The margin lists what the chosen pack reads
and how much each field counts, derived from the pack rather than written out
by hand — `person` gained a date comparator in 0.5.0a1 and a hand-written list
would already have been wrong.

A field the pack does not name is **ignored, not rejected**: no error, no
warning, no change to the score. That is the right behaviour, and it is silent,
so fields the pack will not read are struck through as you type them.

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

## Documents

Drop two or more documents. Every entity is found, everything that identifies
somebody is hidden, and the column on the right says which section of which
statute made that call. Then the matcher runs across the documents.

One document tells you a person is mentioned. Two and a matcher tell you whether
it is the *same* person, which is the question anybody reconciling a register
against a survey actually has.

Three things are worth watching for.

**`uncovered`.** Under NDPA-2023 a person's *name* draws no rule at all. The
statute has plenty to say about a national ID and nothing about `Adesola
Okonkwo`. The tempting reading is that showing it must therefore be fine; that
is exactly backwards. An uncovered detection is one nobody has decided about, so
it is hidden here and labelled as this tool's choice rather than a statute's. A
tool that showed it because no statute objected would turn a gap in coverage
into a permission.

**`retain`.** A statute that permits keeping something is doing as much work as
one that removes it. `Kano` stays visible under NDPA s.31, and the citation says
so. A redactor that only ever deletes has not read the law.

**Reveal is a display control, not a claim.** These are your documents, off your
disk; you are not being shown anything you did not already have. It is built as
a display control honestly: the values are not in the page at all until you ask
for them, so a page that has not asked cannot leak what it never received. The
alternative — send everything and hide it with CSS — would make "redacted" a
statement about styling.

The matching runs on the real values either way. Comparing `[PERSON]` against
`[PERSON]` would score the placeholder, not the person, so the engine sees the
names and the page does not. You can read the judgement without reading the
names, which is a useful thing to be able to do in front of a room.

Plain text is read directly. PDF, DOCX, PPTX and XLSX go through the document
lane, which needs `arche-core[doc]`. Finding a name at all needs a NER backend:
`arche-core[detect]`.

## Spatial roles

Paste a dispatch note or drop a document. The tool marks every place mention
with the role its cue implies, and shows the cue that decided it.

*From Karfi to Kano* names two places, and the difference between them is the
meaning of the sentence. Swap them and the consignment goes backwards.

Watch it get one wrong, on purpose: in the first example, *deliver to the
central warehouse in Kano* comes back as a **location**, not a destination. The
nearer `in` cue beats `deliver to`. The rules are a cue lexicon, not a parser,
and the margin note says so rather than hiding it.

Plain text is read directly. PDF, DOCX, PPTX and XLSX go through the document
lane, which needs `arche-core[doc]`.

## Review queue

Point it at an adjudication pack and walk it: filter to what needs a human, see
both records side by side with the same evidence panel, mark an outcome, give a
reason, save.

Packs live in `data/review_packs/`. CSV, parquet, JSONL and JSON all work, and
the same pack in two of those formats produces the same content digest — so an
adjudication made against one verifies against the other. Parquet needs
`arche-core[parquet]`.

The tool does not parse them itself. `arche.review.read_pack` does, which is
also what infers the two sides from the column prefixes, so a pack with
`grid3_name` and `hfr_name` renders without configuration and the library and
the tool cannot come to disagree about what a pack is.

Marking a row changes what you see. The `resolved` column carries the standing
answer — the reviewer's call where there is one, the matcher's otherwise — and
the *still needs a human* filter drops rows as you settle them, so the queue
gets shorter as you work it. `1` `2` `3` make the call and `j` `k` move.
*Cannot tell* is a finding, not a resolution: the row stays in the queue.

### Getting a match result in here

`arche.report.review_pack` writes the two files this reads, from any
`crosswalk` result:

```python
from arche.report import review_pack
from arche.resolve import crosswalk

result = crosswalk(register, survey, entity="person", id_field="id")
review_pack(result, register, survey,
            out_dir="data/review_packs/register_x_survey",
            sides=("register", "survey"),   # the column prefixes above
            entity="person",
            reveal=True)                    # a masked pack cannot be judged
```

Restart the server, or just reload: the pack picker rereads the directory. Full
notes, including what `reveal` costs you, are in
`docs-site/docs/guides/review-log.md`.

The `manifest.json` it writes beside the CSV carries both digests and the
engine `pins`, so a pack opened months later still says which comparator set
produced it.

Three things are deliberate:

**The original is never written to.** Saving produces a new `_reviewed.csv`
beside it, so the matcher output and its manifest stay intact.

**Saving produces two files, and only one of them is safe to send.** The
`_reviewed.csv` carries real names, because that is what the reviewer was
looking at and a masked pack cannot be judged. Beside it goes a `_shared/`
directory holding the same decisions with every record value masked, its own
`content_sha256`, and a pointer back to the pack it came from. The confirmation
names both, one labelled *your copy* and the other *safe to share*, because the
filenames do not tell them apart and somebody is about to attach one to an
email. Reviewer reasons are dropped from the shared copy: free text can name the
person the row just masked. `arche review share` does the same thing from a
terminal.

**A reviewer name is required.** An unattributed adjudication cannot be
audited, so the save is refused without one.

**The pack carries two digests.** `content_sha256` in the manifest covers every
column the matcher wrote, so an edited name or a flipped decision moves it, and
it is recomputable from the CSV with `arche.report.pack_content_digest`. The
short digest in the header covers the decision ids only: it catches a row added
or dropped and nothing inside a row.


## Deploying it

Short answer: don't, not as it stands.

It binds to `127.0.0.1` and has no authentication, no CSRF protection, and no
per-user anything. Binding to localhost is not a security model: a container
with a published port, a port-forward, or a browser induced into calling it can
all reach a service that assumed nobody could. `POST /api/review` writes a file. Bound to `0.0.0.0` that
becomes a remote write, and the only thing standing in front of it is the path
check that keeps writes inside `data/review_packs/`. That is a guard against a
mistake, not against an attacker.

Three honest options, in order of how much they cost:

**Run it locally, per person.** What it was built for. The data is already on
that machine; the tool is three files and needs no install. This is the
recommended answer and it stays the recommended answer for longer than you
would expect.

**Put it behind an auth proxy.** Tailscale, Cloudflare Access, `oauth2-proxy`.
Zero code change, real access control, identity borrowed from something that
already does it properly. If two or three people need to work the same queue,
this is the answer, and the reviewer name field stops being an honesty system.

**Build multi-user properly.** Sessions, per-user state, an audit trail of who
saw which record, and a threat model. That is a different project with
different obligations, and it should be a decision rather than a drift.

One thing that would need fixing before any network exposure: the reviewer name
is typed by the person reviewing. Locally that is fine, because the only person
who can type it is the person sitting there. Behind a proxy it should come from
the proxy's identity header, not from a text box, or the audit trail records
whatever someone felt like typing.

## What it is not

Not a service. It binds to `127.0.0.1` and is meant to be run on the machine
that has the data. There is no authentication because there is no remote
access, and adding one without the other would be theatre.

It supersedes the earlier Streamlit `tools/review_log`, which needed a
dependency to do less.
