# Place validation plan

This plan separates a useful reconciliation exercise from an accuracy claim.
Every new lane needs a pinned source snapshot, a declared entity contract, and
labels suitable for the metric being reported.

## First lane: Nigeria health facilities

### Current local inputs

- `GRID3_NGA_health_facilities_v2.csv`: national facility master snapshot with
  51,022 rows, NHFR identifiers, administration, type, and coordinates.
- `hfr_kano.csv`: 1,561 HFR rows.
- `hfr_ondo.csv`: 1,025 HFR rows.
- `hfr_edo.csv`: 972 HFR rows.

The GRID3 file describes its facility-name source as `NHFR_2024`. Therefore a
GRID3 to HFR run is a snapshot-reconciliation and data-quality exercise, not
independent evidence of matching accuracy.

### Run the current reconciliation

Run to a directory outside the repository so generated review artifacts do not
become unexamined source data:

```bash
uv run --package arche-core python data/scripts/evaluate_facility_master.py --state Kano --output C:\tmp\arche-kano-evaluation
```

Repeat for `Ondo` and `Edo`. Each run writes:

- `summary.json`: input hashes, engine pins, blocking, and coverage counts.
- `candidate_edges.csv`: every surfaced `match` and `review` edge.
- `adjudication_sample.csv`: a deterministic, decision-balanced review sample.

### Current pinned baseline

The 2026-08-19 baseline used `crosswalk(..., entity="place")` with threshold
0.70, review margin 0.15, distinctive floor 0.75, union blocking, and the
shipped place frequency and phrase tables. The local input hashes were:

| Input | SHA-256 |
| --- | --- |
| `GRID3_NGA_health_facilities_v2.csv` | `0affbed54ecc15b62324e2442341bbb2860ffc982747c4a4f29a9c293f88ee5b` |
| `hfr_kano.csv` | `30b8b4252054827db65f4cd6cd4a9a1703ea5663ed57a964f9c2bd0a0b4f612d` |
| `hfr_ondo.csv` | `b558da7da0b8942471cd60a6fc69da282405623db61c3442d661811285c98eb7` |
| `hfr_edo.csv` | `e9026a5d525906ffc52eec9fc8c769f92d9ac006a5e1f909648ce3df9ecd7492` |

| State | GRID3 rows | HFR rows | Candidate pairs scored | Returned edges | `match` edges | `review` edges |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Kano | 1,723 | 1,561 | 111,249 | 2,538 | 1,349 | 1,189 |
| Ondo | 1,096 | 1,025 | 43,131 | 2,203 | 906 | 1,297 |
| Edo | 1,069 | 972 | 78,040 | 2,322 | 880 | 1,442 |

These are candidate-edge counts, not unique reconciled facilities or accuracy
metrics. The GRID3 file names `NHFR_2024` as its facility-name source, so this
is a snapshot-reconciliation exercise rather than independent validation.

### Review sample

`review_packs/nigeria_facilities_2026-08-19/adjudication_pack.csv` contains
360 deterministic samples: 60 `match` and 60 `review` edges for each state.
Its `manifest.json` hashes the complete decision-ID set.

Reviewers must record `same_entity`, `different`, or `unresolved`, with a
reviewer identifier, UTC time, and reason. Do not edit the original score,
evidence, decision, source fields, or `decision_id`. Only a complete or
predeclared sampled label set can support a precision claim. Recall requires a
complete mapping of true pairs in the evaluation population.

### Independent comparison sources

The Nigeria Health Facility Registry is the official national registry. Use it
as the operating master where the responsible authority confirms that role.
OpenStreetMap may reveal coverage gaps and location conflicts, but inspect
feature provenance before calling it independent evidence. The future evidence
pack should retain source retrieval date, licence, source URL, and a content
hash for every snapshot.

## Second health-facility lane: United Kingdom

Start with a narrowly defined entity, such as an NHS hospital site or GP
practice site, not every organisation in the NHS. Sites, organisations,
departments, and services are different entities and must not be merged under
one generic `healthcare` rule.

Candidate source roles:

| Role | Source | Use |
| --- | --- | --- |
| Operating reference | NHS Organisation Data Service reference data | Official organisation and site identifiers where available. |
| Regulatory comparison | Care Quality Commission location data | Separately managed location and provider information. |
| Geographic enrichment | Ordnance Survey and OpenStreetMap | Address, postcode, and coordinate checks. Do not assume independent lineage. |

The first UK pilot should select one nation and one service type, preserve ODS
codes and CQC location IDs, and route organisational relationships such as a
provider operating several sites to a separate relationship model.

## Third health-facility lane: United States

Use Medicare-certified hospitals only for the first US lane. CMS publishes the
Hospital General Information dataset with a CMS Certification Number, name,
address, phone, ownership, and hospital type. It is a bounded, official,
machine-readable reference with a defined coverage limit.

Compare it to a separately collected source only after verifying the second
source's collection method and licence. Do not describe a directory that
repackages CMS as independent validation.

## Second place type: United Kingdom schools

Use schools after the health-facility workflow has a reviewed evidence pack.
The entity contract should be a school establishment at a physical site, not an
academy trust, governing body, or predecessor school. Those are related but
different entities.

The Department for Education's Get Information About Schools service is the
operating reference for England. It exposes daily downloads and uses stable
URN, LAESTAB, and UKPRN identifiers. Pair it first with a source that can be
shown to have independently collected location data. Treat academy conversion,
relocation, closure, and predecessor-successor links as explicit states, not
matching errors.

## Gates before a public accuracy claim

1. Pin source files and document their lineage and licence.
2. Predeclare the entity contract, decision policy, and label definitions.
3. Label difficult matches, reviews, and likely misses with accountable domain
   reviewers.
4. Report precision, false merges, recall where mapping is complete, review
   rate, and blocking recall.
5. Slice results by geography, urbanicity, entity type, name commonness, and
   missing coordinates.
6. Publish limits and unresolved cases alongside the headline result.

## Source starting points

- Nigeria HFR: https://hfr.fmohconnect.gov.ng/
- GRID3 Nigeria data: https://grid3.org/
- UK school establishments: https://get-information-schools.service.gov.uk/
- US hospital reference: https://data.cms.gov/provider-data/dataset/xubh-q36u
