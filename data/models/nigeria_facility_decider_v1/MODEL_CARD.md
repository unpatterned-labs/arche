# Model card: nigeria-facility-decider-v1

A pair decider for Nigerian health-facility records. Given a GRID3 facility and
a candidate HFR record, it answers **match**, **reject** or **review** (hold for a
person). It is loaded with `arche.resolve.PairDecider.load(bundle)`.

| | |
|---|---|
| Bundle | `decider.json` + `cross_encoder/` + this card (built by `data/scripts/package_decider.py`) |
| Spec digest | `sha256:3b37abf92aa0707918f32b94376a5fc0a7b84fb89ad6542a06bd30909043498d` |
| Cross-encoder | fine-tuned `intfloat/multilingual-e5-small`, one logit; digest in `decider.json` |
| Tested as | X8, `augmented` arm, seed 0 (`data/er_bench/benchmark_x8_uniqueness_*.json`) |
| Licence of the code | Apache-2.0. The weights are not published; see "Distribution" |

## What it does

1. A **cross-encoder** reads both records as `name | LGA` and gives a logit for
   "same facility".
2. A **logistic combiner** weighs that logit against:
   - the distance between the two points, as `log1p(km)`;
   - whether the LGAs agree, read through an alias table of 49 differently
     written LGA names, such as GRID3's "Abuja Municipal Area Council" against
     the HFR's "Municipal Area Council";
   - whether a point is missing.
3. **Match** at or above `hi`, **reject** at or below `lo`, **review** otherwise.
   Pairs with both points use one threshold pair (lo 0.139, hi 0.968). Pairs
   missing a point use their own (lo 0.039, hi 0.957), learned from
   location-free copies of the training pairs. A missing point is never read as
   "0 km apart".

Fitted weights: logit +0.968, log1p km −2.448, LGA agree +3.947, coordinates
missing −1.865, bias −0.167.

## Intended use

- Settling the pairs arche's engine (`arche.resolve.reconcile`) **holds for
  review** when crosswalking GRID3 v2 and the HFR in a Nigerian state, and
  ranking the rest for a person.
- Every decision carries the spec digest and the cross-encoder weights digest,
  so a crosswalk says which decider made each link.

Not intended for:
- **Overruling the engine's own matches.** The decider was tested on the
  engine's held pairs and on lookalike and near-miss pairs, not on pairs the
  engine already matched.
- **Other entity types or countries.** It has not been tested on them.
- **Deduplicating the HFR against itself.**

## Training data

- **Cross-encoder:** the GRID3 v2 ↔ HFR crosswalk (shared source id) in the
  states not held out: 113k pairs, positives plus in-LGA negatives. Held out of
  training: Edo, Kano, Ondo, Lagos, FCT, Oyo, Anambra.
- **Combiner:** 1,707 pairs labelled blind by one reviewer in Studio:
  - the August and X1 packs, as corrected by the 2026-11-22 recheck;
  - the near-miss pack;
  - the X3–X7 packs, with the X4 corrections and the Oyo restore;
  - the far-duplicate recheck outcomes applied over the 37 pairs it covered.

  Each pair is used twice: as labelled, and with both points removed.

## Evaluation

Every test was pre-registered before its labels existed, scored once, and kept
as recorded. The rule:

- settles at least 20% of pairs;
- errors among settled pairs at most 3% (Wilson upper bound ≤ 10%);
- different pairs auto-matched at most 2% (Wilson upper bound ≤ 5%);
- at least 60 different pairs in the test;
- passing on all three training seeds.

**This exact artefact** (seed 0), on X8, Anambra (held out of everything; 67
same, 75 different):

| View | Settled | Errors | Different pairs auto-matched |
|---|---|---|---|
| With location | 68.3% | 2 (2.1%) | 0 of 75 |
| Points hidden | 35.2% | 0 | 0 of 75 |

All three seeds of the arm passed in both views. The located settle rate across
seeds was 68–73%.

**Its predecessors** used the same features but no location-free training.
They're relevant because, with location, the shipped decider's inputs and
behaviour are the same:

| Test | State(s) | Pairs (same / different) | Settled | Errors | Auto-matched different | Pass |
|---|---|---|---|---|---|---|
| X3 | Edo, Kano, Ondo | 180 (69 / 111) | 81–88% | 0.6–0.7% | 0 / 111 | yes |
| X4 | Lagos | 240 (117 / 123) | 78–85% | 3.6–4.4% | 7–9 / 123 | **no** (before the LGA aliases and Lagos labels) |
| X5 | FCT | 200 (126 / 74) | 72–77% | 0.6–0.7% | 0 / 74 | yes |
| X6 | Oyo | 248 (148 / 100) | 71–76% | 2.2–2.8% | 0 / 100 | yes |
| X7 | Lagos, fresh pairs | 149 (70 / 79) | 65–74% | 0% | 0 / 79 | yes |

**What was tried and dropped:**
- facility level (X3: no gain);
- local density as a feature (X5: let one false merge through on two seeds);
- a density gate (X6, X7: no measurable safety, cost about a quarter of the
  pairs settled);
- name uniqueness in the LGA (X8: no consistent gain without location).

## Limits and known risks

- **One reviewer** labelled everything. No second annotator, no agreement
  figure.
- **Small tests.** The largest has 123 different pairs. Zero false merges in 75
  still allows a true rate up to about 5%.
- **The "same" definition moved once.** A far second HFR record of a facility
  that already has its own HFR record was first marked same, then rechecked
  (37 pairs) on the rule "same name in the same LGA is one facility unless the
  name marks another". The recheck labels follow LGA and distance closely, and
  distance is a feature.
- **Errors with location are false rejects** of near-miss pairs the reviewer
  called same. The decider leans towards holding or rejecting, not merging.
- **Not tested:** a missing LGA (it reads as "LGAs disagree"), lists other than
  GRID3 and the HFR, and GRID3 v4. v4's ids don't join to the HFR.
- **The alias table** is built from where facilities stand in GRID3 v2 and the
  HFR. It may not cover other lists' spellings.

## Distribution

The weights (466 MB) are not in this repository or on any hub. The bundle is
built locally by `package_decider.py` from the pinned training run. Publishing
them is a separate decision, which needs a licence choice for the fine-tuned
weights (the base model is MIT) and a check of the training sources' terms
(GRID3 and the HFR, public data with attribution).
