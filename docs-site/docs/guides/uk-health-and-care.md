# Prepare health and care locations in England

Use a regulated location, not a generic health-care organisation, as the first
entity. The Care Quality Commission (CQC) directory provides location and
provider IDs, names, addresses, postcodes, and service types under the Open
Government Licence.

This is a source-preparation guide. It does not claim that each CQC location
is a physical care site or that a later match is correct.

## Pick one service type

The CQC location directory includes doctors and GPs, homecare agencies,
dentists, residential homes, hospitals, and other services. Choose one exact
service type for each lane. For example, use `Hospital` for a first hospital
location lane. Do not mix provider organisations, home-care management bases,
and hospital sites in one matching population.

## Stage a pinned export

Open the CQC [data access page](https://www.cqc.org.uk/about-us/transparency/using-cqc-data), download the current **CQC care directory** CSV, and copy its
exact download URL into this command:

```powershell
$sourceUrl = "https://www.cqc.org.uk/system/files/2026-08/19_August_2026_CQC_directory.csv"
uv run python data/scripts/stage_cqc_care_directory.py --url $sourceUrl --service-type Hospital --output C:\tmp\arche-cqc-hospitals-2026-08-19
```

The date-stamped URL above is an example from 19 August 2026, not a permanent
download endpoint. Always get the live URL from CQC, then retain it in the
output manifest.

The command writes three files:

- `cqc_care_directory.csv`: untouched CQC export.
- `cqc_locations.csv`: selected service-type records, retaining CQC location
  ID, provider ID, address, postcode, and source fields.
- `manifest.json`: source URL, licence, reported production date, retrieval
  time, record counts, and SHA-256 hashes.

For the 19 August 2026 example, the `Hospital` selection contains 782 CQC
locations. It is a source population, not a count of physical hospitals.

## Before matching

Check that the comparison source represents the same entity and has its own
collection method. Preserve CQC location IDs and provider IDs as source
identifiers. A provider can operate many locations; that is a relationship,
not evidence that the locations are the same place.

Use the [facility reconciliation guide](facility-reconciliation.md) for the
candidate, evidence, and review workflow. The [place validation plan](https://github.com/unpatterned-labs/arche/blob/main/data/PLACE_VALIDATION_PLAN.md)
sets the evidence required before publishing an accuracy claim.
