# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Studio label mode: a person marks the parts of a text, and the export is what they marked."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from arche._studio import labels


def _pack(base: Path, name: str = "addr", **spec_extra) -> Path:
    d = base / name
    d.mkdir(parents=True)
    spec = {"schema": labels.SCHEMA, "title": "Addresses", "text_field": "address",
            "id_field": "id", "guide": "GUIDE.md",
            "labels": [{"key": "house_number", "name": "House number", "hotkey": "n"},
                       {"key": "road", "name": "Road", "hotkey": "r"},
                       {"key": "city", "name": "City", "hotkey": "c"}], **spec_extra}
    (d / "pack.json").write_text(json.dumps(spec), encoding="utf-8")
    (d / "GUIDE.md").write_text("Copy each part as written.", encoding="utf-8")
    with (d / "items.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "country", "address"])
        w.writerow(["a1", "ng", "14 AJALA ROAD, TEMANU"])
        w.writerow(["a2", "ke", "Along Kanyiri road, Ashgrove"])
    return d


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHE_LABEL_PACKS", str(tmp_path / "packs"))
    _pack(tmp_path / "packs")
    return tmp_path / "home"


def test_a_pack_is_offered_with_its_progress(home):
    assert labels.packs(home) == [{"id": "addr", "title": "Addresses", "items": 2,
                                   "labelled": 0}]


def test_load_shows_text_labels_and_guide_and_no_model_output(home):
    p = labels.load(home, "addr")
    assert [i["text"] for i in p["items"]] == [
        "14 AJALA ROAD, TEMANU", "Along Kanyiri road, Ashgrove"]
    assert p["guide"] == "Copy each part as written."
    assert set(p) == {"id", "title", "labels", "guide", "digest", "items", "current"}


def test_save_then_export_writes_the_marked_text(home):
    labels.save(home, {"pack": "addr", "item": "a1", "by": "dee", "spans": [
        {"start": 0, "end": 2, "label": "house_number"},
        {"start": 3, "end": 13, "label": "road"},
        {"start": 15, "end": 21, "label": "city"}]})
    labels.save(home, {"pack": "addr", "item": "a2", "by": "dee", "skip": True, "spans": []})
    out = labels.export(home, "addr")
    assert out["labelled"] == 2
    with Path(out["written"]).open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0] == {"id": "a1", "country": "ng", "address": "14 AJALA ROAD, TEMANU",
                            "house_number": "14", "road": "AJALA ROAD", "city": "TEMANU",
                            "skip": "", "labelled_by": "dee"}
    assert rows[1]["skip"] == "x" and rows[1]["road"] == ""


def test_the_latest_save_stands_and_the_history_is_kept(home):
    for end in (13, 8):
        labels.save(home, {"pack": "addr", "item": "a1", "by": "dee",
                           "spans": [{"start": 3, "end": end, "label": "road"}]})
    assert labels.load(home, "addr")["current"]["a1"]["spans"][0]["end"] == 8
    history = (home / "_studio" / "labels" / "addr.jsonl").read_text().splitlines()
    assert len(history) == 2 and all(json.loads(h)["pack_digest"] for h in history)


@pytest.mark.parametrize("payload, message", [
    ({"item": "a1", "by": "", "spans": []}, "labeller name"),
    ({"item": "zz", "by": "dee", "spans": []}, "not in the pack"),
    ({"item": "a1", "by": "dee", "spans": [{"start": 0, "end": 99, "label": "road"}]},
     "outside the text"),
    ({"item": "a1", "by": "dee", "spans": [{"start": 0, "end": 2, "label": "postcode"}]},
     "unknown label"),
    ({"item": "a1", "by": "dee", "spans": [{"start": 0, "end": 5, "label": "road"},
                                           {"start": 3, "end": 8, "label": "city"}]},
     "overlap"),
])
def test_bad_labels_are_refused(home, payload, message):
    with pytest.raises(labels.LabelError, match=message):
        labels.save(home, {"pack": "addr", **payload})


def test_a_pack_outside_the_root_cannot_be_named(home):
    with pytest.raises(labels.LabelError):
        labels.load(home, "../addr")


def test_export_cannot_escape_the_pack(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHE_LABEL_PACKS", str(tmp_path / "packs"))
    _pack(tmp_path / "packs", "evil", export="../../out.csv")
    with pytest.raises(labels.LabelError, match="inside the pack"):
        labels.export(tmp_path / "home", "evil")


def test_hotkeys_must_be_free(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHE_LABEL_PACKS", str(tmp_path / "packs"))
    _pack(tmp_path / "packs", "clash",
          labels=[{"key": "road", "name": "Road", "hotkey": "x"}])
    assert labels.packs(tmp_path / "home") == []


def test_a_pack_linked_from_elsewhere_opens(tmp_path, monkeypatch):
    # Packs built from data that must stay out of a repository are linked in.
    monkeypatch.setenv("ARCHE_LABEL_PACKS", str(tmp_path / "packs"))
    real = _pack(tmp_path / "outside", "g0b")
    (tmp_path / "packs").mkdir()
    (tmp_path / "packs" / "g0b").symlink_to(real, target_is_directory=True)
    home = tmp_path / "home"
    p = labels.load(home, "g0b")
    assert len(p["items"]) == 2 and p["guide"] == "Copy each part as written."
    labels.save(home, {"pack": "g0b", "item": "a1", "by": "dee", "spans": []})
    assert labels.export(home, "g0b")["labelled"] == 1


@pytest.mark.parametrize("name", ["..", ".", ".hidden", "a/b"])
def test_only_a_plain_entry_names_a_pack(home, name):
    with pytest.raises(labels.LabelError):
        labels.load(home, name)


def test_items_carry_their_group_when_the_pack_names_one(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHE_LABEL_PACKS", str(tmp_path / "packs"))
    _pack(tmp_path / "packs", "grouped", group_field="country")
    p = labels.load(tmp_path / "home", "grouped")
    assert [i["group"] for i in p["items"]] == ["ng", "ke"]


def test_a_group_column_that_is_missing_refuses_the_pack(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHE_LABEL_PACKS", str(tmp_path / "packs"))
    _pack(tmp_path / "packs", "nogroup", group_field="region")
    assert labels.packs(tmp_path / "home") == []
