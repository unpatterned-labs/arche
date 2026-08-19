# Entity resolution: `pairwise()`, `crosswalk()`, `sign_edges()`

The `arche.resolve` facade has two entry points by use-shape. Their scores are deliberately **not comparable**, different math for different jobs.

## `resolve.pairwise(a, b, *, entity="person", **kwargs)`

"Are these two the same?" Dispatches on input shape, two Pipeline `Result`s, two canonical `Reference`s, or two raw strings (extract-then-resolve), and returns a signable `CoReferenceDecision` (Fellegi–Sunter log-odds, exact-id gate, id-conflict veto, statute citations travelling with the evidence). Currently `entity="person"` only; place lists go through `crosswalk`.

```python
from arche import resolve

decision = resolve.pairwise("Fatima Abdullahi, NIN 12345678901",
                            "Fatuma Abdullahi, NIN 12345678901")
decision.identity      # "same_entity" | "review" | "different"
decision.action        # what the gate decided to do about it
decision.score         # 0.9999
decision.factors       # per-field evidence
decision.decision_id   # reproducible content address
```

Real output for the pair above:

```text
identity    = 'review'
action      = 'no_op'
score       = 0.9999
decision_id = 'dec:sha256:a5fde8c138c6157f00c0396ce63f6...'
```

!!! note "`identity`, not `decision`"

    The verdict field is `decision.identity`, and its values are
    `same_entity` / `review` / `different`. `decision.decision` does not
    exist and raises `AttributeError`. The `"match"` / `"review"` /
    `"no_match"` vocabulary belongs to **crosswalk edges**, which are a
    different object, see `resolve.crosswalk()` below.

!!! warning "A high score is not a merge"

    Note the pair above scores `0.9999` and still returns `review`. Sharing
    an exact national ID is strong evidence, but the gate requires
    *distinctive* evidence before it will call two references the same
    entity, and it abstains rather than guessing. `review` is the engine
    working, not failing.

Signing a decision requires a keypair. Calling
`arche.attest.attest()` on a decision produced without an `issuer_key` raises,
deliberately:
a keyless `reference_id` is a hash of the person's attributes and can be
brute-forced back to the source record. 

## `resolve.crosswalk(list_a, list_b, *, entity=None, comparators=None, tf=None, decl=None, **kwargs)`

Link or dedupe two record lists at scale. Pass exactly one of:

- `entity=`: a canned pack from `ENTITY_PACKS` (`"person"`, `"place"`, `"artist"`);
- `decl=`: a [`Declaration`](../how-to/declare-your-schema.md): your fields, generated comparators, your `id_field`, the pin entering every edge;
- `comparators=`: explicit specs (see kinds below).

Key keyword arguments (forwarded to `reconcile`):

| Argument | Default | Meaning |
|---|---|---|
| `threshold` | `0.7` | score at/above which a pair is `match` (gate permitting) |
| `review_margin` | `0.15` | `[threshold − margin, threshold)` is `review`; below is dropped |
| `id_field` | `"id"` | record identifier column |
| `tf` | pack-dependent | a `TokenFrequencyTable`, `"default"` (person table), a domain name (`"artist"`), or `None` → self-calibrate over both lists |
| `block` | `"union"` | `"union"` (H3 ∪ rare-token ∪ shared-id), `"h3"` (spatial only), or `None` (full cross-product) |
| `truth_pairs` | `None` | labelled `(a_id, b_id)` true pairs → `blocking["recall"]` reported |
| `extra_pins` | `None` | extra provenance hashed into every `decision_id` (e.g. a boundary-layer vintage) |
| `rerank` | `False` | block-aware distinguishing-token reranker |

Comparator kinds: `name`, `placename` (lexicon-free), `id`, `phone`, `email`, `address`, `date`, `tftoken` (needs `tf`), `geo` (`lat`/`lon`/`decay_km`), `containment` (named admin hierarchy), `type` (`domain=` vocabulary; ships at weight 0 in the place pack).

Returns:

```python
{
  "matches": [{"a_id", "b_id", "score", "decision",      # "match" | "review"
               "evidence",            # per-comparator similarities (+ distance_km)
               "distinctive_max", "decision_id"}],       # content hash over edge + pins
  "count": int,
  "pins": {...},          # engine, thresholds, block, tf provenance, declaration pin
  "blocking": {"candidate_pairs", "reduction_ratio", "strategies", "recall"?},
}
```

Safety semantics: a `match` requires a *distinctive* comparator (name/placename/id/tftoken) at ≥ 0.75, supporting signals (geo, containment, address) amplify but never manufacture a merge, and any containment conflict demotes a would-be match to `review`. Output decoding: [read crosswalk output](../how-to/read-crosswalk-output.md).

## `reconcile.sign_edges(result, *, private_key, kid, decisions=("match", "review"))`

JWS-sign crosswalk edges. Each payload is the edge plus the run's pins under the `arche.crosswalk_edge.v1` schema, so a verifier can recompute the `decision_id` from the signed payload (dropping the `decision_id` field first) and confirm nothing changed. Edges carry ids and numeric evidence only, never raw record values, so the signed artifact is as shareable as the crosswalk output itself.

```python
from arche.resolve.reconcile import sign_edges
from arche.sign import generate_keypair, verify

kp = generate_keypair()
signed = sign_edges(result, private_key=kp.private_key, kid=kp.did_key)
verify(signed[0]["jws"], public_key=kp.public_key).valid   # True
```

## `ENTITY_PACKS`

The canned comparator specs (`person`, `place`, `artist`), config over one engine, never a fork.
