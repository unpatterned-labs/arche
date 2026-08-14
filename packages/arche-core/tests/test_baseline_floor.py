# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for the jurisdiction-neutral baseline floor.

arche ships statute packs for seven regimes. Everywhere else — India, Brazil,
Indonesia, the US outside HIPAA, most of the world — `Pipeline` resolves no
statute, and a Pipeline with no statute returns `redacted_text` unchanged.

That is a trap the moment jurisdiction detection lands. It was measured on a
British bank statement before a UK pack existed: `jurisdiction="NG"` yielded 36
false TIN detections but did mask the email, while `jurisdiction="GB"` yielded
none and masked nothing. "Correcting" the jurisdiction would have taken the
headline false-positive count from 36 to zero *by switching protection off*.

GB is covered now (`UK-GDPR`), so these tests use India — the trap belongs to
every uncovered jurisdiction, not to that one document.

The floor is what makes that correction safe, and it is honest about what it is:
not law, cited as not law, in every reference it emits.
"""

from __future__ import annotations

import warnings

import pytest

from arche import Pipeline

_TEXT = "Contact Jane Smith at jane.smith@monzo.com or 07700 900123."

#: A jurisdiction with no pack. Shipping one for it must update these tests,
#: which is the point — the trap is coverage, not this particular country.
_UNCOVERED = "IN"


def _quietly(**kwargs) -> Pipeline:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return Pipeline(**kwargs)


class TestTheTrap:
    def test_an_uncovered_jurisdiction_protects_nothing_by_default(self):
        """Pinned. This is the behaviour the floor exists to fix."""
        result = _quietly(jurisdiction=_UNCOVERED).process(_TEXT)
        assert result.redacted_text == _TEXT

    def test_the_wrong_jurisdiction_does_protect(self):
        """Which is why a naive 'fix' looks like an improvement and is not."""
        result = _quietly(jurisdiction="NG").process(_TEXT)
        assert result.redacted_text != _TEXT

    def test_the_floor_closes_it(self):
        result = _quietly(jurisdiction=_UNCOVERED,
                          on_uncovered="baseline").process(_TEXT)
        assert result.redacted_text != _TEXT
        assert "jane.smith@monzo.com" not in result.redacted_text


class TestModes:
    def test_silent_is_the_default_so_no_caller_changes(self):
        """Existing output must not move because this shipped."""
        assert Pipeline(jurisdiction=_UNCOVERED).on_uncovered == "silent"
        assert Pipeline(jurisdiction=_UNCOVERED).statute_id is None

    def test_warn_names_the_jurisdiction_and_the_consequence(self):
        with pytest.warns(UserWarning,
                          match=f"no statute pack covers jurisdiction '{_UNCOVERED}'"):
            pipeline = Pipeline(jurisdiction=_UNCOVERED, on_uncovered="warn")
        assert pipeline.statute_id is None, "warn must not silently change behaviour"

    def test_baseline_warns_that_it_is_not_law(self):
        with pytest.warns(UserWarning, match="NOT the law of any country"):
            pipeline = Pipeline(jurisdiction=_UNCOVERED, on_uncovered="baseline")
        assert pipeline.statute_id == "BASELINE"

    def test_an_unknown_mode_raises(self):
        with pytest.raises(ValueError, match="on_uncovered must be"):
            Pipeline(jurisdiction=_UNCOVERED, on_uncovered="maybe")


class TestItNeverOverridesRealLaw:
    @pytest.mark.parametrize(("jurisdiction", "statute"), [
        ("NG", "NDPA-2023"), ("ZA", "POPIA"), ("KE", "KENYA-DPA"),
        ("GH", "GHANA-DPA"), ("DE", "GDPR"), ("FR", "GDPR"), ("GB", "UK-GDPR"),
    ])
    def test_a_covered_jurisdiction_keeps_its_pack(self, jurisdiction, statute):
        """The floor is a floor, not a replacement."""
        pipeline = _quietly(jurisdiction=jurisdiction, on_uncovered="baseline")
        assert pipeline.statute_id == statute
        assert pipeline.uncovered is False

    def test_an_explicit_statute_still_wins(self):
        pipeline = _quietly(jurisdiction="US", statute="HIPAA-SAFE-HARBOR",
                            on_uncovered="baseline")
        assert pipeline.statute_id == "HIPAA-SAFE-HARBOR"

    def test_no_jurisdiction_at_all_is_untouched(self):
        """A caller who names nothing is not opting into anything."""
        pipeline = Pipeline(on_uncovered="baseline")
        assert pipeline.statute_id is None
        assert pipeline.uncovered is False


class TestItSaysItIsNotLaw:
    """The floor's citations must never look like an instrument."""

    @pytest.fixture(scope="class")
    def statute(self):
        from arche.policy.engine import load_statute

        return load_statute("BASELINE")

    def test_every_mapping_disclaims_in_words(self, statute):
        mappings = getattr(statute, "policy_mappings", None) or statute["policy_mappings"]
        assert mappings, "the floor must map something"
        for category, entry in mappings.items():
            reference = (entry.get("statute_reference") if isinstance(entry, dict)
                         else getattr(entry, "statute_reference", ""))
            assert "not law" in reference or "baseline floor" in reference, (
                f"{category} cites {reference!r}, which reads like a statute"
            )

    def test_it_invents_no_rights_or_bases(self, statute):
        """Lawful bases and data-subject rights are creatures of statute.

        A floor that listed them would be asserting law that does not exist.
        """
        assert not (getattr(statute, "lawful_bases", None) or [])
        assert not (getattr(statute, "data_subject_rights", None) or [])

    def test_review_status_claims_nothing_external(self, statute):
        """`self-reviewed` is the weakest value the loader accepts, and true.

        No regulator, lawyer or external body has read these mappings.
        """
        assert getattr(statute, "review_status", "") == "self-reviewed"


class TestConservativeScope:
    """A floor that guessed at foreign identifiers would repeat the NG mistake."""

    @pytest.fixture(scope="class")
    def mappings(self):
        from arche.policy.engine import load_statute

        loaded = load_statute("BASELINE")
        return getattr(loaded, "policy_mappings", None) or loaded["policy_mappings"]

    @pytest.mark.parametrize("category", [
        "PII-2-BVN", "PII-2-NIN", "PII-2-TIN", "PII-2-SSN",
    ])
    def test_country_specific_identifiers_are_absent(self, mappings, category):
        assert category not in mappings

    @pytest.mark.parametrize("category", [
        "PII-3-EMAIL", "PII-3-PHONE", "PII-2-NATIONAL-ID", "PII-4-ADDRESS",
    ])
    def test_universally_agreed_categories_are_present(self, mappings, category):
        assert category in mappings

    def test_the_default_action_is_the_safe_direction(self, mappings):
        """Over-masking costs a reader context; under-masking discloses a person."""
        from arche.policy.engine import load_statute

        loaded = load_statute("BASELINE")
        assert getattr(loaded, "default_action", "") == "mask"


class TestCalibratedToGdprButNotGdpr:
    """The floor copies GDPR's severity and nothing else.

    Copying the strictest widely-adopted regime's *actions* is a defensible
    engineering default. Claiming to BE that regime is not: GDPR has its own
    territorial scope, and asserting its obligations where it does not apply
    invents duties rather than describing them.
    """

    @pytest.fixture(scope="class")
    def packs(self):
        from arche.policy.engine import load_statute

        baseline = load_statute("BASELINE")
        gdpr = load_statute("GDPR")
        return (getattr(baseline, "policy_mappings", {}),
                getattr(gdpr, "policy_mappings", {}))

    def test_shared_categories_take_gdprs_action(self, packs):
        baseline, gdpr = packs
        shared = [c for c in baseline if c in gdpr]
        assert shared, "the floor and GDPR must overlap for this to mean anything"
        for category in shared:
            assert baseline[category]["action"] == gdpr[category]["action"], (
                f"{category}: floor says {baseline[category]['action']}, "
                f"GDPR says {gdpr[category]['action']}"
            )

    def test_no_gdpr_citation_ever_leaks(self, packs):
        """The line between 'as strict as' and 'is'."""
        baseline, _ = packs
        for category, entry in baseline.items():
            reference = str(entry.get("statute_reference", ""))
            assert "GDPR" not in reference, f"{category} cites GDPR: {reference!r}"
            assert "Art " not in reference, f"{category} cites an Article: {reference!r}"

    def test_it_asserts_no_obligations_gdpr_would(self):
        """No breach window, no rights, no bases — those need an instrument."""
        from arche.policy.engine import load_statute

        loaded = load_statute("BASELINE")
        assert not getattr(loaded, "breach_notification_window_hours", None)
        assert not (getattr(loaded, "lawful_bases", None) or [])
        assert not (getattr(loaded, "data_subject_rights", None) or [])


class TestUnitedKingdom:
    """GB is the one new pack that is safe to ship, and it is not a GDPR copy."""

    @pytest.fixture(scope="class")
    def uk(self):
        from arche.policy.engine import load_statute

        return load_statute("UK-GDPR")

    def test_gb_now_resolves_a_statute(self):
        pipeline = Pipeline(jurisdiction="GB")
        assert pipeline.statute_id == "UK-GDPR"
        assert pipeline.uncovered is False

    def test_gb_actually_redacts(self):
        """The whole point: before this, GB protected nothing."""
        result = Pipeline(jurisdiction="GB").process(_TEXT)
        assert result.redacted_text != _TEXT
        assert "jane.smith@monzo.com" not in result.redacted_text

    def test_the_supervisory_authority_is_the_ico(self, uk):
        """Citing an EU authority for UK processing would be the wrong law."""
        assert "ICO" in getattr(uk, "authority", "")

    def test_transfers_use_uk_mechanisms(self, uk):
        """EU SCCs alone are not sufficient out of the UK — the Addendum is."""
        basis = getattr(uk, "cross_border_transfer", {}).get("permitted_basis", [])
        assert "international_data_transfer_agreement" in basis
        assert "uk_addendum_to_eu_sccs" in basis
        assert "standard_contractual_clauses" not in basis

    def test_penalties_are_in_sterling(self, uk):
        assert "GBP" in getattr(uk, "penalties", {}).get("major_violation", "")

    def test_it_does_not_claim_to_be_eu_gdpr(self, uk):
        assert getattr(uk, "statute_id", "") == "UK-GDPR"
        assert getattr(uk, "jurisdiction", "") == "GB"

    def test_it_carries_an_effective_date_because_the_regime_diverges(self, uk):
        """The Data (Use and Access) Act 2025 is amending this regime now."""
        assert getattr(uk, "effective_date", None) is not None


class TestNoOverclaimedPacks:
    """What was deliberately NOT shipped, and a test so it stays that way."""

    def test_there_is_no_generic_us_pack(self):
        """There is no comprehensive US federal privacy statute to encode.

        HIPAA ships as a *sectoral* pack, which is the correct model. A pack
        called "US" would look authoritative while being structurally
        incomplete — the exact overclaim this project keeps retracting.
        """
        assert "US" not in Pipeline._STATUTE_FOR_JURISDICTION

    def test_ca_is_not_silently_aliased_to_california(self):
        """ISO 3166-1 `CA` is Canada. Privacy readers often mean California.

        Guessing either way is worse than routing neither: Canada is PIPEDA
        plus materially different Quebec, Alberta and BC regimes, and
        California is CCPA/CPRA, a US state law. Neither ships yet, and
        neither may quietly borrow the other's code.
        """
        assert "CA" not in Pipeline._STATUTE_FOR_JURISDICTION
