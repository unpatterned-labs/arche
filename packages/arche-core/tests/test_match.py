# Copyright 2026 unpatterned.org
# Tests for the Level 2 match() API and Fellegi-Sunter matcher.


from arche.resolve._matcher import (
    IdentityMatcher,
    MatchScore,
    compare_addresses,
    compare_emails,
    compare_geo,
    compare_ids,
    compare_names,
    compare_phones,
    get_priors,
    load_type_vocab,
    match,
    normalize_type_token,
    to_match_record,
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

    # --- Component-aware behaviour (the "moat fix") ---
    def test_address_same_city_different_street_is_weak(self):
        # Raw string similarity over-matches on a shared "Cape Town"; the
        # component comparison sees the streets differ and scores it low.
        score = compare_addresses(
            "12 Long Street, Cape Town", "99 Main Road, Cape Town"
        )
        assert score < 0.50

    def test_address_house_number_distinguishes(self):
        # Same street, different house number: similar but not identical.
        score = compare_addresses(
            "7B Allen Avenue, Ikeja, Lagos", "9B Allen Avenue, Ikeja, Lagos"
        )
        assert 0.50 < score < 0.90
        # ...and strictly below the identical-address score.
        same = compare_addresses(
            "7B Allen Avenue, Ikeja, Lagos", "7B Allen Avenue, Ikeja, Lagos"
        )
        assert score < same

    def test_landmark_anchor_match(self):
        # Landmark-only addresses (no street/postcode) match on the anchor
        # even when the relation word differs ("behind" vs "opposite").
        score = compare_addresses(
            "behind the Total filling station, Madina, Accra",
            "opposite the Total filling station, Madina, Accra",
        )
        assert score >= 0.80

    def test_landmark_anchor_different(self):
        score = compare_addresses(
            "behind the Total filling station, Accra",
            "near the First Bank, Accra",
        )
        assert score < 0.60

    # --- Code-mixed landmarks + structured input ---
    def test_address_codemixed_landmark_match(self):
        # A Swahili relation word ("nyuma ya") and an English one describe the
        # same landmark; normalize_landmark strips both so they still match.
        score = compare_addresses(
            "nyuma ya Total filling station, Accra",
            "behind the Total filling station, Accra",
        )
        assert score >= 0.80

    def test_address_codemixed_different_landmark(self):
        score = compare_addresses(
            "nyuma ya Total filling station, Accra",
            "behind the First Bank, Accra",
        )
        assert score < 0.80

    def test_address_structured_dict_input(self):
        # A caller can pass the address the pipeline already parsed (anchor
        # included) instead of a flattened string.
        a = {
            "text": "behind the Total filling station, Madina, Accra",
            "anchor": "behind the Total filling station",
            "city": "Accra",
            "neighborhood": "Madina",
        }
        b = {
            "text": "opposite the Total filling station, Accra",
            "anchor": "opposite the Total filling station",
            "city": "Accra",
        }
        assert compare_addresses(a, b) >= 0.80

    def test_address_structured_dict_different_street(self):
        a = {"street": "Long Street", "street_number": "12", "city": "Cape Town"}
        b = {"street": "Main Road", "street_number": "99", "city": "Cape Town"}
        assert compare_addresses(a, b) < 0.50


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

    def test_dict_records_with_structured_address(self):
        # Records may carry the pipeline-parsed address (with anchor) directly.
        a = {"name": "Kofi Mensah",
             "address": {"anchor": "behind the Total filling station", "city": "Accra"}}
        b = {"name": "Kofi Mensah",
             "address": {"anchor": "opposite the Total filling station", "city": "Accra"}}
        score = match(a, b, jurisdiction="GH")
        assert score.decision == "match"
        assert score.factors.get("address") is not None

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


class TestToMatchRecord:
    """to_match_record() bridges pipeline detections into a match() record."""

    _TEXT_A = (
        "Fatima Abdullahi, NIN 12345678901, "
        "behind the Total filling station, Ikeja, Lagos"
    )
    _TEXT_B = (
        "F. Abdullahi, NIN 12345678901, "
        "opposite the Total filling station, Ikeja, Lagos"
    )

    def test_builds_record_with_structured_address(self):
        from arche import Pipeline

        result = Pipeline(jurisdiction="NG").process(self._TEXT_A)
        rec = to_match_record(result)
        assert rec.get("name")
        assert rec.get("national_id")
        # Address is structured (not a flat string) and keeps the anchor.
        assert isinstance(rec.get("address"), dict)
        assert rec["address"].get("anchor")

    def test_record_feeds_match(self):
        from arche import Pipeline

        a = to_match_record(Pipeline(jurisdiction="NG").process(self._TEXT_A))
        b = to_match_record(Pipeline(jurisdiction="NG").process(self._TEXT_B))
        assert match(a, b, jurisdiction="NG").decision == "match"

    def test_accepts_detection_list_and_empty(self):
        from arche import Pipeline

        result = Pipeline(jurisdiction="NG").process(self._TEXT_A)
        # A bare list of detections works the same as passing the Result.
        assert to_match_record(result.detections) == to_match_record(result)
        assert to_match_record([]) == {}


class TestCompareGeo:
    def test_same_point(self):
        assert compare_geo(11.99, 8.55, 11.99, 8.55) == 1.0

    def test_close_points_high(self):
        # ~0.3 km apart → high similarity
        assert compare_geo(11.990, 8.55, 11.9927, 8.55) >= 0.75

    def test_far_points_low(self):
        # ~3 km apart → low similarity
        assert compare_geo(11.99, 8.55, 12.017, 8.55) < 0.30

    def test_tighter_decay_penalises_more(self):
        d = compare_geo(0.0, 0.0, 0.0, 0.02, decay_km=1.5)
        tight = compare_geo(0.0, 0.0, 0.0, 0.02, decay_km=0.5)
        assert tight < d


class TestNormalizeTypeToken:
    VOCAB = {
        "primary health centre": "PHC",
        "primary health center": "PHC",
        "phc": "PHC",
        "dispensary": "DISPENSARY",
        "teaching hospital": "HOSPITAL",
        "health clinic": "CLINIC",
    }

    def test_strips_type_leaves_name(self):
        assert normalize_type_token("Karfi Health Clinic", self.VOCAB) == ("CLINIC", "karfi")

    def test_longest_synonym_wins(self):
        canon, residual = normalize_type_token(
            "Darmanawa Primary Health Centre", self.VOCAB
        )
        assert canon == "PHC"
        assert residual == "darmanawa"

    def test_no_match_returns_none_and_normalised_text(self):
        canon, residual = normalize_type_token("Some Random Place", self.VOCAB)
        assert canon is None
        assert residual == "some random place"


class TestFacilityMatch:
    """The two generic helpers together resolve a facility spelling-variant +
    geo pair — the hard-residue case the health-facility spike targets."""

    def test_spelling_variant_plus_geo_matches(self):
        vocab = {"teaching hospital": "HOSPITAL"}
        _, a = normalize_type_token("Aminu Kano Teaching Hospital", vocab)
        _, b = normalize_type_token("Amino Kanu Teaching Hospital", vocab)
        m = IdentityMatcher("NG")
        score = m.compare_fields(
            name_a=a, name_b=b, geo_a=(11.9767, 8.5942), geo_b=(11.9750, 8.5960)
        )
        assert score.decision == "match"
        assert "geo" in score.factors and "name" in score.factors

    def test_geo_distance_lowers_score(self):
        # Same name, but far-apart coordinates pull the score down.
        m = IdentityMatcher("NG")
        near = m.compare_fields(
            name_a="darmanawa", name_b="darmanawa",
            geo_a=(11.99, 8.55), geo_b=(11.9927, 8.55),
        )
        far = m.compare_fields(
            name_a="darmanawa", name_b="darmanawa",
            geo_a=(11.99, 8.55), geo_b=(12.05, 8.55),
        )
        assert far.score < near.score


class TestLoadTypeVocab:
    def test_health_facility_domain_loads(self):
        v = load_type_vocab("health_facility")
        assert v.get("dispensary") == "DISPENSARY"
        assert v.get("primary health center") == "PHC"
        assert v.get("teaching hospital") == "HOSPITAL"

    def test_normalizes_real_facility_names(self):
        v = load_type_vocab("health_facility")
        assert normalize_type_token("Darmanawa Primary Health Center", v) == ("PHC", "darmanawa")
        # A mislabelled OSM "chemist" is classified as PHARMACY.
        assert normalize_type_token("RAHAMA CHEMIST", v) == ("PHARMACY", "rahama")

    def test_second_domain_organization(self):
        v = load_type_vocab("organization")
        assert normalize_type_token("Kaduna Cocoa Cooperative Society", v)[0] == "COOPERATIVE"
        assert normalize_type_token("Dangote Cement PLC", v)[0] == "LTD"

    def test_unknown_domain_returns_empty(self):
        assert load_type_vocab("does_not_exist") == {}

    def test_cached(self):
        assert load_type_vocab("health_facility") is load_type_vocab("health_facility")
