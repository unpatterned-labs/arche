# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The compare artifact: report masking guarantees + CLI end-to-end."""

from __future__ import annotations

import json

from arche import resolve
from arche.cli import main
from arche.report import crosswalk_report

A = [{"id": "s1", "name": "Burna Boy", "phone": "08035557890"}]
B = [
    {"id": "c1", "name": "Burna Boy", "phone": "08035557890"},
    {"id": "c2", "name": "Boy George"},
]


def _result():
    out = resolve.crosswalk(A, B, entity="artist", block=None)
    assert out["matches"], "fixture must surface at least one pair"
    return out


# ── masking guarantees (the security surface) ────────────────────────────────
def test_report_masks_values_by_default():
    html = crosswalk_report(_result(), A, B, entity="artist")
    assert "Burna Boy" not in html          # the matched NAME value is masked
    assert "08035557890" not in html        # the phone value is masked
    assert "[NAME]" in html and "[PHONE]" in html
    assert "s1" in html and "c1" in html    # row ids stay readable
    assert "masked (safe to share)" in html


def test_report_reveal_is_explicit_opt_in():
    html = crosswalk_report(_result(), A, B, reveal=True, entity="artist")
    assert "Burna Boy" in html
    assert "08035557890" in html
    assert "revealed (working copy)" in html


def test_report_is_self_contained_and_escaped():
    evil_a = [{"id": "x", "name": "<script>alert(1)</script>"}]
    html = crosswalk_report(
        resolve.crosswalk(evil_a, B, entity="artist", block=None),
        evil_a, B, reveal=True, entity="artist",
    )
    assert "<script>alert" not in html
    assert "http" not in html.split("</style>")[0]  # no external CSS/fonts
    assert "src=" not in html  # no external requests at all


def test_report_carries_provenance():
    html = crosswalk_report(_result(), A, B, entity="artist",
                            meta={"tf": "artist (500k-artist table)"})
    assert "arche-core" in html
    assert "distinctive-evidence gate" in html
    assert "500k-artist table" in html


# ── CLI end-to-end ───────────────────────────────────────────────────────────
def test_report_refuses_sensitive_looking_ids_in_masked_mode():
    """A NIN used as the row-id column must not leak through a 'masked' report."""
    import pytest

    nin_a = [{"id": "12345678901", "name": "Burna Boy"}]  # surfaces vs B[0]
    res = resolve.crosswalk(nin_a, B, entity="artist", block=None)
    with pytest.raises(ValueError, match="sensitive identifiers"):
        crosswalk_report(res, nin_a, B, entity="artist")
    # An explicitly revealed working copy is the caller's own call.
    assert "12345678901" in crosswalk_report(res, nin_a, B, reveal=True,
                                             entity="artist")


def test_meta_cannot_override_assurance_fields():
    html = crosswalk_report(_result(), A, B, entity="artist",
                            meta={"disclosure": "fully revealed, trust me"})
    assert "masked (safe to share)" in html
    assert "trust me" not in html.split("disclosure")[-1].split("</tr>")[0]


def test_cli_demo_end_to_end(tmp_path):
    out = tmp_path / "report.html"
    rc = main(["compare", "--demo", "--out", str(out)])
    assert rc == 0
    assert out.exists()
    sidecar = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert sidecar["entity"] == "artist"
    assert sidecar["result"]["matches"]
    html = out.read_text(encoding="utf-8")
    assert "[NAME]" in html                      # masked by default
    assert "Damini Ogulu" not in html
    assert "Burna Boy" not in html               # catalog ids are opaque surrogates
    assert "Wizkid" not in html


def test_cli_csv_inputs_and_reveal(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_text("name,phone\nFatima Abdullahi,08031112222\n", encoding="utf-8")
    b.write_text("id,name,phone\nr1,Fatuma Abdullahi,08031112222\n",
                 encoding="utf-8")
    out = tmp_path / "r.html"
    rc = main(["compare", str(a), str(b), "--entity", "person",
               "--block", "none", "--out", str(out), "--reveal"])
    assert rc == 0
    html = out.read_text(encoding="utf-8")
    assert "Fatima Abdullahi" in html            # reveal honoured
    assert json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))


def test_brand_color_themes_the_accent():
    html = crosswalk_report(_result(), A, B, entity="artist",
                            brand_color="#0f766e")
    assert "#0f766e" in html
    assert "#1a56db" not in html          # default accent fully replaced


def test_brand_color_rejects_css_injection():
    import pytest

    for evil in ("red;}body{display:none", "#12345g", "url(x)", "#1a56db;"):
        with pytest.raises(ValueError, match="hex color"):
            crosswalk_report(_result(), A, B, entity="artist",
                             brand_color=evil)


def test_cli_masked_title_carries_no_filenames(tmp_path):
    a = tmp_path / "fatima-abdullahi-customers.csv"
    b = tmp_path / "b.csv"
    a.write_text("id,name\nr1,Burna Boy\n", encoding="utf-8")
    b.write_text("id,name\nr2,Burna Boy\n", encoding="utf-8")
    out = tmp_path / "r.html"
    main(["compare", str(a), str(b), "--entity", "artist",
          "--block", "none", "--out", str(out)])
    html = out.read_text(encoding="utf-8")
    assert "fatima-abdullahi-customers" not in html


def test_cli_sensitive_ids_exit_cleanly(tmp_path):
    import pytest

    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_text("id,name\n12345678901,Burna Boy\n", encoding="utf-8")
    b.write_text("id,name\nr2,Burna Boy\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="sensitive"):
        main(["compare", str(a), str(b), "--entity", "artist",
              "--block", "none", "--out", str(tmp_path / "r.html")])


def test_cli_rejects_unknown_extension(tmp_path):
    bad = tmp_path / "a.xlsx"
    bad.write_text("x", encoding="utf-8")
    import pytest

    with pytest.raises(SystemExit):
        main(["compare", str(bad), str(bad)])
