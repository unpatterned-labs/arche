<div class="arche-hero" markdown>

# Know what's real.

<p class="arche-hero__sub">An open-source engine for deciding when messy records of people, places, organisations, and products refer to the same real-world entity, with evidence, not just similarity scores or identifiers.</p>

<span class="arche-hero__status">Alpha software · Apache-2.0</span>

</div>

Two lists can refer to the same clinic, supplier, artist, organisation, or product in different ways. A spelling may vary, a code may be missing, or a common name may belong to several different entities. arche helps make that decision explicit.

```text
Registry                         Survey                         Result
Karfi Health Post, Kano          Karfi Health Post, Kano        match
Central Clinic, Kano             Central Clinic, Kaduna         review
```

## What arche does

- Links two record lists with `crosswalk()`.
- Returns `match` when the evidence clears the configured gate.
- Returns `review` when the records are plausible but the evidence is not enough for an automatic link.
- Records comparator evidence, configuration pins, and a reproducible `decision_id` for every returned candidate.

The important outcome is often `review`. It preserves uncertainty instead of turning a similarity score into an unsupported assertion about a person, place, organisation, or product.

## Start here

```bash
pip install arche-core
```

Then follow [Resolve two lists](getting-started/quickstart.md).

## Run a first script

Save this as `first_crosswalk.py`, then run `python first_crosswalk.py`. It uses only the installed package, not a notebook or a repository checkout.

```python
from arche.resolve import crosswalk

left = [{"id": "registry-1", "name": "Gyaranya Health Post", "lat": 11.90, "lon": 8.50}]
right = [{"id": "survey-1", "name": "Gyaranya Health Post", "lat": 11.94, "lon": 8.50}]

edge = crosswalk(left, right, entity="place")["matches"][0]
print(edge["decision"], edge["score"], edge["evidence"])
```

```text
match 0.8454 {'name': 1.0, 'name_tftoken': 1.0, 'name_type': 1.0,
'geo': 0.227, 'distance_km': 4.45}
```

See [How arche works](reference/how-arche-works.md) for standalone scripts for Pipeline, document resolution, direct person comparison, address parsing, and spatial roles.

## Scope for alpha

arche is alpha software. Its APIs and calibration can change. Do not use it to make production decisions about personal data without independent privacy, security, legal, and accuracy review.

The current documentation focuses on record resolution. Document extraction, policy, LLM integrations, product matching, and agent tooling exist at different stages of maturity and are not the alpha promise.

There is no released arche MCP server. An agent can call the Python API through your own tool layer, but it should treat arche as an evidence service, not as a source of unquestionable identity truth.

## How it relates to Splink

**Splink is the better matcher, and arche can use it.** That is measured, not a courtesy: on Febrl 4, on Splink's `historical_50k`, and on a Nigerian school register chosen because collision-heavy names should have favoured arche, Splink wins every time. Its term-frequency adjustments are the same idea as arche's `tftoken` and have been in Splink for years.

So `crosswalk(backend="splink")` hands the scoring to Splink and keeps what arche puts around a score: per-comparator evidence, a gate that can refuse a merge and say why, reproducible decision ids, signing, and a review pack a person can work. Measured against the same Splink recipe run directly, the adapter reaches the same numbers. It is the same scorer with a decision layer attached, not a better one.

Use Splink directly when you want the best available probability that two rows are the same person. Use arche when you need to show why a decision was made, what was refused and on what grounds, and to prove the artifact has not changed since. The two are not competing for the same job.

See [the benchmarks](reference/benchmarks.md), including the runs where arche loses.

## Next steps

- [Prepare your data](guides/prepare-data.md)
- [Interpret a decision](guides/interpret-decisions.md)
- [See places and products in action](guides/places-and-products.md)
- [Reconcile health facilities](guides/facility-reconciliation.md)
- [Resolve people across documents](guides/documents-to-decision.md)
- [Understand how arche works](reference/how-arche-works.md)
- [Read the accuracy and scope notes](guides/accuracy-and-scope.md)
