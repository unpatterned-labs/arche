"""Tests for H3 spatial indexing integration."""

from arche.addr._gazetteer.cities import (
    AFRICAN_CITIES,
    are_locations_nearby,
    cities_near,
    geocode_african_location,
    latlng_to_h3,
)
from arche.extract import Entity
from arche.locate import Location, locate


def test_all_cities_have_h3_cells():
    """Every city with valid coordinates should have an H3 cell."""
    for city in AFRICAN_CITIES:
        if city.lat != 0.0 and city.lng != 0.0:
            assert city.h3_cell, f"{city.name} missing H3 cell"


def test_h3_cell_format():
    """H3 cells should be valid hex strings."""
    lagos = geocode_african_location("Lagos")
    assert lagos is not None
    assert len(lagos.h3_cell) == 15  # H3 v4 cell format


def test_latlng_to_h3():
    cell = latlng_to_h3(6.5244, 3.3792)  # Lagos
    assert cell  # non-empty
    assert isinstance(cell, str)


def test_nearby_same_city():
    """Two points in the same city should be nearby."""
    assert are_locations_nearby(6.5244, 3.3792, 6.6018, 3.3515)  # Lagos center, Ikeja


def test_nearby_different_countries():
    """Lagos and Nairobi should NOT be nearby."""
    assert not are_locations_nearby(6.5244, 3.3792, -1.2921, 36.8219)


def test_cities_near_returns_results():
    results = cities_near(6.5244, 3.3792)  # Near Lagos
    assert len(results) >= 1
    assert any(c.name == "Lagos" for c in results)


def test_locate_includes_h3():
    """The locate() function should include H3 cells in output."""
    entities = [Entity(text="Lagos", entity_type="LOCATION", confidence=0.9, start=0, end=5)]
    locations = locate(entities)
    assert len(locations) >= 1
    assert locations[0].h3_cell != ""


def test_location_dataclass_h3():
    loc = Location(
        name="Test", country="NG", country_name="Nigeria",
        region="Lagos", lat=6.5, lng=3.4, confidence=0.9,
        h3_cell="85589c9bfffffff",
    )
    assert loc.h3_cell == "85589c9bfffffff"
    assert "h3=" in repr(loc)
