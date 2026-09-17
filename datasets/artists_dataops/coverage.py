# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""How much of the truth does the variant list know? Measured before any matcher runs.

    uv run python datasets/artists_dataops/coverage.py

The ablation in plan §7d hands Splink a list of name variants and asks what it
buys. The list (MusicBrainz + the curated YAMLs) and the truth (Wikidata alias
groups) are deliberately different sources, so the list cannot know every
alias the truth contains. **Coverage** is the share it does know, and it bounds
the gain before a single pair is scored: a list that covers 40% of alias pairs
cannot recover more than 40% of them, whatever the matcher does.

Two more numbers come out of the same join and both matter to the article:

- **Extra** -- pairs the list asserts that the truth does not. Where the list
  is right and Wikidata is incomplete, these are free recall on real data.
  Where the list is wrong, they are false merges waiting to happen.
- **List collisions** -- a name that appears in two different list groups.
  Giving a matcher that name as a variant of *both* is how a variant list
  costs precision (the wrong-Tyla case).

Writes ``datasets/data/artist_variants.jsonl``: the list, one group per row,
in the shape the Splink arms consume. It is built here and nowhere else so
the coverage number and the list a matcher is given cannot drift apart.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "data" / "synthetic"))
from arche_synthetic.artists import SPELLING_BOUNDARY, jaro_winkler, load_truth  # noqa: E402

MB = _REPO / "datasets" / "data" / "musicbrainz_artist_aliases.jsonl"
CURATED = sorted((_REPO / "datasets" / "artist_equivalences").glob("*.yaml"))
OUT = _REPO / "datasets" / "data" / "artist_variants.jsonl"
REPORT = _REPO / "datasets" / "artists_dataops" / "coverage_result.json"


def norm(name: str) -> str:
    return " ".join(name.casefold().split())


def list_groups() -> list[dict]:
    """The variant list: every MusicBrainz artist with 2+ names, plus curated."""
    groups = []
    for line in MB.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        names = [r["mb_name"], *(a["name"] for a in r["aliases"])]
        distinct = {norm(n): n for n in names if n and norm(n)}
        if len(distinct) >= 2:
            groups.append({"group_id": f"mb:{r['mbid']}", "source": "musicbrainz",
                           "names": list(distinct.values())})
    for path in CURATED:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for i, g in enumerate(doc.get("groups", [])):
            names = [g["canonical"], *g.get("variants", [])]
            distinct = {norm(n): n for n in names if n}
            if len(distinct) >= 2:
                groups.append({"group_id": f"curated:{path.stem}:{i}",
                               "source": f"curated/{path.stem}",
                               "names": list(distinct.values())})
    return groups


def main() -> int:
    if not MB.exists():
        print(f"  missing {MB.relative_to(_REPO)}; run pull_musicbrainz.py first")
        return 1
    truth = load_truth()
    groups = list_groups()

    # name -> list group ids
    index: dict[str, set[str]] = defaultdict(set)
    for g in groups:
        for n in g["names"]:
            index[norm(n)].add(g["group_id"])

    mb_known = {json.loads(l)["entity_id"]
                for l in MB.read_text(encoding="utf-8").splitlines() if l.strip()}

    # --- coverage of truth pairs ------------------------------------------
    total = covered = 0
    by_stratum = {"alias": [0, 0], "spelling": [0, 0]}
    by_known = {"artist in MusicBrainz": [0, 0], "artist not in MusicBrainz": [0, 0]}
    uncovered_examples = []
    for g in truth:
        known = "artist in MusicBrainz" if g["wikidata"] in mb_known else "artist not in MusicBrainz"
        for a, b in combinations(g["names"], 2):
            total += 1
            stratum = ("spelling" if jaro_winkler(a, b) >= SPELLING_BOUNDARY else "alias")
            hit = bool(index.get(norm(a), set()) & index.get(norm(b), set()))
            covered += hit
            by_stratum[stratum][0] += hit
            by_stratum[stratum][1] += 1
            by_known[known][0] += hit
            by_known[known][1] += 1
            if not hit and stratum == "alias" and len(uncovered_examples) < 8:
                uncovered_examples.append((g["canonical"], a, b))

    # --- what the list asserts beyond the truth --------------------------
    truth_pairs = set()
    for g in truth:
        for a, b in combinations(g["names"], 2):
            truth_pairs.add(frozenset((norm(a), norm(b))))
    list_pairs = set()
    for g in groups:
        for a, b in combinations(g["names"], 2):
            list_pairs.add(frozenset((norm(a), norm(b))))
    extra = list_pairs - truth_pairs

    # --- names the list puts in more than one group ------------------------
    # Two groups that share *several* names are one artist listed twice (the
    # curated Ayra Starr and MusicBrainz's). Two groups that share exactly
    # one name and nothing else are the ambiguity a matcher will pay for.
    names_of = {g["group_id"]: {norm(n) for n in g["names"]} for g in groups}
    collisions = {}
    duplicates = 0
    for n, ids in index.items():
        if len(ids) < 2:
            continue
        ids = sorted(ids)
        if any(len(names_of[a] & names_of[b]) >= 2
               for i, a in enumerate(ids) for b in ids[i + 1:]):
            duplicates += 1
        else:
            collisions[n] = ids

    pct = lambda h, t: f"{100 * h / t:5.1f}%" if t else "   --"  # noqa: E731
    print(f"  truth: {len(truth):,} alias groups, {total:,} name pairs")
    print(f"  list : {len(groups):,} groups "
          f"({sum(1 for g in groups if g['source'] == 'musicbrainz'):,} MusicBrainz, "
          f"{sum(1 for g in groups if g['source'] != 'musicbrainz')} curated), "
          f"{len(list_pairs):,} name pairs\n")
    print(f"  coverage of truth pairs          {pct(covered, total)}   ({covered:,} / {total:,})")
    for k, (h, t) in by_stratum.items():
        print(f"    {k:<30} {pct(h, t)}   ({h:,} / {t:,})")
    for k, (h, t) in by_known.items():
        print(f"    {k:<30} {pct(h, t)}   ({h:,} / {t:,})")
    print(f"\n  list pairs not in truth (extra)  {len(extra):,} of {len(list_pairs):,}")
    print(f"  same artist listed twice         {duplicates:,} names  (curated and MusicBrainz)")
    print(f"  genuine list collisions          {len(collisions):,} names  (one shared name, otherwise different)")
    if collisions:
        for n, ids in list(collisions.items())[:6]:
            print(f"    {n!r}: {ids}")
    if uncovered_examples:
        print("\n  alias pairs the list does not know (sample):")
        for canon, a, b in uncovered_examples:
            print(f"    [{canon}]  {a}  <>  {b}")

    with OUT.open("w", encoding="utf-8", newline="\n") as fh:
        for g in groups:
            fh.write(json.dumps(g, ensure_ascii=False) + "\n")
    report = {
        "truth_groups": len(truth), "truth_pairs": total,
        "list_groups": len(groups), "list_pairs": len(list_pairs),
        "covered": covered, "coverage": round(covered / total, 4) if total else None,
        "by_stratum": {k: {"covered": h, "total": t} for k, (h, t) in by_stratum.items()},
        "by_known": {k: {"covered": h, "total": t} for k, (h, t) in by_known.items()},
        "extra_pairs": len(extra), "list_collisions": len(collisions),
        "list_duplicates": duplicates,
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"\n  wrote {OUT.relative_to(_REPO)} and {REPORT.relative_to(_REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
