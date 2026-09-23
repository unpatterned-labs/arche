<!-- superseded by reference/python-api.md and how-it-works/backends.md on 2026-09-20; kept as working material, not built -->
# Record resolution API

## `reconcile(list_a, list_b, *, entity=None, comparators=None, tf=None, decl=None, store=None, **kwargs)`

Link two record lists. Supply one of the following:

- `entity` for a built-in comparator pack
- `comparators` for explicit comparison specifications
- `decl` for a declared schema

```python
from arche.resolve import reconcile

list_a = [{"id": "a1", "name": "Kano Central PHC", "lat": "12.0022", "lon": "8.5920"}]
list_b = [{"id": "b1", "name": "Kano Central Primary Health Centre",
           "lat": "12.0024", "lon": "8.5918"}]

result = reconcile(list_a, list_b, entity="place", id_field="id")
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
    "backend": {"chosen": "arche", "reason": "...", "records": 0, "floor": 1000},
}
```

Key options include `threshold`, `review_margin`, `id_field`, and `truth_pairs`. Candidates below `threshold - review_margin` are omitted. A candidate that otherwise reaches `match` can be downgraded to `review` by a conflict or a distinctive-evidence gate.

### Which scorer ran

`backend` defaults to `"auto"`: arche's own engine below `AUTO_SPLINK_FLOOR` (1,000 records), and above it a shipped Splink recipe from `arche.resolve.recipes` when the entity has one, Splink is installed (`arche-core[resolve]`), and the records carry the recipe's columns. Otherwise the engine. `result["backend"]` says which was chosen and why, in words; it is on the result rather than in the pins because *which* scorer ran is already pinned and hashed into every `decision_id`, while *why it was chosen* names the batch size and must not move an id.

The floor is measured, not chosen: on the supplier world the two are level on false merges at 444 and 1,215 records, and by 3,081 the engine merges 456 wrong pairs to Splink's 49. It is a precision floor: the engine runs that batch in under a minute. See [Benchmarks](benchmarks.md#the-recipe-arche-ships-instead-and-the-gate-that-holds-it).

Today one recipe ships, `person/febrl-v1`, and it reads `given_name` and `surname` as two columns. A `person` caller with one `name` blob stays on the engine at every size and `result["backend"]["reason"]` says so. `backend="arche"` is the engine regardless; `backend="splink"` is Splink regardless and needs `splink_settings=`.

Read the [decision contract](decision-contract.md) before sending these results to a downstream workflow.

## `compare(a, b, *, entity="person", store=None, **kwargs)`

Resolve one direct person pair.

```python
from arche.resolve import compare

decision = compare(
    {"name": "Fatima Abdullahi", "national_id": "12345678901"},
    {"name": "Fatuma Abdulahi", "national_id": "12345678901"},
)
print(decision.identity)
```

`decision.identity` is `same_entity`, `review`, or `different`. This is a different contract from `reconcile()` and its labels should not be treated as interchangeable. Structured records take the deterministic resolution path; passing free text instead first invokes document extraction and therefore requires an extraction backend.

## `store=`

Every verb accepts `store=`, a `Ledger` from `arche.attach("duckdb:///...")`. The return value is unchanged; the receipt is additionally recorded with the inputs it was made from, so it can be looked up by `decision_id`, replayed, and joined with other receipts into entities. See [Keep, explain, replay](../guides/keep-and-replay.md).

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
