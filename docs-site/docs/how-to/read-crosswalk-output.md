# Read crosswalk output: every number explained

You ran a place crosswalk and got this back:

```python
from arche import resolve

hfr = [
    {"id": "HFR-001", "name": "Karfi Primary Health Centre", "lat": 11.601, "lon": 8.402},
    {"id": "HFR-002", "name": "Central Hospital Kano", "lat": 12.002, "lon": 8.517},
]
osm = [
    {"id": "OSM-77", "name": "Karfi PHC", "lat": 11.6015, "lon": 8.4025},
    {"id": "OSM-91", "name": "Gwale Clinic", "lat": 12.101, "lon": 8.601},
]
out = resolve.reconcile(hfr, osm, entity="place")
```

```text
HFR-001 <-> OSM-77  review  score=0.5779  {'name': 0.837, 'name_tftoken': 0.133, 'geo': 0.949}
```

Same facility, ~60 m apart, name obviously equivalent, **why `review` and not `match`?** This page decodes every field, then explains that verdict (it is the engine being *right*, and the reason teaches you the most important thing about the resolver).

## The output shape

`reconcile` returns `{"matches": [...], "count": int, "blocking": {...}}`. Each entry in `matches` is one candidate pair:

| field | meaning |
|---|---|
| `a_id`, `b_id` | the two records' `id` fields, the output carries **ids and numbers only, never raw values** |
| `score` | the **weighted mean** of all comparator similarities that applied (0–1) |
| `decision` | `match` / `review`, pairs below the review floor are dropped entirely |
| `evidence` | the per-comparator similarity that produced the score |
| `distinctive_max` | the strongest *distinctive* signal seen (drives the gate, below) |

## The evidence keys

Each comparator in the entity pack writes one evidence entry. For the `place` pack:

| key | comparator | what it measures |
|---|---|---|
| `name` | fuzzy name (`kind="name"`) | string similarity with African-name equivalence, `0.837` here, i.e. "Karfi Primary Health Centre" ≈ "Karfi PHC" **is** recognised as close |
| `name_tftoken` | term-frequency token (`kind="tftoken"`) | **distinctiveness-weighted** token overlap, how much the *shared tokens* prove, given how rare they are in this corpus |
| `geo` | haversine (`kind="geo"`) | proximity with exponential decay, `0.949` ≈ 60 m apart |
| `address` / `containment` | (skipped) | comparators skip silently when neither record carries the field, they don't drag the score down |

When two comparators read the same field, the second is suffixed with its kind (`name_tftoken`) so neither hides the other.


## The decision bands

`score` is compared to two thresholds (defaults: `threshold=0.7`, `review_margin=0.15`):

- `score ≥ 0.70` → **`match`**, *if* the distinctive gate also clears
- `0.55 ≤ score < 0.70` → **`review`**, surfaced for a human
- `score < 0.55` → dropped (not in the output at all)

Here: `(2.0·0.837 + 2.0·0.133 + 1.0·0.949) / 5.0 = 0.578` → the review band.

## So why `review`? The distinctiveness lesson

Look at `name_tftoken: 0.133`. The tftoken comparator asks: *how rare are the tokens these two names share?* Agreement on a **rare** token ("Karfi") is strong evidence; agreement on a **common** one ("Central", "Clinic") is nearly none.

But rarity is measured **against a corpus**, and when you pass no `tf=`, `reconcile` self-calibrates over the lists you gave it. Your corpus here is **four names**. "Karfi" appears in half the corpus, so to the engine it looks like a *common* word. The distinctiveness evidence is honestly weak, not because the match is bad, but because **four records cannot tell the engine what's rare**.

Two consequences, both deliberate:

1. **The safe failure mode is `review`, never a silent wrong `match`.** A name variant + close coordinates *without* distinctive proof is exactly the pair a human should confirm, the same shape as two *different* clinics that share a compound.
2. **At real scale, distinctiveness becomes measurable.** Run the same call over the full Kano registry (~1,500 facilities) and "Karfi" is now genuinely rare in the corpus, for the real Karfi pair, `name_tftoken` rises from ~0.15 to **0.47**. And the real data teaches a second lesson: the actual registry pair is *"Karfi Health Post"* vs *"Karfi Primary Health Centre"*, 600 m apart, plausibly two **different** facilities in one town, and the engine correctly holds it at `review` while 111 clean pairs clear to `match` at ~1.0. The review queue is the product working, not failing. See the [place-resolution-at-scale tutorial](../tutorials/place_resolution_at_scale.md).

You can also skip self-calibration and bring population knowledge directly: `resolve.reconcile(..., tf="default")` uses the frequency table shipped with arche (US Census + African names).

## The distinctive-signal gate

Even a score above 0.70 only becomes `match` if some **distinctive** comparator (`name`, `id`, `tftoken`) clears the floor (`distinctive_floor=0.75`). This is the rule that stops a *shared location* from manufacturing a merge: two different facilities at one coordinate score high on `geo`, but geo is not distinctive, the pair lands at `review`. `distinctive_max` in the output tells you how close the gate came to clearing.

## `blocking`: why big lists are fast

```text
{'candidate_pairs': 4, 'reduction_ratio': 0.0}
```

With coordinates present, records are bucketed into H3 spatial cells and only neighbours are compared: `candidate_pairs` is how many pairs were actually scored; `reduction_ratio` is the fraction of the full cross-product that was *skipped* (0.0 here because 2×2 has nothing to skip; at 46,000×46,000 it is
>0.99, see the tutorial). No coordinates → set `block=None` for the full
cross-product.

## Quick reference

- **`review` on a toy example is expected**: distinctiveness needs a corpus.
- **Missing fields don't hurt**: comparators skip, they don't zero.
- **Never raw PII**: ids + numbers only; render values separately with `arche.render` (masked by default).
- Scores from `reconcile` (weighted mean) and `resolve.compare` (Fellegi–Sunter) are **not comparable**, different math, on purpose.
