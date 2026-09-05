# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The shipped name lexicon: what it finds, what it must not, and where it loads from."""

from __future__ import annotations

import subprocess
import sys

from arche.detect.names import detect_names, person_spans
from arche.extract import extract


def _names(text: str) -> list[str]:
    return [d.text for d in detect_names(text)]


class TestWhatItFinds:
    def test_a_nigerian_name_the_starter_set_lacked(self):
        assert _names("Adaeze Okonkwo lives here.") == ["Adaeze", "Okonkwo"]
        assert person_spans("Adaeze Okonkwo lives here.") == [(0, 14, "Adaeze Okonkwo")]

    def test_an_initial_between_two_names_joins_the_span(self):
        spans = person_spans("Adesola E. Okonkwo, NIN 12345678901")
        assert spans == [(0, 18, "Adesola E. Okonkwo")]

    def test_virtue_names_are_kept_on_purpose(self):
        """Grace, Patience and Mercy are among the commonest given names in
        Nigeria and Ghana. They are also English words; the region wins."""
        found = _names("Grace Okonkwo and Patience Mensah met Mercy Adeyemi.")
        assert {"Grace", "Patience", "Mercy"} <= set(found)

    def test_names_travel_so_jane_smith_is_found(self):
        """The lexicon is drawn from people recorded in African countries, and
        Anglo names are common there. The names pack is no longer 'African-only';
        see test_calibration for the negative that replaced Jane Smith."""
        assert person_spans("Jane Smith lives in Manchester.") == [(0, 10, "Jane Smith")]


class TestWhatItMustNot:
    def test_function_words_capitalised_at_a_sentence_start_are_not_names(self):
        assert _names("The weather in the capital was mild on Tuesday.") == []

    def test_months_weekdays_and_modal_verbs_are_not_names(self):
        assert _names("May I introduce Will? We met on Monday in June.") == []

    def test_wikidata_label_noise_does_not_leak(self):
        """'Ebor, New South Wales' and 'Michael the Archangel' are in the export;
        their words are not names."""
        assert _names("New South Wales is the first general secretary.") == []

    def test_a_scandinavian_name_is_not_in_it(self):
        assert _names("Björn Svensson lives in Manchester.") == []

    def test_one_lone_token_is_not_a_person_span(self):
        assert person_spans("Grace was here.") == []


class TestWhereItFeeds:
    def test_the_regex_extractor_emits_a_person(self):
        text = "Adesola E. Okonkwo, NIN 12345678901, adesola@gmail.com"
        found = extract(text, backend="regex")
        kinds = {e.entity_type: e.text for e in found}
        assert kinds["PERSON"] == "Adesola E. Okonkwo"
        assert kinds["NATIONAL_ID"] == "12345678901"

    def test_a_text_record_now_carries_a_name(self):
        from arche import compare

        receipt = compare(
            "Adesola Okonkwo, NIN 12345678901, adesola@example.com",
            "Adesola Okonkwo, NIN 12345678901, adesola@gmail.com",
            entity="person", jurisdiction="NG", backend="regex",
        )
        assert receipt.factors["name"] == 1.0
        assert (receipt.identity, receipt.action) == ("same_entity", "merge")
        record = receipt.reference_a.as_record(include_restricted=True)
        assert record["full_name"] == "Adesola Okonkwo"

    def test_the_lexicon_loads_from_any_working_directory(self, tmp_path):
        """The loader used to look under the cwd and three fixed ancestor depths,
        so the same detection passed from the repository root and failed from
        packages/arche-core. It now walks every ancestor and falls back to the
        copy inside the wheel."""
        code = (
            "from arche.detect.names import detect_names; "
            "found = [d.text for d in detect_names('Adaeze Okonkwo lives here.')]; "
            "assert found == ['Adaeze', 'Okonkwo'], found"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=tmp_path, check=False, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
