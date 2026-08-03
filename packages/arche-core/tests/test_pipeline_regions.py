# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Step 1 (engine reconciliation): region-honest Pipeline.

* EU/EEA jurisdiction codes route to GDPR; the African four keep their statutes.
* Non-African jurisdictions get cross-cutting detectors ONLY (no African ID pack
  -> an 11-digit EU identifier must never mislabel as PII-2-NIN).
* The EU-AI-Act overlay applies as the last step of process().
* The opt-in `emails` detector emits PII-3-EMAIL with statute enrichment.
"""

from arche.detect.emails import detect_emails
from arche.workflow._primitive import Pipeline

# ── statute routing ──────────────────────────────────────────────────────────


def test_eu_codes_route_to_gdpr():
    for code in ("DE", "FR", "NL", "SE", "NO"):
        assert Pipeline(jurisdiction=code).statute_id == "GDPR"


def test_african_codes_keep_their_statutes():
    assert Pipeline(jurisdiction="NG").statute_id == "NDPA-2023"
    assert Pipeline(jurisdiction="ZA").statute_id == "POPIA"
    assert Pipeline(jurisdiction="KE").statute_id == "KENYA-DPA"
    assert Pipeline(jurisdiction="GH").statute_id == "GHANA-DPA"


def test_explicit_statute_escape_hatch():
    p = Pipeline(jurisdiction="US", statute="HIPAA-SAFE-HARBOR")
    assert p.statute_id == "HIPAA-SAFE-HARBOR"


def test_unknown_jurisdiction_has_no_statute():
    assert Pipeline(jurisdiction="BR").statute_id is None


# ── detector routing (the no-mislabel guarantee) ─────────────────────────────


def test_non_african_jurisdiction_gets_cross_cutting_only():
    packages = Pipeline(jurisdiction="DE").detector_packages
    assert "africa" not in packages
    assert not ({"ng", "ke", "za", "gh"} & set(packages))
    assert "core" in packages  # cross-cutting still runs


def test_african_and_default_routing_unchanged():
    assert "ng" in Pipeline(jurisdiction="NG").detector_packages       # per-country
    assert "africa" in Pipeline().detector_packages                    # unspecified
    assert "africa" in Pipeline(jurisdiction="RW").detector_packages   # other African


def test_de_does_not_mislabel_11_digit_id_as_nin():
    # A German Steuer-ID is 11 digits — the same shape a NIN detector accepts.
    text = "Steuer-ID: 12345678901 fuer Herrn Mueller."
    result = Pipeline(jurisdiction="DE").process(text)
    assert not any(d.category == "PII-2-NIN" for d in result.detections), (
        "African ID detectors must not run for non-African jurisdictions"
    )
    # ...whereas the same digits in an NG pipeline ARE (correctly) NIN-checked.
    ng = Pipeline(jurisdiction="NG").process("NIN: 12345678901")
    assert any(d.category == "PII-2-NIN" for d in ng.detections)


# ── the emails detector (opt-in) ─────────────────────────────────────────────


def test_detect_emails_finds_addresses():
    dets = detect_emails("Contact ada.obi+tag@example.co.uk or sales@firma.de.")
    assert [d.text for d in dets] == ["ada.obi+tag@example.co.uk", "sales@firma.de"]
    assert all(d.category == "PII-3-EMAIL" for d in dets)
    assert all(d.id.startswith("det:email:") for d in dets)  # detector-qualified id


def test_emails_not_in_default_detectors_but_opt_in_works():
    # Not in defaults (adding it would change existing users' outputs)...
    assert "emails" not in Pipeline(jurisdiction="DE").detector_packages
    # ...but opt-in routes it, and GDPR enrichment cites the statute.
    p = Pipeline(jurisdiction="DE", detectors=["emails"])
    result = p.process("Kontakt: sales@firma.de")
    emails = [d for d in result.detections if d.category == "PII-3-EMAIL"]
    assert len(emails) == 1
    assert emails[0].regulatory_citation and "GDPR" in emails[0].regulatory_citation


# ── EU-AI-Act overlay ────────────────────────────────────────────────────────


def test_overlay_applies_last_and_stamps_metadata():
    p = Pipeline(
        jurisdiction="DE",
        detectors=["emails"],
        overlays=["EU-AI-ACT"],
        transparency_notice="Automated PII screening; contact dpo@example.eu.",
    )
    result = p.process("Kontakt: sales@firma.de")
    block = result.metadata.get("ai_act")
    assert block and block["overlay_id"] == "EU-AI-ACT"
    # The operator-supplied notice satisfies the Art 50 transparency obligation.
    art50 = [o for o in block["obligations"] if "50" in str(o["article"])]
    assert art50 and art50[0]["satisfied"] is True


def test_overlay_without_notice_leaves_transparency_unsatisfied():
    p = Pipeline(jurisdiction="DE", detectors=["emails"], overlays=["EU-AI-ACT"])
    result = p.process("Kontakt: sales@firma.de")
    art50 = [
        o for o in result.metadata["ai_act"]["obligations"]
        if "50" in str(o["article"])
    ]
    assert art50 and art50[0]["satisfied"] is False


def test_describe_includes_overlays():
    p = Pipeline(jurisdiction="DE", overlays=["EU-AI-ACT"])
    assert p.describe()["overlays"] == ["EU-AI-ACT"]
