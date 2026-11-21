# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Special-category content: cue-anchored, precision first."""

from __future__ import annotations

import pytest
from arche.detect.special import detect_special_categories


def _found(text: str) -> list[tuple[str, str]]:
    return [(d.category, d.text) for d in detect_special_categories(text)]


@pytest.mark.parametrize(("text", "expected"), [
    ("Referral: Mrs Eleanor Whitcombe. Dx: type 2 diabetes and depression. Seen by Dr Okafor.",
     [("PII-6-HEALTH", "type 2 diabetes"), ("PII-6-HEALTH", "depression")]),
    ("Pt: Jane Doe, MRN 00482913. Dx schizophrenia. Attending NPI 1928374655.",
     [("PII-6-HEALTH", "schizophrenia")]),
    ("Discharge: Pieter van der Merwe, admitted 03/09/2026 with HIV. Bed Ward 7B-12.",
     [("PII-6-HEALTH", "HIV")]),
    ("Patient Sipho Dlamini (ID 7508300161085) presents with TB and HIV. Lives in Umlazi.",
     [("PII-6-HEALTH", "TB"), ("PII-6-HEALTH", "HIV")]),
    ("Pt Oluwaseun Adeyemi, 34F, sickle cell disease, HIV positive. Husband Babatunde.",
     [("PII-6-HEALTH", "sickle cell disease"), ("PII-6-HEALTH", "HIV positive")]),
    ("Mr K, 54M, PMH: hypertension, CKD stage 3; on ARVs since 2019.",
     [("PII-6-HEALTH", "hypertension"), ("PII-6-HEALTH", "CKD stage 3"),
      ("PII-6-HEALTH", "ARVs")]),
    ("Medications: metformin 500mg bd, sertraline 50 mg. Allergies: none.",
     [("PII-6-HEALTH", "metformin 500mg bd"), ("PII-6-HEALTH", "sertraline 50 mg")]),
    ("She was diagnosed with bipolar disorder in 2015.",
     [("PII-6-HEALTH", "bipolar disorder")]),
    ("Family history of breast cancer.", [("PII-6-HEALTH", "breast cancer")]),
    ("HIV status: negative.", [("PII-6-HEALTH", "negative")]),
    ("Race: Black African (EE report). Religion: Methodist.",
     [("PII-6-RACE", "Black African"), ("PII-6-RELIGION", "Methodist")]),
    ("Ethnicity: Igbo. Sexual orientation: bisexual.",
     [("PII-6-RACE", "Igbo"), ("PII-6-SEXUAL_ORIENTATION", "bisexual")]),
    ("She is a devout Muslim. He came out as gay. She converted to Islam.",
     [("PII-6-RELIGION", "Muslim"), ("PII-6-SEXUAL_ORIENTATION", "gay"),
      ("PII-6-RELIGION", "Islam")]),
    ("He is a member of the Labour Party and a member of the National Union of Mineworkers.",
     [("PII-6-POLITICAL_AFFILIATION", "Labour Party"),
      ("PII-6-TRADE_UNION", "National Union of Mineworkers")]),
    ("COSATU shop steward. Trade union membership: Unite.",
     [("PII-6-TRADE_UNION", "COSATU"), ("PII-6-TRADE_UNION", "Unite")]),
])
def test_cue_anchored_values(text: str, expected: list[tuple[str, str]]) -> None:
    assert _found(text) == expected


@pytest.mark.parametrize("text", [
    "Thanks for the positive feedback on the launch.",
    "The union of sets A and B is commutative.",
    "He lives on Christian Street, Leeds.",
    "The party arrived at 9 and the music started.",
    "We bought a 2 TB drive for his laptop.",
    "The Great Depression changed the economy.",
    "She is a Christian school teacher.",
    "Race: 5k fun run on Saturday.",
    "He admitted with regret that the plan failed.",
    "The report presents with clarity the case for change.",
    "His history of fraud is well known.",
    "Pass condition: one of them asks what it would cost.",
    "He is a member of the European Union delegation.",
    "Allergies: none. Medications: nil.",
    "The HIV programme budget rose by 4% this year.",
])
def test_ordinary_words_are_not_special_categories(text: str) -> None:
    assert _found(text) == []


def test_label_is_not_part_of_the_span_and_metadata_names_the_cue() -> None:
    text = "Religion: Methodist"
    [d] = detect_special_categories(text)
    assert text[:d.start] == "Religion: "
    assert d.metadata == {"kind": "religion", "cue": "religion", "rule": "cue"}
    assert d.detector == "rule:special_cue"


def test_standalone_terms_need_a_person_in_the_sentence() -> None:
    assert _found("HIV positive.") == []
    assert _found("The patient is HIV positive.") == [("PII-6-HEALTH", "HIV positive")]
    [d] = detect_special_categories("The patient is HIV positive.")
    assert d.metadata["rule"] == "standalone"
