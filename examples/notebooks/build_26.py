"""Build 26_local_documents_to_entities.ipynb.

    python examples/notebooks/build_26.py

One invented referral letter, end to end on one machine: a PDF, parsed by
Docling, masked under NDPA-2023, facility mentions found by GLiNER 2.5, linked
to the public GRID3 Nigeria health-facility list, recorded in a ledger,
corrected by a reviewer, and issued as a verifiable credential.
"""

import json
from pathlib import Path

MD, CODE = "markdown", "code"
cells: list[tuple[str, str]] = []


def md(text: str) -> None:
    cells.append((MD, text.strip("\n")))


def code(text: str) -> None:
    cells.append((CODE, text.strip("\n")))


md("""
# From a PDF to linked, verifiable entities, locally

**One referral letter: Docling reads it, GLiNER finds the facilities, arche decides which real facilities they are.**

Extraction tools now do a good job of reading a document's structure and
picking out the names in it. The question that comes after is still mostly
done by hand: *which real facility is "Zango Health Post"?* Get it wrong and a
referral, a stock count or a payment goes to the wrong clinic.

This notebook runs the whole chain on one machine:

1. write an **invented** clinical referral letter as a PDF;
2. parse it with Docling (`arche.doc`);
3. mask what the Nigeria Data Protection Act 2023 requires, with a receipt;
4. find the health-facility mentions with GLiNER 2.5;
5. fetch the public GRID3 list of Kano State health facilities;
6. link the mentions to it, and hold the one the letter cannot settle;
7. keep the decisions in a ledger, let a reviewer correct a wrong link, and undo the merge;
8. issue a credential for the confirmed link that anyone can check.

The patient, NIN, phone number and date of birth are made up. The facility
names are real public records from GRID3.

```
pip install "arche-core[doc,detect2,ledger]" fpdf2
```

`fpdf2` only writes the demo PDF. The first run downloads the Docling layout models,
RapidOCR's models, GLiNER 2.5 and GLiNER2-PII (roughly 2 GB together); later
runs use the cache.
""")

code('''
import logging, socket, time, warnings

# Docling, RapidOCR and transformers log a lot at load time; none of it is
# about this letter.
logging.disable(logging.WARNING)
warnings.filterwarnings("ignore")

# Every hostname this kernel looks up from here on, and the step it was in.
# This is how the last section can say what went over the network instead of
# asserting it.
STEP = "setup"
CONTACTED: list[tuple[str, str]] = []
_getaddrinfo = socket.getaddrinfo

def _logged(host, *args, **kwargs):
    if (STEP, str(host)) not in CONTACTED:
        CONTACTED.append((STEP, str(host)))
    return _getaddrinfo(host, *args, **kwargs)

socket.getaddrinfo = _logged

import arche
print("arche-core", arche.__version__)
''')

md("""
## 1. An invented referral letter, as a PDF

A community health extension worker at a health post in Rimin Gado LGA refers
a pregnant patient to a specialist hospital in Kano city, copying a teaching
hospital. The patient's details sit in a table, the way they usually do on a
printed form.
""")

code('''
import tempfile
from pathlib import Path
from fpdf import FPDF

WORK = Path(tempfile.mkdtemp(prefix="arche-26-"))
PDF = WORK / "referral_letter.pdf"

pdf = FPDF()
pdf.add_page()
pdf.set_margins(22, 22, 22)

def para(text, size=11, style="", gap=5):
    pdf.set_font("Helvetica", style, size)
    pdf.multi_cell(0, 6, text, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(gap)

para("Zango Health Post", 16, "B", 1)
para("Zango Ward, Rimin Gado LGA, Kano State", 10, gap=8)
para("Referral letter", 13, "B", 4)
para("Date: 18 November 2026", gap=4)
para("To: The Medical Officer, Antenatal Clinic, Murtala Muhammad Specialist "
     "Hospital, Kano Municipal LGA, Kano State.", gap=6)

pdf.set_font("Helvetica", "", 11)
with pdf.table(col_widths=(45, 120), first_row_as_headings=True) as table:
    for row in [("Patient details", ""),
                ("Name", "Hauwa Danladi Yakasai"),      # invented
                ("Date of birth", "14/03/1994"),        # invented
                ("NIN", "70412938561"),                 # invented
                ("Phone", "0803 555 0142")]:            # invented
        cells = table.row()
        for value in row:
            cells.cell(value)
pdf.ln(6)

para("Dear Colleague,", gap=3)
para("I am referring the above patient, a 32-year-old woman at 34 weeks of "
     "gestation, with a blood pressure of 160/110 mmHg and proteinuria on "
     "dipstick. She was first seen at Zango Health Post on 11 November 2026. "
     "Kindly see and manage.")
para("A copy of this letter goes to the obstetric registrar at Aminu Kano "
     "Teaching Hospital, Tarauni LGA, Kano State.")
para("Yours faithfully,", gap=10)
para("Community Health Extension Worker", gap=1)
para("Zango Health Post, Rimin Gado LGA")
pdf.output(str(PDF))

print(f"{PDF.name}: {PDF.stat().st_size:,} bytes, written to a temporary folder")
''')

md("""
## 2. Docling turns the PDF into structure

`arche.doc.parse` is a thin wrapper over Docling's `DocumentConverter`. It
returns the linear text, the Markdown and the tables, and a `provenance`
block: the hash of the input file, the parser and its version, and the hash of
the text it produced. Everything downstream indexes into that text, so the
hash is what ties a later decision back to this exact parse.
""")

code('''
from arche.doc import parse

STEP = "parse"
t0 = time.perf_counter()
doc = parse(PDF)
text = doc.text
print(f"parsed in {time.perf_counter() - t0:.1f}s: {doc.num_pages} page, "
      f"{len(text):,} characters, {len(doc.tables)} table\\n")
print(doc.markdown)
''')

code('''
print("table rows:", doc.tables[0])
print()
for key in ("parser", "parser_version", "artifact_sha256", "text_sha256"):
    print(f"{key:<16} {doc.provenance[key]}")
''')

md("""
The table came back as a table and the paragraphs in reading order. Docling
keeps the justified spacing (`To:  The  Medical`), which is why the extracted
names below carry double spaces.
""")

md("""
## 3. Mask what the statute requires, with a receipt

`arche.deidentify(text, "NG")` loads the NDPA-2023 pack. Rules with validators
find the NIN, phone and dates; GLiNER2-PII (installed with `[detect2]`)
proposes the names the rules cannot see. The pack, not the caller, decides
what happens to each category: mask the NIN, tokenise the name and phone,
reduce the date of birth to the year, keep the state name.
""")

code('''
STEP = "deidentify"
t0 = time.perf_counter()
masked = arche.deidentify(text, "NG")
print(f"{masked.count} spans under {masked.statute} in {time.perf_counter() - t0:.1f}s\\n")
print(masked.text)
''')

code('''
# The letter is invented, so printing the matched text here is safe. On real
# data, `masked.spans()` is the account to keep: it carries no values.
for s in masked.spans():
    print(f"{s['category']:<15} {s['action']:<10} {text[s['start']:s['end']]!r:<26} "
          f"{s['citation']:<40} {s['detector']}")
''')

md("""
Two things to read in that table.

- **Over-masking.** `Rimin` and `Gado` are tokenised as personal names by the
  name lexicon: it does not know that Rimin Gado is an LGA. The masked copy
  loses the place, a privacy-safe error but still an error. The linking below
  runs on the original text, which never leaves the machine; the masked copy
  is what you would hand on.
- **Coverage is stated, not implied.** The receipt says which NDPA categories
  no installed detector looks for:
""")

code('''
print(masked.coverage["verdict"], "-", masked.coverage["note"])
''')

md("""
The receipt is content-addressed: its `decision_id` is a hash over the
document hash, every span (category, offsets, action, citation) and the pins
(engine version, model, detectors, statute version). Run it again and you get
the same id; change the model, the statute version or one span and you get a
different one.
""")

code('''
again = arche.deidentify(text, "NG")
print("decision_id:", masked.decision_id)
print("re-run gives the same id:", again.decision_id == masked.decision_id)
print("pins:", {k: masked.pins[k] for k in ("engine", "model", "statute", "statute_version")})
''')

md("""
The `NAME_…` and `PHONE_…` tokens are different on every run of this notebook,
and the id is not. Without `salt=`, tokens are keyed per process; the receipt
records which spans were found and what was done to them, not the token text.
Pass `salt=` (a secret of your own) when two masked copies must share tokens.
""")

md("""
## 4. GLiNER 2.5 finds the facility mentions

`arche.extract` with `backend="gliner2"` asks GLiNER 2.5 for the labels you
name. It is zero-shot: `"health facility"`, `"local government area"` and
`"state"` are just strings.

> **On a Mac with Apple Silicon, or an NVIDIA GPU (including WSL2),** the same
> call can run through MLX with `arche.configure(gliner2_runtime="mlx")`. That
> runtime is landing separately and is not exercised in this notebook; every
> span below came from the PyTorch build on CPU.
""")

code('''
STEP = "extract"
t0 = time.perf_counter()
spans = arche.extract(text, entity_types=["health facility", "local government area", "state"],
                      backend="gliner2")
print(f"{len(spans)} spans in {time.perf_counter() - t0:.1f}s\\n")
for e in spans:
    print(f"{e.entity_type:<22} {e.start:>4}-{e.end:<4} {e.confidence:.3f}  {e.text!r}")
''')

md("""
The model found all three real facilities, each time they appear, and two
things that are not facilities: `Zango Ward` (an administrative ward) and
`Antenatal Clinic` (a department of the receiving hospital). Neither is
filtered out here. Step 6 shows what linking does with them.

To turn spans into records, each facility mention takes the first LGA and
state mentioned within 80 characters after it, and repeated mentions of one
name are folded into one record. This is a small rule written for this letter,
not part of arche.
""")

code('''
from arche.jurisdictions.nigeria import admin_path

def squash(s):
    return " ".join(s.split())

def after(e, label, window=80):
    return next((x for x in spans if x.entity_type == label
                 and e.end <= x.start <= e.end + window), None)

mentions, seen = [], {}
for e in spans:
    if e.entity_type != "HEALTH FACILITY":
        continue
    lga, state = after(e, "LOCAL GOVERNMENT AREA"), after(e, "STATE")
    key = squash(e.text).casefold()
    if key not in seen:
        seen[key] = {"id": f"mention:{len(seen) + 1}", "name": squash(e.text),
                     "state": None, "lga": None}
        mentions.append(seen[key])
    m = seen[key]
    m["lga"] = m["lga"] or (lga and lga.text)
    m["state"] = m["state"] or (state and state.text)

for m in mentions:
    m["admin_path"] = admin_path(m.pop("state"), m.pop("lga"))
    print(f"{m['id']:<10} {m['name']:<38} {m['admin_path']}")
''')

md("""
`admin_path` folds `Kano State` to `kano` and `Rimin Gado LGA` to
`rimin gado`, the same folding applied to the reference below, so the two
sides compare as equals.

## 5. The reference: GRID3 Nigeria health facilities, Kano State

GRID3 NGA Health Facilities v4.0 (CIESIN, Columbia University, 2026,
[doi:10.7916/pjpv-9q55](https://doi.org/10.7916/pjpv-9q55), CC BY 4.0) is
published as a public ArcGIS feature service. This cell pages it for Kano State
only (2,000 records a page, ordered by `OBJECTID`, coordinates in WGS 84) and
caches the result under `~/.cache/arche/examples/`. Nothing is written into
the repository.
""")

code('''
import json, urllib.parse, urllib.request
from datetime import date

STEP = "grid3"
SERVICE = ("https://services3.arcgis.com/BU6Aadhn6tbBEdyk/arcgis/rest/services/"
           "GRID3_NGA_Health_Facilities_v4_0/FeatureServer/0/query")
FIELDS = ["unique_id", "facility_name", "state_standard", "lga_standard",
          "ward_standard", "facility_type"]
CACHE = Path.home() / ".cache" / "arche" / "examples" / "grid3_nga_hf_v4_kano.json"

def fetch_page(offset, tries=5):
    query = {"where": "state_standard='Kano'", "outFields": ",".join(FIELDS),
             "returnGeometry": "true", "outSR": 4326, "orderByFields": "OBJECTID ASC",
             "resultOffset": offset, "resultRecordCount": 2000, "f": "json"}
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(f"{SERVICE}?{urllib.parse.urlencode(query)}",
                                        timeout=60) as response:
                page = json.load(response)
            if "error" not in page:
                return page
        except OSError:
            pass
        time.sleep(2 ** attempt)       # the service returns the odd 503
    raise RuntimeError(f"GRID3 page at offset {offset} failed {tries} times")

if not CACHE.exists():
    features, offset = [], 0
    while True:
        page = fetch_page(offset)
        features += page["features"]
        if not page.get("exceededTransferLimit"):
            break
        offset += 2000
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps({"fetched": date.today().isoformat(), "features": features}))

cached = json.loads(CACHE.read_text())
grid3 = []
for f in cached["features"]:
    a, g = f["attributes"], f.get("geometry") or {}
    row = {"id": a["unique_id"], "name": " ".join(a["facility_name"].split()),
           "admin_path": admin_path(a["state_standard"], a["lga_standard"], a["ward_standard"])}
    if g.get("x") is not None:
        row["lat"], row["lon"] = g["y"], g["x"]
    if a.get("facility_type"):
        row["facility_type"] = a["facility_type"]
    grid3.append(row)

print(f"GRID3 v4.0, Kano State: {len(grid3):,} facilities (fetched {cached['fetched']})")
for r in grid3:
    if r["admin_path"].get("admin2") == "rimin gado" and r["name"].startswith("Zango"):
        print(" ", r["id"], r["name"], r["admin_path"], r.get("lat"), r.get("lon"))
''')

md("""
Rimin Gado LGA has **two** health posts called Zango, `Zango 1` and `Zango 2`,
both in Zango ward and about 4 km apart. The letter names neither number.

## 6. Link the mentions to GRID3

Candidates first: a mention is compared only with GRID3 records in the same
state and LGA that share at least one distinctive name token. Facility-type
words (`health`, `post`, `hospital`, ...) and the names of the state and LGA
themselves do not count, because inside Rimin Gado LGA, sharing `Rimin` says
nothing. This is the retriever the GRID3 linking runs use, inlined.

Then `reconcile(..., entity="health_facility", unique_match=True)` scores each
candidate with the health-facility pack and **holds any match that is not the
only plausible candidate on both sides.**
""")

code('''
import re
from arche.resolve import reconcile

STOP = {"health", "healthcare", "centre", "center", "clinic", "hospital", "primary", "phc",
        "post", "general", "comprehensive", "maternity", "medical", "model", "basic",
        "dispensary", "care", "home", "specialist", "mission", "cottage", "state", "federal",
        "the", "and", "for", "ltd", "limited", "nig", "nigeria"}

def tokens(s):
    return {t for t in re.split(r"[^a-z0-9]+", (s or "").lower()) if len(t) >= 3}

def distinctive(r):
    place = tokens(r["admin_path"].get("admin1")) | tokens(r["admin_path"].get("admin2"))
    return tokens(r["name"]) - STOP - place

def lga(r):
    return (r["admin_path"].get("admin1"), r["admin_path"].get("admin2"))

pairs = [{"a_id": m["id"], "b_id": g["id"], "route": "state_lga_shared_token"}
         for m in mentions for g in grid3
         if None not in lga(m) and lga(m) == lga(g) and distinctive(m) & distinctive(g)]

STEP = "reconcile"
result = reconcile(mentions, grid3, entity="health_facility", unique_match=True,
                   candidate_pairs=pairs,
                   candidate_pins={"retriever": "state_lga_shared_token",
                                   "stop_words": sorted(STOP)})

by_id = {r["id"]: r for r in [*mentions, *grid3]}
for m in mentions:
    n = sum(p["a_id"] == m["id"] for p in pairs)
    edges = [e for e in result["matches"] if e["a_id"] == m["id"]]
    print(f"{m['name']:<38} {n} candidate(s)")
    for e in edges:
        print(f"    -> {by_id[e['b_id']]['name']:<36} {e['decision']:<7} score={e['score']:<7}"
              f"distinctive={e['distinctive_max']}  ambiguous={e.get('ambiguous', '-')}")
''')

md("""
Read it mention by mention:

- **Aminu Kano Teaching Hospital → `match`.** The name agrees exactly, the
  type agrees, it is in the stated LGA, and nothing else competes.
- **Murtala Muhammad Specialist Hospital → `match`**, against GRID3's
  `Murtala Mohammed Specialist Hospital`. The spelling differs
  (`Muhammad`/`Mohammed`) and the score is only just over the 0.7 threshold.
- **Zango Health Post → `review` twice, `ambiguous=2`.** Either sibling would
  have scored as a match on its own. Because there are two, neither is chosen:
  the edge is held for a person, with the reason on it.
- **Zango Ward** had candidates (it shares `zango`) and every one scored below
  the review floor, so it produced no edge. **Antenatal Clinic** had no
  candidate at all. The two extraction errors from step 4 stop here rather
  than becoming links.

The evidence on an edge is numeric only, no names, and every edge carries a
`decision_id`:
""")

code('''
murtala = next(e for e in result["matches"] if by_id[e["a_id"]]["name"].startswith("Murtala"))
zango = sorted((e for e in result["matches"] if by_id[e["a_id"]]["name"] == "Zango Health Post"),
               key=lambda e: by_id[e["b_id"]]["name"])

for e in (murtala, zango[0]):
    print(json.dumps({k: e[k] for k in ("a_id", "b_id", "decision", "score", "evidence",
                                        "distinctive_max", "decision_id") if k in e}
                     | ({"ambiguous": e["ambiguous"]} if "ambiguous" in e else {}), indent=1))
''')

md("""
### The receipt is checkable

A `decision_id` is not a random key. It is a hash over the edge and the run's
pins (comparator pack digest, thresholds, frequency table digest, the
retriever and its stop words, `unique_match`). Anyone holding the edge and the
pins can recompute it with `arche.ids.edge_decision_id`, and any change to the
evidence or the configuration gives a different id.
""")

code('''
from arche.ids import edge_decision_id

pins = result["pins"]
print("every id recomputes:",
      all(edge_decision_id(e, pins) == e["decision_id"] for e in result["matches"]))

doctored = {**murtala, "score": 0.99}
print("doctored score recomputes to the same id:",
      edge_decision_id(doctored, pins) == murtala["decision_id"])

print("\\npinned:", {k: pins[k] for k in ("engine", "comparators_sha256", "threshold",
                                          "review_margin", "unique_match")})
''')

md("""
## 7. A ledger: record, correct, un-merge

`arche.attach("duckdb:///:memory:")` opens a ledger in memory (give it a file
path to keep one). Pass it to `reconcile` as `store=` and the run is recorded
as it is scored: the decisions, entities built from the `match` edges, and
`review` edges kept open as cases. The records go in exactly as `reconcile`
saw them, `admin_path` and all, so every stored edge can be replayed against
the inputs that produced it. The same call as section 6 gives the same
receipts.
""")

code('''
STEP = "ledger"
# A fixed record key makes the record ids, and so the entity ids, the same on
# every run of this notebook. Omit it and the ledger generates its own.
ledger = arche.attach("duckdb:///:memory:", record_key=b"notebook-26-demo-key")

stored = reconcile(mentions, grid3, entity="health_facility", unique_match=True,
                   candidate_pairs=pairs,
                   candidate_pins={"retriever": "state_lga_shared_token",
                                   "stop_words": sorted(STOP)},
                   store=ledger)
print("same receipts as section 6:",
      [e["decision_id"] for e in stored["matches"]]
      == [e["decision_id"] for e in result["matches"]])

for ent in ledger.entities("health_facility"):
    print(ent.entity_id, ent.held_together_by)
    for r in ent.records:
        print(f"    {r.source:<12} {r.caller_id:<14} {r.attributes['name']}")
    print("    held by", ent.decision_ids)
''')

code('''
for case in ledger.cases("health_facility"):
    b = ledger.record(case.decision.record_b)
    print(f"open: {case.decision.evidence['a_id']} vs {b.attributes['name']:<20} "
          f"{case.decision.identity}  ambiguous={case.decision.evidence.get('ambiguous')}  "
          f"{case.decision.explanation}")
''')

md("""
Two entities, two open cases. Now a reviewer works the queue. In this
illustration the first reviewer picks `Zango 1`, which is wrong; a second
reviewer, who knows the referring health post, corrects it to `Zango 2`. The
identity of the referring post is part of the story, not something the
notebook can know: the point is what a correction costs.
""")

code('''
from datetime import datetime, timezone

to_zango1, to_zango2 = (ledger.decision(e["decision_id"]) for e in zango)
mention_rec = to_zango1.record_a

ledger.assert_same(mention_rec, to_zango1.record_b, by="reviewer:1",
                   reason="letterhead says Zango Health Post; picked Zango 1",
                   decision_id=to_zango1.decision_id)
wrong = ledger.entity_of(mention_rec)
print("after reviewer 1:", wrong, [r.attributes["name"] for r in ledger.entity(wrong).records])

time.sleep(0.01)
before = datetime.now(timezone.utc)
time.sleep(0.01)

ledger.assert_different(mention_rec, to_zango1.record_b, by="reviewer:2",
                        reason="the referring post is Zango 2, not Zango 1",
                        decision_id=to_zango1.decision_id)
print("after reviewer 2:", "mention ->", ledger.entity_of(mention_rec),
      "| Zango 1 ->", ledger.entity_of(to_zango1.record_b))

ledger.assert_same(mention_rec, to_zango2.record_b, by="reviewer:2",
                   reason="confirmed with the referring post",
                   decision_id=to_zango2.decision_id)
right = ledger.entity_of(mention_rec)
print("after the fix:   ", right, [r.attributes["name"] for r in ledger.entity(right).records])
''')

md("""
The wrong entity is gone. The `different_from` assertion on the same pair
retracts the earlier `same_as` (both stay on record), the two records are
separated, and the mention is free to join the right one. A two-record entity
that loses its only link is `retire`d rather than split: each record stands
alone again. Nothing was deleted. The lineage says what happened and why, each
step pointing at the assertion that caused it:
""")

code('''
events = {ev.event_id: ev for ev in [*ledger.lineage(wrong), *ledger.lineage(right)]}
for ev in sorted(events.values(), key=lambda ev: ev.occurred_at):
    print(f"{ev.kind:<7} {ev.before_ids or '()'} -> {ev.after_ids or '()'}  cause={ev.cause[:30]}...")

print("\\nthe wrong entity as it stood before the correction:")
then = ledger.entity(wrong, at=before)
print("   ", then.entity_id, [r.attributes["name"] for r in then.records])

print("\\nassertions on the mention:")
for a in ledger.assertions(mention_rec):
    print(f"    {a.kind:<15} by {a.asserted_by:<11} {a.reason!r}"
          + (f"  (retracts {a.retracts[:22]}...)" if a.retracts else ""))

print("\\nrebuild from the evidence, differences:", ledger.rebuild()["differences"])
''')

md("""
`entity(..., at=before)` answers "what did this entity look like before the
correction?" from the append-only history. `rebuild()` recomputes every entity
from the decisions and assertions and finds no difference from what is stored.

## 8. A credential for the confirmed link

`arche.credentials` wraps one reconcile edge in a W3C Verifiable Credential 2.0
envelope signed with Ed25519 (a `vc+jwt`). The edge and the pins travel inside
it, so a verifier recomputes the decision id rather than trusting the one
written down. The credential also states its **level**:

- `machine`: arche decided and nobody looked. Only a `match` can be issued at this level.
- `adjudicated`: a reviewer's signed label is embedded and checked.

The Murtala link is a machine match. The Zango 2 link was a held `review`
until a person settled it, so it can only be issued as `adjudicated`, with the
reviewer's label.
""")

code('''
from arche.credentials import (CredentialError, build_credential, criterion_digest,
                               issue, sign_label, verify_credential)
from arche.sign import generate_keypair

STEP = "credentials"
issuer, reviewer = generate_keypair(), generate_keypair()
criterion = criterion_digest("the same physical health facility: one site, one GRID3 record")

def names(edge):
    return ({"scheme": "referral-letter-mention", "id": edge["a_id"]},
            {"scheme": "grid3-nga-hf-v4", "id": edge["b_id"]})

subject, obj = names(murtala)
machine = issue(build_credential(murtala, pins, subject=subject, obj=obj, level="machine",
                                 issuer=issuer.did_key, criterion=criterion), issuer)

label = sign_label(reviewer, decision_id=zango[1]["decision_id"], label="same_as",
                   criterion=criterion)
subject, obj = names(zango[1])
adjudicated = issue(build_credential(zango[1], pins, subject=subject, obj=obj,
                                     level="adjudicated", issuer=issuer.did_key,
                                     criterion=criterion, label_jws=label), issuer)

for name, token in (("machine", machine), ("adjudicated", adjudicated)):
    check = verify_credential(token, issuer_key=issuer.public_key,
                              reviewer_keys={reviewer.did_key: reviewer.public_key})
    print(f"{name:<12} ok={check.ok}  signature={check.signature_valid}  "
          f"issuer_trusted={check.issuer_trusted}  decision_id_ok={check.decision_id_ok}  "
          f"level_ok={check.level_ok}  type={check.credential['type'][1]}")
''')

md("""
And the refusals, which are the reason to use this rather than a signed JSON
blob:
""")

code('''
try:
    build_credential(zango[0], pins, subject=names(zango[0])[0], obj=names(zango[0])[1],
                     level="machine", issuer=issuer.did_key, criterion=criterion)
except CredentialError as exc:
    print("held edge as machine credential  -> refused:", exc)

payload = verify_credential(machine, issuer_key=issuer.public_key).credential
payload["credentialSubject"]["decision"]["edge"]["score"] = 0.99
forged = verify_credential(issue(payload, issuer), issuer_key=issuer.public_key)
print("score raised, re-signed by issuer -> ok =", forged.ok, forged.problems)

stranger = generate_keypair()
check = verify_credential(machine, issuer_key=stranger.public_key)
print("checked against the wrong key    -> ok =", check.ok, check.problems)
''')

md("""
A held edge cannot be issued as a machine link. Changing the evidence breaks
the decision id even when the issuer re-signs it: the signature proves who said
it, the recomputed id proves what was decided. Trust in the issuer comes only
from the key the verifier supplies.

## 9. What ran where, and what this shows

**Network.** Every hostname the kernel looked up during this run, by step:
""")

code('''
STEP = "summary"
for step, host in CONTACTED:
    print(f"{step:<12} {host}")
if not CONTACTED:
    print("none: models and the GRID3 extract were already cached")
''')

md("""
The PDF, its text and the masked copy are not sent anywhere by any call in
this notebook. The hostnames above can only be the GRID3 feature service
(when the Kano cache is missing) and model hubs fetching or checking model
files: Hugging Face for Docling's layout models and GLiNER, and on a first run
ModelScope for RapidOCR's models. Once the models are cached,
`HF_HUB_OFFLINE=1` stops the Hugging Face checks.

**Illustrated, not measured.** One invented letter, three real facilities.
That shows each mechanism working: Docling's table and reading order, the NDPA
pack's decisions and coverage note, GLiNER's spans, the ambiguity hold, the
receipt recomputation, the un-merge and the credential checks. It is not
evidence of accuracy. Nothing here measures Docling on scanned or handwritten
letters, GLiNER's recall on facility names, or the linking error rate across
GRID3.

**Shortfalls seen in this run, left in view:**

- `Rimin Gado` was masked as a person's name.
- GLiNER labelled `Zango Ward` and `Antenatal Clinic` as health facilities.
  Linking produced no edge for either, which is luck of the reference as much
  as design.
- The Murtala match cleared the threshold by about 0.02.
- The mention-to-LGA rule in step 4 is written for this letter's layout.

**Other notebooks**

- [01 · Reconciling two health facility lists](01_facility_reconciliation.ipynb): facility matching and refusals, list to list
- [14 · Nigeria schools](14_nigeria_schools.ipynb): when names stop working
- [23 · Three texts, one person](23_three_texts_one_person.ipynb): the ledger, `explain` and `replay`
- [25 · Attesting a crosswalk decision with JWS](25_jws_attestation.ipynb): signing and re-verifying decisions
""")

nb = {
    "cells": [
        {"cell_type": t, "metadata": {}, "source": (s + "\n").splitlines(True),
         **({"execution_count": None, "outputs": []} if t == CODE else {})}
        for t, s in cells
    ],
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python",
                       "name": "python3"},
        "language_info": {"name": "python", "version": "3.11"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

out = Path(__file__).resolve().parent / "26_local_documents_to_entities.ipynb"
out.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
print(f"wrote {out.name}: {len(cells)} cells "
      f"({sum(1 for t, _ in cells if t == CODE)} code)")
