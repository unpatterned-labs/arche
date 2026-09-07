# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""`Pipeline(backend=...)`: a model proposes, the rules and the statute decide.

The model is stood in for by a fake that answers in the shape GLiNER2-PII
answers in (label-grouped spans with offsets), so these run without the
extra and without a download. What is under test is the contract around the
model, which is where the safety lives:

* a validated detection outranks a proposal over the same text;
* a whole-name proposal absorbs the lexicon's per-token names;
* a label arche has no category for is dropped, not invented;
* `auto` without the extra runs the rules and says so once;
* an explicit `gliner2-pii` without the extra raises.
"""

from __future__ import annotations

import warnings

import pytest
from arche import Pipeline
from arche.detect import model as model_module
from arche.detect.model import (
    CATEGORY_FOR_LABEL,
    LABELS_ASKED,
    UNMAPPED,
    merge,
    propose_pii,
    resolve_backend,
)
from arche.workflow._primitive import Detection

# No lexicon name in here on purpose: *Zephyrine Quill* is what the model is
# for. (The first draft said "Ember Close", and the lexicon read *Close* as a
# surname -- which it is, in the lexicon. The basic path has its own false
# positives; that is a benchmark's job to count, not this test's.)
TEXT = ("Patient Zephyrine Quill, NIN 12345678901, lives at 4 Ember Street, Ikeja. "
        "Login zq_2026.")


def _span(text, needle, label, confidence=0.9):
    start = text.index(needle)
    return {"text": needle, "confidence": confidence, "start": start, "end": start + len(needle)}


RESPONSE = {"entities": {
    "person": [_span(TEXT, "Zephyrine Quill", "person", 0.91)],
    "national_id_number": [_span(TEXT, "12345678901", "national_id_number", 0.62)],
    "street_address": [_span(TEXT, "4 Ember Street, Ikeja", "street_address", 0.8)],
    "username": [_span(TEXT, "zq_2026", "username", 0.7)],
    "email": [],
}}


class _FakeExtractor:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def extract_entities(self, text, labels, **kwargs):
        self.calls.append({"text": text, "labels": labels, **kwargs})
        return self.response


@pytest.fixture
def fake_pii_model(monkeypatch):
    model = _FakeExtractor(RESPONSE)
    monkeypatch.setattr("arche._models.get_gliner2", lambda *a, **k: model)
    monkeypatch.setattr(model_module, "_warned", False)
    return model


@pytest.fixture
def no_model(monkeypatch):
    def missing(*a, **k):
        raise ImportError("GLiNER 2 is not installed. pip install 'arche-core[detect2]'")
    monkeypatch.setattr("arche._models.get_gliner2", missing)
    monkeypatch.setattr(model_module, "_warned", False)


# ---------------------------------------------------------------------------
# the vocabulary
# ---------------------------------------------------------------------------


def test_basic_is_the_default_and_regex_still_spells_it():
    assert Pipeline(jurisdiction="NG").backend == "basic"
    assert Pipeline(jurisdiction="NG", backend="regex").backend == "basic"
    assert resolve_backend("auto") == "auto"


@pytest.mark.parametrize("bad, hint", [
    ("gliner", "removed in 0.9.0"),
    ("gliner2", "general extractor"),
    ("magic", "gliner2-pii"),
])
def test_a_backend_the_pipeline_cannot_run_is_refused_with_a_hint(bad, hint):
    with pytest.raises(ValueError, match=hint):
        Pipeline(jurisdiction="NG", backend=bad)


def test_basic_never_touches_the_model(no_model):
    result = Pipeline(jurisdiction="NG").process(TEXT)
    assert result.metadata["backend"] == "basic" and result.metadata["model"] is None


# ---------------------------------------------------------------------------
# the model as a proposer
# ---------------------------------------------------------------------------


def test_the_model_finds_the_name_the_lexicon_does_not_hold(fake_pii_model):
    basic = Pipeline(jurisdiction="NG").process(TEXT)
    assert not [d for d in basic.detections if "Zephyrine" in d.text]
    with_model = Pipeline(jurisdiction="NG", backend="gliner2-pii").process(TEXT)
    names = [d for d in with_model.detections if d.text == "Zephyrine Quill"]
    assert len(names) == 1 and names[0].category == "PII-1-NAME"
    assert names[0].detector.startswith("model:fastino/gliner2-privacy-filter")
    # Enriched like any other detection: the statute's section travels with it.
    assert names[0].regulatory_citation and "NDPA-2023" in names[0].regulatory_citation
    assert with_model.metadata["model"] == "fastino/gliner2-privacy-filter-PII-multi"


def test_a_validated_identifier_outranks_the_models_reading_of_it(fake_pii_model):
    result = Pipeline(jurisdiction="NG", backend="gliner2-pii").process(TEXT)
    nins = [d for d in result.detections if d.start == TEXT.index("12345678901")]
    assert len(nins) == 1
    assert nins[0].category == "PII-2-NIN" and nins[0].detector.startswith("rule:")


def test_the_redaction_covers_what_the_model_proposed(fake_pii_model):
    result = Pipeline(jurisdiction="NG", backend="gliner2-pii").process(TEXT)
    assert "Zephyrine Quill" not in result.redacted_text
    assert "12345678901" not in result.redacted_text


def test_an_unmapped_label_is_dropped_not_invented(fake_pii_model):
    result = Pipeline(jurisdiction="NG", backend="gliner2-pii").process(TEXT)
    assert not [d for d in result.detections if "zq_2026" in d.text]
    assert "username" in UNMAPPED and "username" not in CATEGORY_FOR_LABEL


def test_the_model_is_asked_for_the_mapped_labels_with_offsets(fake_pii_model):
    Pipeline(jurisdiction="NG", backend="gliner2-pii").process(TEXT)
    call = fake_pii_model.calls[0]
    assert set(call["labels"]) == set(LABELS_ASKED)
    assert set(LABELS_ASKED) <= set(CATEGORY_FOR_LABEL)
    assert call["include_spans"] is True and call["include_confidence"] is True


def test_every_mapped_category_is_one_a_statute_can_govern():
    from arche.policy import load_statute

    governed = set()
    for statute_id in ("NDPA-2023", "POPIA", "KENYA-DPA", "GHANA-DPA", "UK-GDPR",
                       "GDPR", "HIPAA-SAFE-HARBOR", "BASELINE"):
        governed |= set(load_statute(statute_id).policy_mappings)
    orphaned = sorted(set(CATEGORY_FOR_LABEL.values()) - governed)
    # A category no pack maps falls to the statute's default action. Naming
    # the orphans here keeps that a known list rather than a surprise.
    assert orphaned == ["PII-1-DOB"], orphaned


# ---------------------------------------------------------------------------
# the merge rule, directly
# ---------------------------------------------------------------------------


def _det(category, start, end, text="x", detector="rule:test"):
    return Detection(id=f"det:{category}:{start}:{end}", category=category, text=text,
                     start=start, end=end, confidence=0.9, detector=detector)


def test_a_whole_name_proposal_absorbs_the_lexicons_tokens():
    rules = [_det("PII-1-NAME", 0, 7, "Adesola"), _det("PII-1-NAME", 8, 15, "Okonkwo"),
             _det("PII-2-NIN", 21, 32, "12345678901")]
    proposal = _det("PII-1-NAME", 0, 15, "Adesola Okonkwo", detector="model:x")
    merged = merge(rules, [proposal])
    assert [(d.category, d.start, d.end) for d in merged] == \
        [("PII-1-NAME", 0, 15), ("PII-2-NIN", 21, 32)]


def test_the_model_against_itself_keeps_the_whole_name():
    # Asked for several name labels, the model answers `first_name`, `person`
    # and `last_name` over one name. Measured: the last one processed used to
    # win, which left "Example" masked and "Casey" in the clear.
    proposals = [_det("PII-1-NAME", 8, 13, "Casey", detector="model:x"),
                 _det("PII-1-NAME", 8, 21, "Casey Example", detector="model:x"),
                 _det("PII-1-NAME", 14, 21, "Example", detector="model:x")]
    merged = merge([], proposals)
    assert [(d.text, d.start, d.end) for d in merged] == [("Casey Example", 8, 21)]


def test_a_proposal_over_a_validated_span_is_dropped():
    rules = [_det("PII-2-NIN", 21, 32)]
    proposal = _det("PII-2-NATIONAL_ID", 17, 32, detector="model:x")
    assert merge(rules, [proposal]) == rules


def test_a_name_proposal_over_a_non_name_rule_is_dropped():
    # An address span that a name proposal overlaps: the address is the rule's
    # finding, and a name is not the same finding at another granularity.
    rules = [_det("PII-4-ADDRESS", 0, 30)]
    proposal = _det("PII-1-NAME", 5, 12, detector="model:x")
    assert merge(rules, [proposal]) == rules


# ---------------------------------------------------------------------------
# without the extra
# ---------------------------------------------------------------------------


def test_auto_without_the_extra_runs_the_rules_and_warns_once(no_model):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        first = Pipeline(jurisdiction="NG", backend="auto").process(TEXT)
        second = Pipeline(jurisdiction="NG", backend="auto").process(TEXT)
    assert first.metadata["model"] is None and second.metadata["model"] is None
    said = [w for w in caught if "arche-core[detect2]" in str(w.message)]
    assert len(said) == 1
    assert [d.category for d in first.detections] == \
        [d.category for d in Pipeline(jurisdiction="NG").process(TEXT).detections]


def test_an_explicit_model_backend_without_the_extra_raises(no_model):
    with pytest.raises(ImportError, match="detect2"):
        Pipeline(jurisdiction="NG", backend="gliner2-pii").process(TEXT)


def test_propose_pii_reports_what_ran(no_model):
    assert propose_pii(TEXT, backend="basic") == ([], None)
    detections, model = propose_pii(TEXT, backend="auto")
    assert detections == [] and model is None
