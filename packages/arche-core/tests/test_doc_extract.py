# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for schema-driven extraction.

The design claim: a document in, a *validated* object out, with the evidence
for every field kept rather than discarded. Most extractors return a dict of
values, which throws away the only thing that makes a value defensible — where
it came from, and whether it was validated or guessed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import pytest
from pydantic import BaseModel, Field

from arche.doc import DOC_FEATURE_AVAILABLE
from arche.doc._extract import Extraction, FieldEvidence, From, extract

_BENCH = Path(__file__).resolve().parents[3] / "data" / "doc_bench"

_TEXT = (
    "INVOICE from Netlify, Inc.\n"
    "Bill to: Amara Nwosu\n"
    "Contact amara@example.com or 0803 555 7890.\n"
    "Total: $412.00\n"
)


class Contact(BaseModel):
    email: str = Field(description="contact email address")
    phone: str = Field(description="contact phone number")


class TestTheBasicPromise:
    def test_a_validated_instance_comes_back(self):
        result = extract(Contact, text=_TEXT)
        assert isinstance(result.data, Contact)
        assert "@" in result.data.email

    def test_it_is_not_a_dict(self):
        """The difference from every extractor that hands back `dict[str, object]`."""
        result = extract(Contact, text=_TEXT)
        assert result.data.__class__ is Contact
        assert result.schema_name == "Contact"

    def test_truthiness_tracks_validation(self):
        assert bool(extract(Contact, text=_TEXT))


class TestEvidence:
    def test_every_filled_field_says_where_it_came_from(self):
        result = extract(Contact, text=_TEXT)
        assert set(result.fields) == {"email", "phone"}
        for name, evidence in result.fields.items():
            assert evidence.source in ("detector", "metadata", "extractor", "llm")
            assert isinstance(evidence, FieldEvidence)

    def test_a_detector_hit_carries_its_span(self):
        """So a reviewer can go and look at the text that produced it."""
        result = extract(Contact, text=_TEXT)
        email = result.fields["email"]
        assert email.source == "detector"
        assert email.span is not None
        start, end = email.span
        assert _TEXT[start:end] == email.value

    def test_structure_validated_evidence_outranks_a_model_guess(self):
        """Detectors are consulted before the entity extractor, always.

        Collapsing that order is how a pattern-matched 'identifier' that is
        really a formatting coincidence ends up treated as proof.
        """
        result = extract(Contact, text=_TEXT)
        assert result.fields["email"].source == "detector"


class TestUnresolved:
    def test_a_field_that_cannot_be_filled_is_named(self):
        """Not silently defaulted, not invented."""

        class Wants(BaseModel):
            email: str
            passport: str = ""

        result = extract(Wants, text="Contact amara@example.com.")
        assert "passport" in result.unresolved
        assert "passport" not in result.fields

    def test_evidence_survives_a_failed_validation(self):
        """A schema that did not validate is still a record of what was found."""

        class Demanding(BaseModel):
            email: str
            national_id: str  # required, and absent from the text

        result = extract(Demanding, text="Contact amara@example.com.")
        assert result.data is None
        assert result.errors, "a failure must say why"
        assert "email" in result.fields, "found evidence must not be thrown away"

    def test_an_extractor_that_never_abstains_would_be_unfalsifiable(self):
        """Pins the intent of `unresolved` existing at all."""

        class Impossible(BaseModel):
            wingspan: str = ""

        result = extract(Impossible, text="Contact amara@example.com.")
        assert result.unresolved == ["wingspan"]


class TestExplicitBinding:
    def test_from_overrides_the_automatic_mapping(self):
        class Bound(BaseModel):
            anything: Annotated[str, From("detector:EMAIL")]

        result = extract(Bound, text=_TEXT)
        assert result.fields["anything"].source == "detector"
        assert "@" in result.data.anything

    def test_from_parses_its_spec(self):
        binding = From("metadata:author")
        assert (binding.source, binding.key) == ("metadata", "author")


class TestFieldNameMapping:
    @pytest.mark.parametrize("field_name", ["email", "billing_email", "billingEmail"])
    def test_naming_variants_reach_the_same_source(self, field_name):
        model = type("M", (BaseModel,), {
            "__annotations__": {field_name: str},
        })
        result = extract(model, text=_TEXT)
        assert result.fields[field_name].source == "detector"

    def test_the_description_is_used_when_the_name_is_opaque(self):
        class Opaque(BaseModel):
            f1: str = Field(description="contact email")

        result = extract(Opaque, text=_TEXT)
        assert "@" in result.fields["f1"].value


class TestBackends:
    def test_local_is_the_default_and_needs_nothing(self):
        """No key, no account, no network."""
        assert extract(Contact, text=_TEXT).data is not None

    def test_an_unknown_backend_raises(self):
        with pytest.raises(ValueError, match="unknown extract backend"):
            extract(Contact, text=_TEXT, backend="magic")

    def test_the_llm_only_sees_fields_nothing_else_could_fill(self):
        """It must not be able to overwrite validated evidence with a guess."""
        offered = {}

        def fake_llm(*, text, fields):
            offered.update(fields)
            return {"passport": "X1234567"}

        class Mixed(BaseModel):
            email: str
            passport: str

        result = extract(Mixed, text=_TEXT, backend="llm", llm=fake_llm)
        assert "email" not in offered, "a detector already answered this"
        assert "passport" in offered
        assert result.fields["email"].source == "detector"
        assert result.fields["passport"].source == "llm"

    def test_a_model_failure_does_not_fail_extraction(self):
        def broken_llm(*, text, fields):
            raise RuntimeError("upstream is down")

        class Mixed(BaseModel):
            email: str
            passport: str = ""

        result = extract(Mixed, text=_TEXT, backend="llm", llm=broken_llm)
        assert result.fields["email"].source == "detector"


class TestExport:
    def test_masked_by_default(self):
        result = extract(Contact, text=_TEXT)
        exported = result.to_dict()
        assert "amara@example.com" not in str(exported["data"])
        assert "amara@example.com" in str(result.to_dict(reveal=True)["data"])

    def test_provenance_is_never_masked(self):
        """The source and confidence are not personal data and a reviewer needs them."""
        exported = extract(Contact, text=_TEXT).to_dict()
        assert exported["evidence"]["email"]["source"] == "detector"
        assert exported["evidence"]["email"]["span"] is not None


class TestArguments:
    def test_it_needs_something_to_read(self):
        with pytest.raises(ValueError, match="document= or text="):
            extract(Contact)


# `parse()` needs docling, which is the `[doc]` extra and is absent from the
# base CI environment. The corpus check alone was not enough: the files are
# committed, so it passed and then `parse()` raised.
@pytest.mark.skipif(not DOC_FEATURE_AVAILABLE,
                    reason="parse() requires the [doc] extra (docling)")
@pytest.mark.skipif(not (_BENCH / "invoice_6_ak.pdf").exists(),
                    reason="doc_bench corpus not present")
class TestOnARealDocument:
    def test_end_to_end_from_a_pdf(self):
        from arche.doc import parse

        class Invoice(BaseModel):
            email: str = Field(description="contact email")

        result = extract(Invoice, document=parse(_BENCH / "invoice_6_ak.pdf"))
        assert result.data is not None
        assert result.document == "invoice_6_ak.pdf"

    def test_a_known_limitation_issuer_is_not_disambiguated(self):
        """`issuer` picks the highest-confidence organisation, not the issuer.

        On `invoice_6_ak.pdf` that returns the *customer's* organisation rather
        than the company that sent the invoice. Nothing in the local path knows
        which party a document is written from — that is a role, not an entity
        type, and the extractor does not label roles.

        Pinned rather than hidden: use `From("metadata:author")` where the PDF
        header states the issuer, or `backend="llm"` where it does not.
        """
        from arche.doc import parse

        class Invoice(BaseModel):
            issuer: str = Field(description="the company that issued this invoice")

        result = extract(Invoice, document=parse(_BENCH / "invoice_6_ak.pdf"))
        assert result.fields["issuer"].source == "extractor"
        assert result.fields["issuer"].confidence < 1.0
