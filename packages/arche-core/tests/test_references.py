# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""References and `link()`: candidates from a list, the release in the receipt,
and nothing but the projected fields ever sent."""

from __future__ import annotations

import pytest
from arche.ids import edge_decision_id
from arche.jurisdictions.nigeria import admin_path
from arche.references import FileReference, Reference, link

KANO_DALA = admin_path("Kano", "Dala")

GRID3 = [
    {"id": "g1", "name": "Murtala Mohammed Specialist Hospital",
     "admin_path": admin_path("Kano", "Kano Municipal", "Sharada")},
    {"id": "g2", "name": "Zango 1 Health Post", "admin_path": admin_path("Kano", "Dala", "Zango")},
    {"id": "g3", "name": "Zango 2 Health Post", "admin_path": admin_path("Kano", "Dala", "Zango")},
    {"id": "g4", "name": "Karfi Primary Health Centre", "admin_path": admin_path("Kano", "Kura")},
    {"id": "g5", "name": "Dala Primary Health Centre", "admin_path": KANO_DALA},
]


@pytest.fixture
def ref():
    return FileReference(GRID3, name="grid3-kano", licence="CC BY 4.0")


class TestFileReference:
    def test_is_a_reference(self, ref):
        assert isinstance(ref, Reference)

    def test_release_is_the_content_digest(self, ref):
        same = FileReference(list(reversed(GRID3)), name="other-name")
        changed = FileReference(GRID3[:-1], name="grid3-kano")
        assert ref.pins()["release"] == same.pins()["release"]
        assert ref.pins()["release"] != changed.pins()["release"]
        assert ref.pins()["release"].startswith("sha256:")

    def test_from_file_pins_the_file_digest(self, tmp_path):
        import csv
        import hashlib

        path = tmp_path / "facilities.csv"
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["id", "name"])
            w.writeheader()
            w.writerows({"id": r["id"], "name": r["name"]} for r in GRID3)
        loaded = FileReference.from_file(path)
        assert loaded.pins()["release"] == "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        assert loaded.name == "facilities" and len(loaded) == len(GRID3)

    def test_type_words_alone_never_make_a_candidate(self, ref):
        # "Primary Health Centre" is what every PHC is called.
        assert ref.candidates({"name": "Primary Health Centre"}) == []

    def test_a_place_own_name_is_not_distinctive_inside_it(self, ref):
        # In Dala LGA, "Dala" names the place, not the facility.
        assert ref.candidates({"name": "Dala Health Post", "admin_path": KANO_DALA}) == []

    def test_admin_block_and_shared_token(self, ref):
        found = ref.candidates({"name": "Zango Health Post", "admin_path": KANO_DALA})
        assert {c["id"] for c in found} == {"g2", "g3"}
        elsewhere = ref.candidates({"name": "Zango Health Post",
                                    "admin_path": admin_path("Kano", "Kura")})
        assert elsewhere == []

    def test_radius_when_both_sides_have_points(self):
        pts = FileReference([{"id": "a", "name": "Karfi Clinic", "lat": 11.80, "lon": 8.50},
                             {"id": "b", "name": "Karfi Clinic", "lat": 12.30, "lon": 8.50}],
                            name="pts", radius_m=3000)
        assert [c["id"] for c in pts.candidates({"name": "Karfi", "lat": 11.801,
                                                 "lon": 8.501})] == ["a"]

    def test_ids_are_required(self):
        with pytest.raises(ValueError, match="needs an id"):
            FileReference([{"name": "x"}], name="bad")


class TestLink:
    def test_a_clean_match_and_a_held_sibling(self, ref):
        mentions = [
            {"id": "m1", "name": "Murtala Muhammad Specialist Hospital",
             "admin_path": admin_path("Kano", "Kano Municipal")},
            {"id": "m2", "name": "Zango Health Post", "admin_path": KANO_DALA},
        ]
        out = link(mentions, ref, entity="health_facility", unique_match=True)
        by = {(m["a_id"], m["b_id"]): m for m in out["matches"]}
        assert by[("m1", "g1")]["decision"] == "match"
        zango = [m for k, m in by.items() if k[0] == "m2"]
        assert zango and all(m["decision"] == "review" for m in zango)
        assert {r["id"] for r in out["reference_records"]} >= {"g1", "g2", "g3"}

    def test_the_release_is_in_every_decision_id(self, ref):
        m = [{"id": "m1", "name": "Murtala Muhammad Specialist Hospital",
              "admin_path": admin_path("Kano", "Kano Municipal")}]
        out = link(m, ref, entity="health_facility")
        assert out["pins"]["candidate_provider"]["reference"]["release"] == ref.pins()["release"]
        edge = out["matches"][0]
        assert edge["decision_id"] == edge_decision_id(edge, out["pins"])
        newer = FileReference([*GRID3, {"id": "g9", "name": "New Clinic"}], name="grid3-kano")
        moved = link(m, newer, entity="health_facility")["matches"][0]
        assert moved["score"] == edge["score"] and moved["decision_id"] != edge["decision_id"]

    def test_only_the_projected_fields_reach_the_reference(self):
        seen: list[dict] = []

        class Spy:
            name = "spy"

            def candidates(self, record, *, limit=20):
                seen.append(dict(record))
                return []

            def pins(self):
                return {"reference": "spy", "release": "r1"}

        link([{"id": "m", "name": "Karfi Clinic", "admin_path": KANO_DALA,
               "text": "the whole letter", "nin": "48291736451"}], Spy(), entity="place")
        assert seen == [{"name": "Karfi Clinic", "admin_path": KANO_DALA}]

    def test_a_reference_without_a_release_is_refused(self):
        class NoRelease:
            name = "nr"

            def candidates(self, record, *, limit=20):
                return []

            def pins(self):
                return {"reference": "nr"}

        with pytest.raises(ValueError, match="does not name its release"):
            link([{"id": "m", "name": "x"}], NoRelease())
