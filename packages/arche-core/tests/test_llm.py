"""Tests for the LLM proposer module (arche.llm).

Covers:
    - LLMConfig validation
    - Provider dispatch (mocked)
    - Extraction prompt building
    - JSON response parsing with offset repair
    - Graceful handling of invalid LLM output (bad JSON, wrong offsets, unknown types)
    - Merge logic: LLM + GliNER + regex through _merge_entities
    - LLM proposals going through validators (structured types must be validated)
"""

from __future__ import annotations

import json

import pytest

from arche.extract import Entity, _merge_entities, extract
from arche.llm import LLMConfig
from arche.llm.extraction import (
    _build_extraction_messages,
    _clamp_confidence,
    _parse_llm_response,
    _repair_offsets,
    extract_with_llm,
)


# ═══════════════════════════════════════════════════════════════════════════════
# LLMConfig validation
# ═══════════════════════════════════════════════════════════════════════════════


class TestLLMConfig:
    """LLMConfig dataclass validation."""

    def test_default_config(self):
        cfg = LLMConfig()
        assert cfg.provider == "openai"
        assert cfg.model == "gpt-4o-mini"
        assert cfg.temperature == 0.0
        assert cfg.max_tokens == 4096
        assert cfg.timeout == 30.0
        assert cfg.api_key is None
        assert cfg.base_url is None

    def test_valid_providers(self):
        for provider in ("openai", "anthropic", "ollama", "litellm"):
            cfg = LLMConfig(provider=provider)
            assert cfg.provider == provider

    def test_invalid_provider(self):
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            LLMConfig(provider="grok")

    def test_invalid_temperature_too_high(self):
        with pytest.raises(ValueError, match="temperature"):
            LLMConfig(temperature=3.0)

    def test_invalid_temperature_negative(self):
        with pytest.raises(ValueError, match="temperature"):
            LLMConfig(temperature=-0.1)

    def test_invalid_max_tokens(self):
        with pytest.raises(ValueError, match="max_tokens"):
            LLMConfig(max_tokens=0)

    def test_invalid_timeout(self):
        with pytest.raises(ValueError, match="timeout"):
            LLMConfig(timeout=0)

    def test_frozen(self):
        cfg = LLMConfig()
        with pytest.raises(AttributeError):
            cfg.provider = "anthropic"  # type: ignore[misc]

    def test_ollama_config(self):
        cfg = LLMConfig(
            provider="ollama",
            model="llama3.1",
            base_url="http://localhost:11434",
        )
        assert cfg.provider == "ollama"
        assert cfg.model == "llama3.1"

    def test_extra_kwargs(self):
        cfg = LLMConfig(extra={"top_p": 0.9})
        assert cfg.extra == {"top_p": 0.9}


# ═══════════════════════════════════════════════════════════════════════════════
# Prompt building
# ═══════════════════════════════════════════════════════════════════════════════


class TestPromptBuilding:
    """Test the extraction prompt message construction."""

    def test_messages_structure(self):
        messages = _build_extraction_messages("Hello world")
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "Hello world"

    def test_system_prompt_mentions_entity_types(self):
        messages = _build_extraction_messages("test")
        system = messages[0]["content"]
        assert "PERSON" in system
        assert "NATIONAL_ID" in system
        assert "PHONE" in system


# ═══════════════════════════════════════════════════════════════════════════════
# Offset repair
# ═══════════════════════════════════════════════════════════════════════════════


class TestOffsetRepair:
    """Test the _repair_offsets function -- critical for LLM extraction."""

    def test_correct_offsets_kept(self):
        text = "Hello Fatima Abdullahi"
        start, end = _repair_offsets(text, "Fatima Abdullahi", 6, 22)
        assert start == 6
        assert end == 22

    def test_wrong_offsets_repaired(self):
        text = "Hello Fatima Abdullahi"
        # LLM claims offsets 0-16 but text is at 6-22
        start, end = _repair_offsets(text, "Fatima Abdullahi", 0, 16)
        assert start == 6
        assert end == 22

    def test_no_offsets_provided(self):
        text = "Hello Fatima Abdullahi"
        start, end = _repair_offsets(text, "Fatima Abdullahi", None, None)
        assert start == 6
        assert end == 22

    def test_case_insensitive_fallback(self):
        text = "Hello FATIMA ABDULLAHI"
        start, end = _repair_offsets(text, "fatima abdullahi", None, None)
        assert start == 6
        assert end == 22

    def test_entity_not_in_text(self):
        text = "Hello world"
        start, end = _repair_offsets(text, "Nonexistent Person", None, None)
        assert start is None
        assert end is None

    def test_non_numeric_offsets(self):
        text = "Hello Fatima"
        start, end = _repair_offsets(text, "Fatima", "six", "twelve")  # type: ignore[arg-type]
        assert start == 6
        assert end == 12

    def test_float_offsets_converted(self):
        text = "Hello Fatima"
        start, end = _repair_offsets(text, "Fatima", 6.0, 12.0)
        assert start == 6
        assert end == 12

    def test_negative_offsets_rejected(self):
        text = "Hello Fatima"
        start, end = _repair_offsets(text, "Fatima", -1, 6)
        # Falls back to search
        assert start == 6
        assert end == 12


# ═══════════════════════════════════════════════════════════════════════════════
# JSON response parsing
# ═══════════════════════════════════════════════════════════════════════════════


class TestParseResponse:
    """Test _parse_llm_response with various LLM output formats."""

    SAMPLE_TEXT = "Fatima Abdullahi, NIN 12345678901, called from +234 803 555 7890"

    def test_valid_json_response(self):
        response = json.dumps({
            "entities": [
                {
                    "text": "Fatima Abdullahi",
                    "entity_type": "PERSON",
                    "confidence": 0.95,
                    "start": 0,
                    "end": 16,
                },
                {
                    "text": "12345678901",
                    "entity_type": "NATIONAL_ID",
                    "confidence": 0.90,
                    "start": 22,
                    "end": 33,
                },
            ]
        })
        entities = _parse_llm_response(response, self.SAMPLE_TEXT)
        assert len(entities) == 2
        assert entities[0].entity_type == "PERSON"
        assert entities[0].source == "llm"
        assert entities[0].text == "Fatima Abdullahi"
        assert entities[1].entity_type == "NATIONAL_ID"

    def test_json_in_markdown_code_block(self):
        response = '```json\n{"entities": [{"text": "Fatima Abdullahi", "entity_type": "PERSON", "confidence": 0.9, "start": 0, "end": 16}]}\n```'
        entities = _parse_llm_response(response, self.SAMPLE_TEXT)
        assert len(entities) == 1
        assert entities[0].entity_type == "PERSON"

    def test_empty_entities_list(self):
        response = json.dumps({"entities": []})
        entities = _parse_llm_response(response, self.SAMPLE_TEXT)
        assert entities == []

    def test_invalid_json(self):
        entities = _parse_llm_response("this is not json", self.SAMPLE_TEXT)
        assert entities == []

    def test_entities_not_a_list(self):
        response = json.dumps({"entities": "not a list"})
        entities = _parse_llm_response(response, self.SAMPLE_TEXT)
        assert entities == []

    def test_response_not_a_dict(self):
        response = json.dumps([1, 2, 3])
        entities = _parse_llm_response(response, self.SAMPLE_TEXT)
        assert entities == []

    def test_unknown_entity_type_dropped(self):
        response = json.dumps({
            "entities": [
                {
                    "text": "something",
                    "entity_type": "ALIEN_SPECIES",
                    "confidence": 0.9,
                    "start": 0,
                    "end": 9,
                },
            ]
        })
        entities = _parse_llm_response(response, "something here")
        assert entities == []

    def test_entity_text_not_in_input_dropped(self):
        response = json.dumps({
            "entities": [
                {
                    "text": "Completely Made Up Name",
                    "entity_type": "PERSON",
                    "confidence": 0.9,
                    "start": 0,
                    "end": 22,
                },
            ]
        })
        entities = _parse_llm_response(response, self.SAMPLE_TEXT)
        assert entities == []

    def test_wrong_offsets_repaired(self):
        response = json.dumps({
            "entities": [
                {
                    "text": "Fatima Abdullahi",
                    "entity_type": "PERSON",
                    "confidence": 0.95,
                    "start": 999,   # wrong
                    "end": 1015,    # wrong
                },
            ]
        })
        entities = _parse_llm_response(response, self.SAMPLE_TEXT)
        assert len(entities) == 1
        assert entities[0].start == 0
        assert entities[0].end == 16

    def test_confidence_clamped(self):
        response = json.dumps({
            "entities": [
                {"text": "Fatima Abdullahi", "entity_type": "PERSON", "confidence": 1.5, "start": 0, "end": 16},
                {"text": "12345678901", "entity_type": "NATIONAL_ID", "confidence": -0.5, "start": 22, "end": 33},
            ]
        })
        entities = _parse_llm_response(response, self.SAMPLE_TEXT)
        assert entities[0].confidence == 1.0
        assert entities[1].confidence == 0.0

    def test_missing_confidence_defaults(self):
        response = json.dumps({
            "entities": [
                {"text": "Fatima Abdullahi", "entity_type": "PERSON", "start": 0, "end": 16},
            ]
        })
        entities = _parse_llm_response(response, self.SAMPLE_TEXT)
        assert entities[0].confidence == 0.70

    def test_lowercase_entity_type_normalised(self):
        response = json.dumps({
            "entities": [
                {"text": "Fatima Abdullahi", "entity_type": "person", "confidence": 0.9, "start": 0, "end": 16},
            ]
        })
        entities = _parse_llm_response(response, self.SAMPLE_TEXT)
        assert entities[0].entity_type == "PERSON"

    def test_label_field_accepted(self):
        """Some LLMs use 'label' instead of 'entity_type'."""
        response = json.dumps({
            "entities": [
                {"text": "Fatima Abdullahi", "label": "PERSON", "confidence": 0.9, "start": 0, "end": 16},
            ]
        })
        entities = _parse_llm_response(response, self.SAMPLE_TEXT)
        assert len(entities) == 1
        assert entities[0].entity_type == "PERSON"

    def test_reasoning_stored_in_metadata(self):
        response = json.dumps({
            "entities": [
                {
                    "text": "Fatima Abdullahi",
                    "entity_type": "PERSON",
                    "confidence": 0.9,
                    "start": 0,
                    "end": 16,
                    "reasoning": "Full name of the caller",
                },
            ]
        })
        entities = _parse_llm_response(response, self.SAMPLE_TEXT)
        assert entities[0].metadata.get("llm_reasoning") == "Full name of the caller"

    def test_source_is_always_llm(self):
        response = json.dumps({
            "entities": [
                {"text": "Fatima Abdullahi", "entity_type": "PERSON", "confidence": 0.9, "start": 0, "end": 16},
            ]
        })
        entities = _parse_llm_response(response, self.SAMPLE_TEXT)
        assert all(e.source == "llm" for e in entities)

    def test_sorted_by_position(self):
        response = json.dumps({
            "entities": [
                {"text": "12345678901", "entity_type": "NATIONAL_ID", "confidence": 0.9, "start": 22, "end": 33},
                {"text": "Fatima Abdullahi", "entity_type": "PERSON", "confidence": 0.9, "start": 0, "end": 16},
            ]
        })
        entities = _parse_llm_response(response, self.SAMPLE_TEXT)
        assert entities[0].start < entities[1].start

    def test_non_dict_entity_skipped(self):
        response = json.dumps({
            "entities": [
                "this is not a dict",
                {"text": "Fatima Abdullahi", "entity_type": "PERSON", "confidence": 0.9, "start": 0, "end": 16},
            ]
        })
        entities = _parse_llm_response(response, self.SAMPLE_TEXT)
        assert len(entities) == 1

    def test_empty_text_entity_skipped(self):
        response = json.dumps({
            "entities": [
                {"text": "", "entity_type": "PERSON", "confidence": 0.9, "start": 0, "end": 0},
                {"text": "Fatima Abdullahi", "entity_type": "PERSON", "confidence": 0.9, "start": 0, "end": 16},
            ]
        })
        entities = _parse_llm_response(response, self.SAMPLE_TEXT)
        assert len(entities) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Confidence clamping
# ═══════════════════════════════════════════════════════════════════════════════


class TestClampConfidence:

    def test_normal_value(self):
        assert _clamp_confidence(0.85) == 0.85

    def test_high_value_clamped(self):
        assert _clamp_confidence(1.5) == 1.0

    def test_negative_value_clamped(self):
        assert _clamp_confidence(-0.3) == 0.0

    def test_non_numeric_defaults(self):
        assert _clamp_confidence("not a number") == 0.70

    def test_none_defaults(self):
        assert _clamp_confidence(None) == 0.70

    def test_integer_accepted(self):
        assert _clamp_confidence(1) == 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# Merge logic: LLM + GliNER + regex
# ═══════════════════════════════════════════════════════════════════════════════


class TestMergeWithLLM:
    """Test that _merge_entities correctly integrates LLM proposals."""

    def test_llm_fills_gaps(self):
        """LLM proposal for a PERSON that GliNER + regex missed should be kept."""
        primary = [
            Entity("12345678901", "NATIONAL_ID", 0.95, 22, 33, source="african"),
        ]
        llm = [
            Entity("Fatima Abdullahi", "PERSON", 0.90, 0, 16, source="llm"),
        ]
        merged = _merge_entities(primary, llm)
        types = {e.entity_type for e in merged}
        assert "PERSON" in types
        assert "NATIONAL_ID" in types

    def test_trusted_regex_beats_llm(self):
        """African-validated NIN should beat LLM's NIN proposal on overlap."""
        primary = []
        secondary_african = Entity(
            "12345678901", "NATIONAL_ID", 0.95, 22, 33, source="african",
        )
        secondary_llm = Entity(
            "12345678901", "NATIONAL_ID", 0.90, 22, 33, source="llm",
        )
        # african is in secondary, llm is also in secondary
        # When both are secondary, african is trusted and wins
        merged = _merge_entities(primary, [secondary_african, secondary_llm])
        # Only one entity should be in the result for that span
        nid_entities = [e for e in merged if e.entity_type == "NATIONAL_ID"]
        assert len(nid_entities) == 1
        assert nid_entities[0].source == "african"

    def test_primary_beats_llm_on_overlap(self):
        """Existing GliNER entity should beat overlapping LLM proposal."""
        primary = [
            Entity("Fatima Abdullahi", "PERSON", 0.92, 0, 16, source="gliner"),
        ]
        llm = [
            Entity("Fatima Abdullahi", "PERSON", 0.88, 0, 16, source="llm"),
        ]
        merged = _merge_entities(primary, llm)
        persons = [e for e in merged if e.entity_type == "PERSON"]
        assert len(persons) == 1
        assert persons[0].source == "gliner"

    def test_llm_non_overlapping_kept(self):
        """LLM entities that don't overlap with anything should be kept."""
        primary = [
            Entity("Fatima", "PERSON", 0.90, 0, 6, source="gliner"),
        ]
        llm = [
            Entity("Lagos", "LOCATION", 0.85, 50, 55, source="llm"),
        ]
        merged = _merge_entities(primary, llm)
        assert len(merged) == 2
        types = {e.entity_type for e in merged}
        assert "LOCATION" in types

    def test_empty_llm_results(self):
        """Empty LLM results should not affect existing entities."""
        primary = [
            Entity("Fatima", "PERSON", 0.90, 0, 6, source="gliner"),
        ]
        merged = _merge_entities(primary, [])
        assert len(merged) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# extract_with_llm with mocked provider
# ═══════════════════════════════════════════════════════════════════════════════


class TestExtractWithLLM:
    """Test extract_with_llm with a mocked LLM provider."""

    SAMPLE_TEXT = "Dr. Fatima Abdullahi, NIN 12345678901, lives in Lagos"

    def _mock_complete(self, response_json: dict):
        """Create a mock that replaces providers.complete."""
        def mock_fn(config, messages):
            return json.dumps(response_json)
        return mock_fn

    def test_basic_extraction(self, monkeypatch):
        mock = self._mock_complete({
            "entities": [
                {"text": "Fatima Abdullahi", "entity_type": "PERSON", "confidence": 0.95, "start": 4, "end": 20},
                {"text": "12345678901", "entity_type": "NATIONAL_ID", "confidence": 0.90, "start": 26, "end": 37},
                {"text": "Lagos", "entity_type": "LOCATION", "confidence": 0.85, "start": 48, "end": 53},
            ]
        })
        monkeypatch.setattr("arche.llm.providers.complete", mock)

        config = LLMConfig(provider="openai", model="gpt-4o-mini")
        entities = extract_with_llm(self.SAMPLE_TEXT, config)

        assert len(entities) == 3
        assert all(e.source == "llm" for e in entities)
        assert entities[0].entity_type == "PERSON"
        assert entities[1].entity_type == "NATIONAL_ID"
        assert entities[2].entity_type == "LOCATION"

    def test_api_failure_raises(self, monkeypatch):
        def fail_fn(config, messages):
            raise ConnectionError("Network down")
        monkeypatch.setattr("arche.llm.providers.complete", fail_fn)

        config = LLMConfig(provider="openai")
        with pytest.raises(RuntimeError, match="LLM extraction failed"):
            extract_with_llm(self.SAMPLE_TEXT, config)

    def test_empty_response(self, monkeypatch):
        mock = self._mock_complete({"entities": []})
        monkeypatch.setattr("arche.llm.providers.complete", mock)

        config = LLMConfig(provider="openai")
        entities = extract_with_llm(self.SAMPLE_TEXT, config)
        assert entities == []

    def test_malformed_json_returns_empty(self, monkeypatch):
        def bad_json(config, messages):
            return "I'm sorry, I can't help with that."
        monkeypatch.setattr("arche.llm.providers.complete", bad_json)

        config = LLMConfig(provider="openai")
        entities = extract_with_llm(self.SAMPLE_TEXT, config)
        assert entities == []


# ═══════════════════════════════════════════════════════════════════════════════
# Integration: extract() with backend="auto+llm" (mocked)
# ═══════════════════════════════════════════════════════════════════════════════


class TestExtractAutoLLM:
    """Test the extract() function with backend='auto+llm' and mocked LLM."""

    SAMPLE_TEXT = "Fatima Abdullahi called from +234 803 555 7890"

    def test_auto_llm_merges_all_sources(self, monkeypatch):
        """LLM entities should merge with GliNER + regex through _merge_entities."""
        import sys
        _extract_mod = sys.modules["arche.extract"]

        # Mock GliNER to raise ImportError (so only regex + LLM run)
        def fail_gliner(*args, **kwargs):
            raise ImportError("GliNER not installed")
        monkeypatch.setattr(_extract_mod, "_extract_gliner", fail_gliner)

        # Mock LLM to return a LOCATION that regex won't find
        def mock_llm(text, llm_config):
            return [Entity("Lagos", "LOCATION", 0.85, 100, 105, source="llm")]
        monkeypatch.setattr(_extract_mod, "_extract_llm", mock_llm)

        config = LLMConfig(provider="openai")
        entities = extract(
            self.SAMPLE_TEXT + " in Lagos",
            backend="auto+llm",
            llm_config=config,
        )

        # Should have phone from regex and location from LLM at minimum
        types = {e.entity_type for e in entities}
        assert "PHONE" in types
        assert "LOCATION" in types

    def test_auto_backend_does_not_call_llm(self, monkeypatch):
        """Default 'auto' backend should never call the LLM."""
        import sys
        _extract_mod = sys.modules["arche.extract"]

        called = {"llm": False}

        def spy_llm(text, llm_config):
            called["llm"] = True
            return []
        monkeypatch.setattr(_extract_mod, "_extract_llm", spy_llm)

        # Mock GliNER to avoid needing the model
        def mock_gliner(text, entity_types):
            return []
        monkeypatch.setattr(_extract_mod, "_extract_gliner", mock_gliner)

        extract(self.SAMPLE_TEXT, backend="auto")
        assert not called["llm"]


# ═══════════════════════════════════════════════════════════════════════════════
# Backend validation
# ═══════════════════════════════════════════════════════════════════════════════


class TestBackendValidation:

    def test_unknown_backend_raises(self):
        with pytest.raises(ValueError, match="Unknown backend"):
            extract("test", backend="magic")

    def test_auto_plus_llm_is_valid(self, monkeypatch):
        """backend='auto+llm' should not raise ValueError."""
        import sys
        _extract_mod = sys.modules["arche.extract"]

        def mock_gliner(text, entity_types):
            return []
        monkeypatch.setattr(_extract_mod, "_extract_gliner", mock_gliner)

        def mock_llm(text, llm_config):
            return []
        monkeypatch.setattr(_extract_mod, "_extract_llm", mock_llm)

        config = LLMConfig(provider="openai")
        # Should not raise
        entities = extract("test", backend="auto+llm", llm_config=config)
        assert isinstance(entities, list)
