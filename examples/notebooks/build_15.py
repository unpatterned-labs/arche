# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Generate 15_parrish_record_linkage.ipynb.

    python examples/notebooks/build_15.py

Reproduces the deterministic linkage from Jared Parrish's R record linkage
tutorial, then runs arche over the same two files and the same ground truth.
"""
from __future__ import annotations

import json
from pathlib import Path

MD, CODE = "markdown", "code"
cells: list[tuple[str, str]] = []
md = lambda t: cells.append((MD, t.strip("\n")))      # noqa: E731
code = lambda t: cells.append((CODE, t.strip("\n")))  # noqa: E731


md("""
# Reproducing someone else's benchmark first

**Jared Parrish's R record linkage tutorial, reproduced exactly, then run
through arche against the same ground truth.**

Every benchmark in this repo so far is one we built. That is a weakness. A
method looks good on the tests its authors chose, and the only cure is to pick
up someone else's test, reproduce their number first, and only then report your
own.

This notebook uses [Jared Parrish's record linkage
tutorial](https://rstudio-pubs-static.s3.amazonaws.com/1203076_6c678b417f564183a8708e3b4720c6c0.html),
built on the R `RecordLinkage` package, with two teaching files of child
records. The order matters:

1. Reproduce his preprocessing and his deterministic result exactly.
2. Only if that matches, score it against the ground truth he sets aside.
3. Only then run arche, on the same records, scored the same way.

If step 1 does not land on his numbers, nothing after it means anything.

**What this is not.** These are synthetic teaching files, not a population
register. The tutorial's probabilistic section is cut off in the published HTML,
so the deterministic result is the only number available to reproduce. A clean
score here is evidence that the reproduction is faithful, not evidence that
either method behaves this way on real data.
""")

md("""
## The two files

`SourceA.csv` is the register, 1,183 rows. `SourceB.csv` is a sample of 302
records that came back from somewhere else, with names cased differently, dates
formatted differently, and sex coded differently.

Both are read as Latin-1. The register holds `García`, `Sánchez`, `González`
and `Tío`, and reading those files as UTF-8 fails outright.
""")

code('''
import csv, io, re, unicodedata, urllib.request
from collections import Counter
from pathlib import Path

RAW = "https://raw.githubusercontent.com/parrish-epi/R-recordLinkage/main/"
CACHE = Path("../../data/_cache/parrish")
CACHE.mkdir(parents=True, exist_ok=True)

def source(name):
    """Fetch once, then read from disk. Latin-1: these files are not UTF-8."""
    p = CACHE / name
    if not p.exists():
        urllib.request.urlretrieve(RAW + name, p)
    return list(csv.DictReader(p.read_bytes().decode("latin-1").splitlines()))

A, B = source("SourceA.csv"), source("SourceB.csv")
print(f"SourceA  {len(A):>6,} rows   {A[0].keys()}")
print(f"SourceB  {len(B):>6,} rows   {B[0].keys()}")
print()
print(f"SourceA distinct ID   {len({r['ID'] for r in A}):>5}   "
      f"so {len(A) - len({r['ID'] for r in A})} rows are duplicates")
print(f"SourceB distinct ID   {len({r['ID'] for r in B}):>5}")
print()
print("date formats  A:", Counter(re.sub(r"\\d", "9", r["Date of Birth"]) for r in A).most_common(3))
print("              B:", Counter(re.sub(r"\\d", "9", r["DOB"]) for r in B).most_common(3))
print("sex coding    A:", dict(Counter(r["Sex"] for r in A)))
print("              B:", dict(Counter(r["Sex"] for r in B)))
''')

md("""
## Preprocessing, copied from the tutorial

The tutorial does five things, and all five matter:

- uppercase the three name fields
- strip punctuation and blanks, `gsub('[[:punct:][:blank:]]+', '', .)`
- transliterate to ASCII, `stri_trans_general(id = 'Latin-ASCII')`, so
  `García` becomes `GARCIA`
- recode sex to `F` and `M`
- parse the register's `m/d/Y` dates into the ISO form source B already uses

Ten register rows carry no date at all. `lubridate::mdy()` yields `NA` there.
An empty string does the same job, since it can never equal an ISO date.
""")

code('''
latin_ascii = lambda s: "".join(
    c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
norm = lambda s: re.sub(r"[^\\w]+", "", latin_ascii(s or "").upper())

def mdy(s):
    s = (s or "").strip()
    if not s:
        return ""                       # 10 rows have no date; NA in R
    m, d, y = s.split("/")
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"

a = [{"ID": r["ID"], "GivenName": norm(r["First Name"]),
      "MiddleName": norm(r["Middle Name"]), "FamilyName": norm(r["Last Name"]),
      "Sex": {"Female": "F", "Male": "M"}.get(r["Sex"], ""),
      "DOB": mdy(r["Date of Birth"])} for r in A]
b = [{"ID": r["ID"], "GivenName": norm(r["GivenName"]),
      "MiddleName": norm(r["MiddleName"]), "FamilyName": norm(r["FamilyName"]),
      "Sex": r["Sex"].strip().upper(), "DOB": r["DOB"].strip()} for r in B]

# "It is easiest to link de-duplicated records."  dat1a %>% unique()
KEY = ("GivenName", "FamilyName", "Sex", "DOB")
seen, ded = set(), []
for r in a:
    k = tuple(r[c] for c in KEY) + (r["ID"],)
    if k not in seen:
        seen.add(k); ded.append(r)

print(f"register  {len(a):,} rows -> {len(ded)} after dedup, "
      f"{len(a) - len(ded)} removed")
print(f"tutorial reports          986 after dedup, 197 removed   "
      f"{'MATCH' if len(ded) == 986 and len(a) - len(ded) == 197 else 'MISMATCH'}")
''')

md("""
## The number to reproduce

The tutorial's deterministic step reports **205 linked, 97 non-linked, a 67.9%
linkage rate**.

One detail is easy to get wrong. The prose says the comparison variables are
"GivenName, MiddleName, FamilyName, Sex, and DOB", but the tutorial's own
uniqueness table is computed on the set "GivenName, FamilyName, Sex, DOB", four
fields, and reports 986 unique combinations. Matching on all five gives 174, not
205. The 31 pairs in the gap differ only on middle name. The four-field key is
the one that reproduces both published numbers, so that is the key used here.
""")

code('''
def exact_link(right, left, key):
    idx = {}
    for r in left:
        idx.setdefault(tuple(r[c] for c in key), []).append(r)
    return [(r, idx.get(tuple(r[c] for c in key), [])) for r in right]

for key in [("GivenName", "FamilyName", "Sex", "DOB"),
            ("GivenName", "MiddleName", "FamilyName", "Sex", "DOB")]:
    linked = [x for x in exact_link(b, ded, key) if x[1]]
    tag = "  <- tutorial's key" if len(linked) == 205 else ""
    print(f"{len(key)} fields {str(key):<58} linked {len(linked):>3}  "
          f"rate {len(linked)/len(b):>5.1%}{tag}")

print()
print("tutorial reports: linked 205, non-linked 97, rate 67.9%")

deterministic = [x for x in exact_link(b, ded, KEY) if x[1]]
print(f"reproduced      : linked {len(deterministic)}, "
      f"non-linked {len(b) - len(deterministic)}, "
      f"rate {len(deterministic)/len(b):.1%}")
''')

md("""
## The ground truth the tutorial sets aside

Source A carries an `InSample` flag, and source B's `ID` column is the register
ID of the record it came from. The tutorial deliberately drops both, to
"simulate real-world conditions". For scoring we want them back.

**294 of the 302 sampled records have a true match in the deduplicated
register. The other 8 have none, and no method should link them.**

That makes this a rarer thing than most linkage benchmarks: positives and
negatives are both known, so precision and recall both mean something.
""")

code('''
truth = {r["ID"] for r in b} & {r["ID"] for r in ded}
print(f"sampled records          {len(b)}")
print(f"with a true register match {len(truth)}")
print(f"genuine non-matches        {len(b) - len(truth)}")

def score(linked_pairs, label):
    """linked_pairs: {source_B_id: chosen_source_A_id}"""
    tp = sum(1 for bid, aid in linked_pairs.items() if aid == bid)
    fp = len(linked_pairs) - tp
    fn = len(truth) - tp
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / len(truth)
    f1 = 2 * tp / (2 * tp + fp + fn) if tp else 0.0
    print(f"{label:<32}{len(linked_pairs):>7}{tp:>6}{fp:>5}{fn:>5}"
          f"{p:>11.4f}{r:>9.4f}{f1:>8.4f}")
    return {"linked": len(linked_pairs), "tp": tp, "fp": fp, "fn": fn,
            "precision": p, "recall": r, "f1": f1}

print()
print(f"{'method':<32}{'linked':>7}{'TP':>6}{'FP':>5}{'FN':>5}"
      f"{'precision':>11}{'recall':>9}{'F1':>8}")
results = {}
results["parrish"] = score(
    {r["ID"]: hits[0]["ID"] for r, hits in deterministic}, "Parrish deterministic")
''')

md("""
Exact matching on four fields is **perfectly precise and misses 89 of 294**.
That is the shape of every exact-match baseline: it is right about what it
claims, and it claims too little.

Where do the 89 go? Almost nowhere interesting. They are ordinary transcription
variation: a dropped middle name, `GORGE` for `JORGE`, a sex left blank, a date
keyed a month out.
""")

code('''
byid = {}
for r in ded:
    byid.setdefault(r["ID"], []).append(r)

missed = [(r, hits) for r, hits in exact_link(b, ded, KEY)
          if not hits and r["ID"] in truth]
reasons = Counter()
for r, _ in missed:
    t = byid[r["ID"]][0]
    reasons[tuple(c for c in KEY if r[c] != t[c])] += 1

print(f"{len(missed)} true pairs the exact key cannot see:\\n")
for fields, n in reasons.most_common():
    print(f"  {n:>3}x  differs on {', '.join(fields)}")

print("\\nexamples:")
for r, _ in missed[:4]:
    t = byid[r["ID"]][0]
    diff = [c for c in KEY if r[c] != t[c]]
    print(f"  register {t['GivenName']:<12}{t['FamilyName']:<14}{t['Sex']:<3}{t['DOB']}")
    print(f"  sample   {r['GivenName']:<12}{r['FamilyName']:<14}{r['Sex']:<3}{r['DOB']}"
          f"   ({', '.join(diff)})")
    print()
''')

md("""
## arche, with the pack it ships

`crosswalk(entity="person")` applies the shipped person pack. Read the evidence
keys on the result before reading the score, because they say what was actually
compared.

**This benchmark changed the pack.** Up to `0.4.0a3` the person pack declared
name, a token-frequency view of the name, `national_id`, `phone`, `email` and
`address`. These files carry none of the last four, so the pack was a name-only
matcher that never looked at the birth date it was handed, and it scored 219
true against 14 false: less precise than the R tutorial. `0.4.0a4` added a date
comparator, and the cell below is the pack as it now ships.
""")

code('''
from arche.resolve import crosswalk

def to_record(r):
    return {"id": r["ID"],
            "name": " ".join(x for x in (r["GivenName"], r["MiddleName"],
                                         r["FamilyName"]) if x).title(),
            "birth_date": r["DOB"], "sex": r["Sex"]}

left, right = [to_record(r) for r in ded], [to_record(r) for r in b]

shipped = crosswalk(left, right, entity="person", id_field="id")
print("pins    :", shipped["pins"])
print("evidence:", sorted(shipped["matches"][0]["evidence"].keys()))
print("edges   :", len(shipped["matches"]),
      dict(Counter(e["decision"] for e in shipped["matches"])))

def best_per_sample(res, keep):
    best = {}
    for e in res["matches"]:
        if e["decision"] in keep and (
                e["b_id"] not in best or e["score"] > best[e["b_id"]]["score"]):
            best[e["b_id"]] = e
    return {bid: e["a_id"] for bid, e in best.items()}

print()
print(f"{'method':<32}{'linked':>7}{'TP':>6}{'FP':>5}{'FN':>5}"
      f"{'precision':>11}{'recall':>9}{'F1':>8}")
results["parrish"] = score(
    {r["ID"]: hits[0]["ID"] for r, hits in deterministic}, "Parrish deterministic")
results["shipped"] = score(best_per_sample(shipped, {"match"}), "arche shipped pack")
''')

md("""
**`birth_date` is in the evidence dict now, and that is the whole difference.**

The 14 false positives the old pack made were each a real child matched to a
different real child with the same name and a different birthday. Every one of
them is separable by looking at two dates, which is what the pack now does.

What survives is worth more attention than what was fixed.
""")

code('''
fps = [(bid, aid) for bid, aid in best_per_sample(shipped, {"match"}).items()
       if aid != bid]
bb = {r["ID"]: r for r in b}
print(f"{len(fps)} false positive(s) left, against 14 before the pack could "
      f"see a date.\\n")
for bid, aid in fps:
    s, picked = bb[bid], byid[aid][0]
    real = byid[bid][0] if bid in byid else None
    print(f"  sample   {s['GivenName']:<10}{s['FamilyName']:<12}{s['DOB']}")
    print(f"  matched  {picked['GivenName']:<10}{picked['FamilyName']:<12}"
          f"{picked['DOB']}   <- different child")
    if real:
        print(f"  truth    {real['GivenName']:<10}{real['FamilyName']:<12}{real['DOB']}")
    print()

disagree = [(bid, byid[bid][0]["DOB"], bb[bid]["DOB"]) for bid in truth
            if bid in byid and byid[bid][0]["DOB"] and bb[bid]["DOB"]
            and byid[bid][0]["DOB"] != bb[bid]["DOB"]]
print(f"{len(disagree)} true pairs have dates that disagree at all. The shapes:")
for bid, x, y in disagree[:5]:
    print(f"  register {x}   sample {y}")
print("\\nThose are keying slips, not different people, which is why the")
print("comparator grades them at 0.35 instead of zeroing them out of sight.")
''')

md("""
## The option the pack does not take

`refutes_below` turns a comparator into a refuter: score under the threshold and
the pair is demoted to review however well the names agree. A date is the
clearest case for it, and on this set it takes precision to 1.0000.

The shipped pack still does not declare it. `test_discriminator_veto.py` guards
`place`, `person` and `artist` against gaining refutation as a side effect of an
unrelated change, on the grounds that each has published numbers a refutation
would move. Adding the comparator was that unrelated change, so turning
refutation on stays a separate decision with its own measurement.

It is one line for a caller who wants it, through the documented `comparators=`
route. Nothing below changes arche's shipped behaviour.
""")

code('''
COMPARATORS = [
    {"field": "name", "kind": "name", "weight": 2.0},
    {"field": "name", "kind": "tftoken", "weight": 2.0},
    # A different birthday refutes, however well the names agree.
    {"field": "birth_date", "kind": "date", "weight": 2.0, "refutes_below": 0.5},
]

dated = crosswalk(left, right, entity="person", id_field="id",
                  comparators=COMPARATORS)
print("evidence:", sorted(dated["matches"][0]["evidence"].keys()))
print()
print(f"{'method':<32}{'linked':>7}{'TP':>6}{'FP':>5}{'FN':>5}"
      f"{'precision':>11}{'recall':>9}{'F1':>8}")
results["parrish"] = score(
    {r["ID"]: hits[0]["ID"] for r, hits in deterministic}, "Parrish deterministic")
results["shipped"] = score(best_per_sample(shipped, {"match"}), "arche shipped pack")
results["dated"] = score(best_per_sample(dated, {"match"}), "arche + date refutation")
results["dated_review"] = score(best_per_sample(dated, {"match", "review"}),
                                "arche + refutation, incl. review")
''')

md("""
## Working the result by hand

The numbers above are an aggregate. Adjudicating is the other half, and it needs
the pairs in something a person can sit in front of. `review_pack` writes the
two files `tools/arche-studio` opens.

`reveal=True` because a masked pack cannot be judged: nobody can say whether two
children are the same when both names are redacted. That makes the output a
local working file, which is why it lands in `data/review_packs/` and is not
committed.
""")

code('''
from arche.report import review_pack

manifest = review_pack(
    shipped, left, right,
    out_dir="../../data/review_packs/parrish_person",
    sides=("register", "sample"),
    entity="person",
    reveal=True,
    meta={"benchmark": "Parrish R RecordLinkage", "true_pairs": len(truth)},
)
for k in ("schema", "rows", "decisions", "disclosure"):
    print(f"{k:<12} {manifest[k]}")
print(f"{'pins':<12} {manifest['pins'].get('comparators_sha256')}")
print()
print("open it with:  python tools/arche-studio/serve.py")
''')

md("""
## What this run showed

The reproduction lands on the tutorial's numbers exactly: 986 after dedup, 197
duplicates removed, 205 linked, 97 not, 67.9%. Everything after that is scored
against the same 294 true pairs.

Given the date of birth, arche recovers **69 more true pairs than the exact key
and makes no false matches doing it**. Precision stays at 1.0000, so this is not
the usual recall-for-precision trade. Those 69 are the dropped middle names and
the `GORGE`/`JORGE` keying errors: pairs a human would call obvious and an
equality test cannot see.

**The finding that matters most here is a gap in arche, not a win.** The shipped
person pack has no date comparator, so out of the box it scored 219 true matches
with 14 false ones, worse on precision than the R tutorial it was being compared
to. `compare_dates` has been in `_matcher.py` all along. It is simply not wired
into the pack, and date of birth is close to the most common identifier in
person linkage. The pack should carry it. That is a behaviour change, so it
belongs in a release with a changelog entry and a decision-id note, not in a
notebook.

**What this does not show.** These are synthetic teaching files with clean
dates and a truth column, and the 14 false positives disappear here because the
generator made every same-name pair differ on birthday. Real registers hold
twins, shared birthdays, and dates that are wrong rather than missing. The
tutorial's probabilistic section is truncated in the published HTML, so the
comparison above is against its deterministic step only, and a Fellegi-Sunter
model on the same fields would very likely close much of the 69.
""")

code('''
print(f"{'':32}{'linked':>7}{'TP':>6}{'FP':>5}{'recall':>9}{'F1':>8}")
for label, key in (("Parrish deterministic", "parrish"),
                   ("arche shipped pack", "shipped"),
                   ("arche + date refutation", "dated"),
                   ("arche + refutation, incl. review", "dated_review")):
    r = results[key]
    print(f"{label:<32}{r['linked']:>7}{r['tp']:>6}{r['fp']:>5}"
          f"{r['recall']:>9.4f}{r['f1']:>8.4f}")
print(f"\\n{len(truth)} true pairs, {len(b) - len(truth)} genuine non-matches, "
      f"{len(ded)} register records after dedup.")
''')


nb = {
    "cells": [
        {"cell_type": t, "metadata": {},
         **({"source": s.splitlines(keepends=True)} if t == MD else
            {"source": s.splitlines(keepends=True), "outputs": [], "execution_count": None})}
        for t, s in cells
    ],
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python",
                       "name": "python3"},
        "language_info": {"name": "python"},
    },
    "nbformat": 4, "nbformat_minor": 5,
}

out = Path(__file__).parent / "15_parrish_record_linkage.ipynb"
out.write_text(json.dumps(nb, indent=1), encoding="utf-8")
print(f"wrote {out}  ({len(cells)} cells)")
