# Record resolution API

## `crosswalk(list_a, list_b, *, entity=None, comparators=None, tf=None, decl=None, **kwargs)`

Link two record lists. Supply one of the following:

- `entity` for a built-in comparator pack
- `comparators` for explicit comparison specifications
- `decl` for a declared schema

```python
from arche.resolve import crosswalk

list_a = [{"id": "a1", "name": "Kano Central PHC", "lat": "12.0022", "lon": "8.5920"}]
list_b = [{"id": "b1", "name": "Kano Central Primary Health Centre",
           "lat": "12.0024", "lon": "8.5918"}]

result = crosswalk(list_a, list_b, entity="place", id_field="id")
```

The result has this shape:

<!-- docs-test: fragment -->
```python
{
    "matches": [
        {
            "a_id": "left-record-id",
            "b_id": "right-record-id",
            "decision": "match",  # or "review"
            "score": 0.0,
            "evidence": {},
            "decision_id": "dec:sha256:...",
        },
    ],
    "count": 1,
    "pins": {},
    "blocking": {},
}
```

Key options include `threshold`, `review_margin`, `id_field`, and `truth_pairs`. Candidates below `threshold - review_margin` are omitted. A candidate that otherwise reaches `match` can be downgraded to `review` by a conflict or a distinctive-evidence gate.

Read the [decision contract](decision-contract.md) before sending these results to a downstream workflow.

## `pairwise(a, b, *, entity="person", **kwargs)`

Resolve one direct person pair.

```python
from arche.resolve import pairwise

decision = pairwise(
    "Fatima Abdullahi, NIN 12345678901",
    "Fatuma Abdulahi, NIN 12345678901",
)
print(decision.identity)
```

`decision.identity` is `same_entity`, `review`, or `different`. This is a different contract from `crosswalk()` and its labels should not be treated as interchangeable.

## Signing crosswalk edges

Use `sign_edges()` to sign selected crosswalk candidates. The signed payload contains the edge and the run pins, allowing a recipient to verify the artifact and recompute its decision identifier.

```python
from arche.resolve.reconcile import sign_edges
from arche.sign import generate_keypair

keypair = generate_keypair()
signed = sign_edges(result, private_key=keypair.private_key, kid=keypair.did_key)
assert signed
```

Read the source and tests for the complete current parameter contract. Alpha APIs can change between releases.
