# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""GLiNER 2.5 as an extraction backend.

Two things are being guarded here, and only one of them is the adapter.

The adapter itself translates a response shape that differs from GLiNER v1 in
a way that is easy to get wrong: v1 returns a flat list of spans each carrying
its own label, 2.5 returns spans grouped BY label. The fake below reproduces
the real response byte-for-byte in shape -- it was captured from
``fastino/gliner2.5-base-v1`` running on the sentence in ``_TEXT`` -- so these
tests exercise the translation without a 500MB download.

The other thing is the install boundary. ``pip install gliner2`` does NOT give
you local extraction; it gives you an API client that posts text to a hosted
service. Local inference is ``gliner2[local]``. Declaring the wrong one would
ship a code path that sends customer text off the machine while looking exactly
like on-device extraction, so the extra is asserted here rather than trusted.
"""

from __future__ import annotations

import pytest

# Imported from the module that defines it, not from the package. Both
# spellings work in a fresh process, but `arche.extract` is a module AND
# a function, so any `from arche.extract import ...` anywhere in the
# process rebinds the package attribute to the module -- after which
# `from arche import extract` yields something that is not callable.
# Two existing test files do exactly that, which is why these tests
# passed alone and failed in the suite.
from arche._models import get_gliner2
from arche.extract import extract

_TEXT = (
    "Karfi Agro Cooperative Society Ltd of 12 Zaria Road, Kano "
    "invoiced Zenith Bank Plc on 3 March 2026."
)

#: Captured from the real model. Label-keyed, spans carry text/confidence/
#: start/end -- the shape `include_confidence=True, include_spans=True` returns.
_REAL_SHAPE = {
    "entities": {
        "organization": [
            {"text": "Karfi Agro Cooperative Society Ltd",
             "confidence": 0.9842, "start": 0, "end": 34},
            {"text": "Zenith Bank Plc",
             "confidence": 0.9881, "start": 67, "end": 82},
        ],
        "location": [
            {"text": "Kano", "confidence": 0.9339, "start": 53, "end": 57},
        ],
        # A label the model was asked about and found nothing for. Must not
        # produce an entity, and must not raise.
        "person": [],
    }
}


class _FakeExtractor:
    """Stands in for AutoExtractor, and records how it was called."""

    def __init__(self, response=None):
        self.response = _REAL_SHAPE if response is None else response
        self.calls = []

    def extract_entities(self, text, labels, **kwargs):
        self.calls.append({"text": text, "labels": labels, **kwargs})
        return self.response


@pytest.fixture
def fake_model(monkeypatch):
    model = _FakeExtractor()
    monkeypatch.setattr("arche._models.get_gliner2", lambda *a, **k: model)
    return model


# ---------------------------------------------------------------------------
# The install boundary
# ---------------------------------------------------------------------------


def test_the_extra_pins_the_local_stack_not_the_api_client():
    # The single most consequential line in this integration. `gliner2` alone
    # is a hosted-API client; `gliner2[local]` is on-device inference. Getting
    # this wrong would not fail loudly -- extraction would appear to work while
    # the text left the machine.
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    extras = pyproject["project"]["optional-dependencies"]
    assert any("gliner2[local]" in dep for dep in extras["detect2"]), (
        "detect2 must depend on gliner2[local]; bare gliner2 sends text to a "
        "hosted service"
    )


def test_gliner2_is_not_a_core_dependency():
    # The wheel promise is a small CPU-only base install. gliner2[local] pulls
    # torch, so it belongs in an extra permanently -- not just until it is
    # convenient to promote.
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    core = " ".join(pyproject["project"]["dependencies"])
    assert "gliner" not in core and "torch" not in core


def test_a_missing_install_says_which_extra_and_why():
    pytest.importorskip
    try:
        import gliner2  # noqa: F401
    except ImportError:
        pass
    else:
        pytest.skip("gliner2 is installed here; the absent path cannot be shown")
    with pytest.raises(ImportError) as excinfo:
        get_gliner2()
    message = str(excinfo.value)
    assert "arche-core[detect2]" in message
    # The warning about the bare package matters more than the install line:
    # a reader who fixes the ImportError with `pip install gliner2` gets a
    # working import and a network call.
    assert "API client" in message


# ---------------------------------------------------------------------------
# The adapter
# ---------------------------------------------------------------------------


def test_label_grouped_spans_become_flat_entities(fake_model):
    entities = extract(_TEXT, backend="gliner2")
    assert [e.text for e in entities] == [
        "Karfi Agro Cooperative Society Ltd",
        "Kano",
        "Zenith Bank Plc",
    ]


def test_entities_are_sorted_by_position(fake_model):
    entities = extract(_TEXT, backend="gliner2")
    assert [e.start for e in entities] == sorted(e.start for e in entities)


def test_labels_map_onto_arches_taxonomy(fake_model):
    kinds = {e.entity_type for e in extract(_TEXT, backend="gliner2")}
    assert kinds == {"ORGANIZATION", "LOCATION"}


def test_offsets_cite_the_source_text(fake_model):
    # An entity whose offsets do not select its own text cannot be cited back
    # to the document, which is what makes it evidence rather than a guess.
    for entity in extract(_TEXT, backend="gliner2"):
        assert _TEXT[entity.start:entity.end] == entity.text


def test_confidence_and_source_travel(fake_model):
    entities = extract(_TEXT, backend="gliner2")
    assert all(e.source == "gliner2" for e in entities)
    assert entities[0].confidence == pytest.approx(0.9842)


def test_an_empty_label_bucket_yields_nothing(fake_model):
    assert not [e for e in extract(_TEXT, backend="gliner2")
                if e.entity_type == "PERSON"]


def test_offsets_are_requested_explicitly(fake_model):
    # Without these flags the model returns bare strings. Asserted because the
    # failure is silent: extraction still "works", and every mention loses the
    # offsets that make it citable.
    extract(_TEXT, backend="gliner2")
    call = fake_model.calls[0]
    assert call["include_spans"] is True
    assert call["include_confidence"] is True


def test_a_span_without_offsets_is_skipped_not_faked(monkeypatch):
    # If the model answers with bare strings anyway, dropping them is right.
    # An uncitable mention is worse than a missing one, because it looks like
    # evidence and cannot be checked.
    model = _FakeExtractor({"entities": {
        "organization": ["Karfi Agro Cooperative Society Ltd",
                         {"text": "Zenith Bank Plc", "confidence": 0.98,
                          "start": 67, "end": 82}],
    }})
    monkeypatch.setattr("arche._models.get_gliner2", lambda *a, **k: model)
    entities = extract(_TEXT, backend="gliner2")
    assert [e.text for e in entities] == ["Zenith Bank Plc"]


def test_caller_labels_are_honoured(fake_model):
    extract(_TEXT, backend="gliner2", entity_types=["Supplier", "Buyer"])
    assert fake_model.calls[0]["labels"] == ["supplier", "buyer"]


def test_an_empty_response_is_not_an_error(monkeypatch):
    model = _FakeExtractor({})
    monkeypatch.setattr("arche._models.get_gliner2", lambda *a, **k: model)
    assert extract(_TEXT, backend="gliner2") == []


# ---------------------------------------------------------------------------
# The backend is discoverable
# ---------------------------------------------------------------------------


def test_the_v1_backend_is_untouched():
    # GLiNER 2.5 is an addition, not a migration. v1 keeps its name, its model
    # setting and its threshold, so nobody's pinned pipeline changes because a
    # newer model became available.
    from arche.config import get_config

    config = get_config()
    assert config.gliner_model and config.gliner2_model
    assert config.gliner_model != config.gliner2_model


def test_an_unknown_backend_lists_gliner2():
    with pytest.raises(ValueError, match="gliner2"):
        extract(_TEXT, backend="glienr2")
