# The maths underneath

*How a match score is actually computed, with hand-computable numbers. Fellegi-Sunter, why rarity is evidence, how geometry is handled, and what arche adds on top.*

*Folded in from a separate page, because the signals table above and the formulas below were describing the same thing twice.*

Two rows, two Nigerian registries: *Karfi Health Post* and *Karfi Primary Health Centre*, coordinates 2.1 km apart, each record carrying its named admin path (Kano State → Kura LGA → Karfi). Feed them to `reconcile(..., entity="place")` with the small frequency table we build below, and the engine answers: score **0.6942**, decision **review**. This page teaches the math behind that number, from a 1969 statistics paper down to the exponential in the geo comparator, so that by the end you can compute it by hand, and we will, and it will agree with the engine to four decimal places. The five positions say where we stand; this page is why the numbers come out the way they do.

### The probability heritage: Fellegi–Sunter

Ivan Fellegi and Alan Sunter (1969) put record linkage on probability theory: for each field, estimate `m = P(agree | same entity)` and `u = P(agree | different entities)`, sum the log likelihood ratios across fields, and. Their own third verdict, often forgotten. Send the middle band to a human. arche's pairwise path implements this directly:

```
agreement      →  w = log2(m / u)
disagreement   →  w = log2((1 − m) / (1 − u))
partial (similarity s)  →  w = s · log2(m/u) + (1 − s) · log2((1−m)/(1−u))
```

Weights sum across fields, then `P(match) = 2^W / (1 + 2^W)`. One worked number, with the shipped defaults `name_m = 0.92`, `name_u = 0.01`: exact name agreement is worth `log2(0.92/0.01) = 6.52` bits, so a name alone gives `2^6.52 / (1 + 2^6.52) ≈ 0.989`. Disagreement costs `log2(0.08/0.99) = −3.63` bits. The pairwise decision then bands at 0.85 (match) and 0.40 (review). The math is not ours and we do not improve it. [Splink runs the same model](../tutorials/arche_vs_alternatives.md) with proper EM-estimated parameters, and runs it better. arche implements a thin version itself and spends its effort on the representation the model scores over. At scale the shipped path is arche's own engine; nothing in `compare`, `reconcile` or the frequency tables imports Splink.

### Rarity is evidence

Howard Newcombe noticed in 1959. A decade before the theory. That agreeing on a rare surname proves more than agreeing on a common one, and William Winkler later formalized it as the value-specific frequency adjustment: don't use one `u` per field, use one per *value*. arche does this twice. In the pairwise path, the Nigeria pack overrides `u` for common names: agreeing on *Mohammed* (`u = 0.08`) is worth `log2(0.92/0.08) = 3.52` bits against 6.52 for a default-rare name. The identical agreement, exactly 3 bits cheaper, because `0.08/0.01 = 2³`. Alone it yields `P ≈ 0.92` instead of 0.989.

In the crosswalk path the same idea generalizes to a table computed over real corpora: `distinctiveness(t) = min(1, −log10(rel_freq(t)) / 5)`, so a token at frequency 10⁻⁴ scores 0.8 and one at 10⁻¹ scores 0.2. The `tftoken` comparator is then a distinctiveness-weighted Jaccard. Take *Karfi Health Post* vs *Karfi Primary Health Centre* with a table where karfi = 10⁻⁴, health = centre = 10⁻¹, post = primary = 10⁻²: shared tokens weigh 0.8 + 0.2 = 1.0, all tokens weigh 2.0, similarity **0.50**, and most of that 0.50 is *Karfi*. Swap Karfi for another common token and the same overlap drops fast. Agreement is worth what its rarity says, and the shipped population tables are what make the rarity estimate trustworthy when your list is too small to calibrate itself.

### Geometry, honestly

Coordinates get one comparator and it is deliberately humble: `sim = exp(−d / decay_km)` over the haversine distance. The place pack sets `decay_km = 3.0` (the generic default is 1.5) because in field-captured African facility data roughly a quarter of true-match pairs sit more than 2 km apart. Someone measured at the gate, someone at the junction. Numbers you can check on a calculator: 1 km → `exp(−1/3)` = **0.72**, 2 km → **0.51**, 3 km → **0.37**. Never zero, never decisive on its own. The evidence dict also reports `distance_km` raw, because a reviewer reads "2.1 km apart", not "0.497".

The other half of location is the *named* hierarchy, and `compare_containment` is a small decision tree over it: walk state → LGA → settlement, top-down, and stop at the first disagreement. Full agreement to the finest level scores by depth. Settlement **1.0**, LGA **0.6**, state **0.3**, and the top-down stop rule exists because settlement names repeat heavily (Sabon Gari, Tudun Wada): two points in different LGAs whose settlements merely share a name stop at the LGA disagreement and never collect the settlement score. Disagreement at the coarsest level returns 0.0, and downstream any containment conflict demotes a would-be match to review. The map gets a voice, not a gavel.

### The engineering that makes it safe at scale

Scoring every pair in two 100k-record lists is 10¹⁰ comparisons, so every real system *blocks*. Only scores pairs that could plausibly co-refer. The brutal property of blocking is that a dropped true pair is unrecoverable: no downstream math can rescore a pair it never saw, which is why recall is the only metric a blocker is judged on, and why `reconcile` reports `blocking_recall` against labelled truth when you have it. The default is a union of three keys. H3 spatial cells (resolution 7, with a coarser safety ring because 1-ring recall collapses beyond ~2 km of GPS offset), rare shared tokens, and shared identifiers. ORed, so a true match with discordant coordinates, or none at all, still reaches the comparators. Rarity here is enforced as a cost bound, not a guess: a token whose occurrences would contribute more than `pair_cap = 1000` pairs ("clinic") is too common to block on and is skipped.

Each surviving pair gets a weighted mean of its comparator similarities. Comparators with nothing to say return `None` and are dropped from the mean, never scored as disagreement. Then two safety devices apply. The **distinctive-signal gate**: a pair may only be `match` if some *distinctive* comparator (name, placename, id, tftoken) reaches `distinctive_floor = 0.75`; geo, containment, and address amplify but never manufacture a merge, so a shared coordinate with a weak name lands in review, never match. And **banding**: `match` at/above `threshold = 0.7`, `review` within `review_margin = 0.15` below it. Fellegi–Sunter's third verdict, kept as a first-class outcome rather than an embarrassment.

Now the promised hand computation. Place-pack weights: placename 2, tftoken 2, geo 1, containment 1 (the type comparator shows in evidence at weight 0. Health Post vs PHC disagree, a reviewer sees it, the score ignores it until calibrated). Fuzzy placename similarity is the one number you take from the library: `compare_place_names` returns 0.8342. Geo at 2.1 km: `exp(−2.1/3) = 0.4966`. Containment: same settlement, 1.0. Tftoken from the table above: 0.50.

```
(2 × 0.8342 + 2 × 0.5000 + 1 × 0.4966 + 1 × 1.0) / 6 = 0.6942
```

0.6942 sits six thousandths below the 0.7 threshold, inside the review band: **review**, which is the correct answer. This pair is the upgrade story, and only local knowledge resolves it. To reproduce it exactly, give both records an `admin_path` dict keyed by the containment levels the comparator walks (`admin1`, `admin2`, `settlement`) and pass `tf=TokenFrequencyTable({"karfi": 1e-4, "health": 1e-1, "centre": 1e-1, "post": 1e-2, "primary": 1e-2})`; leave the table out and the engine self-calibrates over your two lists instead, `tftoken` falls from 0.50 to 0.30, and the score lands at 0.6276. Same verdict, different arithmetic, which is itself the lesson about why shipped tables matter: a two-record corpus cannot tell you that *Karfi* is rare and *Health* is not.

The edge then gets a `decision_id`: a content hash over the evidence, the decision, and the run's pins (engine version, comparator-spec hash, thresholds, blocking strategy, frequency-table provenance). No timestamp, no randomness. Anyone holding the same inputs recomputes the same id, which is what makes the edge citable and signable.

### Measuring honesty: the referee math

The same discipline runs upstream, where `extract_places` labels spans with spatial roles. Its confidences are a lookup table over evidence tiers. Cue quality × span quality, from (adjacent cue, parsed address) = 0.95 down to a floor of 0.25. Ordinal labels, not probabilities, and nothing in arche ever multiplies them. An absent or conflicting cue structurally forces `role="unknown"`: abstention is built into the table, not bolted on.

`grade_places` scores any extractor against the gold set with per-role precision, recall, and F1. Plus two numbers standard F1 cannot see, because F1 treats a non-answer and a wrong answer identically. **`over_guess`**: predicting a committed role where gold abstained, counted as a false positive *and* named separately, because it is the failure the feature exists to prevent. **`missed_by_abstention`**: answering `unknown` where gold committed, counted as a false negative but never a false positive. The asymmetry is the argument: an agent that flips origin and destination books the courier backwards; one that abstains asks a question. Those are not the same cost, so they must not be the same number. Empty denominators return `None`, never a fake zero. No grade over zero items.

### What arche adds

The math above is commodity and we say so plainly: the three-verdict model is 1969, rarity-as-evidence is 1959, the string comparators are the 1980s, and Splink executes all of it better at scale than our in-memory core. What we claim is narrower, and it is delivery form, defaults, and discipline:

- **Representation shipped as data, not weights.** The literature gives the model and its parameters; engines let you supply them. We ship the *inputs*. Equivalence packs, frequency tables, type vocabularies, cue packs, gold sets. As inspectable, versioned files with content-hash pins, correctable by the person who knows the fact. The thesis page makes the full case.
- **The refusal architecture.** Fellegi–Sunter defined the review verdict; we extend abstention structurally through every layer: comparators return `None` rather than fake zeros, roles return `unknown` on conflicting cues, the distinctive gate demotes rather than merges, uncalibrated signals ride at weight 0 in plain sight.
- **Signable decisions with provenance pins.** The literature provides reproducibility norms; we make each decision a content-addressed, Ed25519-signable claim pinned to the exact representation that produced it. *given this evidence and this representation, this was the decision*.
- **Refusal-aware evaluation.** Christen's discipline gives precision/recall on labelled pairs; we add `over_guess` and `missed_by_abstention` as first-class metrics, so an evaluated extractor (including your LLM) is priced on when it should have stayed silent.
- **African calibration as first-class data.** The classical results assume populations someone already tabulated. We ship the tables nobody shipped: measured name frequencies, a 3 km decay calibrated on African facility data, landmark-address grammar, cultural equivalences. Kept *out* of the place lane where they would cause false merges. That last decision is representation too.

None of these is a new theorem. All of them are choices the papers leave open, and they are where arche's measured [name-frequency result](../about/the-whole-picture.md#the-frequency-row-used-to-say-something-else) comes from: precision 0.162 to 0.946 on 1,114 real same-surname pairs, at a recall cost the page states rather than hides.
