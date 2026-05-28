"""Tests for configuration system."""

from arche.config import configure, get_config


def test_default_config():
    config = get_config()
    assert config.gliner_threshold == 0.35
    assert config.similarity_threshold == 0.80
    assert config.max_text_length == 500_000
    assert config.safe_logging is True


def test_configure_changes_values():
    old = get_config().similarity_threshold
    configure(similarity_threshold=0.90)
    assert get_config().similarity_threshold == 0.90
    # Restore
    configure(similarity_threshold=old)


def test_configure_preserves_other_fields():
    old_gliner = get_config().gliner_threshold
    configure(max_text_length=1_000_000)
    assert get_config().gliner_threshold == old_gliner
    # Restore
    configure(max_text_length=500_000)


def test_config_is_frozen():
    import pytest
    config = get_config()
    with pytest.raises(AttributeError):
        config.similarity_threshold = 0.99  # type: ignore


def test_configure_invalid_field():
    import pytest
    with pytest.raises(TypeError):
        configure(nonexistent_field=42)
