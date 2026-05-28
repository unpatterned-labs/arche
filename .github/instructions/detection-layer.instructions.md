---
applyTo:
  - "packages/arche-core/src/arche/detect/**/*.py"
  - "packages/arche-core/src/arche/addr/**/*.py"
  - "packages/arche-core/src/arche/locate.py"
  - "packages/arche-core/tests/test_african.py"
  - "packages/arche-core/tests/test_extract.py"
  - "packages/arche-core/tests/test_ids_validators.py"
  - "datasets/**/*"
---

# Detection layer (`arche.detect`, `arche.addr`)

## What lives where
- `arche/detect/_base.py` — `NationalID`, `Detection` (when emitted at the detector boundary), shared confidence helpers.
- `arche/detect/{ng,ke,za,gh}/` — per-country detectors. Each country has `ids.py` (national IDs, BVN, etc.) and `phones.py` (libphonenumber-backed validators).
- `arche/detect/_africa/` — pan-African fallback (`ids.py`, `phones.py`). Runs when `Pipeline` has no jurisdiction or one we don't have a specific detector for.
- `arche/detect/names/` — African name lexicon (114+ equivalence groups, ~454 forms). Loaded lazily.
- `arche/detect/locations/` — African city gazetteer (~500 cities + aliases).
- `arche/detect/{ip,digital_id,phones,gliner,presidio}/` — cross-cutting detectors. Phone numbers are libphonenumber-validated. GLiNER and Presidio are opt-in extras.
- `arche/addr/` — address parser (NG + ZA MVP). Stage 1 / Week 3 delivery; emits `PII-4-ADDRESS` with structured components.
- `arche/locate.py` — coordinate enrichment for `LOCATION` entities.

## The detector contract
Every detector exposes a top-level function returning a list. Two acceptable shapes:

1. **Old-style** `NationalID` (or sibling dataclass with `start`, `end`, `text`, `confidence`, `id_type`, `country`). The `Pipeline._to_detection` adapter converts these to canonical `Detection`. Use for per-country IDs.
2. **New-style** `Detection` (the canonical shape from `arche.workflow._primitive`). Use for cross-cutting detectors (`ip`, `digital_id`, address). The detector controls its own `category` mapping.

Choose new-style for new detectors. Old-style remains only for backward-compat.

## Category naming (PRD §10.2)
Use the **Pan-African PII Taxonomy** prefix scheme — do not invent new top-level categories without an RFC:

- `PII-1-NAME` — names (full, given, family)
- `PII-2-{ID_TYPE}` — government identifiers (`PII-2-NIN`, `PII-2-BVN`, `PII-2-GHANA_CARD`, `PII-2-NATIONAL_ID`, etc.)
- `PII-3-PHONE` — phone numbers
- `PII-3-EMAIL` — email addresses
- `PII-4-ADDRESS` / `PII-4-LOCATION` — physical addresses, city/region tokens
- `PII-5-IP` — IP addresses
- `PII-6-DIGITAL_ID` — handles, wallet addresses, etc.

The category string is **the policy key**. Statute YAML files map these categories to `(action, statute_reference, sensitivity_tier)`. A mismatched category here silently disables policy enforcement — see `policy-and-statutes.instructions.md`.

## African-context rules
- **Phone numbers** — use `arche.detect.phones.detect_phones` with `default_country=<jurisdiction>` for local-format parsing. Never hand-roll a country code regex; libphonenumber handles 30+ African networks plus E.164.
- **Names** — the `names` detector loads the lexicon lazily on first call. Names are case- and tonal-mark-sensitive: Adeyemi ≠ Adeyẹmí for byte-exact matching, but they cluster in the equivalence groups. Do not strip tonal marks at the detector boundary; strip only at comparator time inside `arche.resolve._matcher`.
- **National IDs** — every per-country `ids.py` validates with checksum / length / prefix rules (e.g. NIN = 11 digits, BVN = 11 digits with `22` prefix, SA ID = 13 digits Luhn-validated + embeds DOB and gender). When adding a new country, ship the checksum validator with the pattern.

## Adding a new country detector — checklist
1. Create `arche/detect/<cc>/` with `__init__.py`, `ids.py`, `phones.py`.
2. Implement `detect_<country>_ids(text: str) -> list[NationalID]` returning every validated ID found.
3. Wire it into `Pipeline._run_detectors` (`_primitive.py`, the `elif pkg == "<cc>"` block).
4. Add the country to `Pipeline._STATUTE_FOR_JURISDICTION` if it has a statute YAML, otherwise it falls back to no-policy.
5. Add a statute YAML in `arche/policy/_data/` (see `policy-and-statutes.instructions.md`).
6. Add tests in `packages/arche-core/tests/test_jurisdiction_<country>.py`. The four existing jurisdiction test files are your templates.
7. If the country has a unique phone numbering plan with libphonenumber gaps, add a focused regression test in `test_african.py`.

## Tests live here
- `tests/test_extract.py` — generic extractor + GliNER + regex backends.
- `tests/test_african.py` — pan-African ID detector regressions.
- `tests/test_ids_validators.py` — per-country checksum/length validators.
- `tests/test_jurisdiction_{nigeria,kenya,south_africa,ghana}.py` — end-to-end through `Pipeline`.
- `tests/test_pipeline.py` — `Pipeline` composition smoke tests.
