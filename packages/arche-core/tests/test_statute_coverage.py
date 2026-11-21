# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Does every statute pack govern only what something can find?

For each shipped pack, the categories it maps are compared with the categories
a rule detector can emit on the rules-only path (``backend="basic"``) for the
pack's own jurisdiction. Every gap must be explained by one of three things:

* the category is proposed only by the model (:data:`MODEL_ONLY`);
* nothing in arche emits it at all (:data:`NO_DETECTOR`), which is a known gap;
* it is another jurisdiction's identifier (a Nigerian NIN in the GDPR pack),
  which a rule pack detects where it belongs and which the pack governs for
  caller-supplied detections.

A pack that starts governing a category none of these explain fails here, and
so does an allowlist entry that stops being true, so the lists cannot rot into
a blanket excuse.

The HIPAA pack makes a stronger claim, one row per Safe Harbor identifier
(``safe_harbor_identifiers``), and every row is checked in both directions.
"""

from __future__ import annotations

import re
import warnings

import pytest
from arche import Pipeline
from arche.coverage import coverage, detectable_categories
from arche.detect.model import CATEGORY_FOR_LABEL
from arche.policy import list_available_statutes, load_statute

#: Proposed by GLiNER2-PII (``backend="gliner2-pii"``) and by no rule detector
#: in the jurisdictions listed.
MODEL_ONLY: dict[str, str] = {
    "PII-2-DRIVERS_LICENCE": "licence numbers outside NG (NG_DRIVERS is a rule)",
    "PII-2-NATIONAL_ID": "national ids outside ZA (ZA_ID is a rule)",
    "PII-2-PASSPORT": "passports outside ZA (ZA_PASSPORT is a rule)",
    "PII-2-TIN": "generic tax ids outside NG/GH (those packs have rules)",
    "PII-8-PASSWORD": "secrets and credentials",
}

#: Governed by at least one pack, emitted by nothing in arche. The honest gap.
NO_DETECTOR: dict[str, str] = {
    # Special-category data: a span-level rule for health or religion would be
    # a keyword list pretending to be a detector.
    "PII-6-HEALTH": "special category", "PII-6-RACE": "special category",
    "PII-6-RELIGION": "special category",
    "PII-6-SEXUAL_ORIENTATION": "special category",
    "PII-6-POLITICAL_AFFILIATION": "special category",
    # Biometric references are structured data, not text spans.
    "PII-6-BIOMETRIC": "biometric", "PII-7-FINGERPRINT_REF": "biometric",
    "PII-7-FACE_TEMPLATE": "biometric",
    "PII-8-DEVICE_ID": "no device-identifier detector",
    "PII-8-COOKIE": "no cookie detector",
    "PII-8-URL": "no URL detector",
    "PII-5-MPESA_REF": "no mobile-money reference detector",
    "PII-5-MOMO_REF": "no mobile-money reference detector",
}

_ALL_RULE_PACKS = ["ng", "ke", "za", "gh", "us", "names", "locations", "emails", "ip",
                   "digital_id", "addr", "core", "financial"]
_RULES_ANYWHERE = detectable_categories(_ALL_RULE_PACKS)
_MODEL = set(CATEGORY_FOR_LABEL.values())

#: A pack's jurisdiction, as a Pipeline takes it. BASELINE applies where no
#: pack does, so it is measured on such a jurisdiction.
_JURISDICTION = {"*": "BR"}


def _report(statute_id: str) -> dict:
    statute = load_statute(statute_id)
    jurisdiction = _JURISDICTION.get(statute.jurisdiction, statute.jurisdiction)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pipeline = Pipeline(jurisdiction=jurisdiction, statute=statute_id, backend="basic")
    return coverage(pipeline)


def _explained(category: str) -> str | None:
    if category in MODEL_ONLY:
        return "model-only"
    if category in NO_DETECTOR:
        return "no detector"
    if category in _RULES_ANYWHERE:
        return "other jurisdiction"
    return None


@pytest.mark.parametrize("statute_id", list_available_statutes())
def test_every_governed_category_is_detected_or_explained(statute_id):
    report = _report(statute_id)
    rows = [(c, "rules" if c in report["covered"] else _explained(c))
            for c in report["governed"]]
    print(f"\n{statute_id} ({report['jurisdiction']}): "
          f"{len(report['covered'])}/{len(report['governed'])} by rules")
    for category, how in rows:
        print(f"  {category:<28} {how}")
    unexplained = [c for c, how in rows if how is None]
    assert not unexplained, (
        f"{statute_id} governs {unexplained}, which no rule detector emits for "
        f"{report['jurisdiction']} and no allowlist explains")


def test_model_only_entries_are_model_categories_and_still_gaps():
    uncovered = set().union(*(_report(s)["uncovered"] for s in list_available_statutes()))
    for category in MODEL_ONLY:
        assert category in _MODEL, f"{category} is listed model-only but no label maps to it"
        assert category in uncovered, f"{category} is detected everywhere now; drop it"


def test_no_detector_entries_are_really_undetected():
    for category in NO_DETECTOR:
        assert category not in _RULES_ANYWHERE, f"{category} has a rule detector now"
        assert category not in _MODEL, f"{category} is proposed by the model now"


# ── HIPAA Safe Harbor: the 18-identifier claim ───────────────────────────────

_HIPAA = "HIPAA-SAFE-HARBOR"


@pytest.fixture(scope="module")
def safe_harbor():
    statute = load_statute(_HIPAA)
    rules = set(_report(_HIPAA)["detectable_categories"])
    return statute, statute.raw["safe_harbor_identifiers"], rules


def test_the_pack_lists_all_18_identifiers(safe_harbor):
    _, rows, _ = safe_harbor
    assert [r["n"] for r in rows] == list(range(1, 19))
    assert {r["status"] for r in rows} <= {"rules", "model-only", "none"}


def test_each_identifier_row_matches_the_detectors(safe_harbor):
    statute, rows, rules = safe_harbor
    print(f"\n{'#':>2}  {'identifier':<46} {'claim':<10} categories")
    for r in rows:
        cats = set(r["categories"])
        print(f"{r['n']:>2}  {r['name']:<46} {r['status']:<10} {', '.join(sorted(cats))}")
        if r["status"] == "rules":
            assert cats and cats <= rules, f"#{r['n']} claims rules; {cats - rules} are not"
            assert cats <= set(statute.policy_mappings), f"#{r['n']} has unmapped {cats}"
        elif r["status"] == "model-only":
            assert cats and cats <= _MODEL, f"#{r['n']}: {cats - _MODEL} not model labels"
            assert not cats & rules, f"#{r['n']} is rule-detected now: {cats & rules}"
            assert cats <= set(statute.policy_mappings), f"#{r['n']} has unmapped {cats}"
        else:
            assert not cats & (rules | _MODEL), f"#{r['n']} is detected now"


def test_the_stated_count_matches_the_rows(safe_harbor):
    """The header says "Rules-only: N of 18"; N must be the rows marked rules."""
    _, rows, _ = safe_harbor
    from arche.policy.engine import _STATUTES_DIR

    header = (_STATUTES_DIR / f"{_HIPAA}.yaml").read_text(encoding="utf-8")
    stated = int(re.search(r"Rules-only: (\d+) of 18", header).group(1))
    assert stated == sum(r["status"] == "rules" for r in rows)
