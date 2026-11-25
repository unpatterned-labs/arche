# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Retrievers: what they find, and that every candidate list names its retriever."""

from __future__ import annotations

import numpy as np
import pytest
from arche.jurisdictions.nigeria import admin_path
from arche.references import Reference, link
from arche.retrieval import (
    CharNgramIndex,
    EncoderIndex,
    IndexedReference,
    record_text,
    weights_digest,
)
from arche.retrieval._tfidf import char_ngrams
from arche.retrieval._train import pairs_digest

FACILITIES = [
    {"id": "g1", "name": "Kalahaddi Health Post", "admin_path": admin_path("Kano", "Dala")},
    {"id": "g2", "name": "Yan Amar Health Post", "admin_path": admin_path("Kano", "Dala")},
    {"id": "g3", "name": "Murtala Mohammed Specialist Hospital",
     "admin_path": admin_path("Kano", "Kano Municipal")},
    {"id": "g4", "name": "Karfi Primary Health Centre", "admin_path": admin_path("Kano", "Kura")},
]


class TestCharNgrams:
    def test_word_edges_are_marked_and_accents_folded(self):
        grams = char_ngrams("Ébène")
        assert "#eb" in grams and "ne#" in grams

    def test_a_dropped_letter_still_ranks_first(self):
        index = CharNgramIndex([f["name"] for f in FACILITIES])
        (best, score), *_ = index.search("Kalahadi Health Post", k=2)
        assert best == 0 and 0 < score < 1

    def test_a_split_word_still_ranks_first(self):
        index = CharNgramIndex([f["name"] for f in FACILITIES])
        assert index.search("Yanamar Health Post", k=1)[0][0] == 1

    def test_no_shared_gram_no_candidate(self):
        assert CharNgramIndex(["Karfi"]).search("zzz", k=5) == []

    def test_pins_name_the_vocabulary(self):
        a = CharNgramIndex(["Karfi Clinic", "Dala Clinic"]).pins()
        b = CharNgramIndex(["Karfi Clinic", "Dala Clinic"]).pins()
        c = CharNgramIndex(["Karfi Clinic", "Kura Clinic"]).pins()
        assert a == b and a["vocabulary"] != c["vocabulary"]
        assert a["retriever"] == "tfidf-char" and a["n"] == 3


def test_record_text_reads_dotted_fields_and_skips_missing():
    rec = {"name": "Zango  Health Post", "admin_path": admin_path("Kano", "Dala")}
    assert record_text(rec) == "Zango Health Post | dala | kano"
    assert record_text({"name": "Karfi"}) == "Karfi"


class FakeEncoder:
    """Vectors by first letter: what matters here is the plumbing, not a model."""

    name = "fake"

    def encode(self, texts):
        vecs = np.array([[1.0 if t and t[0].lower() == c else 0.0 for c in "kymz"] + [0.1]
                         for t in texts], dtype="float32")
        return vecs / np.linalg.norm(vecs, axis=1, keepdims=True)

    def pins(self):
        return {"encoder": "fake", "weights": "sha256:" + "0" * 64}


class TestEncoderIndex:
    def test_nearest_first_and_ties_by_row(self):
        index = EncoderIndex(["Karfi", "Kura", "Murtala"], FakeEncoder())
        hits = index.search("Kalahadi", k=3)
        assert [r for r, _ in hits] == [0, 1, 2]
        assert hits[0][1] == hits[1][1] > hits[2][1]

    def test_pins_carry_the_encoder(self):
        pins = EncoderIndex(["Karfi"], FakeEncoder()).pins()
        assert pins["retriever"] == "encoder" and pins["weights"].startswith("sha256:")


class TestIndexedReference:
    @pytest.fixture
    def ref(self):
        return IndexedReference(FACILITIES, name="grid3-kano", retriever=CharNgramIndex,
                                licence="CC BY 4.0")

    def test_is_a_reference(self, ref):
        assert isinstance(ref, Reference)

    def test_candidates_best_first(self, ref):
        found = ref.candidates({"name": "Kalahadi Health Post",
                                "admin_path": admin_path("Kano", "Dala")}, limit=2)
        assert found[0]["id"] == "g1"

    def test_the_retriever_is_in_every_decision_id(self, ref):
        m = [{"id": "m1", "name": "Murtala Muhammad Specialist Hospital",
              "admin_path": admin_path("Kano", "Kano Municipal")}]
        out = link(m, ref, entity="health_facility")
        retriever = out["pins"]["candidate_provider"]["reference"]["retriever"]
        assert retriever == ref.pins()["retriever"]
        edge = next(e for e in out["matches"] if e["b_id"] == "g3")
        assert edge["decision"] == "match"
        other = IndexedReference(FACILITIES, name="grid3-kano",
                                 retriever=lambda t: EncoderIndex(t, FakeEncoder()))
        moved = next(e for e in link(m, other, entity="health_facility")["matches"]
                     if e["b_id"] == "g3")
        assert moved["score"] == edge["score"] and moved["decision_id"] != edge["decision_id"]

    def test_release_matches_a_file_reference_of_the_same_records(self, ref):
        from arche.references import FileReference

        assert ref.pins()["release"] == FileReference(FACILITIES, name="x").pins()["release"]


def test_weights_digest_moves_with_one_byte(tmp_path):
    (tmp_path / "config.json").write_text("{}")
    (tmp_path / "model.safetensors").write_bytes(b"\x00" * 16)
    before = weights_digest(tmp_path)
    (tmp_path / "model.safetensors").write_bytes(b"\x00" * 15 + b"\x01")
    assert weights_digest(tmp_path) != before
    with pytest.raises(ValueError, match="no model files"):
        weights_digest(tmp_path / "missing")


def test_pairs_digest_covers_the_negatives():
    pairs = [("a", "b")]
    assert pairs_digest(pairs) != pairs_digest(pairs, [["c"]])
    assert pairs_digest(pairs, [["c"]]) == pairs_digest(pairs, [["c"]])
