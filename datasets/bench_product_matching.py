# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Product matching benchmarks against cross-retailer ground truth.

    python datasets/bench_product_matching.py <data-dir> [--limit N] [--suite all]

Two suites, both with **complete truth over the sampled block**, which is what
makes a false-merge rate countable rather than estimated.

**General merchandise.** Offer feeds carrying an `ITEM_ID` that spans retailers,
so two offers sharing one are a known positive and every other pair in the block
is a known negative. Amazon against Walmart, furniture, bedding, rugs and decor.

**UK grocery.** Five supermarkets with a `gtin` on every row. A GTIN is an
external standard rather than one vendor's internal key, which makes it the
better of the two truths: nobody assigned it to make matching easy.

The grocery suite exists to close a gap the library documents about itself. The
`food` product category ships with extraction tests and no matching benchmark,
because no *open* grocery corpus with complete ground truth was available. This
is not open either -- it is client data and it stays out of the repository, which
is why this script takes a path rather than embedding one -- but it lets the
number be measured, and a measured number with a stated provenance beats a gap.

Reported per run: precision and recall on automatic matches, F1, the false-merge
count, the share of true pairs that were surfaced as candidates at all (a
ceiling no scoring can beat), and the share held for review. Review is not a
failure here: a held pair is returned with its evidence, and for a pricing
decision a wrong merge costs more than a human glance.
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import pathlib
import sys
import time
import warnings

warnings.filterwarnings("ignore")

csv.field_size_limit(10_000_000)

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages" / "arche-core" / "src"))

from arche.resolve import TokenFrequencyTable, reconcile  # noqa: E402
from arche.resolve import ENTITY_PACKS  # noqa: E402

#: Same schema, two dumps. Both carry `ITEM_ID`, so they pool.
#: Feeds are found by their COLUMNS, not their filenames.
#:
#: Hardcoding the supplier's filenames would name a client in a public
#: repository, and it would also make the harness useless to anyone whose
#: export is called something else. Any CSV carrying these headers is the feed
#: this suite understands, whatever it is named.
GM_COLUMNS = {"ITEM_ID", "PRODUCT_TITLE", "COMPANY_NAME"}
GROCERY_COLUMNS = {"gtin", "seller", "name"}


def find_feeds(root: pathlib.Path, required: set[str]) -> list[pathlib.Path]:
    """Every CSV under `root` whose header carries all of `required`."""
    found = []
    for path in sorted(root.glob("*.csv")):
        try:
            with path.open(encoding="utf-8-sig", newline="") as fh:
                header = next(csv.reader(fh), [])
        except (OSError, StopIteration, UnicodeDecodeError):
            continue
        if required <= set(header):
            found.append(path)
    return found

#: Below this many digits a `gtin` is a retailer-internal code rather than a
#: barcode, and two retailers' internal codes can collide by accident. 86% of
#: the rows carry a full EAN-13; the floor costs little and removes the one way
#: this truth could be silently wrong.
MIN_GTIN_DIGITS = 8


#: Items drawn per grouping key. FIXED, not derived from the block size.
#:
#: It used to be `limit // 200`, which silently coupled two variables: a
#: 250-pair block drew 1 item per brand and a 2,325-pair block drew 11. The
#: bigger block was therefore also a *denser* one, packed with same-brand
#: near-duplicates -- and near-duplicates are what produce false merges.
#:
#: Precision duly fell from 0.93 to 0.73 as the limit rose, and that was read
#: as a scaling law: "false merges grow with n-squared". It is not. Holding
#: composition fixed and varying only n, precision is flat across a 9x range
#: (0.805, 0.806, 0.776, 0.806 at threshold 0.70). The harness was measuring
#: its own sampling.
PER_KEY = 8


def _spread(groups: dict, per_key: int, key_of) -> list:
    """Sample across a grouping key instead of taking a prefix.

    Two sampling bugs have been found in this function's short life, and both
    produced confident conclusions that had to be withdrawn.

    **File order is not random.** A first version kept the first N items as they
    appeared. That block was 83% one vendor's rug catalogue, so every figure
    described that vendor rather than retail matching.

    **The sample rate must not depend on the sample size.** See `PER_KEY`.
    Varying block size and block composition together, then attributing the
    result to size, is the same error in a subtler dress.
    """
    by_key = collections.defaultdict(list)
    for item, rows in groups.items():
        by_key[key_of(rows)].append(item)
    picked = []
    for _, items in sorted(by_key.items()):
        step = max(1, len(items) // per_key)
        picked.extend(items[::step][:per_key])
    return picked


def load_general_merchandise(root: pathlib.Path, limit: int):
    """Amazon and Walmart offers of one product, keyed by `ITEM_ID`."""
    by_item = collections.defaultdict(dict)
    rows = 0
    feeds = find_feeds(root, GM_COLUMNS)
    if not feeds:
        print(f"  no offer feed found under {root} "
              f"(needs columns {sorted(GM_COLUMNS)})")
        return [], [], {}
    for path in feeds:
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                rows += 1
                item = (row.get("ITEM_ID") or "").strip()
                title = (row.get("PRODUCT_TITLE") or "").strip()
                company = (row.get("COMPANY_NAME") or "").strip()
                if not (item and title and company):
                    continue
                by_item[item].setdefault(
                    company, {"title": title,
                              "brand": (row.get("BRAND") or "").strip()})
    both = {i: v for i, v in by_item.items()
            if "Amazon" in v and "Walmart" in v}
    picked = _spread(both, PER_KEY,
                     lambda v: (v["Amazon"]["brand"] or "?").upper())
    print(f"  parsed {rows:,} rows · {len(by_item):,} items · "
          f"{len(both):,} at both retailers · sampling {limit:,}")
    return _pairs(both, picked, "Amazon", "Walmart", limit)


def load_grocery(root: pathlib.Path, limit: int, left="Tesco Groceries",
                 right="Sainsburys"):
    """Two supermarkets' listings of one product, keyed by barcode."""
    feeds = find_feeds(root, GROCERY_COLUMNS)
    if not feeds:
        print(f"  no grocery feed found under {root} "
              f"(needs columns {sorted(GROCERY_COLUMNS)})")
        return [], [], {}
    path = feeds[0]
    by_gtin = collections.defaultdict(dict)
    rows = 0
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            rows += 1
            gtin = (row.get("gtin") or "").strip()
            seller = (row.get("seller") or "").strip()
            name = (row.get("name") or "").strip()
            if not (gtin.isdigit() and len(gtin) >= MIN_GTIN_DIGITS):
                continue
            if not (seller and name and name != "NA"):
                continue
            by_gtin[gtin].setdefault(
                seller, {"title": name,
                         "brand": (row.get("brand") or "").strip("[]'\" ")})
    both = {g: v for g, v in by_gtin.items() if left in v and right in v}
    picked = _spread(both, PER_KEY,
                     lambda v: (v[left]["brand"] or "?").upper()[:14])
    print(f"  parsed {rows:,} rows · {len(by_gtin):,} barcodes · "
          f"{len(both):,} at both {left}/{right} · sampling {limit:,}")
    return _pairs(both, picked, left, right, limit)


def _pairs(groups, picked, left, right, limit):
    """One record per side per product, so recall is not inflated."""
    a_rows, b_rows, truth = [], [], {}
    for key in picked:
        sides = groups[key]
        aid, bid = f"a{len(a_rows)}", f"b{len(b_rows)}"
        a_rows.append({"id": aid, "name": sides[left]["title"]})
        b_rows.append({"id": bid, "name": sides[right]["title"]})
        truth[aid] = bid
        if len(a_rows) >= limit:
            break
    return a_rows, b_rows, truth


def score(a_rows, b_rows, truth, pack, threshold=0.7):
    tf = TokenFrequencyTable.from_corpus(
        [r["name"] for r in a_rows] + [r["name"] for r in b_rows])
    started = time.time()
    edges = reconcile(a_rows, b_rows, ENTITY_PACKS[pack], tf=tf, id_field="id",
                      threshold=threshold)["matches"]
    matched = [e for e in edges if e["decision"] == "match"]
    tp = sum(1 for e in matched if truth.get(e["a_id"]) == e["b_id"])
    fp = len(matched) - tp
    surfaced = sum(1 for e in edges if truth.get(e["a_id"]) == e["b_id"])
    held = sum(1 for e in edges
               if e["decision"] == "review" and truth.get(e["a_id"]) == e["b_id"])
    precision = tp / len(matched) if matched else 0.0
    recall = tp / len(truth) if truth else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"pack": pack, "n": len(truth), "precision": round(precision, 4),
            "recall": round(recall, 4), "f1": round(f1, 4), "false_merges": fp,
            "true_matched": tp, "surfaced": round(surfaced / len(truth), 4),
            "held_for_review": held, "seconds": round(time.time() - started, 1)}


def report(title, rows):
    print(f"\n  {title}")
    print(f"  {'pack':<22}{'n':>7}{'prec':>8}{'recall':>8}{'F1':>8}"
          f"{'false':>7}{'surfaced':>10}{'review':>8}{'sec':>7}")
    print("  " + "-" * 85)
    for r in rows:
        print(f"  {r['pack']:<22}{r['n']:>7}{r['precision']:>8.3f}"
              f"{r['recall']:>8.3f}{r['f1']:>8.3f}{r['false_merges']:>7}"
              f"{r['surfaced']:>9.1%}{r['held_for_review']:>8}{r['seconds']:>7.1f}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir")
    ap.add_argument("--limit", type=int, default=4000)
    ap.add_argument("--suite", default="all",
                    choices=["all", "general", "grocery"])
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    root = pathlib.Path(args.data_dir)
    results = {}

    if args.suite in ("all", "general"):
        print("\nGENERAL MERCHANDISE — Amazon vs Walmart, ITEM_ID truth")
        a, b, truth = load_general_merchandise(root, args.limit)
        if truth:
            rows = [score(a, b, truth, p) for p in
                    ("product_electronics", "product_home_goods")]
            report("furniture, bedding, rugs, decor", rows)
            results["general_merchandise"] = rows

    if args.suite in ("all", "grocery"):
        print("\nUK GROCERY — Tesco vs Sainsbury's, GTIN truth")
        a, b, truth = load_grocery(root, args.limit)
        if truth:
            rows = [score(a, b, truth, p) for p in
                    ("product_electronics", "product_home_goods",
                     "product_grocery")]
            report("supermarket own-label and branded", rows)
            results["uk_grocery"] = rows

    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps(results, indent=2), encoding="utf-8")
        print(f"\n  wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
