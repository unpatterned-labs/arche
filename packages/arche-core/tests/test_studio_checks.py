# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Studio check mode: a person says whether a proposed reading is right.

The export says how the checking went: planted errors caught, and seconds per item."""

from __future__ import annotations

import csv
import json

import pytest
from arche._studio import checks

ROWS = [
    {"id": "c1", "text": "deliver tomorrow by 4pm", "words": "tomorrow by 4pm", "n": "1",
     "written": "Wed 25 Nov 2026, 10:00", "proposal": "Thu 26 Nov 2026, 16:00; a deadline",
     "control": ""},
    {"id": "c2", "text": "pay on Friday or Friday next week", "words": "Friday", "n": "2",
     "written": "Wed 25 Nov 2026, 10:00", "proposal": "Fri 4 Dec 2026", "control": ""},
    {"id": "c3", "text": "see you next tomorrow", "words": "next tomorrow", "n": "1",
     "written": "Wed 25 Nov 2026, 10:00", "proposal": "Thu 26 Nov 2026", "control": "1"},
]


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.delenv("ARCHE_CHECK_PACKS", raising=False)
    d = tmp_path / "check_packs" / "times"
    d.mkdir(parents=True)
    (d / "pack.json").write_text(json.dumps({
        "schema": checks.SCHEMA, "title": "Times", "id_field": "id", "text_field": "text",
        "proposal_field": "proposal", "mark_field": "words", "occurrence_field": "n",
        "context_fields": ["written"], "control_field": "control", "guide": "GUIDE.md"}))
    with (d / "items.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(ROWS[0]))
        w.writeheader()
        w.writerows(ROWS)
    (d / "GUIDE.md").write_text("Read the day name too.", encoding="utf-8")
    return tmp_path


def test_listed(home):
    assert checks.packs(home) == [{"id": "times", "title": "Times", "items": 3, "checked": 0}]


def test_the_browser_never_sees_which_readings_are_planted(home):
    p = checks.load(home, "times")
    assert p["has_controls"] is True
    assert all("control" not in json.dumps(i) and i.get("control") != "1" for i in p["items"])
    assert "control" not in json.dumps(p["items"])


def test_the_words_are_marked_at_the_right_occurrence(home):
    items = {i["id"]: i for i in checks.load(home, "times")["items"]}
    assert items["c1"]["mark"] == [8, 23]
    text = ROWS[1]["text"]
    assert items["c2"]["mark"][0] == text.index("Friday", text.index("Friday") + 1)
    assert items["c1"]["context"] == [["written", "Wed 25 Nov 2026, 10:00"]]


def test_save_needs_a_name_and_a_known_verdict(home):
    with pytest.raises(checks.CheckError, match="name"):
        checks.save(home, {"pack": "times", "item": "c1", "verdict": "right"})
    with pytest.raises(checks.CheckError, match="verdict"):
        checks.save(home, {"pack": "times", "item": "c1", "verdict": "fine", "by": "dee"})


def test_export_reports_caught_controls_and_speed(home):
    for item, verdict, sec in (("c1", "right", 9), ("c2", "right", 1), ("c3", "right", 2)):
        checks.save(home, {"pack": "times", "item": item, "verdict": verdict, "by": "dee",
                           "seconds": sec})
    checks.save(home, {"pack": "times", "item": "c3", "verdict": "wrong", "by": "dee", "seconds": 6,
                       "correction": "Fri 27 Nov"})
    out = checks.export(home, "times")
    s = out["summary"]
    assert s["checked"] == 3 and s["verdicts"] == {"right": 2, "wrong": 1, "unsure": 0}
    assert s["controls"] == {"checked": 1, "caught": 1, "passed_as_right": 0}
    assert s["under_3_seconds"] == 1 and s["median_seconds"] == 6.0
    with open(out["written"], encoding="utf-8") as fh:
        rows = {r["id"]: r for r in csv.DictReader(fh)}
    assert rows["c3"]["verdict"] == "wrong" and rows["c3"]["correction"] == "Fri 27 Nov"


def test_a_pack_missing_a_column_is_left_out(home):
    d = home / "check_packs" / "times"
    spec = json.loads((d / "pack.json").read_text())
    spec["proposal_field"] = "missing"
    (d / "pack.json").write_text(json.dumps(spec))
    assert checks.packs(home) == []


def test_the_page_has_the_check_tab():
    from pathlib import Path
    page = (Path(checks.__file__).with_name("index.html")).read_text(encoding="utf-8")
    for needle in ('id="t-check"', 'id="s-check"', "/api/check_pack", "/api/check_export",
                   '"check"'):
        assert needle in page
