# Copyright 2026 unpatterned.org
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""C2-T1: the egress guard is fail-closed and never leaks raw PII."""

import pytest

from arche.guard import EgressGuard, GuardDenied, GuardedProjection
from arche.policy import load_statute
from arche.workflow._primitive import Detection, Pipeline


def _det(category: str, text: str, start: int, end: int) -> Detection:
    return Detection(
        id="d", category=category, text=text, start=start, end=end,
        confidence=0.9, detector="test",
    )


# ── fail-closed teeth ────────────────────────────────────────────────────────

def test_requires_non_empty_key():
    with pytest.raises(ValueError):
        EgressGuard(Pipeline(statute="NDPA-2023"), key="")


def test_deny_when_no_statute_configured():
    # A bare Pipeline applies no policy; the guard must refuse, not pass raw text.
    guard = EgressGuard(Pipeline(), key="k")
    with pytest.raises(GuardDenied):
        guard.guarded("Fatima, NIN 12345678901")


def test_deny_disallowed_provider():
    guard = EgressGuard(
        Pipeline(statute="NDPA-2023"), key="k", allowed_providers={"bedrock"}
    )
    with pytest.raises(GuardDenied):
        guard.guarded("hello", provider="sketchy-ai")


def test_allow_listed_provider_passes():
    guard = EgressGuard(
        Pipeline(statute="NDPA-2023"), key="k", allowed_providers={"bedrock"}
    )
    proj = guard.guarded("hello world", provider="bedrock")
    assert isinstance(proj, GuardedProjection)


def test_deny_cross_border_without_basis_and_cites():
    guard = EgressGuard(Pipeline(statute="GDPR"), key="k")
    with pytest.raises(GuardDenied) as ei:
        guard.guarded("hello", crosses_border=True)
    assert ei.value.citation and "GDPR" in ei.value.citation


def test_deny_cross_border_with_impermissible_basis():
    guard = EgressGuard(
        Pipeline(statute="GDPR"), key="k", transfer_basis="pinky_promise"
    )
    with pytest.raises(GuardDenied):
        guard.guarded("hello", crosses_border=True)


def test_allow_cross_border_with_permitted_basis():
    guard = EgressGuard(
        Pipeline(statute="GDPR"), key="k",
        transfer_basis="standard_contractual_clauses",
    )
    proj = guard.guarded("hello", crosses_border=True)
    assert proj.metadata["transfer_basis"] == "standard_contractual_clauses"


# ── projection: no raw PII leaves ────────────────────────────────────────────

def _guard_ng() -> EgressGuard:
    return EgressGuard(Pipeline(statute="NDPA-2023"), key="k")


def test_project_replaces_all_spans_no_raw_leak():
    statute = load_statute("NDPA-2023")
    text = "Fatima, NIN 12345678901, phone 08031234567"
    dets = [
        _det("PII-1-NAME", "Fatima", 0, 6),
        _det("PII-2-NIN", "12345678901", 12, 23),
        _det("PII-3-PHONE", "08031234567", 31, 42),
    ]
    redacted, fields = _guard_ng()._project(text, dets, statute)
    for d in dets:
        assert d.text not in redacted
    assert len(fields) == 3
    assert all(f.token for f in fields)  # nothing dropped here
    assert "[NIN:" in redacted and "[NAME:" in redacted and "[PHONE:" in redacted


def test_project_drop_removes_value_and_emits_no_token():
    statute = load_statute("NDPA-2023")
    # PII-5-CARD is dropped under NDPA — never retained, not even as a token.
    text = "card 4111111111111111 end"
    dets = [_det("PII-5-CARD", "4111111111111111", 5, 21)]
    redacted, fields = _guard_ng()._project(text, dets, statute)
    assert "4111111111111111" not in redacted
    assert fields[0].action == "drop"
    assert fields[0].token is None


def test_project_token_deterministic_for_same_value():
    statute = load_statute("NDPA-2023")
    text = "a 12345678901 b 12345678901 c"
    dets = [
        _det("PII-2-NIN", "12345678901", 2, 13),
        _det("PII-2-NIN", "12345678901", 16, 27),
    ]
    _, fields = _guard_ng()._project(text, dets, statute)
    assert fields[0].token == fields[1].token


def test_project_carries_citation_and_tier():
    statute = load_statute("NDPA-2023")
    dets = [_det("PII-2-NIN", "12345678901", 0, 11)]
    _, fields = _guard_ng()._project("12345678901", dets, statute)
    assert fields[0].citation and "NDPA" in fields[0].citation
    assert fields[0].tier == "high"


def test_guarded_end_to_end_runs_with_real_detectors():
    # Smoke: the whole guarded() path runs over real detectors without error and
    # returns a projection (no raw NIN survives whatever the detectors find).
    guard = EgressGuard(Pipeline(jurisdiction="NG"), key="k")
    proj = guard.guarded("My NIN is 12345678901 for KYC.")
    assert isinstance(proj, GuardedProjection)
    assert "12345678901" not in proj.redacted_text


# ── overlapping detections ───────────────────────────────────────────────────
#
# The guard used to sort spans by (start, end) descending and skip any span
# whose end ran past the last one it consumed. Descending order reaches the
# INNER span first, so the container was skipped and its prefix crossed the
# boundary in clear. The NG detector set produces that shape on any ordinary
# address, so this was not a corner case.


def test_nested_spans_replace_the_whole_region_no_raw_prefix():
    statute = load_statute("NDPA-2023")
    text = "Janet Okafor lives at 12 Awolowo Road, Ikoyi, Lagos."
    dets = [
        _det("PII-1-NAME", "Okafor", 6, 12),
        _det("PII-4-LOCATION", "Lagos", 46, 51),
        _det("PII-4-ADDRESS", "12 Awolowo Road, Ikoyi, Lagos", 22, 51),
    ]
    redacted, fields = _guard_ng()._project(text, dets, statute)
    # The regression: the address prefix used to survive verbatim.
    assert "Awolowo" not in redacted
    for d in dets:
        assert d.text not in redacted
    # One field per disjoint region, not one per detection.
    assert len(fields) == 2
    region = next(f for f in fields if f.category == "PII-4-ADDRESS")
    assert set(region.covers) == {"PII-4-ADDRESS", "PII-4-LOCATION"}


def test_overlapping_region_takes_the_most_restrictive_action():
    # ADDRESS generalises, LOCATION is retained. The container must not inherit
    # the laxer action just because it contains a laxer span.
    statute = load_statute("NDPA-2023")
    text = "Janet Okafor lives at 12 Awolowo Road, Ikoyi, Lagos."
    dets = [
        _det("PII-4-LOCATION", "Lagos", 46, 51),
        _det("PII-4-ADDRESS", "12 Awolowo Road, Ikoyi, Lagos", 22, 51),
    ]
    _, fields = _guard_ng()._project(text, dets, statute)
    assert len(fields) == 1
    assert fields[0].action == "generalize"


def test_overlapping_region_is_labelled_by_the_widest_member():
    # An address containing a name is still an address. Labelling the region
    # [NAME:…] would be equally safe and factually wrong.
    statute = load_statute("NDPA-2023")
    text = "at 12 Awolowo Road, Ikoyi, Lagos."
    dets = [
        _det("PII-4-ADDRESS", "12 Awolowo Road, Ikoyi, Lagos", 3, 32),
        _det("PII-4-LOCATION", "Lagos", 27, 32),
    ]
    redacted, fields = _guard_ng()._project(text, dets, statute)
    assert "[ADDRESS:" in redacted
    assert fields[0].category == "PII-4-ADDRESS"


def test_drop_inside_a_region_removes_the_whole_region():
    # `drop` is the most restrictive action, so a region containing a dropped
    # span is removed entirely rather than tokenised around it.
    statute = load_statute("NDPA-2023")
    text = "ref card 4111111111111111 end"
    dets = [
        _det("PII-4-ADDRESS", "card 4111111111111111", 4, 25),
        _det("PII-5-CARD", "4111111111111111", 9, 25),
    ]
    redacted, fields = _guard_ng()._project(text, dets, statute)
    assert "4111111111111111" not in redacted
    assert "card" not in redacted
    assert len(fields) == 1
    assert fields[0].action == "drop"
    assert fields[0].token is None


def test_identical_spans_collapse_to_one_region():
    statute = load_statute("NDPA-2023")
    text = "Fatima here"
    dets = [
        _det("PII-1-NAME", "Fatima", 0, 6),
        _det("PII-4-LOCATION", "Fatima", 0, 6),
    ]
    redacted, fields = _guard_ng()._project(text, dets, statute)
    assert "Fatima" not in redacted
    assert len(fields) == 1
    assert set(fields[0].covers) == {"PII-1-NAME", "PII-4-LOCATION"}


def test_end_to_end_address_does_not_leak_through_the_guard():
    # The bug as a user would hit it: real pipeline, real detectors, no mocks.
    guard = EgressGuard(
        Pipeline(jurisdiction="NG"), key="k" * 32, allowed_providers={"openai"}
    )
    text = "Janet Okafor lives at 12 Awolowo Road, Ikoyi, Lagos."
    result = Pipeline(jurisdiction="NG").process(text)
    projection = guard.guarded(text, provider="openai")
    for det in result.detections:
        if det.text:
            assert det.text not in projection.redacted_text
