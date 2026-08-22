# Places and products in action

The [places and products notebook](https://github.com/unpatterned-labs/arche/blob/main/examples/notebooks/11_places_and_products_tour.ipynb) is the shortest end-to-end demonstration of arche's record-resolution API. It contains both a small, inspectable example and a run against a public labelled product benchmark.

## What it shows

- A rare shared facility name can clear the automatic-match gate.
- An identical but common facility name can correctly remain in `review`, even when it has the same raw score.
- Two electronics listings with different marketing copy can match on a rare product code.
- The experimental electronics pack can be evaluated on Abt-Buy, where false merges are visible because ground truth is complete.

## Run it locally

From the repository root:

```bash
uv run --package arche-core python examples/notebooks/build_11.py
jupyter notebook examples/notebooks/11_places_and_products_tour.ipynb
```

The notebook uses only repository data. Its full Abt-Buy run processes 1,081 Abt products, 1,092 Buy products, and 1,097 labelled true pairs.

## Scope

The product workflow is experimental and limited to exact electronics-variant matching. It does not establish a general product-matching capability, nor does it identify product families, substitutes, bundles, or compatible products.

For place resolution, `review` is deliberate. A caller needs an explicit review policy before using automatic matches in an operational workflow.
