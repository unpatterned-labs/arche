# `arche.detect`

Per-country PII / identity detectors. Each launch jurisdiction exposes an `ids` module with a single entry function taking only `text` and returning `list[NationalID]`.

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

These per-country detectors return `NationalID` objects - a lighter record than the
[`Detection`](pipeline.md#detection) the `Pipeline` emits. Fields: `text`, `country`,
`id_type`, `confidence`, `start`, `end`, `metadata`:

```python
from arche.detect.ng.ids import detect_nigerian_ids

detect_nigerian_ids("NIN 12345678901, BVN 22156789012.")[0]
# NationalID(text='22156789012', country='NG', id_type='BVN', confidence=0.85,
#            start=21, end=32, metadata={'validator_status': 'format_valid'})
```

Run the same text through `Pipeline` to get `Detection` objects carrying the
[Pan-African PII Taxonomy v0.1](https://github.com/unpatterned-labs/arche/blob/main/datasets/pan-african-pii-taxonomy/v0.1.yaml)
category label, the sensitivity tier, and the statute citation.

> Most callers don't need this surface directly - `Pipeline(jurisdiction=...)` calls the right detectors automatically. Use these primitives when you're building your own composition.

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

`arche.detect._africa.ids.detect_african_ids(text)` covers: RW, TZ, UG, ET, CI, SN, CM, EG, MA, AO, MZ. It takes only `text` - there is no `country` parameter; the country is inferred and reported on each returned `NationalID.country`.

Country-specific coverage promotes to a top-level `arche.detect.<cc>` module as Stage 2 work - based on launch-partner deployments.

---

## Phone normalization

```python
from arche.detect._africa.phones import normalize_e164, validate_phone

normalize_e164("0803 555 7890", default_country="NG")
# '+2348035557890'

validate_phone("+254 712 345 678", default_country="KE")
# {'valid': True,
#  'country': 'KE',
#  'e164': '+254712345678',
#  'national': '0712 345678',
#  'international': '+254 712 345678',
#  'country_calling_code': 254,
#  'line_type': 'mobile',
#  'carrier_hint': 'Safaricom',
#  'region_hint': 'Kenya'}
```

The keyword is `default_country`, not `country`, and it defaults to `"NG"`.
`normalize_e164` returns `str | None`; `validate_phone` returns a `dict`, not a
tuple.

Wraps the `phonenumbers` Python port of libphonenumber. Covers 30+ African telecom networks per PRD FR-DETECT-9.

---

## Optional ML backends

The GLiNER2 NER backend is available behind the `[detect]` extra:

```bash
pip install arche-core[detect]
```

There is **no public API under `arche.detect.gliner` or `arche.detect.presidio`** -
both packages are empty placeholder namespaces in this release. `import
arche.detect.gliner` succeeds but the module exports nothing, so any
`from arche.detect.gliner import ...` line raises `ImportError`.

The optional backends are wired in through `backend=` on the extraction entry
point instead:

```python
from arche.extract import extract

extract("Call 0803 555 7890", backend="regex")
# [EntityReference(text='080***', type='PHONE', confidence=0.90, source='african')]

extract(text, backend="gliner")   # raises ModuleNotFoundError without [detect]
```

`backend` accepts `"auto"` (default - GLiNER when installed, regex otherwise),
`"auto+llm"`, `"gliner"`, and `"regex"`. Presidio is reached through
`arche.protect`, which uses it when installed and falls back to regex when it is
not; it has no `arche.detect.presidio` surface.

Future model-backed detectors will be documented when they are ready for public evaluation.
