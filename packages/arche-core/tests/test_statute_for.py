# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Which law governs a jurisdiction, and what to say when none does.

`arche.jurisdictions.infer` can name a country with confidence 1.0 that no
statute pack covers. What happened next was a refusal reading *"no statute
configured on the pipeline"*, which describes arche's internal state rather
than the caller's situation, and reads as a bug. An agent following the
detect-jurisdiction flow hit that wall on any US or EU document.

Two different problems wore the same message, and separating them is the fix:

**EU was a missing row.** `GDPR.yaml` ships and `"EU"` mapped to nothing,
because `"EU"` is an ISO 3166-1 exceptional reservation rather than an alpha-2
country code and so never arrived with the member states. The inferrer emits it
from a VAT number or a euro amount.

**US is a fact about the world.** The United States has no omnibus federal
privacy statute. There is nothing to pack. The right behaviour is still to
refuse, but to say why and offer the sectoral alternative.
"""

from __future__ import annotations

import warnings

import pytest
from arche import Pipeline
from arche.guard import EgressGuard, GuardDenied
from arche.jurisdictions.infer import _SIGNALS, infer_jurisdiction
from arche.policy import STATUTE_FOR_JURISDICTION, statute_for


class TestEveryInferableCountryIsAnswerable:
    """The contract that keeps the flow from dead-ending again.

    The inferrer's output vocabulary must not outrun the policy layer's input
    vocabulary. Not every country needs a pack — most cannot have one — but
    every country the inferrer can name must get an *answer*, and an answer is
    either a statute or a reason.
    """

    INFERABLE = sorted({country for _n, _t, country, _p in _SIGNALS})

    def test_the_inferrer_emits_exactly_the_countries_we_think(self):
        """Pinned, so adding a signal for a new country fails here first and
        forces a decision about what governs it."""
        assert self.INFERABLE == ["DE", "EU", "GB", "KE", "NG", "US", "ZA"]

    @pytest.mark.parametrize("code", INFERABLE)
    def test_every_one_gets_an_answer(self, code):
        choice = statute_for(code)
        assert choice.statute_id or choice.reason, code

    @pytest.mark.parametrize("code", INFERABLE)
    def test_an_unavailable_one_always_offers_an_alternative(self, code):
        """A refusal with no way forward is a wall. Every unpoliced
        jurisdiction names something the caller can pass explicitly."""
        choice = statute_for(code)
        assert choice.available or choice.alternatives, code


class TestTheMissingRow:

    def test_eu_now_maps_to_gdpr(self):
        assert statute_for("EU").statute_id == "GDPR"

    def test_it_is_in_the_shared_table(self):
        assert STATUTE_FOR_JURISDICTION["EU"] == "GDPR"

    def test_a_member_state_still_maps_to_gdpr(self):
        """The row was added beside the member states, not instead of them."""
        assert statute_for("DE").statute_id == "GDPR"

    def test_an_eu_document_now_gets_through_the_guard(self):
        """The end-to-end case. It used to infer EU at confidence 1.0 and then
        be refused for having no statute."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            inferred = infer_jurisdiction("VAT DE123456789, total 1.250,00 EUR")
            assert inferred.country == "EU"
            projection = EgressGuard(
                Pipeline(jurisdiction=inferred.country), key="k",
            ).guarded("VAT DE123456789, total 1.250,00 EUR")
        assert projection.metadata["statute_id"] == "GDPR"


class TestTheFactAboutTheWorld:
    """US stays refused. Only the explanation changes."""

    def test_it_is_still_unavailable(self):
        assert statute_for("US").available is False
        assert statute_for("US").statute_id is None

    def test_the_reason_is_about_us_law_not_about_arche(self):
        reason = statute_for("US").reason
        assert "no omnibus federal privacy statute" in reason
        assert "a fact about US law rather than a gap in arche" in reason

    def test_it_offers_the_sectoral_pack_first(self):
        """HIPAA covers health and nothing else, so it is an alternative rather
        than an answer — but it is the one a US health caller wants."""
        assert statute_for("US").alternatives[0] == "HIPAA-SAFE-HARBOR"

    def test_the_guard_refusal_carries_the_reason(self):
        guard = EgressGuard(Pipeline(jurisdiction="US"), key="k")
        with pytest.raises(GuardDenied, match="no omnibus federal privacy"):
            guard.guarded("SSN 123-45-6789")

    def test_and_points_at_the_escape_hatch(self):
        try:
            EgressGuard(Pipeline(jurisdiction="US"), key="k").guarded("x")
        except GuardDenied as exc:
            assert "HIPAA-SAFE-HARBOR" in str(exc)

    def test_passing_a_statute_explicitly_works(self):
        """The escape hatch the message advertises has to actually exist."""
        pipeline = Pipeline(jurisdiction="US", statute="BASELINE")
        assert pipeline._ensure_statute().statute_id == "BASELINE"


class TestTheEdges:

    def test_no_jurisdiction_is_not_an_error(self):
        choice = statute_for(None)
        assert choice.available is False
        assert "no jurisdiction given" in choice.reason

    def test_an_unknown_code_gets_a_generic_reason_rather_than_a_crash(self):
        assert "ZZ" in statute_for("ZZ").reason

    def test_lowercase_is_accepted(self):
        assert statute_for("ng").statute_id == "NDPA-2023"

    def test_the_pipeline_reads_the_same_table(self):
        """One copy. Two would drift, and the drift would be silent."""
        assert Pipeline._STATUTE_FOR_JURISDICTION is STATUTE_FOR_JURISDICTION

    def test_it_serialises_for_a_tool_response(self):
        """arche-mcp returns this over the wire, so it has to be plain data."""
        import json
        json.dumps(statute_for("US").as_dict())
