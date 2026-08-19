# Notebook release evidence

This record states what was exercised for the alpha documentation. It is not a
claim that the examples establish production accuracy in another population or
workflow.

## Environment

- Package: `arche-core` 0.4.0a3 from this workspace
- Date checked: 2026-08-19
- Runner: `uv run --package arche-core`
- Execution method: `nbclient`, with each code cell completing successfully
- Timings: local development timings only. They are not performance targets.

## Exercised notebooks

| Notebook | Data in this repository | Run location and command | Evidence from the check | Scope |
| --- | --- | --- | --- | --- |
| `01_facility_reconciliation.ipynb` | `data/GRID3_NGA_health_facilities_v2.csv`, `data/osm_kano.csv` | From `examples/notebooks`: `uv run --package arche-core jupyter notebook 01_facility_reconciliation.ipynb` | 9 code cells completed in 39.4 seconds. The run refreshed `review_queue.csv`. | Worked Nigerian facility example. It is not a national master facility list or an accuracy benchmark. |
| `02_same_person_across_documents.ipynb` | `data/docs/*.pdf` | From `examples/notebooks`: `uv run --package arche-core jupyter notebook 02_same_person_across_documents.ipynb` | 3 code cells completed in 148.5 seconds. | Demonstrates extraction and person-resolution reporting. It is not a person-resolution benchmark. |
| `07_places_on_a_public_benchmark.ipynb` | `data/er_bench/places/settlements.json`, `data/er_bench/places/combinedSettlements_perfectMatch.json` | From repository root: `uv run --package arche-core jupyter notebook examples/notebooks/07_places_on_a_public_benchmark.ipynb` | 11 code cells completed in 105.9 seconds. | Public place benchmark. Its result is specific to this candidate set and decision policy. |
| `09_matching_products.ipynb` | `data/er_bench/products/Abt.csv`, `Buy.csv`, `Abt_Buy_perfectMapping.csv`, plus the vendored Amazon-Google data | From repository root: `uv run --package arche-core jupyter notebook examples/notebooks/09_matching_products.ipynb` | 13 code cells completed in 368.5 seconds after splitting its long benchmark comparisons into separate cells. On Abt-Buy: 1,012 candidates, 750 automatic matches, 262 review candidates, precision 0.9707, recall 0.6636, F1 0.7883, and 22 false merges. | Experimental product lane. Do not generalise these figures to other catalogues. |

## Reproduction notes

- The facility and document notebooks use relative paths that require
  `examples/notebooks` as the working directory.
- The public-benchmark notebooks are intended to run from the repository root.
- Notebook `11_places_and_products_tour.ipynb` is a short orientation notebook,
  not part of this primary evidence set. It completed its five code cells in
  the same local environment.
- Re-run the relevant notebook after changing comparison rules, vendored data,
  or the decision policy. Record the new package version and results before
  making an accuracy claim.
