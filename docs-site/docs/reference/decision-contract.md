# Decision contract

Use the outcome label, evidence, and provenance together. A score alone is not an instruction to merge records.

## Two-list reconciliation

`crosswalk()` compares two collections and returns **candidate edges only** in `result["matches"]`.

| Field | Meaning |
| --- | --- |
| `decision: "match"` | The candidate cleared the configured threshold and gates. It is eligible for the workflow's pre-agreed automatic action. |
| `decision: "review"` | The candidate was surfaced, but evidence or a gate prevents an automatic match. It needs the workflow's review policy. |
| pair not returned | It was not a surfaced candidate. It is not a statement that the records are different. |

Every returned edge includes record IDs, `score`, `evidence`, `decision_id`, and run `pins`. Retain these fields with any downstream decision. A `review` edge must never be silently promoted by a consuming system.

## Direct person decisions

`pairwise()` makes a direct co-reference claim for two person references. It has two separate fields:

| Identity | Recommended action | Meaning |
| --- | --- | --- |
| `same_entity` | `merge` or `hold` | The evidence supports one real-world entity. `hold` means the calling policy has not authorised a merge. |
| `review` | `no_op` | Evidence is insufficient for an identity claim. Present it to an authorised reviewer if the use case requires a decision. |
| `different` | `no_op` | Evidence supports keeping the references separate. |

Do not convert `crosswalk()` labels to `pairwise()` identities, or the reverse. They answer different questions and have different output shapes.

## Rules for pipelines and agents

1. Apply an automated action only to a contractually permitted `match` edge or `same_entity` decision.
2. Preserve `evidence`, `decision_id`, and `pins` in the audit trail.
3. Treat `review` as a stop for automation, not a soft match.
4. Do not cluster pairwise links into entities unless the workflow defines transitivity, conflict handling, and review rules.
5. Do not interpret `score` as a calibrated probability.

See [review and evaluate a crosswalk](../guides/review-and-evaluate.md) for a portable review-outcome shape and the conditions required to make accuracy claims.

This is the alpha consumer contract for `arche-core` 0.4.0a3. Any incompatible change should be called out in the release notes before a downstream system is expected to adopt it.
