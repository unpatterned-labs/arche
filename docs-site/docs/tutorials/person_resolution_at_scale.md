# Person resolution at scale: 10k records, zero false merges, scored

*The [places tutorial](place_resolution_at_scale.md) linked registries. This one links **people**, on the standard record-linkage benchmark, with ground truth, so for the first time we can put hard numbers on the question an identity system lives or dies by: **how often does the engine merge two records that are actually different people?***

The runnable version is `notebooks/person_resolution_at_scale.ipynb`. The dataset is [Febrl 4](https://github.com/J535D165/recordlinkage/tree/master/recordlinkage/datasets/febrl): 5,000 person records and 5,000 deliberately corrupted duplicates (typos, swapped name order, changed addresses), every true pair known. The people are **synthetic**, no real PII appears anywhere.

## Why this benchmark is hard

Among the 5,000 true pairs:

| field corrupted | share |
|---|---|
| address | **81%** |
| name | **51%** |
| postcode | 16% |
| date of birth | 9% |
| national id | 9% |

Exact matching is hopeless by construction. This is the mess real registries contain.

## The scored run

```python
out = resolve.reconcile(list_a, list_b, entity="person", block=None, tf="default")
m = metrics.evaluate(out["matches"], gold_pairs)
```

`tf="default"` loads the population-scale name-frequency table shipped with arche, so token distinctiveness works without calibration. `metrics.evaluate` scores against ground truth. On a 500×500 slice (250k pairs, ~60s):

```text
precision        1.0     <- every auto-match is a true match
recall           0.884   <- true pairs matched automatically
surfaced recall  0.97    <- true pairs that reached a human (match OR review)
review queue     45
```

**Precision 1.0.** The engine trades recall for it: the hardest ~12% of pairs land in `review` rather than being guessed. In identity systems that trade *is* the product, a false merge is a stranger's records fused; a review row is seconds of human time.

## Blocking for people: measured, not hoped

Places had coordinates, so H3 blocking was free. People don't. The full 5,000 × 5,000 is **25 million pairs**. The classic answer is **multi-pass key blocking**, compare two records only if they share a cheap key. Three passes (postcode / surname-prefix / exact national id), and because we have ground truth we can *measure* the cost:

```text
candidate pairs: 167,183   (99.3% of the cross-product skipped)
blocking recall: 0.9988    (6 of 5,000 true pairs lost - all three keys corrupted at once)
```

That's the blocking bargain stated in numbers: **99.3% of the work for 0.12% of the truth.** Multi-pass is the defence, any one surviving key keeps a pair alive. When you have any labelled data, always measure this.

## The full 10,000 records

Bucket-by-bucket crosswalk over the blocked candidates:

```text
full run in ~52s
precision        1.0    false merges: 0
recall           0.877
surfaced recall  0.9622
review queue     774    (15% of true-pair volume)
```

**Ten thousand records, under a minute, zero false merges**, with 87.7% resolved automatically and 96.2% of the truth surfaced. What the fuzzy machinery caught includes wholesale name-order swaps, matched at 1.0:

```text
'blakeston curihual' <-> 'curihual blakeston'   1.0
'daniel gaden'       <-> 'gaden daniel'         1.0
```

## From bulk linkage to a signable decision

A crosswalk row says *these two probably co-refer*. When one specific link **matters**, a benefits claim, a KYC approval, escalate that pair to the pairwise engine, whose decision is reproducible and cryptographically signable:

```python
decision = resolve.compare(ref_a, ref_b, issuer_key=KEY)   # Fellegi-Sunter + gate
signed  = attest(decision, issuer, mode="jws")               # PII-free artifact
verify_attestation(signed.compact).valid                     # True - offline
```

The attestation carries content-addressed ids and numeric evidence, never raw values, and the same decision re-runs to the same bytes. (Full story: the resolution-attestation notebook.)

## Takeaways

- **Safety is measurable, and it held**: precision 1.0 across 10k deliberately corrupted records. `false_merge_rate` is the metric an identity system must be judged on, and here you can compute it, because the benchmark has truth.
- **The review queue is the deliverable**: 774 rows is what "we don't guess on people" costs.
- **Places have H3; people have keys.** Everything else, the entity pack, the distinctive gate, the shipped frequency table, the metrics, is the same engine.
- **Bulk and signable are one continuum**: `reconcile` for the list, `compare` + `attest` for the link you must prove.

**Next:** [read crosswalk output field-by-field](../how-to/read-crosswalk-output.md) · places at scale · the resolution-attestation notebook for the full signing story.
