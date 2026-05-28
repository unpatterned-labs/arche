# Copyright 2026 unpatterned.org
# Tests for the Level 2 match() API and Fellegi-Sunter matcher.

import pytest

from arche.resolve._matcher import (
    IdentityMatcher,
    JurisdictionPriors,
    MatchScore,
    compare_addresses,
    compare_emails,
    compare_ids,
    compare_names,
    compare_phones,
    get_priors,
    match,
)


class TestMatchScore:
    def test_repr(self):
        s = MatchScore(score=0.95, decision="match")
        assert "0.9500" in repr(s)
        assert "match" in repr(s)

    def test_float_conversion(self):
        s = MatchScore(score=0.85, decision="match")
        assert float(s) == 0.85


class TestCompareFunctions:
    """Test individual comparison functions."""

    # --- Names ---
    def test_name_exact(self):
        sim, u = compare_names("John Smith", "John Smith")
        assert sim == 1.0

    def test_name_fuzzy(self):
        sim, u = compare_names("John Smith", "J. Smith")
        assert sim >= 0.70

    def test_name_cultural_equivalence(self):
        sim, u = compare_names("Mamadou Diallo", "Mohamed Diallo")
        assert sim >= 0.80

    def test_name_unrelated(self):
        sim, u = compare_names("Alice Johnson", "Bob Williams")
        assert sim < 0.50

    def test_name_empty(self):
        sim, u = compare_names("", "John")
        assert sim == 0.0

    # --- Phones ---
    def test_phone_exact(self):
        assert compare_phones("+234 801 234 5678", "+234 801 234 5678") == 1.0

    def test_phone_normalised(self):
        assert compare_phones("+234-801-234-5678", "+2348012345678") == 1.0

    def test_phone_country_code_vs_local(self):
        assert compare_phones("+2348012345678", "08012345678") == 1.0

    def test_phone_different(self):
        assert compare_phones("+2348012345678", "+2348099999999") == 0.0

    def test_phone_empty(self):
        assert compare_phones("", "+2348012345678") == 0.0

    # --- National IDs ---
    def test_id_exact(self):
        assert compare_ids("12345678901", "12345678901") == 1.0

    def test_id_with_formatting(self):
        assert compare_ids("123-456-78901", "12345678901") == 1.0

    def test_id_different(self):
        assert compare_ids("12345678901", "99999999999") == 0.0

    # --- Emails ---
    def test_email_exact(self):
        assert compare_emails("user@example.com", "user@example.com") == 1.0

    def test_email_case_insensitive(self):
        assert compare_emails("User@Example.com", "user@example.com") == 1.0

    def test_email_different(self):
        assert compare_emails("a@test.com", "b@test.com") == 0.0

    # --- Addresses ---
    def test_address_exact(self):
        assert compare_addresses("14 Rue de Rivoli, Paris", "14 Rue de Rivoli, Paris") == 1.0

    def test_address_reordered(self):
        score = compare_addresses("Lagos, Ikeja", "Ikeja, Lagos")
        assert score >= 0.80

    def test_address_similar(self):
        score = compare_addresses("Allen Avenue, Ikeja", "Allen Ave, Ikeja Lagos")
        assert score >= 0.60

    def test_address_different(self):
        score = compare_addresses("Paris, France", "Tokyo, Japan")
        assert score < 0.60


class TestJurisdictionPriors:
    def test_default_priors_exist(self):
        priors = get_priors()
        assert priors.name == "default"
        assert 0 < priors.name_m < 1
        assert 0 < priors.name_u < 1

    def test_nigeria_priors(self):
        priors = get_priors("NG")
        assert priors.name == "Nigeria"
        assert priors.common_name_u.get("mohammed", 0) > 0.05

    def test_ghana_priors(self):
        priors = get_priors("GH")
        assert priors.name == "Ghana"
        assert "kwame" in priors.common_name_u

    def test_unknown_jurisdiction_falls_back(self):
        priors = get_priors("XX")
        assert priors.name == "default"


class TestIdentityMatcher:
    def test_name_only_match(self):
        m = IdentityMatcher("default")
        score = m.compare_fields(name_a="Jean Dupont", name_b="J. Dupont")
        assert score.score >= 0.60
        assert "name" in score.factors

    def test_multi_field_match(self):
        m = IdentityMatcher("NG")
        score = m.compare_fields(
            name_a="Fatima Abdullahi",
            name_b="F. Abdullahi",
            phone_a="+2348035557890",
            phone_b="08035557890",
        )
        assert score.decision == "match"
        assert score.score >= 0.90
        assert "phone match" in score.explanation

    def test_id_match_is_strong(self):
        m = IdentityMatcher()
        score = m.compare_fields(
            name_a="Person A",
            name_b="Person B",
            national_id_a="12345678901",
            national_id_b="12345678901",
        )
        # ID match should dominate even with name mismatch
        assert score.score >= 0.80

    def test_no_fields_gives_low_score(self):
        m = IdentityMatcher()
        score = m.compare_fields()
        assert score.score <= 0.50


class TestMatch:
    """Test the top-level match() function."""

    def test_string_names(self):
        score = match("John Smith", "J. Smith")
        assert isinstance(score, MatchScore)
        assert score.score > 0.60

    def test_string_phones(self):
        score = match("+234 801 234 5678", "08012345678", entity_type="phone")
        assert score.decision == "match"

    def test_string_ids(self):
        score = match("12345678901", "12345678901", entity_type="national_id")
        assert score.decision == "match"

    def test_dict_records(self):
        score = match(
            {"name": "Alice", "phone": "+1234567890"},
            {"name": "Alice", "phone": "+1234567890"},
        )
        assert score.decision == "match"

    def test_entity_objects(self):
        from arche.extract import Entity

        a = Entity(text="John", entity_type="PERSON", confidence=0.9, start=0, end=4)
        b = Entity(text="John", entity_type="PERSON", confidence=0.9, start=0, end=4)
        score = match(a, b)
        assert score.decision == "match"

    def test_jurisdiction_affects_score(self):
        # Common name "Mohammed" in Nigeria has higher u-probability
        score_ng = match("Mohammed", "Mohammed", jurisdiction="NG")
        score_fr = match("Mohammed", "Mohammed", jurisdiction="FR")
        # Both should match, but FR should have higher confidence
        # because Mohammed is less common there
        assert score_ng.decision == "match"
        assert score_fr.decision == "match"
        assert score_fr.score > score_ng.score

    def test_no_match(self):
        score = match("Alice Johnson", "Bob Williams")
        assert score.decision in ("no_match", "review")
        assert score.score < 0.80
