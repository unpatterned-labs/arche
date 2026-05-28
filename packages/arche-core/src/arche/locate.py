# Copyright 2026 unpatterned labs
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Location intelligence — enrich LOCATION entities with coordinates from the African gazetteer.

Usage:
    from arche.extract import extract
    from arche.locate import locate
    entities = extract("Meeting in Lagos and Nairobi next week.")
    locations = locate(entities)
    for loc in locations:
        print(loc.name, loc.country, loc.lat, loc.lng)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .extract import Entity

_log = logging.getLogger("arche")


@dataclass
class Location:
    """A geocoded location with coordinates, H3 cell, and metadata."""

    name: str
    country: str
    country_name: str
    region: str
    lat: float
    lng: float
    confidence: float
    source: str = "gazetteer"  # "gazetteer", "entity_extraction"
    h3_cell: str = ""  # H3 hexagonal cell index at resolution 5

    def __repr__(self) -> str:
        h3_str = f", h3={self.h3_cell[:12]}..." if self.h3_cell else ""
        return (
            f"Location(name={self.name!r}, country={self.country!r}, "
            f"lat={self.lat:.4f}, lng={self.lng:.4f}{h3_str})"
        )


# ===================================================================
# Public API
# ===================================================================


def locate(entities: list[Entity]) -> list[Location]:
    """Enrich LOCATION entities with coordinates from the African gazetteer.

    Parameters
    ----------
    entities:
        A list of extracted entities from :func:`arche.extract.extract`.
        Only entities with ``entity_type == "LOCATION"`` are processed.

    Returns
    -------
    list[Location]
        Geocoded locations. Entities that could not be matched against the
        gazetteer are returned with zero coordinates and ``source="entity_extraction"``.
    """
    location_entities = [e for e in entities if e.entity_type == "LOCATION"]
    if not location_entities:
        return []

    locations: list[Location] = []
    for ent in location_entities:
        loc = _geocode(ent.text, ent.confidence)
        if loc is not None:
            locations.append(loc)

    return locations


# ===================================================================
# Geocoding logic
# ===================================================================


def _geocode(place_name: str, entity_confidence: float) -> Location | None:
    """Attempt to geocode a place name using the African gazetteer, with fallback."""
    # Try the African gazetteer first
    try:
        from .addr._gazetteer.cities import geocode_african_location

        result = geocode_african_location(place_name)
        if result is not None:
            h3_cell = getattr(result, "h3_cell", "")
            # Compute H3 cell if not already set
            if not h3_cell and result.lat != 0.0 and result.lng != 0.0:
                try:
                    from .addr._gazetteer.cities import latlng_to_h3
                    h3_cell = latlng_to_h3(result.lat, result.lng)
                except Exception:
                    pass

            return Location(
                name=result.name if hasattr(result, "name") else place_name,
                country=result.country if hasattr(result, "country") else "",
                country_name=result.country_name if hasattr(result, "country_name") else "",
                region=result.region if hasattr(result, "region") else "",
                lat=float(result.lat) if hasattr(result, "lat") else 0.0,
                lng=float(result.lng) if hasattr(result, "lng") else 0.0,
                confidence=result.confidence if hasattr(result, "confidence") else 0.85,
                source="gazetteer",
                h3_cell=h3_cell,
            )
    except ImportError:
        pass
    except Exception as e:
        _log.debug("Geocoding failed for '%s': %s", place_name, e)

    # Fallback: return the entity as a location without coordinates
    return Location(
        name=place_name,
        country="",
        country_name="",
        region="",
        lat=0.0,
        lng=0.0,
        confidence=entity_confidence * 0.5,  # Lower confidence without geocoding
        source="entity_extraction",
    )
