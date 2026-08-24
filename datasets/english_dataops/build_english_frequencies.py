# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Build the general-English word-frequency table shipped with arche.

    python datasets/english_dataops/build_english_frequencies.py

Why this exists
---------------
Every other table here answers "how common is this token among *places*, among
*person names*, among *companies*". None answers "how common is this word in
English", and that turns out to be a different question with a measurable cost.

The `rival` comparator refutes a pair when each side carries a distinctive token
the other lacks -- one retailer listing a rug as `AT21E`, another as `Bethanie`.
It needs to know which unshared tokens are *identifiers*. Measured on a
catalogue-sized self-calibrated corpus of 1,200 retail titles::

    spout   0.766     an ordinary English word
    reach   0.766     an ordinary English word
    at21e   0.721     a product code

**An ordinary word scored rarer than a product code**, because rarity in a
self-calibrated table is a fact about that catalogue rather than about English.
`spout` appears twice in 1,200 titles; that makes it rare *here* and says
nothing about whether it identifies anything. The rule therefore refuted 26 true
pairs out of 150 -- the largest single recoverable bucket in that benchmark.

A general-English table separates them directly: `spout` and `reach` are common
English, `bethanie` and `at21e` are not English at all.

Source and licence
------------------
**Project Gutenberg**, plain-text ebooks. The works themselves are in the public
domain in the United States, which is why they are on Gutenberg at all. Each
file carries a Project Gutenberg header and licence footer around the text; both
are stripped here and only the public-domain body is counted, so the resulting
table is derived from public-domain text and carries no licence condition.

Deliberately not Wikipedia or Wiktionary. Both are CC BY-SA, whose share-alike
reaches derived databases -- a word-frequency table built from them is one, and
vendoring it would oblige us to license the wheel's contents under CC BY-SA.
That is the same reasoning that keeps OpenStreetMap out of the place table, and
it is a real blocker rather than a preference.

What this table is not
----------------------
**It is literary and historical English, and the vocabulary gap is real.**
Gutenberg's corpus is overwhelmingly pre-1930 fiction and non-fiction, so
`microfiber`, `polyester` and `USB` are absent from it and read as maximally
distinctive -- exactly the error this table exists to prevent, in a different
part of the vocabulary.

That is tolerable for the one job it is built for and would not be for others.
`rival` requires *both* sides of a pair to carry an unshared rare token, and a
modern product word like `microfiber` is almost always shared by both listings
when it appears at all. The failure mode needs a modern word on one side and a
different modern word on the other, which is rarer than it sounds.

Do not read this as a general English language model. It is a list of how often
words appeared in old books, and it is used here to answer one narrow question:
is this token a word, or is it a label?
"""

from __future__ import annotations

import collections
import gzip
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DEST = (REPO / "packages" / "arche-core" / "src" / "arche" / "resolve"
        / "_data" / "english_frequencies.json.gz")
CACHE = HERE / "gutenberg_cache"

#: Gutenberg ebook ids. Chosen for breadth of register rather than literary
#: merit: fiction, science, reference, travel, cookery and technical manuals, so
#: the table sees domestic and mechanical vocabulary and not only novels. A
#: corpus of nothing but Austen would call `faucet` a rare word.
BOOK_IDS = [
    1342, 11, 84, 1661, 2701, 98, 1400, 74, 76, 2600,    # fiction
    345, 5200, 1080, 174, 43, 46, 16, 35, 36, 164,
    120, 209, 158, 161, 105, 141, 768, 219, 215, 203,
    1497, 2814, 30254, 3207, 4300, 2591, 1232, 2542,     # classics, philosophy
    15784, 14975, 24022, 10681, 33283, 20203,            # cookery, household
    5001, 28885, 2148, 2680, 3600, 7370, 8800,           # essays, reference
    18269, 12814, 13103, 15859, 21279, 23428,            # science, technical
    16452, 17921, 19337, 22381, 25545, 27827,            # travel, trades
]

#: Where Gutenberg's own header ends and the public-domain text begins. The
#: header names the work and the licence; counting it would put `gutenberg`,
#: `ebook` and `licence` into the language.
_START = re.compile(r"\*\*\*\s*START OF TH(?:E|IS) PROJECT GUTENBERG[^\n]*\*\*\*",
                    re.I)
_END = re.compile(r"\*\*\*\s*END OF TH(?:E|IS) PROJECT GUTENBERG[^\n]*\*\*\*", re.I)

#: Words only. Digits are excluded on purpose: a page number is not a word, and
#: this table's whole job is to say which tokens are language.
_WORD = re.compile(r"[a-z]{2,}")

URL = "https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt"


def fetch(book_id: int) -> str | None:
    """One ebook's public-domain body, cached on disk after the first run."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f"pg{book_id}.txt.gz"
    if cached.exists():
        with gzip.open(cached, "rt", encoding="utf-8") as fh:
            return fh.read()
    try:
        with urllib.request.urlopen(URL.format(id=book_id), timeout=40) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"  skip {book_id}: {type(exc).__name__} {exc}", file=sys.stderr)
        return None

    start = _START.search(raw)
    end = _END.search(raw)
    if not start:
        # No marker means the layout changed, and counting the header would
        # quietly put licence boilerplate into the language. Skip it.
        print(f"  skip {book_id}: no Gutenberg start marker", file=sys.stderr)
        return None
    body = raw[start.end():end.start() if end else len(raw)]
    with gzip.open(cached, "wt", encoding="utf-8") as fh:
        fh.write(body)
    time.sleep(0.6)  # Gutenberg asks for gentle automated access.
    return body


def main() -> int:
    counts: collections.Counter[str] = collections.Counter()
    books = 0
    for book_id in BOOK_IDS:
        body = fetch(book_id)
        if body is None:
            continue
        books += 1
        counts.update(_WORD.findall(body.lower()))
        print(f"  {book_id:>6}  {len(counts):>8,} distinct so far")

    if books < 20:
        print(f"ERROR: only {books} books collected; refusing to ship a table "
              "too thin to be a claim about English.", file=sys.stderr)
        return 1

    total = sum(counts.values())
    if total < 2_000_000:
        print(f"ERROR: only {total:,} tokens; too thin.", file=sys.stderr)
        return 1

    # A hapax in a five-million-token corpus is a scanning artefact as often as
    # a word, and keeping them triples the shipped file for tokens that fall to
    # the unknown floor anyway -- which is already the right answer for them.
    pruned = {word: n for word, n in counts.items() if n >= 3}

    sys.path.insert(0, str(REPO / "packages" / "arche-core" / "src"))
    from arche.resolve._tokenfreq import TokenFrequencyTable

    # `from_counts`, not `from_corpus`: only the former marks the table
    # population-scale, which is what licenses it to answer a rarity question.
    table = TokenFrequencyTable.from_counts(pruned)
    assert table.population_scale, "table must be population-scale to be useful"
    DEST.parent.mkdir(parents=True, exist_ok=True)
    table.save(DEST)

    print()
    print(f"books           : {books}")
    print(f"tokens counted  : {total:,}")
    print(f"distinct kept   : {len(pruned):,} (dropped {len(counts)-len(pruned):,} "
          f"seen once or twice)")
    print(f"table           : {DEST} ({DEST.stat().st_size/1024:.0f} KB)")
    print()
    print("the separation this exists for:")
    for word in ("spout", "reach", "panel", "panels", "blanket", "wool",
                 "bethanie", "at21e", "microfiber"):
        seen = pruned.get(word, 0)
        print(f"    {word:<12} count {seen:>8,}   distinctiveness "
              f"{table.distinctiveness(word):.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
