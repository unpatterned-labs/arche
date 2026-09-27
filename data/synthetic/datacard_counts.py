#!/usr/bin/env python
# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Print the counts DATACARD.md states, read from the shipped world files.

    python data/synthetic/datacard_counts.py                  # every world
    python data/synthetic/datacard_counts.py ng_supplier_v0    # one

DATACARD.md is a hand-written document with numbers in it, and numbers in a
hand-written document drift: before this script existed, every count in its
first table disagreed with the Parquet file it described, by 1 to 8 per cent,
because the worlds had been regenerated after a name-pool fix and the prose had
not. A reader who checks the first table and finds it wrong stops trusting the
rest of the page, which is the whole asset.

So the counts are *derived* here and pasted in, and this script is what the next
regeneration runs instead of a hand edit. It reads the shipped files only and
writes nothing.
"""

from __future__ import annotations

import collections
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from arche_synthetic import available, load  # noqa: E402


def _counted(rows: list[dict], key: str) -> collections.Counter:
    return collections.Counter(r[key] for r in rows if r.get(key) is not None)


def report(name: str) -> None:
    w = load(name)
    print(f"\n{'=' * 72}\n{name}   pack {w.pack}, seed {w.seed}\n{'=' * 72}")

    print("\n  tables")
    for table, rows in sorted(w.tables.items()):
        print(f"    {table:<16} {len(rows):>8,}")

    manifest_entities = w.manifest.get("counts", {}).get("entities", {})
    if manifest_entities:
        print("\n  entities the generator drew (from the manifest)")
        for kind, drawn in sorted(manifest_entities.items()):
            print(f"    {kind:<16} {drawn:>8,}")

    observed = len({r["truth_entity_id"] for r in w.tables.get("truth", [])})
    if observed:
        # Only one kind is the subject of the truth table, so the drawn counts
        # above cannot be compared kind by kind. The number that matters to a
        # matcher is this one: entities it can actually see.
        drawn_total = max(manifest_entities.values(), default=observed)
        print(f"\n  entities with at least one observation   {observed:>7,}")
        if drawn_total != observed:
            print(f"    of {drawn_total:,} drawn, so {drawn_total - observed:,} were "
                  "never written to any source and cannot be found")

    if w.kind == "records":
        sources = _counted(w.observations, "source")
        if sources:
            print("\n  records per source")
            for source, n in sources.most_common():
                print(f"    {source:<16} {n:>8,}")

        per_entity = collections.Counter(
            r["truth_entity_id"] for r in w.tables.get("truth", []))
        singletons = sum(1 for n in per_entity.values() if n == 1)
        print(f"\n  entities with more than one record   "
              f"{len(per_entity) - singletons:>7,}")
        print(f"  entities with exactly one record     {singletons:>7,}"
              "   (singletons a matcher should not merge)")

        if w.tables.get("events"):
            print("\n  event rows by kind")
            for kind, n in _counted(w.tables["events"], "kind").most_common():
                print(f"    {kind:<24} {n:>7,}")

        print("\n  every cause, with its count")
        by_kind: dict[str, collections.Counter] = collections.defaultdict(
            collections.Counter)
        for d in w.differences:
            by_kind[d["difference_kind"]][d["cause"]] += 1
        for kind in sorted(by_kind):
            total = sum(by_kind[kind].values())
            print(f"    {kind}   ({total:,} rows)")
            for cause, n in by_kind[kind].most_common():
                share = n / total
                print(f"      {cause:<28} {n:>7,}   {share:>5.1%} of this kind")

        if w.tables.get("collisions"):
            print(f"\n  collisions   {len(w.tables['collisions']):>7,}"
                  "   (different entities that genuinely share a name)")

    else:
        print("\n  request endpoints by rendering")
        renderings = _counted(w.tables.get("requests", []), "rendering")
        for rendering, n in renderings.most_common():
            print(f"    {rendering:<20} {n:>7,}")


def main() -> int:
    names = sys.argv[1:] or available()
    if not names:
        print("no worlds found beside the package", file=sys.stderr)
        return 1
    for name in names:
        report(name)
    print("\nPaste these into DATACARD.md rather than editing its numbers by hand.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
