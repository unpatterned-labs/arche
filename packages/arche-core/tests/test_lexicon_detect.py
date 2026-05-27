# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for arche.detect._base._compile_lexicon and _lexicon_detect.

Locks the shared lexicon-detect helper that arche.detect.names and
arche.detect.locations will share per the 2026-05-22 eng review §2
issue 7 DRY extraction decision.
"""

from __future__ import annotations

import re

import pytest
from arche.detect._base import _compile_lexicon, _lexicon_detect
from arche.workflow._primitive import Detection

# ----------------------------------------------------------------------
# _compile_lexicon
# ----------------------------------------------------------------------


def test_compile_lexicon_returns_compiled_pattern() -> None:
    """Returns a re.Pattern object."""
    pat = _compile_lexicon(["alice", "bob"])
    assert isinstance(pat, re.Pattern)


def test_compile_lexicon_case_insensitive_by_default() -> None:
    """Lowercase pattern matches Title Case input."""
    pat = _compile_lexicon(["adesola"])
    assert pat.search("Met Adesola today")


def test_compile_lexicon_case_sensitive_when_flagged() -> None:
    """With case_insensitive=False, case must match exactly."""
    pat = _compile_lexicon(["adesola"], case_insensitive=False)
    assert pat.search("met adesola today")
    assert not pat.search("met Adesola today")


def test_compile_lexicon_longest_match_wins() -> None:
    """`Cape Town` matches before `Cape` so we don't half-match."""
    pat = _compile_lexicon(["Cape Town", "Cape"])
    matches = list(pat.finditer("Cape Town and Cape separately"))
    assert len(matches) == 2
    assert matches[0].group(0) == "Cape Town"
    assert matches[1].group(0) == "Cape"


def test_compile_lexicon_word_boundaries() -> None:
    """`mark` should NOT match inside `marker`."""
    pat = _compile_lexicon(["mark"])
    assert pat.search("Mark called today")
    assert not pat.search("The marker on the wall")


def test_compile_lexicon_handles_regex_special_chars() -> None:
    """Terms with regex metacharacters (`'`, `-`) are escaped, not interpreted.

    Real-world lexicon entries include names like 'O'Connor' (apostrophe) and
    'Jean-Pierre' (hyphen). These contain word-boundary-friendly characters
    so \\b still works; the regex-escape guarantees the apostrophe and
    hyphen are treated as literals.
    """
    pat = _compile_lexicon(["O'Connor", "Jean-Pierre"])
    assert pat.search("Met O'Connor at the gate")
    assert pat.search("Greeted Jean-Pierre yesterday")
    # No partial-character matches
    assert not pat.search("Saw OConnor without the apostrophe")


def test_compile_lexicon_deduplicates() -> None:
    """Duplicate terms are merged."""
    pat = _compile_lexicon(["alice", "alice", "ALICE"])
    matches = list(pat.finditer("alice ALICE Alice"))
    assert len(matches) == 3  # all 3 instances detected once each


def test_compile_lexicon_rejects_empty_list() -> None:
    """Empty term list raises ValueError loudly."""
    with pytest.raises(ValueError, match="non-empty"):
        _compile_lexicon([])


# ----------------------------------------------------------------------
# _lexicon_detect
# ----------------------------------------------------------------------


def test_lexicon_detect_emits_detection_objects() -> None:
    """Returns list of Detection (the canonical shape, not NationalID)."""
    pat = _compile_lexicon(["Adesola"])
    detections = _lexicon_detect(
        "Met Adesola today",
        pat,
        category="PII-1-NAME",
        detector_name="rule:test_names",
    )
    assert len(detections) == 1
    assert isinstance(detections[0], Detection)


def test_lexicon_detect_populates_canonical_fields() -> None:
    """category, detector, identity_class, confidence all set correctly."""
    pat = _compile_lexicon(["Adesola"])
    detections = _lexicon_detect(
        "Met Adesola today",
        pat,
        category="PII-1-NAME",
        detector_name="rule:test_names",
        identity_class="inferred",
        confidence=0.85,
    )
    d = detections[0]
    assert d.category == "PII-1-NAME"
    assert d.detector == "rule:test_names"
    assert d.identity_class == "inferred"
    assert d.confidence == 0.85
    assert d.text == "Adesola"


def test_lexicon_detect_offsets_are_correct() -> None:
    """start/end point to the matched substring."""
    text = "Met Adesola today"
    pat = _compile_lexicon(["Adesola"])
    d = _lexicon_detect(text, pat, category="PII-1-NAME", detector_name="x")[0]
    assert text[d.start:d.end] == "Adesola"


def test_lexicon_detect_id_format() -> None:
    """Detection.id follows the det:{start}:{end} convention."""
    pat = _compile_lexicon(["Adesola"])
    d = _lexicon_detect("Met Adesola today", pat,
                         category="PII-1-NAME", detector_name="x")[0]
    assert d.id == f"det:{d.start}:{d.end}"


def test_lexicon_detect_returns_empty_on_no_match() -> None:
    pat = _compile_lexicon(["Adesola"])
    assert _lexicon_detect("No names here", pat,
                            category="PII-1-NAME", detector_name="x") == []


def test_lexicon_detect_metadata_factory_called_with_match() -> None:
    """metadata_factory receives the re.Match, can populate per-detection data."""
    pat = _compile_lexicon(["Lagos"])

    def factory(match: re.Match) -> dict:
        return {"matched_text": match.group(0), "country": "NG"}

    detections = _lexicon_detect(
        "City: Lagos",
        pat,
        category="PII-4-LOCATION",
        detector_name="rule:locations",
        metadata_factory=factory,
    )
    assert detections[0].metadata == {"matched_text": "Lagos", "country": "NG"}


def test_lexicon_detect_metadata_empty_when_no_factory() -> None:
    pat = _compile_lexicon(["Adesola"])
    d = _lexicon_detect("Met Adesola", pat,
                         category="PII-1-NAME", detector_name="x")[0]
    assert d.metadata == {}


def test_lexicon_detect_multiple_matches_ordered_by_offset() -> None:
    """finditer returns matches in document order."""
    pat = _compile_lexicon(["Adesola", "Fatima", "Chukwuemeka"])
    detections = _lexicon_detect(
        "Adesola, then Chukwuemeka, then Fatima",
        pat,
        category="PII-1-NAME",
        detector_name="x",
    )
    assert len(detections) == 3
    offsets = [d.start for d in detections]
    assert offsets == sorted(offsets)


def test_lexicon_detect_default_confidence_is_0_9() -> None:
    """The default confidence floor for lexicon matches."""
    pat = _compile_lexicon(["Adesola"])
    d = _lexicon_detect("Met Adesola", pat,
                         category="PII-1-NAME", detector_name="x")[0]
    assert d.confidence == 0.9


def test_lexicon_detect_default_identity_class_is_inferred() -> None:
    pat = _compile_lexicon(["Adesola"])
    d = _lexicon_detect("Met Adesola", pat,
                         category="PII-1-NAME", detector_name="x")[0]
    assert d.identity_class == "inferred"
