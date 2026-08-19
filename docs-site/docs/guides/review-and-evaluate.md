# Review and evaluate a crosswalk

Use this workflow to turn a crosswalk into evidence for a decision policy. It
does not make a score a probability, and it does not allow a reviewer or agent
to silently change a result.

The runnable [review and evaluation notebook](https://github.com/unpatterned-labs/arche/blob/main/examples/notebooks/12_review_feedback_and_evaluation.ipynb)
uses two facility candidates to show the complete loop.

## 1. Preserve the run artifact

Keep the full `crosswalk()` result. In particular, retain each candidate's
`decision_id`, `evidence`, and `pins` alongside the source IDs. The ID binds a
review outcome to the candidate that was actually considered.

## 2. Capture review outcomes separately

For every reviewed edge, store a small, append-only record. Use the identity
claim rather than a replacement score or a replacement `crosswalk` decision.

```json
{
  "schema": "arche.review_outcome.v1",
  "decision_id": "xwd:sha256:...",
  "outcome": "different",
  "reviewer": "facility-steward-17",
  "reviewed_at": "2026-08-19T10:00:00Z",
  "reason": "The facilities share a generic name but are different sites."
}
```

Allowed outcomes are:

| Outcome | Meaning | Use in evaluation |
| --- | --- | --- |
| `same_entity` | The reviewer confirms one real-world entity. | A labelled positive pair. |
| `different` | The reviewer confirms separate entities. | A hard negative pair. |
| `unresolved` | The reviewer cannot make a supported claim. | Keep it out of the labelled set. |

Require a non-empty reviewer identifier, UTC review time, and reason. Keep any
links to authoritative source checks in your own case-management system rather
than placing sensitive values in this artifact.

An agent may prepare this record, validate its schema, or retrieve cited
evidence. Only an authorised reviewer may set `same_entity` or `different`.

## 3. Measure against complete labels

`arche.resolve.metrics.evaluate()` reports automatic-match precision, recall,
F1, review queue size, surfaced recall, and false merges.

```python
from arche.resolve.metrics import evaluate

metrics = evaluate(
    result["matches"],
    gold=labelled_same_entity_pairs,
    hard_negatives=labelled_different_pairs,
)
print(metrics)
```

Precision and recall have different label requirements:

- Claim precision only when every automatic match can be checked or the
  labelled set is otherwise a valid, predeclared sample.
- Claim recall only when the true-pair mapping is complete for the evaluation
  population. Reviewing the queue alone cannot reveal missed candidates.
- Report false merges separately. A generic name that is wrongly auto-matched
  is often more costly than a record sent to review.
- Report `review_queue` and `surfaced_recall` so conservative routing is not
  mistaken for an error-free system.

## 4. Publish a pinned evaluation report

Record the dataset version, selection method, matcher pins, decision policy,
label definitions, and every metric together. Re-run the evaluation whenever
the data, representation, blocking, thresholds, or policy changes.

The report is a release gate, not marketing copy. A result that does not meet
the pre-agreed false-merge or review-capacity limit should remain in review or
stop the proposed automatic action.

## Run the example

From the repository root:

```bash
uv run --package arche-core python examples/notebooks/build_12.py
jupyter notebook examples/notebooks/12_review_feedback_and_evaluation.ipynb
```

The example is deliberately small. Its point is the artifact contract and the
measurement discipline, not a claim about facility-resolution accuracy.
