# `arche.detect`

Per-country PII / identity detectors. Each launch jurisdiction exposes an `ids` module with a single entry function returning `list[Detection]`.

```python
from arche.detect.ng.ids import detect_nigerian_ids
from arche.detect.ke.ids import detect_kenyan_ids
from arche.detect.za.ids import detect_south_african_ids
from arche.detect.gh.ids import detect_ghanaian_ids
```

For pan-African coverage (RW, TZ, UG, ET, CI, SN, CM, EG, MA, AO, MZ):

```python
from arche.detect._africa.ids import detect_african_ids
from arche.detect._africa.phones import normalize_e164, validate_phone
```

Detectors return [`Detection`](resolve.md#detection) objects with category labels from the [Pan-African PII Taxonomy v0.1](https://github.com/unpatterned-labs/archeblob/main/datasets/pan-african-pii-taxonomy/v0.1.yaml).

> Most callers don't need this surface directly — `Pipeline(jurisdiction=...)` calls the right detectors automatically. Use these primitives when you're building your own composition.

---

## Launch jurisdictions

| Country | Module | IDs covered |
|---|---|---|
| **NG** Nigeria | `arche.detect.ng.ids` | NIN, BVN, TIN, RC number, voter PVC, driver's licence |
| **KE** Kenya | `arche.detect.ke.ids` | National ID, KRA PIN, NHIF |
| **ZA** South Africa | `arche.detect.za.ids` | SA ID (full Luhn + DOB/gender/citizenship decode), tax reference, passport |
| **GH** Ghana | `arche.detect.gh.ids` | Ghana Card, SSNIT, TIN |

---

## Non-launch African countries

`arche.detect._africa.ids.detect_african_ids(text, country=...)` covers: RW, TZ, UG, ET, CI, SN, CM, EG, MA, AO, MZ.

Country-specific coverage promotes to a top-level `arche.detect.<cc>` module as Stage 2 work — based on launch-partner deployments.

---

## Phone normalization

```python
from arche.detect._africa.phones import normalize_e164, validate_phone

normalize_e164("0803 555 7890", country="NG")
# "+2348035557890"

validate_phone("+254 712 345 678", country="KE")
# (True, "+254712345678", "MOBILE")
```

Wraps the `phonenumbers` Python port of libphonenumber. Covers 30+ African telecom networks per PRD FR-DETECT-9.

---

## Optional ML backends

The v0.1 GLiNER2 NER backend is still available behind the `[detect]` extra:

```bash
pip install arche-core[detect]
```

```python
from arche.detect.gliner import detect_soft_pii
```

Stage 2 grant work delivers `arche-core-model-v1`, a fine-tuned GLiNER2-PII model trained on a synthetic Afro-PII corpus across six anchor languages.
