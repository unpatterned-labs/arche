# Interpret a decision

`crosswalk()` returns candidate edges with two labels.

| Label | Meaning | Appropriate action |
|---|---|---|
| `match` | The candidate cleared the configured score and evidence gates. | Apply only under a policy that accepts the measured risk. |
| `review` | The candidate is plausible but lacks sufficient evidence for an automatic link. | Send to an accountable review process. |

Pairs that fall below the review floor are not included in the result. They are
not labelled `different`, because the resolver did not make a negative identity
claim about them.

## Score is not a probability

Treat `score` as an internal ranking signal. It is useful for prioritising
review, but it is not a statement that two records have a particular
probability of being the same entity.

Inspect the evidence instead:

```python
for edge in result["matches"]:
    print(edge["decision"])
    print(edge["evidence"])
    print(edge["decision_id"])
```

The `decision_id` ties the decision to the evidence and run settings. Persist
the source identifiers and those settings with any downstream action.

## Pairwise is a different contract

`pairwise(a, b)` answers a direct person-resolution question. Its identity
field uses `same_entity`, `review`, or `different`. Do not mix those labels
with crosswalk edge labels without translating the meaning for your users.

## Agent use

An agent may extract fields, propose candidates, or explain returned evidence.
It must not silently convert `review` to `match`. Give the agent a constrained
tool call, redacted inputs by default, and an explicit escalation path for
human review.

To record reviewer outcomes and evaluate a labelled crosswalk, see [review and
evaluate a crosswalk](review-and-evaluate.md).
