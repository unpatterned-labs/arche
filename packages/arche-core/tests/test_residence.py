# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Proof of address: does a bundle of documents show someone lives somewhere?

Every fixture here is synthetic. The behaviours they pin were found on a real
document bundle -- an energy statement, a payslip, vendor invoices, a contract
letter -- and the failures they guard are the ones that bundle actually caused.

The four questions, and why each needs its own test:

1. is the subject named, including on a joint account;
2. WHICH address on the document is theirs, not the issuer's;
3. how old is it, and does a date cue mean what it appears to;
4. how many independent sources is that really.
"""

from __future__ import annotations

import datetime as dt

import pytest

from arche.doc._residence import ResidenceCheck, assess_residence

TODAY = dt.date.today()


def _recent(days: int) -> str:
    d = TODAY - dt.timedelta(days=days)
    return d.strftime("%d %b %Y")


def _energy_bill(days_old: int = 3, name: str = "Dennis Irorere",
                 postcode: str = "B16 8WS") -> str:
    """An energy statement -- the strongest proof-of-address document there is.

    Modelled on a real one, including the part that breaks naive extraction:
    the issuer's own postcode appears MORE often than the customer's.
    """
    return f"""
E.ON Next Energy Limited Registered Office: Trinity House, Nottingham, NG1 4BX.
Registered in England and Wales No.: 03782443
Date: {_recent(days_old)}
{name} & Love Kamebi
2 Coal House
3 Marina Place
Birmingham
{postcode}
Your charges in detail.
Supply address: 2 Coal House, 3 Marina Place, Birmingham, {postcode}
E.ON Next Energy Limited Registered Office: Trinity House, Nottingham, NG1 4BX.
Energy Ombudsman, PO Box 966, Warrington, WA4 9DF.
E.ON Next Energy Limited Registered Office: Trinity House, Nottingham, NG1 4BX.
"""


def _vendor_invoice(number: str, days_old: int, postcode: str = "B16 8WS",
                    vendor: str = "Netlify, Inc.") -> str:
    return f"""
INVOICE
{vendor}
PO BOX 7775
San Francisco, CA 94120
Invoice number {number}
Date of issue {_recent(days_old)}
Bill to
Dennis Irorere
2 Coal House, 3 Marina Place
Birmingham {postcode}
"""


# ---------------------------------------------------------------------------
# Question 2: whose address is it?
# ---------------------------------------------------------------------------


def test_the_issuers_address_is_not_the_subjects():
    # THE defect this module exists for. Generic extraction over these
    # documents returned the vendor's PO box and a New York letterhead as the
    # applicant's home address. A cue -- "Bill to" -- is the document saying
    # whose address follows.
    check = assess_residence(
        {"invoice": _vendor_invoice("A1", 10)},
        name="Dennis Irorere", min_sources=1,
    )
    assert check.address == "B16 8WS"
    assert check.documents[0]["postcodes"] == ["B16 8WS"]


def test_the_most_frequent_postcode_is_the_wrong_answer():
    # In the energy bill fixture the issuer's postcode appears three times and
    # the subject's twice, exactly as in the real statement. Any rule based on
    # frequency picks the supplier's registered office.
    text = _energy_bill()
    assert text.count("NG1 4BX") > text.count("B16 8WS")
    check = assess_residence({"bill": text}, name="Dennis Irorere",
                             min_sources=1)
    assert check.address == "B16 8WS"


def test_the_cue_is_reported_so_the_answer_can_be_audited():
    check = assess_residence({"bill": _energy_bill()}, name="Dennis Irorere",
                             min_sources=1)
    assert check.documents[0]["anchored_by"].startswith("cue:")


def test_an_unanchored_address_says_so():
    # No cue and no name adjacency: every postcode is reported and the anchor
    # is declared missing. Guessing here is how a registered office becomes
    # somebody's home.
    check = assess_residence(
        {"scrap": "Some text. B16 8WS. More text."},
        name="Nobody Here", min_sources=1,
    )
    assert check.documents[0]["anchored_by"] in {"unanchored", "none found"}


# ---------------------------------------------------------------------------
# Question 1: is the subject named, including jointly?
# ---------------------------------------------------------------------------


def test_a_joint_account_still_names_the_subject():
    # The strongest document in a real bundle was a joint energy account
    # reading "A & B". An exact-name comparison fails on precisely the document
    # a bank most wants to see.
    check = assess_residence({"bill": _energy_bill()}, name="Dennis Irorere",
                             min_sources=1)
    assert check.documents[0]["names_subject"] is True
    assert check.verdict == "verified"


def test_a_bundle_naming_nobody_is_insufficient_not_contradicted():
    # Documents that simply do not mention the applicant are missing evidence,
    # never evidence against. Collapsing the two would fail honest applicants.
    check = assess_residence(
        {"bill": _energy_bill(name="Someone Else")},
        name="Dennis Irorere",
    )
    assert check.verdict == "insufficient"
    assert "no document" in check.reason


# ---------------------------------------------------------------------------
# Question 4: how many sources, really?
# ---------------------------------------------------------------------------


def test_three_documents_from_one_vendor_are_one_source():
    # The count banks actually require is issuers, not documents. Counting
    # documents is how a bundle looks stronger than it is.
    docs = {
        "inv1": _vendor_invoice("A1", 10),
        "inv2": _vendor_invoice("A2", 20),
        "receipt": _vendor_invoice("A3", 30),
    }
    check = assess_residence(docs, name="Dennis Irorere", min_sources=2)
    assert check.independent_sources == 1
    assert check.verdict == "insufficient"
    assert "same issuer" in check.reason


def test_two_issuers_clear_the_bar():
    docs = {
        "bill": _energy_bill(days_old=3),
        "invoice": _vendor_invoice("A1", 10),
    }
    check = assess_residence(docs, name="Dennis Irorere", min_sources=2)
    assert check.independent_sources == 2
    assert check.verdict == "verified"


# ---------------------------------------------------------------------------
# Question 3: how old is it?
# ---------------------------------------------------------------------------


def test_stale_evidence_is_insufficient():
    check = assess_residence(
        {"bill": _energy_bill(days_old=400),
         "invoice": _vendor_invoice("A1", 400)},
        name="Dennis Irorere", min_sources=2, max_age_days=90,
    )
    assert check.verdict == "insufficient"
    assert "days old" in check.reason


def test_recency_is_a_policy_not_a_fact():
    docs = {"bill": _energy_bill(days_old=120),
            "invoice": _vendor_invoice("A1", 130)}
    assert assess_residence(docs, name="Dennis Irorere",
                            max_age_days=90).verdict == "insufficient"
    assert assess_residence(docs, name="Dennis Irorere",
                            max_age_days=180).verdict == "verified"


def test_a_referenced_date_is_not_this_documents_date():
    # A contract-termination letter said "dated August 1, 2025" -- the date of
    # the contract BEING terminated. Treating `dated` as an issue-date cue read
    # the letter as thirteen months older than it was.
    letter = f"""
9 June 2026
Mr. Dennis Irorere
3 Marina Place, Birmingham B16 8WS
This letter confirms termination of your contract dated August 1, 2025,
for the role of Data Engineer.
"""
    check = assess_residence({"letter": letter}, name="Dennis Irorere",
                             min_sources=1, max_age_days=100_000)
    assert check.documents[0]["date"] != dt.date(2025, 8, 1)


def test_an_uncued_date_is_read_conservatively_and_flagged():
    # A document carrying a period ("Feb 17 - Mar 17") would otherwise report
    # the later date and claim recency it has not earned. Erring old costs a
    # re-request; erring new costs the check its purpose.
    doc = """
Bill to
Dennis Irorere
Birmingham B16 8WS
Service period 1 Jan 2026 to 1 Jun 2026
"""
    check = assess_residence({"d": doc}, name="Dennis Irorere",
                             min_sources=1, max_age_days=100_000)
    assert check.documents[0]["date"] == dt.date(2026, 1, 1)
    assert check.documents[0]["date_anchored"] is False


def test_a_cued_date_wins_over_an_uncued_one():
    doc = """
Bill to
Dennis Irorere
Birmingham B16 8WS
Date of issue 1 Jun 2026
Service period 1 Jan 2026 to 1 Jun 2026
"""
    check = assess_residence({"d": doc}, name="Dennis Irorere",
                             min_sources=1, max_age_days=100_000)
    assert check.documents[0]["date"] == dt.date(2026, 6, 1)
    assert check.documents[0]["date_anchored"] is True


# ---------------------------------------------------------------------------
# Moving house: the case that must not be called fraud
# ---------------------------------------------------------------------------


def test_an_older_different_address_is_a_previous_address():
    # Somebody who moved has documents at two addresses. The older one is not
    # a contradiction, and treating it as one fails every honest applicant who
    # has ever moved.
    docs = {
        "old_invoice": _vendor_invoice("OLD", 200, postcode="B16 8DE",
                                       vendor="Cursor"),
        "bill": _energy_bill(days_old=3),
        "invoice": _vendor_invoice("NEW", 10),
    }
    check = assess_residence(docs, name="Dennis Irorere", min_sources=2)
    assert check.verdict == "verified"
    assert check.address == "B16 8WS"
    assert [c["document"] for c in check.conflicting] == ["old_invoice"]


def test_a_newer_different_address_does_contradict():
    # The same evidence in the other order. If the most recent document places
    # them somewhere else, the claim is contradicted rather than merely
    # unsupported -- and the two must not be reported as the same thing.
    docs = {
        "bill": _energy_bill(days_old=200),
        "invoice": _vendor_invoice("OLD", 210),
        "new": _vendor_invoice("NEW", 2, postcode="B16 8DE", vendor="Cursor"),
    }
    check = assess_residence(docs, name="Dennis Irorere", min_sources=1,
                             max_age_days=100_000)
    assert check.verdict == "contradicted"


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------


def test_the_three_verdicts_are_distinct():
    assert {"verified", "insufficient", "contradicted"} >= {
        assess_residence({"b": _energy_bill(), "i": _vendor_invoice("A", 5)},
                         name="Dennis Irorere").verdict,
        assess_residence({"b": _energy_bill(name="Other")},
                         name="Dennis Irorere").verdict,
    }


def test_the_claimed_address_can_be_supplied_or_inferred():
    docs = {"b": _energy_bill(), "i": _vendor_invoice("A", 5)}
    assert assess_residence(docs, name="Dennis Irorere",
                            address="B16 8WS").verdict == "verified"
    inferred = assess_residence(docs, name="Dennis Irorere")
    assert inferred.address == "B16 8WS"


def test_age_days_is_exposed():
    check = assess_residence({"b": _energy_bill(days_old=7)},
                             name="Dennis Irorere", min_sources=1)
    assert check.age_days == 7


def test_every_document_is_accounted_for():
    docs = {"b": _energy_bill(), "i": _vendor_invoice("A", 5),
            "junk": "nothing useful here"}
    check = assess_residence(docs, name="Dennis Irorere")
    assert len(check.documents) == 3


def test_an_empty_bundle_is_answerable():
    check = assess_residence({}, name="Dennis Irorere")
    assert check.verdict == "insufficient"
    assert check.independent_sources == 0


def test_the_result_is_a_dataclass_not_a_dict():
    # It is handed to a reviewer and to a downstream system; a typed result
    # keeps the field names honest.
    check = assess_residence({"b": _energy_bill()}, name="Dennis Irorere",
                             min_sources=1)
    assert isinstance(check, ResidenceCheck)
    assert check.subject == "Dennis Irorere"


def test_a_month_followed_by_a_comma_still_parses():
    # The regression that only a real PDF produced. A termination letter
    # extracted as "9 June, 2026" -- comma after the month, which a pattern
    # expecting whitespace there will not match. The letter's own date then
    # failed to parse, the fallback reached the contract date it *referenced*,
    # and the document read as thirteen months older than it was.
    #
    # The synthetic fixtures in this file all wrote "9 June 2026" and passed
    # throughout. Running on the real bundle is what found it.
    letter = """
9 June, 2026
Mr. Dennis Irorere
3 Marina Place, Birmingham B16 8WS
This confirms termination of your contract dated August 1, 2025.
"""
    check = assess_residence({"letter": letter}, name="Dennis Irorere",
                             min_sources=1, max_age_days=100_000)
    assert check.documents[0]["date"] == dt.date(2026, 6, 9)
