# Entity resolution

Entity resolution is the task of linking multiple mentions of the same real person across documents — *"is `Adesola Okonkwo` in our customer database the same person as `A. Okonkwo` in this signup form?"* 

arche-core ships entity resolution in the base install:

```python
from arche.resolve import resolve_entities, resolve_identity_records
```

Two callables, two use cases:

- `resolve_entities(entities, ...)` deduplicates a flat list of extracted `Entity` objects (typical post-`Pipeline.process()` output).
- `resolve_identity_records(evidence, threshold=..., jurisdiction=...)` is the v2 evidence-driven path that produces `IdentityRecord` objects for DPI hand-off.

Under the hood, two backends:

1. **Fuzzy** (always available) — rapidfuzz token-sort + union-find clustering + Yoruba/Hausa/Swahili name equivalence. Suitable up to ~100K records on a laptop.
2. **Splink** (via `pip install arche-core[resolve]`) — Splink 4.x + DuckDB Fellegi-Sunter probabilistic matching with EM parameter estimation. Auto-engages for >=10 entities when the extra is installed; falls back to fuzzy on import error.

A first-class `SplinkResolver` user class (CSV-in / cluster-out) lands in **v0.3** alongside the `arche-core[graph]` embeddable graph backend.

---

## Worked example — Nigerian fintech dedup

Three customer signup records arrive from three different channels (web form, USSD callback, branch tablet). All three are the same person, but the names are spelled differently and only one has a NIN.

```python
from arche import Pipeline
from arche.resolve import resolve_entities

texts = [
    "Customer Adesola Okonkwo, NIN 12345678901, phone 0803 555 7890.",
    "A. Okonkwo, BVN 22156789012, phone +234 803 555 7890.",
    "Adesola Okonkwo, phone +2348035557890, email aokonkwo@example.com.",
]

pipeline = Pipeline(jurisdiction="NG")
all_entities = []
for t in texts:
    result = pipeline.process(t)
    all_entities.extend(result.entities)   # populated in v0.2.0a2; for v0.2.0a1, see result.detections

# Resolve into canonical records
clusters = resolve_entities(all_entities, use_splink=True)
for c in clusters:
    print(c.canonical_name, "↔", [m.text for m in c.mentions])
# Adesola Okonkwo ↔ ['Adesola Okonkwo', 'A. Okonkwo', 'Adesola Okonkwo']
```

The resolver succeeded for three reasons:

1. **Phone normalization** — `0803 555 7890`, `+234 803 555 7890`, and `+2348035557890` all normalize to `+2348035557890` via libphonenumber. That's the strongest match key.
2. **African-name equivalence** — `arche.detect._names.lexicon` recognises Yoruba spelling variants (`Adesola` ↔ `Adésọ́la`, `A. Okonkwo` ↔ `Adesola Okonkwo` via initial-match logic).
3. **NIN / BVN cross-linking** — record 1 has a NIN, record 2 has a BVN, record 3 has neither. The resolver still groups them because of (1) and (2). If a fourth record came in with the same NIN but a totally different name, it would merge by exact-match NIN — the typical bank-fraud-vs-typo signal.

---

## NIN-based blocking — the production pattern

For 1M+ record dedup, blocking is the cost-controlling step. Splink's default blocking on entity_type + name-prefix is too loose for arche workloads. Override:

```python
from arche.resolve import resolve_identity_records

records = resolve_identity_records(
    evidence,
    threshold=0.85,
    jurisdiction="NG",
    # In v0.3, expose: blocking_rules=["nin", "phone"]
)
```

The Splink pipeline runs roughly:

```
1. Block on NIN (exact match) ∪ phone-prefix (first 6 digits)
2. Compare:
   - name: JaroWinkler thresholds [0.9, 0.7]
   - phone: ExactMatch
   - NIN: ExactMatch
   - BVN: ExactMatch
3. EM-estimate parameters
4. Predict pairwise probabilities
5. Cluster at threshold (default 0.5)
```

For the v0.2.0a3 release, this pipeline runs internally when `arche-core[resolve]` is installed. The v0.3 `SplinkResolver` class exposes each step as a tunable parameter and adds CSV-in / CSV-out ergonomics.

---

## Picking your backend

| Records | Backend | How to engage |
|---|---|---|
| <100 | Fuzzy | Default — no extra needed |
| 100 – 100K | Fuzzy or Splink | Default fuzzy; `pip install arche-core[resolve]` for Splink |
| 100K – 1M | Splink | `pip install arche-core[resolve]` — auto-engages |
| 1M+ | Splink + DuckDB-backed staging | Same install; in v0.3 the `SplinkResolver` exposes pre-blocking knobs |

If you need a pluggable graph store for the resolved clusters (embedded, or Postgres), that's the v0.3 scope. For the v0.2.0a3 alpha, resolution outputs `ResolvedEntity` / `IdentityRecord` Python objects that you can persist however you like.

---

## See also

- [API reference: `arche.resolve`](../api/resolve.md)
- [Splink 4.x documentation](https://moj-analytical-services.github.io/splink/)
