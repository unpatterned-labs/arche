# Resolve two lists

This example links a facility registry to a survey. Each list has a stable row
identifier, a name, and coordinates. The same approach works for other entity
packs when their relevant fields are present.

```python
from arche.resolve import crosswalk

registry = [
    {
        "id": "registry-1",
        "name": "Karfi Health Post",
        "lat": "11.62",
        "lon": "8.49",
    },
]

survey = [
    {
        "id": "survey-7",
        "name": "Karfi Health Post",
        "lat": "11.62",
        "lon": "8.49",
    },
]

result = crosswalk(registry, survey, entity="place")

for edge in result["matches"]:
    print(edge["a_id"], edge["b_id"], edge["decision"])
```

The returned candidate is labelled `match` when it clears both the score
threshold and the distinctive-evidence gate.

```text
registry-1 survey-7 match
```

## Read the result before acting on it

`result["matches"]` contains only candidates that reached the review floor.
Each edge contains:

- `a_id` and `b_id`, the source record identifiers
- `decision`, either `match` or `review`
- `score`, a model score and not a calibrated probability
- `evidence`, the per-field comparison results
- `decision_id`, a reproducible identifier for the evidence and run settings

Pairs below the review floor are not returned. Their absence is not proof that
the records describe different entities.

Use `review` as a queue for an accountable human or business process. Do not
promote it to a match solely because its score is high.

## Next steps

- [Prepare your data](../guides/prepare-data.md)
- [Interpret a decision](../guides/interpret-decisions.md)
- [See places and products in action](../guides/places-and-products.md)
- [Read the record-resolution reference](../reference/record-resolution.md)
