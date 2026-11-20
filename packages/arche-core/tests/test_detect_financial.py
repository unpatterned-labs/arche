# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Bank and card details, UK phone numbers and titled names on the rules-only path (20 Nov 2026).

Found while masking invented texts: under UK GDPR the basic backend returned UK
phone numbers, account numbers, sort codes, IBANs and cards in the clear; under
NDPA a labelled NUBAN came out as a phone; a surname the lexicon lacks stayed
in clear after "Mrs". All values here are invented (the IBAN and card are the
standard published test numbers).
"""

from __future__ import annotations

from arche import deidentify
from arche.detect.financial import detect_financial, iban_valid, luhn_valid
from arche.detect.names import detect_names
from arche.detect.phones import detect_phones

GB_TEXT = ("Mr John Okafor, phone 07700 900123 or +44 7700 900456 or 020 7946 0958, "
           "account 12345678 sort code 12-34-56, IBAN GB29 NWBK 6016 1331 9268 19, "
           "card 4111 1111 1111 1111.")
SECRETS = ("Okafor", "07700 900123", "7700 900456", "020 7946 0958", "12345678", "12-34-56",
           "GB29 NWBK", "4111 1111")
IBAN = "GB29 NWBK 6016 1331 9268 19"
CARD = "4111 1111 1111 1111"


def test_checksums():
    assert iban_valid(IBAN) and not iban_valid("GB28 NWBK 6016 1331 9268 19")
    assert luhn_valid(CARD) and not luhn_valid("4111 1111 1111 1112")


def test_financial_details_need_structure_or_a_label():
    found = {(d.category, d.text) for d in detect_financial(GB_TEXT)}
    assert ("PII-5-BANK_ACCOUNT", "12345678") in found
    assert ("PII-5-BANK_ACCOUNT", "12-34-56") in found
    assert ("PII-5-BANK_ACCOUNT", IBAN) in found and ("PII-5-CARD", CARD) in found
    # never a bare digit run, an invoice or an order number
    plain = "Invoice INV-2026-0042, order 100045, total 12345678.00, ref 0123456789"
    assert detect_financial(plain) == []
    # the label stays outside the span
    assert detect_financial("Account number: 0123456789")[0].text == "0123456789"


def test_uk_text_is_fully_masked_under_uk_gdpr():
    r = deidentify(GB_TEXT, "GB", backend="basic", method="mask")
    assert not any(s in r.text for s in SECRETS), r.text
    cats = {s["category"] for s in r.spans()}
    assert {"PII-3-PHONE", "PII-5-BANK_ACCOUNT", "PII-5-CARD", "PII-1-NAME"} <= cats
    assert all(s["citation"] for s in r.spans())


def test_uk_phones_are_checked_for_shape():
    text = "Call 07700 900123, +44 7700 900456 or 020 7946 0958."
    got = [d.text for d in detect_phones(text, default_country="GB")]
    assert got == ["07700 900123", "+44 7700 900456", "020 7946 0958"]
    assert detect_phones("Ref 0770 0900, year 2026, order 01234", default_country="GB") == []
    first = next(iter(detect_phones("tel 020 7946 0958", default_country="GB")))
    assert first.metadata["international"] == "+442079460958"


def test_a_labelled_nigerian_account_is_an_account_not_a_phone():
    r = deidentify("Account 0123456789. BVN 22233344455. Phone 0803 555 7890.", "NG",
                   backend="basic", method="mask")
    assert r.text == "Account [BANK_ACCOUNT]. BVN [BVN]. Phone [PHONE]."


def test_a_surname_after_a_title_is_a_name_even_when_the_lexicon_lacks_it():
    text = "Dear Mrs Ada Okwuosa-Bello and Chief B. Adeyemi, thanks."
    names = [d.text for d in detect_names(text)]
    assert "Okwuosa-Bello" in names and "Adeyemi" in names
    assert detect_names("The Monday meeting") == []
    tail = "thanks. Invoice INV-2026-0042 dated 12 March 2026, order 100045."
    r = deidentify(f"Dear Mrs Ada Example, {tail}", "GB", backend="basic", method="mask")
    assert r.text == f"Dear Mrs [NAME] [NAME], {tail}"


def test_decision_ids_stay_deterministic():
    a = deidentify(GB_TEXT, "GB", backend="basic").decision_id
    assert a == deidentify(GB_TEXT, "GB", backend="basic").decision_id
