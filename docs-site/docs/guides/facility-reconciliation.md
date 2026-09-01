# Reconcile health facilities

Health-facility reconciliation is a good place-resolution workflow because a wrong merge can remove a clinic from an allocation, while a missed link leaves two records to be reviewed. Both risks matter.

The [facility reconciliation notebook](https://github.com/unpatterned-labs/arche/blob/main/examples/notebooks/01_facility_reconciliation.ipynb) walks through public Nigerian facility data. It builds two lists, runs `reconcile(..., entity="place")`, inspects the evidence, and separates automatic matches from a review queue.

## What to look for

- Facility names often mix a distinctive local name with a generic type such as Health Post or Primary Health Centre.
- Coordinates support a decision but must not manufacture one.
- A geographic conflict should route a candidate to `review`, not silently turn it into a non-match.
- Source lineage matters. Agreement between datasets with a shared upstream source is a consistency check, not independent validation.

## Run it locally

```bash
cd examples/notebooks
uv run --package arche-core jupyter notebook 01_facility_reconciliation.ipynb
```

The notebook uses the facility data stored in this repository. It is a worked example, not a claim that the resulting crosswalk is a national master facility list.

## Review candidates

The current Kano, Ondo, and Edo baseline records candidate and review counts, not accuracy claims. Reviewers should complete the outcome, reviewer, UTC time, and reason for each candidate without changing its original evidence or `decision_id`.

| Outcome | Meaning |
| --- | --- |
| `same_entity` | The two records refer to one physical facility. |
| `different` | The records refer to separate facilities. |
| `unresolved` | The available evidence does not support either claim. |

Confirm administration and distance, compare the distinctive part of the name, and check stable facility codes and source dates where available. Escalate a closure, relocation, duplicate source row, or unclear provenance rather than forcing a binary result.

Use the [local review log](review-log.md) to filter candidates, inspect their evidence, and download a separately labelled copy. It does not overwrite the original adjudication pack.

The [place validation plan](https://github.com/unpatterned-labs/arche/blob/main/data/PLACE_VALIDATION_PLAN.md) contains the pinned Nigeria baseline, the 360-pair sample location, and the UK, US, and schools next-stage plan.

## Make it operational

Before using an automatic match in an allocation, define:

1. The canonical source that wins when sources disagree.
2. The policy for `match`, `review`, and unreturned pairs.
3. The reviewer who can confirm or reject a candidate.
4. The audit record retained with the downstream decision.

The matcher can identify and explain disagreement. It cannot decide the governance question of which source is authoritative.

See the [notebook release evidence](https://github.com/unpatterned-labs/arche/blob/main/examples/notebooks/RELEASE_EVIDENCE.md) for the data sources, execution check, and scope of this example.
