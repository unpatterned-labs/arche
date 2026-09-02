# Decision contract

Use the outcome label, evidence, and provenance together. A score alone is not an instruction to merge records.

## Two-list reconciliation

`reconcile()` compares two collections and returns **candidate edges only** in `result["matches"]`.

| Field | Meaning |
| --- | --- |
| `decision: "match"` | The candidate cleared the configured threshold and gates. It is eligible for the workflow's pre-agreed automatic action. |
| `decision: "review"` | The candidate was surfaced, but evidence or a gate prevents an automatic match. It needs the workflow's review policy. |
| pair not returned | It was not a surfaced candidate. It is not a statement that the records are different. |

Every returned edge includes record IDs, `score`, `evidence`, `decision_id`, and run `pins`. Retain these fields with any downstream decision. A `review` edge must never be silently promoted by a consuming system.

## Direct person decisions

`compare()` makes a direct co-reference claim for two person references. It has two separate fields:

| Identity | Recommended action | Meaning |
| --- | --- | --- |
| `same_entity` | `merge` or `hold` | The evidence supports one real-world entity. `hold` means the calling policy has not authorised a merge. |
| `review` | `no_op` | Evidence is insufficient for an identity claim. Present it to an authorised reviewer if the use case requires a decision. |
| `different` | `no_op` | Evidence supports keeping the references separate. |

Do not convert `reconcile()` labels to `compare()` identities, or the reverse. They answer different questions and have different output shapes.

## The engine pin, and when it bumps

Every edge carries `pins`, and `pins` is hashed into `decision_id`. The first entry names the engine:

```json
"pins": {
  "engine": "crosswalk.v1",
  "comparators_sha256": "8d1e03d2...",
  "block": "union",
  "threshold": 0.7,
  "review_margin": 0.15,
  "distinctive_floor": 0.75,
  "tf": "self-calibrated@sha256:372034bf..."
}
```

It is there so a decision read years later says what produced it. That only works if the string means something, so here is what it means.

### What `engine` covers, and what it does not

`crosswalk.v1` names **the shape of the decision**: how comparator scores combine into `score`, what `evidence` contains, how the distinctive-signal gate reaches a verdict, and which of `match` / `review` / `no_match` can be returned.

It deliberately does **not** cover the inputs to that shape. Those have their own pins, because they change independently and far more often:

| what changed | which pin moves |
| --- | --- |
| A comparator added, removed or reweighted | `comparators_sha256` |
| A different blocking strategy | `block` |
| A threshold, margin or floor | the field itself |
| A frequency table rebuilt | `tf` |
| The scoring formula, the gate, or the meaning of a field | **`engine`** |

Putting the inputs in `engine` too would make it move on every pack edit, and a version that moves constantly tells a reader nothing.

### The rule

**Bump to `crosswalk.v2` when the same inputs would produce a different decision, or when a field in the edge means something new.**

Concretely, a bump is required for:

- a change to how `score` is computed from comparator similarities
- a change to the gate: what clears `distinctive_max`, or what `review` means
- a new decision value, or a change to when an existing one is returned
- a field in `evidence` changing meaning while keeping its name
- a refutation or veto rule that can move a verdict

A bump is **not** required for:

- a new comparator kind, or a reweighting — `comparators_sha256` carries that
- a new blocking channel — `block` carries that
- a new frequency table — `tf` carries that
- a bug fix that makes the implementation match what the version already claimed
- anything that changes which pairs are *offered* without changing what a verdict means

That last exclusion has a caveat worth stating, because the code and an earlier draft of this page disagreed about it. **Changing the blocker does change `decision_id`**, because `block` is part of `pins` and `pins` is hashed. Same verdict, same score, different id. That is correct and intended: the id addresses the decision *as configured*, and a run configured differently is a different run. It is not an engine bump, because nothing about what a verdict means has moved.

### What a bump obliges

A new engine version is not a rename. It means previously-issued ids stay valid and verifiable — anyone holding the old edge and the old pins recomputes the same id forever — and stop being reproducible by re-running the current code. Both halves are true at once, and saying only the first would be dishonest.

So a bump also requires: a changelog entry describing what decisions move, republished benchmark numbers for any figure this page or `reference/benchmarks.md` quotes, and a note in the release saying that ids issued under the previous version cannot be regenerated.

### A known inconsistency

`reconcile(backend="splink")` does not pin `engine: crosswalk.v1`. It pins the Splink model, corpus, blocking and library versions instead, because a trained scorer is a function of the data it saw and naming a version would claim less than the truth.

The result is two engines with two provenance vocabularies, and no single field a reader can compare across them. That is a real gap rather than a design; it is recorded here so it is not discovered as a surprise.

## Rules for pipelines and agents

1. Apply an automated action only to a contractually permitted `match` edge or `same_entity` decision.
2. Preserve `evidence`, `decision_id`, and `pins` in the audit trail.
3. Treat `review` as a stop for automation, not a soft match.
4. Do not cluster pairwise links into entities unless the workflow defines transitivity, conflict handling, and review rules.
5. Do not interpret `score` as a calibrated probability.

See [review and evaluate a crosswalk](../guides/review-and-evaluate.md) for a portable review-outcome shape and the conditions required to make accuracy claims.

This is the alpha consumer contract for `arche-core` 0.4.0a3. Any incompatible change should be called out in the release notes before a downstream system is expected to adopt it.
