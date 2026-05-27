# Pan-African PII Taxonomy

An open hierarchical taxonomy of personally identifying information
categories with explicit attention to African contexts. Published as a
digital public good under **CC-BY-4.0** by Unpatterned Labs CIC as part
of the arche-core identity workflow framework.

## What this is

`v0.1.yaml` is the working-draft source of truth for the PII category
labels that `arche-core` uses across:

- **Statute YAMLs** (`arche.policy.statutes/*.yaml`) — per-statute
  action mappings reference these category codes.
- **Detector emissions** (`arche.detect.*`) — every detection carries
  one of these category codes.
- **Pipeline results** (`arche.workflow.Pipeline.Result`) — the
  `category` field on `Detection` and `PolicyOutcome` records.
- **Verifiable credentials** (`arche.credentials.sd_jwt`) —
  selectively-disclosable claim names align with these codes.

## Why African-context-specific

Western PII taxonomies (Presidio's category list, GLiNER2-PII's 42-class
schema, OneTrust's policy library) miss the realities of African
identity data:

- **Foundational identifiers** like NIN, BVN, Huduma, Fayda, Ghana
  Card, SAID — none appear as first-class categories in incumbent tools.
- **Praise names, patronymics, clan names** — direct person identifiers
  that Western "PERSON" detectors miss.
- **Landmark-anchored addresses** — "behind the Total filling station,
  Madina Junction" is a re-identifying address in informal African
  geographies but doesn't match libpostal's structured-address shape.
- **Mobile money references** — M-Pesa / MoMo / Wave transaction IDs
  are functional identifiers in pan-African fintech but absent from
  card-and-IBAN-focused Western taxonomies.
- **Special-category data with regional weight** — sexual orientation
  in jurisdictions where LGBTQ+ identity carries legal risk, refugee
  status in conflict-affected regions, tribal affiliation under POPIA's
  race definition.

## How to use

```python
import yaml
from pathlib import Path

with open("datasets/pan-african-pii-taxonomy/v0.1.yaml") as f:
    taxonomy = yaml.safe_load(f)

# Look up a category
for cat in taxonomy["categories"]:
    if cat["code"] == "PII-2-NIN":
        print(cat["description"])
        print(cat["identity_class"])  # "foundational"
```

The categories also flow naturally into the `arche.policy` engine, where
statute YAMLs map them to one of six closed actions (mask, tokenize,
drop, generalize, audit, retain) per PRD §6.3.

## Identity classes

Every category carries an `identity_class` field per PRD §4.4:

| Class | Description |
|---|---|
| **foundational** | Root national identifiers issued by a foundational identity authority. The base of the DPI identity stack. |
| **functional** | Purpose-specific identifiers issued by a sector regulator or service provider. |
| **federated** | Third-party-verified identifiers (typically commercial). |
| **inferred** | Quasi-identifiers — not themselves identifiers but in combination can re-identify. |

This four-class distinction is novel in production PII tooling and is
one of arche's distinguishing contributions.

## Roadmap

| Version | Status | Notes |
|---|---|---|
| v0.1 | **published** (2026-06-09) | Working draft by Unpatterned Labs. 9 top-level groups, 40+ categories. |
| v1.0 | planned, Stage 1 month 7 | DPA consultation: Nigerian NDPC, Kenyan ODPC, South African Information Regulator, Ghanaian DPC. |
| v1.1+ | ongoing | Expansion to additional African jurisdictions and emerging DPI deployments. |

## License

[CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/). Attribution to
"Unpatterned Labs (2026). Pan-African PII Taxonomy v0.1." appreciated.

## Citation

```
Unpatterned Labs (2026). Pan-African PII Taxonomy v0.1.
https://github.com/unpatterned/arche/datasets/pan-african-pii-taxonomy
```

## Contributing

Issues, additions, and corrections welcome via GitHub. Particularly
needed:

- Detection regex / format specs for identifiers without
  publicly-documented validation algorithms.
- Code-mixed and informal identifier patterns (PII-9 category needs the
  most expansion).
- Per-jurisdiction sensitivity classifications where statute treatment
  differs from the defaults.
