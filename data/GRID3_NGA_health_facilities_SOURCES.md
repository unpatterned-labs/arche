# GRID3 Nigeria health facilities — sources & attribution

`GRID3_NGA_health_facilities_v2.csv` is the file in this directory and the stratum behind the shipped place frequency and bigram tables. CIESIN has since superseded it with **v4.0**, which is **not in this repository**: adopting it is a change of its own, and the second half of this file is the attribution and the findings it will need when that happens.

Both releases are CC BY 4.0, which the licence policy in `datasets/places_dataops/SOURCES.md` admits, and under CC BY attribution is a condition of the licence rather than a courtesy. That is what this file is for.

## `GRID3_NGA_health_facilities_v2.csv` — 51,022 facilities

- **Source:** GRID3 NGA – Health Facilities v2.0, Center for Integrated Earth System Information (CIESIN), Columbia University.
- **Citation:** Center for Integrated Earth System Information (CIESIN), Columbia University. 2024. *GRID3 NGA - Health Facilities v2.0.* New York: GRID3. https://doi.org/10.7916/kv1n-0743.
- **Licence:** Creative Commons Attribution 4.0 International (CC BY 4.0), https://creativecommons.org/licenses/by/4.0. Use, adaptation and redistribution are permitted, commercially included, with clear attribution of the source.
- **Copyright:** 2024 The Trustees of Columbia University in the City of New York.
- **Status:** superseded upstream by v4.0 by the publisher's own statement. `last_updated` 2024-11-11.
- **Modifications:** none to content.
- **Read by:** `datasets/places_dataops/build_place_frequencies.py` and `build_place_bigrams.py`, both of which take `facility_name` only.

### Why v2.0 stays even once v4.0 is adopted

Beyond being the current stratum, it is pinned by two recorded benchmark results, and deleting it would make them unreproducible rather than merely stale:

- `data/scripts/evaluate_facility_master.py` defaults to it and writes its **sha256 into the result file**, so the file itself is part of the record.
- `examples/notebooks/build_05.py` uses it for the Kano GRID3/OpenStreetMap comparison whose 59% coordinate-agreement finding is quoted in `data/er_bench/places/SOURCES.md`.

Both read v2.0 on purpose and should go on doing so; neither is a pack input, so neither is affected by which release the strata use.

### Two quality columns in v2.0 that nothing reads

`lga_name_disagreement` is set on 950 records and `ward_name_disagreement` on 7,764. Nothing in the codebase reads either. v4.0's `dist_ward_grid3_bdry_km` and `ward_bdry` are the same signal, measured rather than flagged.

Separately, `nhfr_facility_code` is **not** a key in v2.0: 34,541 non-empty values hold only 32,501 distinct codes, 497 codes are shared by more than one record, and one code is carried by 54 records.

## GRID3 NGA Health Facilities v4.0 — the release to adopt, not in this repository

Attribution first, because it is a condition of the licence and the measurements below are derived from the data.

- **Source:** GRID3 NGA – Health Facilities v4.0, CIESIN, Columbia University.
- **Citation:** Center for Integrated Earth System Information (CIESIN), Columbia University. 2026. *GRID3 NGA - Health Facilities v4.0.* New York: Columbia University. https://doi.org/10.7916/pjpv-9q55. Accessed 9 November 2026.
- **Licence:** CC BY 4.0, https://creativecommons.org/licenses/by/4.0.
- **Copyright:** 2026 The Trustees of Columbia University in the City of New York.
- **Funding, as the publisher asks it be recorded:** development and dissemination funded by GRID3 under the Gates Foundation project INV-044979. CIESIN credits input from, among others, the Federal Ministry of Health and Social Welfare, NPHCDA and state primary health care boards, NMEP, NERICC, WHO, CDC, eHealth Africa, Catholic Relief Services, Clinton Health Access Initiative, Malaria Consortium, Pathfinder International, Society for Family Health, Fact Foundation, Natview Foundation, Novel-T and Proxy Logics. The full acknowledgement list is on the dataset's own item page.
- **Release notes / data dictionary:** linked from the item description; the codebook is Table 7 and the harmonisation method is Section II.

### How to fetch it

The bytes are deliberately not vendored — 21.6 MB of CSV that nothing reads would sit in history forever. It is 70,235 records over 36 attribute fields, and this recipe reproduces exactly what the measurements below were taken from:

Page the published feature service's attribute table at

    https://services3.arcgis.com/BU6Aadhn6tbBEdyk/arcgis/rest/services/GRID3_NGA_Health_Facilities_v4_0/FeatureServer/0

with `where=1=1`, `outFields=*`, `returnGeometry=false`, `orderByFields=objectid ASC`, and `resultOffset` stepping by 2000 (`maxRecordCount` is 2000 and `supportsPagination` is true, so 36 pages). Expect an occasional 503; retry with backoff. Write the attributes in the service's own field order, sorted by `OBJECTID`, as UTF-8 with LF endings. Geometry can be skipped because `latitude`/`longitude` carry the same coordinates.

That yields the file unmodified in content. Note that 11 records contain newlines inside quoted fields and a few carry trailing spaces inside quoted facility names; both are in the source and should be preserved rather than cleaned.

### What to read from it, and what not to

When it becomes a stratum, only `facility_name` should be read, as for v2.0. **`alt_name` must not be used as a name field.** Of its 28,188 non-empty values, 24,989 are the strings `Yes` or `No`, a further ~142 are `Nil`/`Nill`/`None`/`NON`/`0`, and 214 are the ownership values `Private`/`Public` leaked in from another column. About 2,800 values remain and are mostly generic facility types (`Dispensary`, `Health Post`, `General Hospital`) rather than alternate names. Feeding the column to the frequency table would make `no` and `yes` common place tokens.

### Quality signals it carries that v2.0 does not

- `ward_standard` vs `ward_bdry` — the ward label against the ward the coordinates actually fall inside. They disagree on 15,966 of the 67,528 records where both are populated (23.6%).
- `dist_ward_grid3_bdry_km` — 0 on 48,891 records, positive on 9,638, null on the 11,706 with no coordinates.
- `gps_accuracy` — per-record positional precision on 25,829 records (36.8%); median 8 m, p90 10 m, max 12,455 m.
- `flag1`..`flag6`, `issues`, `flag_count` — publisher quality flags. 40,259 records are unflagged; the common issues are `missing xy coordinates` (11,706), `cluster with another point in 50m/100m` (~11,000) and `outside of ward boundary` (5,846).
- `input_data_record_ids` / `input_data_sources` — the input records harmonised into each facility. 37,611 facilities (53.55%) merge two or more.
- `ward_in_grid3_ward_list` — 3,759 records carry a ward name absent from the GRID3 harmonised ward list.
- `unique_id` — a **stable** key, unlike v2.0's `globalid`. See the crosswalk section below.

### Known limitations, as the publisher states them

11,706 records (16.7%) were retained without spatial information and have null `latitude`/`longitude`. The dataset is non-exhaustive and has not been fully validated by government or in-country stakeholders. Temporal mismatch against reference imagery and settlement polygons may mean facilities are missed or abandoned ones included.

## There is no crosswalk from v4.0's record ids back to v2.0

v4.0's `input_data_record_ids` carries `grid3v2_`-prefixed tokens — 44,941 of them, one per v2.0 record that survived into v4.0, with 6,081 v2.0 records dropped. It is tempting to read these as a published mapping onto the rows in `GRID3_NGA_health_facilities_v2.csv`. They are not one.

Release notes Section 2.2: *"A unique identifier was created by combining the source data acronym (e.g. `nphcda`) with a randomly generated 10-character alphanumeric string (e.g. `nphcda_A94X2B7KQ1`)."*

The tokens are random by construction, minted during harmonisation, and no column of v2.0 derives them. Checked rather than assumed: the observed 155,330 tokens are uniform over `0-9A-F` to within 0.4%, and no hash of any v2.0 field reproduces one (15 field variants — `globalid` in six spellings, `nhfr_uid`, `nhfr_facility_code`, `OBJECTID`, name, coordinates and composites — against 11 digest functions, both hex cases: 0 hits in 4,000 records). Direct slices of `globalid` also miss.

They are stable *forward*: every one of the 1,523 `grid3v2_` tokens in a 2,000-record sample of v3.0 reappears in v4.0, and `unique_id` values are identical across the two releases. So adopting v4.0 gives arche a durable primary key for future releases, which v2.0's `globalid` never offered. It does not give a route back to v2.0.

The practical consequence is in `datasets/places_dataops/SOURCES.md` under "The adjudicated duplicate set that cannot be used".
