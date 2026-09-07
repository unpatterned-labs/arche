# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""`detect_pii` and `deidentify`: the personal data in a text, and a copy to hand on.

Both are `Pipeline` with the choices made. What these tests guard is the part
that is *not* a rename: the jurisdiction is never guessed silently, a
redaction has a content-addressed id the ledger can explain and replay, and a
tokenised copy is still comparable -- two masked notes about one person link
on their tokens without either side holding the value.

Everything runs on ``backend="basic"`` so the suite needs no model; the model
path is covered in ``test_pipeline_backend.py`` with a captured response.
"""

from __future__ import annotations

import json
import subprocess
import sys
import warnings

import arche
import pytest
from arche import Pipeline, deidentify, detect_pii
from arche.protect import METHODS, Deidentified, JurisdictionRequiredError

NOTE = ("Patient Casey Example (NIN 12345678901) called from 0803 555 7890, "
        "email casey@example.com.")
A = "Adesola Okonkwo, NIN 12345678901, adesola@example.com, 123 Maple Street"
B = "Adesola E. Okonkwo, NIN 12345678901, adesola@gmail.com, 231 Elim Street"
C = "Ibrahim Musa, NIN 98765432109, ibrahim@example.com"


def _deid(text=NOTE, **kw):
    kw.setdefault("jurisdiction", "NG")
    kw.setdefault("backend", "basic")
    return deidentify(text, **kw)


# ---------------------------------------------------------------------------
# detect_pii
# ---------------------------------------------------------------------------


def test_detect_pii_returns_spans_with_the_statute_section():
    found = detect_pii(NOTE, jurisdiction="NG", backend="basic")
    by_category = {d.category: d for d in found}
    assert {"PII-2-NIN", "PII-3-PHONE", "PII-3-EMAIL"} <= set(by_category)
    nin = by_category["PII-2-NIN"]
    assert NOTE[nin.start:nin.end] == "12345678901"
    assert nin.regulatory_citation and "NDPA-2023" in nin.regulatory_citation


def test_detect_pii_is_the_pipeline_with_the_choices_made():
    ours = detect_pii(NOTE, jurisdiction="NG", backend="basic")
    theirs = Pipeline(jurisdiction="NG", on_uncovered="baseline").process(NOTE).detections
    assert [(d.category, d.start, d.end) for d in ours] == \
        [(d.category, d.start, d.end) for d in theirs]


# ---------------------------------------------------------------------------
# deidentify: the copy
# ---------------------------------------------------------------------------


def test_the_statute_decides_the_rendering_by_default():
    safe = _deid()
    assert "12345678901" not in safe.text
    assert "0803 555 7890" not in safe.text
    assert "casey@example.com" not in safe.text
    # NDPA masks a national id and tokenises a phone: two different renderings
    # from one statute, which is why "statute" is a method and not the absence of one.
    assert "[NIN]" in safe.text
    assert "PHONE_" in safe.text
    assert safe.method == "statute" and safe.statute == "NDPA-2023"


@pytest.mark.parametrize("method, marker", [
    ("mask", "[PHONE]"), ("token", "PHONE_"), ("drop", "called from ,"),
])
def test_a_method_overrides_the_rendering_not_the_finding(method, marker):
    safe = _deid(method=method)
    assert marker in safe.text
    # The finding and the citation are still the statute's.
    assert safe.count == 3
    assert all(d.regulatory_citation for d in safe.detections)


def test_an_unknown_method_is_refused():
    with pytest.raises(ValueError, match="method"):
        _deid(method="blur")
    assert METHODS == ("statute", "mask", "token", "drop")


def test_the_repr_never_carries_the_text():
    safe = _deid()
    assert "Casey" not in repr(safe) and "12345678901" not in repr(safe)
    assert "count=3" in repr(safe)


def test_spans_are_value_free():
    for span in _deid().spans():
        assert set(span) == {"category", "start", "end", "confidence", "action",
                             "citation", "detector"}


# ---------------------------------------------------------------------------
# deidentify: the decision
# ---------------------------------------------------------------------------


def test_the_decision_id_is_a_content_address():
    assert _deid().decision_id == _deid().decision_id
    assert _deid().decision_id.startswith("red:sha256:")


def test_the_id_moves_with_the_method_and_the_statute_not_the_salt():
    base = _deid()
    assert _deid(method="mask").decision_id != base.decision_id
    assert _deid(jurisdiction="ZA").decision_id != base.decision_id
    # The salt keys the tokens, not the decision: what was found and what
    # was done to it are the same under any salt.
    assert _deid(salt="k1").decision_id == _deid(salt="k2").decision_id
    assert _deid(salt="k1").text != _deid(salt="k2").text


def test_the_pins_say_what_ran():
    pins = _deid().pins
    assert pins["backend"] == "basic" and pins["model"] is None
    assert pins["statute"] == "NDPA-2023" and pins["statute_version"]
    assert pins["jurisdiction_source"] == "given"
    assert pins["engine"].startswith("arche-core@")


# ---------------------------------------------------------------------------
# the jurisdiction is never guessed silently
# ---------------------------------------------------------------------------


def test_a_jurisdiction_is_inferred_from_the_text_and_said_so():
    text = "Monzo Bank Limited, London EC2A 2AG. Contact jane.smith@monzo.com."
    safe = deidentify(text, backend="basic")
    assert safe.jurisdiction == "GB" and safe.statute == "UK-GDPR"
    assert safe.pins["jurisdiction_source"] == "inferred"
    assert "jane.smith@monzo.com" not in safe.text


def test_no_evidence_means_a_refusal_that_names_the_packs():
    with pytest.raises(JurisdictionRequiredError, match="NG") as excinfo:
        deidentify("call me on the usual number", backend="basic")
    assert "will not guess" in str(excinfo.value)
    assert issubclass(JurisdictionRequiredError, ValueError)


def test_an_uncovered_jurisdiction_gets_the_baseline_floor_and_a_warning():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        safe = _deid("Contact jane@example.com about the invoice.", jurisdiction="IN")
    assert safe.statute == "BASELINE"
    assert "jane@example.com" not in safe.text
    assert any("baseline" in str(w.message).lower() for w in caught)


def test_an_unknown_backend_is_refused_with_the_vocabulary():
    with pytest.raises(ValueError, match="gliner2-pii"):
        _deid(backend="magic")
    with pytest.raises(ValueError, match="removed in 0.9.0"):
        _deid(backend="gliner")


def test_regex_is_still_accepted_as_a_spelling_of_basic():
    assert _deid(backend="regex").pins["backend"] == "basic"


# ---------------------------------------------------------------------------
# the ledger
# ---------------------------------------------------------------------------


@pytest.fixture
def ledger():
    pytest.importorskip("duckdb")
    with arche.attach("duckdb:///:memory:") as led:
        yield led


def test_a_stored_redaction_is_explained_by_id(ledger):
    safe = _deid(store=ledger)
    why = ledger.explain(safe.decision_id)
    assert why["verb"] == "deidentify"
    assert why["by_category"] == {"PII-2-NIN": 1, "PII-3-EMAIL": 1, "PII-3-PHONE": 1}
    assert any("NDPA-2023" in c for c in why["citations"])
    assert all("text" not in span for span in why["spans"])


def test_a_stored_redaction_replays(ledger):
    safe = _deid(store=ledger, method="token", salt="k1")
    replay = ledger.replay(safe.decision_id)
    assert replay.reproduced and replay.changed == {}


def test_a_redaction_links_nothing_and_sits_in_the_document_history(ledger):
    safe = _deid(store=ledger)
    decision = ledger.decision(safe.decision_id)
    assert decision.verb == "deidentify" and not decision.linked
    assert decision.record_a == decision.record_b
    assert [d.verb for d in ledger.history(decision.record_a)] == ["deidentify"]
    assert not ledger.entities()


def test_recording_the_same_redaction_twice_writes_one_row(ledger):
    a = _deid(store=ledger)
    b = _deid(store=ledger)
    assert a.decision_id == b.decision_id
    assert len(ledger.history(ledger.decision(a.decision_id).record_a)) == 1


# ---------------------------------------------------------------------------
# linkable after masking
# ---------------------------------------------------------------------------


def test_two_tokenised_copies_of_one_person_still_link():
    ma, mb = (_deid(t, method="token", salt="k1") for t in (A, B))
    assert "12345678901" not in ma.text + mb.text
    assert ma.record()["national_id"] == mb.record()["national_id"]
    receipt = arche.compare(ma.record(), mb.record(), entity="person", jurisdiction="NG")
    assert receipt.identity == "same_entity"
    assert receipt.factors["national_id"] == 1.0


def test_two_tokenised_copies_of_different_people_do_not():
    ma, mc = (_deid(t, method="token", salt="k1") for t in (A, C))
    receipt = arche.compare(ma.record(), mc.record(), entity="person", jurisdiction="NG")
    assert receipt.identity == "different"


def test_a_masked_copy_is_not_linkable_and_the_record_says_so_by_omission():
    # NDPA masks the national id to "[NIN]": no token, no identity to link on.
    assert "national_id" not in _deid(A).record()
    assert "national_id" not in _deid(A, method="mask").record()


def test_tokens_under_different_salts_do_not_link():
    ma = _deid(A, method="token", salt="k1")
    mb = _deid(B, method="token", salt="k2")
    assert ma.record()["national_id"] != mb.record()["national_id"]


# ---------------------------------------------------------------------------
# the public surface and the shell
# ---------------------------------------------------------------------------


def test_the_two_verbs_are_on_the_package():
    assert arche.detect_pii is detect_pii and arche.deidentify is deidentify
    assert "detect_pii" in arche.__all__ and "deidentify" in arche.__all__
    assert isinstance(_deid(), Deidentified)


def _arche(*args):
    return subprocess.run([sys.executable, "-m", "arche.cli", *args],
                          capture_output=True, text=True, encoding="utf-8")


def test_arche_redact_from_the_shell(tmp_path):
    proc = _arche("redact", "--text", NOTE, "--jurisdiction", "NG", "--backend", "basic",
                  "--json", "-")
    assert proc.returncode == 0, proc.stderr
    text, _, rest = proc.stdout.partition("\n")
    assert "12345678901" not in text and "[NIN]" in text
    payload = json.loads(rest)
    assert payload["count"] == 3 and payload["decision_id"].startswith("red:sha256:")
    assert all("text" not in s for s in payload["spans"])


def test_arche_redact_reads_a_file_and_writes_the_copy(tmp_path):
    source = tmp_path / "note.txt"
    source.write_text(NOTE, encoding="utf-8")
    out = tmp_path / "note.redacted.txt"
    proc = _arche("redact", str(source), "--jurisdiction", "NG", "--backend", "basic",
                  "--method", "mask", "--out", str(out))
    assert proc.returncode == 0, proc.stderr
    assert "[PHONE]" in out.read_text(encoding="utf-8")
    assert "decision_id red:sha256:" in proc.stdout


def test_arche_redact_refuses_without_a_jurisdiction():
    proc = _arche("redact", "--text", "call me on the usual number", "--backend", "basic")
    assert proc.returncode != 0
    assert "will not guess" in proc.stderr
