# Distinctiveness, and why identical records can still be `review`

Two records can agree perfectly and still not be a match. This page explains the gate that does that, because it is the part of arche most likely to surprise you, and the surprise is usually arche being right.

## The two gates

Every candidate pair passes through two independent tests, and it must clear both to be labelled `match`.

| Gate | Question | Field |
| --- | --- | --- |
| Agreement | Do these records say the same things? | `score` |
| Distinctiveness | Is what they agree on rare enough to identify anything? | `distinctive_max` |

The first is a weighted mean of per-field similarities. The second is not a similarity measure at all — it asks how much information the agreement carries.

A pair that clears the score threshold but falls below `DISTINCTIVE_FLOOR` (0.75) is demoted from `match` to `review`. Nothing is discarded: the edge is still returned, still carries its evidence, and is still available to a reviewer. Only the automatic action is withheld.

## Why agreement alone is not evidence

Two clinics both called **General Hospital** agree completely. So do two people both called **Mohammed Ibrahim**. In neither case does the agreement tell you they are the same, because almost nothing was said. The words are shared by thousands of other records.

Two facilities both called **Karfi Health Post** also agree completely — but `Karfi` is a settlement name that few places carry, so the agreement is close to conclusive.

Similarity cannot tell these cases apart. Both score 1.0. The difference is not in the strings, it is in how many *other* records use the same words, and that is a fact about the population, not about the pair.

This is why arche ships frequency tables. `distinctive_max` is the strongest signal among the pair's distinctive comparators, priced by how rare the agreeing tokens are:

```
distinctiveness(token) = -log10(relative frequency) / 5     clamped to [0, 1]
```

A token that is one in 100,000 or rarer scores ~1.0. A token that is most of the corpus scores ~0.0. The divisor spreads five decades of frequency across the range.

## The same string, two answers

`distinctive_max` is measured against **the frequency table the entity pack uses**, and the packs ship different tables built from different populations. This is the single most common source of surprise:

```python
from arche.resolve import reconcile

a = [{"id": "a1", "name": "General Hospital"}]
b = [{"id": "b1", "name": "General Hospital"}]

place = reconcile(a, b, entity="place", id_field="id")["matches"][0]
org = reconcile(a, b, entity="organisation", id_field="id")["matches"][0]

assert (place["decision"], place["score"], place["distinctive_max"]) == ("review", 1.0, 0.564)
assert (org["decision"], org["score"], org["distinctive_max"]) == ("match", 1.0, 0.862)
```

Both runs score 1.0 on agreement. Only the rarity judgment moves, and here is why:

| token | place table (facility gazetteer) | organisation table (GLEIF registry) |
| --- | --- | --- |
| `general` | 1 in 660 → 0.564 | 1 in 929 → 0.594 |
| `hospital` | **1 in 57** → 0.351 | **1 in 20,349** → 0.862 |
| `distinctive_max` | **0.564** → below the floor → `review` | **0.862** → clears it → `match` |

The place table is built from facility registers and settlement gazetteers, where `hospital` is 1.7% of every token in the corpus — the most ordinary word a facility name can contain. The organisation table is built from GLEIF legal-entity records, where the ordinary words are `limited` and `ltd`, and `hospital` appears eleven times in 223,842.

**Read that second column carefully, because it is the honest limitation.** `hospital` is not rare in the world. It is rare *in a registry of entities that participate in financial markets*, because hospitals do not generally register Legal Entity Identifiers. The organisation table's 0.862 is a true statement about GLEIF and a misleading one about hospitals. A frequency table cannot distinguish "rare" from "absent from my sampling frame", and no gate downstream can recover the difference.

The practical rule follows from that: **choosing an entity pack is choosing which population rarity is measured against.** Pick the pack that matches what your records actually are. Picking a different one does not get you a better answer, it gets you a different question — and if it turns a `review` into a `match`, you have routed around the refusal rather than resolved it.

`describe_pack(entity)` reports which table a pack uses, so you can check before you commit to one.

## Which packs use which table

| Pack | Population it measures against |
| --- | --- |
| `place` | shipped place table — 1,248,172 records, 40 strata, 20 countries |
| `organisation` / `organization` | shipped GLEIF organisation table — 41,387 tokens |
| `artist` | shipped MusicBrainz artist table — 95,306 tokens |
| `person` | **self-calibrated over the two lists being compared** |

The last row is the one to know about. With no shipped table in play, the "population" is whatever you passed in — so a two-record comparison cannot know that `Mohammed` is common, and everything in it looks maximally rare:

```python
p = [{"id": "p1", "name": "Mohammed Ibrahim"}]
q = [{"id": "p2", "name": "Mohammed Ibrahim"}]

alone = reconcile(p, q, entity="person", id_field="id")["matches"][0]
table = reconcile(p, q, entity="person", id_field="id", tf="default")["matches"][0]

assert (alone["decision"], alone["distinctive_max"]) == ("match", 1.0)
assert (table["decision"], table["distinctive_max"]) == ("review", 0.683)
```

Both runs are self-consistent; the first simply has no population to consult. A name table does ship (`tf="default"` loads it: 50,591 tokens from US Census surnames and an African names lexicon), and it is not wired in by default. That is recorded in the changelog with the benchmark that has so far argued against changing it — on the current data, self-calibration scores F1 0.637 against the shipped table's 0.577, trading precision for recall.

**If you are resolving people at population scale, pass `tf="default"`.** If you are comparing two curated lists where every name is already known to be distinct, the self-calibrated default is defensible. Either way the run pins which one it used, so the decision is auditable after the fact.

## Reading the pin

Every result carries a `tf` pin naming the exact table that scored it:

| Pin | Meaning |
| --- | --- |
| `shipped:place@sha256:c94f20a1c2dfba18+phrases@sha256:...` | A shipped table, identified by content hash |
| `shipped:organisation` | A shipped table with no version stamp |
| `self-calibrated@sha256:...` | Built from the two lists in this run |
| `provided@sha256:...` | Your own table |

The digest matters. Two runs that pin different `tf` values were scored against different vocabularies and are not expected to agree — comparing their decisions is a category error, not a discrepancy to investigate. The pin is hashed into `decision_id`, so a table change is visible as a changed decision identity even when the verdict is unchanged.

## What this gate does not do

- It does not reject the pair. `review` is a returned edge with full evidence, not a `no_match` and not a silence.
- It does not fire on disagreement. Conflicting values are handled separately, by refutation and by hard constraints such as `veto_km`.
- It does not apply to identifiers. An agreeing `national_id` or `registration_id` is strong on its own terms; the distinctiveness gate governs name-like signals, where a shared token can be coincidence.

A pair can also be demoted to `review` by a conflict — an administrative-unit disagreement or a geographic impossibility — independently of `distinctive_max`. Check both fields before concluding which gate moved a decision.

## See also

- [Decision contract](decision-contract.md) — what each label obliges a consuming system to do
- [How arche works](how-arche-works.md) — where this sits in the pipeline
- [Benchmarks](benchmarks.md) — measured effects of the gate on labelled data
