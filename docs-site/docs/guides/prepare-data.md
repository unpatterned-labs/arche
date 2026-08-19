# Prepare your data

Start with two explicit lists. Give every row a stable `id`; use the same
field name in both lists where possible.

```python
left = [{"id": "left-1", "name": "Karfi Health Post", "lat": 11.62, "lon": 8.49}]
right = [{"id": "right-7", "name": "Karfi Health Post", "lat": 11.62, "lon": 8.49}]
```

## Include evidence, not just a name

A name alone is rarely enough. Include the fields that can distinguish one
entity from another.

| Entity | Useful fields |
|---|---|
| Person | name, verified identifier, date of birth, phone, email |
| Place | name, coordinates, address, administrative area, facility type |
| Organisation | name, registration number, address, phone, website |
| Product | brand, model code, GTIN or MPN, variant attributes |

Use only fields you are permitted to process. A field should be accurate enough
to support a decision and traceable back to its source.

## Choose the relation before matching

For alpha, `crosswalk()` asks a narrow question: should these two records be
treated as the same entity? Do not use it to represent related but distinct
relationships such as supplier and brand, product family and product variant,
or compatible products.

Those distinctions are particularly important for future product matching. An
exact variant match, a family match, a substitute, and a bundle relationship
need different labels, evidence, and evaluation.

## Start with a labelled sample

Before processing a full dataset:

1. Sample likely matches and likely non-matches.
2. Have domain reviewers label them independently.
3. Measure false merges separately from missed matches.
4. Set the review process and its capacity before automation.

Accuracy only transfers when the target data, decision rule, and review process
are comparable to the evaluation data.
