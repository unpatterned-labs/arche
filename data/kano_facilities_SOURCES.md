# Kano health-facility data — sources & attribution

Two **independent** public sources, fetched by `notebooks/fetch_facility_data.py`
for the arche facility-resolution spike. Independence matters: the HFR is
compiled by eHealth Africa partly from GRID-3, so GRID-3 is *not* independent of
it — OpenStreetMap is (crowd-mapped, separate from the registry).

## `hfr_kano.csv` — 1,561 facilities

- **Source:** Nigeria Health Facility Registry (HFR), official Master Facility
  List (Federal Ministry of Health / NPHCDA; data managed by eHealth Africa),
  via the Humanitarian Data Exchange mirror.
- **URL:** https://data.humdata.org/dataset/nigeria-health-facilities
- **License:** Creative Commons Attribution (CC BY).
- **Fields:** id, name, alternate_name, category, lga, ward_code, lon, lat.

## `osm_kano.csv` — 726 facilities

- **Source:** OpenStreetMap health facilities in the Kano state bounding box,
  via the Overpass API.
- **URL:** https://www.openstreetmap.org (© OpenStreetMap contributors)
- **License:** Open Database License (ODbL). Derived databases inherit ODbL;
  attribution required.
- **Fields:** id, name, amenity, healthcare, lga, lat, lon.

Re-fetch: `uv run python notebooks/fetch_facility_data.py`
