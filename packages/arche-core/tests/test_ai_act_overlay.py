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

"""C1-T4: the EU AI Act overlay asserts document-level obligations, no per-PII action."""

from types import SimpleNamespace

from arche.policy.overlay import (
    apply_overlay,
    list_available_overlays,
    load_overlay,
)
from arche.workflow._primitive import Result


def _outcome(action: str) -> SimpleNamespace:
    return SimpleNamespace(action=action)


def _result(actions=(), audit=()) -> Result:
    return Result(
        document_hash="x",
        policy_outcomes=[_outcome(a) for a in actions],
        audit_log=list(audit),
        metadata={},
    )


def test_overlay_available_and_loads():
    assert "EU-AI-ACT" in list_available_overlays()
    ov = load_overlay("EU-AI-ACT")
    assert ov.overlay_id == "EU-AI-ACT"
    assert len(ov.obligations_spec) == 3


def test_all_obligations_satisfied_when_logged_disclosed_minimised():
    res = _result(actions=["mask", "drop", "tokenize"], audit=["evt"])
    res = apply_overlay(res, load_overlay("EU-AI-ACT"),
                        transparency_notice="This assistant uses AI.")
    block = res.metadata["ai_act"]
    assert block["all_satisfied"] is True
    arts = {o["article"] for o in block["obligations"]}
    assert "EU AI Act Art 12" in arts and "EU AI Act Art 50" in arts


def test_transparency_fails_without_notice():
    res = apply_overlay(_result(actions=["mask"], audit=["evt"]),
                        load_overlay("EU-AI-ACT"))  # no transparency_notice
    block = res.metadata["ai_act"]
    art50 = next(o for o in block["obligations"] if o["article"] == "EU AI Act Art 50")
    assert art50["satisfied"] is False
    assert block["all_satisfied"] is False


def test_minimisation_fails_when_field_retained():
    res = apply_overlay(_result(actions=["mask", "retain"], audit=["evt"]),
                        load_overlay("EU-AI-ACT"),
                        transparency_notice="AI in use.")
    block = res.metadata["ai_act"]
    minim = next(o for o in block["obligations"] if "minim" in o["name"].lower())
    assert minim["satisfied"] is False
    assert "retained in place" in minim["rationale"]


def test_minimisation_vacuous_when_no_pii():
    res = apply_overlay(_result(actions=[], audit=["evt"]),
                        load_overlay("EU-AI-ACT"),
                        transparency_notice="AI in use.")
    minim = next(o for o in res.metadata["ai_act"]["obligations"]
                 if "minim" in o["name"].lower())
    assert minim["satisfied"] is True
    assert "no personal data" in minim["rationale"]


def test_log_obligation_fails_with_no_record():
    res = apply_overlay(_result(actions=[], audit=()),
                        load_overlay("EU-AI-ACT"),
                        transparency_notice="AI in use.")
    art12 = next(o for o in res.metadata["ai_act"]["obligations"]
                 if o["article"] == "EU AI Act Art 12")
    assert art12["satisfied"] is False


def test_block_carries_honest_disclaimer():
    res = apply_overlay(_result(actions=["mask"], audit=["evt"]),
                        load_overlay("EU-AI-ACT"),
                        transparency_notice="AI in use.")
    assert "not a compliance certificate" in res.metadata["ai_act"]["disclaimer"]


def test_pipeline_result_can_be_overlaid_end_to_end():
    # A real Pipeline run, then overlaid.
    from arche.workflow._primitive import Pipeline

    res = Pipeline(statute="GDPR").process("Contact john@example.com for details.")
    res = apply_overlay(res, load_overlay("EU-AI-ACT"),
                        transparency_notice="AI-generated output.")
    assert "ai_act" in res.metadata
    assert res.metadata["ai_act"]["framework"].startswith("EU AI Act")
