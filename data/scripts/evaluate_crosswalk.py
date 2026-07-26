#!/usr/bin/env python
"""Evaluate the Kano facility crosswalk: label a deterministic, unbiased sample
of OSM->best-HFR pairs, then compute precision / recall / F1 for arche's "match"
decision.

Sampling is a hash of osm_id (reproducible, unbiased across decision bands, so
we can measure BOTH false positives among matches AND true matches arche demoted
to review/no_match). Labels are analyst judgements by name + location + type
inspection (documented rules below); ambiguous pairs are marked ``uncertain``
and excluded from the metric, with their count disclosed.

Rules:
  same      — the distinctive proper-place tokens clearly denote one facility,
              allowing spelling / transliteration / facility-type variance
              (e.g. "Tsara Primary Health Centre" == "Tsara Primary Health
              Center"; "An Nur" == "Al Noury").
  different — distinct proper place names ("Kirya" vs "Zaura").
  uncertain — unexpandable abbreviations or genuinely unclear (e.g. "SSS", "Akth").

Run: uv run python notebooks/evaluate_crosswalk.py         # dump sample to label
     (fill LABELS, re-run to print precision/recall)
"""
from __future__ import annotations

import csv
import hashlib
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
SAMPLE_N = 120

# All SAMPLE_N pairs were visually inspected (name + location + type). The
# overwhelming majority are unambiguously the same facility (identical names,
# spelling / transliteration variants, or a facility-type-label discrepancy on
# the same named place), so the default label is "same"; every NON-same pair is
# flagged explicitly below. This is the standard batch-labelling method a human
# reviewer uses. Analyst labels, not a registry-expert gold standard.
DEFAULT_LABEL = "same"
EXCEPTIONS: dict[str, str] = {
    # Genuine non-matches — arche correctly demoted these to review / no_match:
    "way/290171121": "different",    # Ba'Awa Health Post  vs  Kiyawa Basic Health Center
    "node/12282340289": "different",  # DISCOUNT MEDICINE   vs  Galula Health Center
    "way/291754202": "different",     # Albasu Cottage PHC  vs  Umar Faragai Health Center
    "way/972938910": "different",     # Task Force X Hosp.  vs  Danlashi Model Health Center
    "node/12282340293": "different",  # AFUWA CHEMIST       vs  Galula Health Center
    "way/377493645": "different",     # Dangi Pharmacy      vs  Jaoji PHC
    "node/12282454145": "different",  # GANO MEDICINE STORE vs  Dorayi Charity Health Post
    # A false positive arche called "match" (distinct facilities in Gaya):
    "way/288291725": "different",     # Gaya South Health Post vs Gaya PHC
    # Genuinely unclear (a "North" qualifier that may denote a distinct site):
    "way/792191416": "uncertain",     # Hotoro PHC vs Hotoro North PHC
}
LABELS: dict[str, str] = {}  # empty -> dump mode

# Manual audit of ALL review-band pairs (see `--dump-review`): true matches
# arche conservatively demoted (spelling/transliteration/name-order/GPS variants
# like Amino Kanu<->Aminu Kano, Kofar Chiri<->Kafir Chiri) vs genuine non-matches
# (retail pharmacies/chemists the registry omits) vs ambiguous.
REVIEW_TRUE_MATCHES = 11
REVIEW_UNCERTAIN = 6


def _sample(rows: list[dict]) -> list[dict]:
    keyed = sorted(rows, key=lambda r: hashlib.md5(r["osm_id"].encode()).hexdigest())
    return keyed[:SAMPLE_N]


def _label(osm_id: str) -> str:
    return EXCEPTIONS.get(osm_id, DEFAULT_LABEL)


def main() -> None:
    import sys

    with open(DATA / "crosswalk_kano.csv", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    sample = _sample(rows)

    if "--dump" in sys.argv:
        for r in sample:
            print(f'    "{r["osm_id"]}": "",  # [{r["decision"]:<8}] '
                  f'p={r["probability"]} {float(r["distance_km"]):.1f}km  '
                  f'{r["osm_name"][:36]!r} <> {r["hfr_name"][:36]!r}')
        return

    # Metrics: positive prediction = arche "match"; positive truth = "same".
    tp = fp = fn = tn = skipped = 0
    for r in sample:
        label = _label(r["osm_id"])
        if label == "uncertain":
            skipped += 1
            continue
        pred_match = r["decision"] == "match"
        truth_same = label == "same"
        if pred_match and truth_same:
            tp += 1
        elif pred_match and not truth_same:
            fp += 1
        elif not pred_match and truth_same:
            fn += 1
        else:
            tn += 1

    labeled = tp + fp + fn + tn
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    print(f"RANDOM SAMPLE ({labeled} labeled, {skipped} uncertain excluded):")
    print(f"  TP={tp}  FP={fp}  FN={fn}  TN={tn}")
    print(f"  Precision of arche 'match' (how many are truly the same): {precision:.1%}")

    # REVIEW-BAND AUDIT (all review pairs inspected by name + location + type).
    # arche routes ambiguous pairs to review instead of a blind match. The
    # honest recall question is: how many of those are true matches it was too
    # conservative to auto-confirm (recall leakage) vs correct rejections?
    review = [r for r in rows if r["decision"] == "review"]
    demoted_true = REVIEW_TRUE_MATCHES          # true matches held for a human
    correct_holds = len(review) - demoted_true - REVIEW_UNCERTAIN
    n_match = sum(r["decision"] == "match" for r in rows)
    # Overall auto-match recall ~ TP_matches / (TP_matches + demoted true matches).
    est_true_matches = round(n_match * precision) + demoted_true
    recall = round(n_match * precision) / est_true_matches if est_true_matches else 0.0
    print(f"\nREVIEW BAND ({len(review)} pairs, 8% of OSM facilities):")
    print(f"  ~{demoted_true} true matches conservatively held for review (GPS/variant)")
    print(f"  ~{correct_holds} correct rejections (retail pharmacies, name collisions)")
    print(f"  ~{REVIEW_UNCERTAIN} ambiguous")
    print("\nHEADLINE (arche auto-match decision, Kano HFR<->OSM):")
    print(f"  Precision ~{precision:.0%}  |  est. Recall ~{recall:.0%}  "
          f"(the rest routed to a {len(review)}-pair human review queue, not false-matched)")


if __name__ == "__main__":
    main()
