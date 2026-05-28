---
mode: agent
description: Onboard a new jurisdiction (new country + statute YAML + detectors + tests).
---

# New jurisdiction onboarding

A jurisdiction in `arche` is a tuple of (country, statute, detectors, tests). Adding one is a non-trivial coordinated change across four files minimum.

## Prerequisite
**Read the regulator's actual published guidance** before writing any YAML. Do not infer sensitivity tiers from "vibes" or from a neighbouring country. If you can't cite a section, you don't have the mapping yet.

## 1. Statute YAML — `arche/policy/_data/<STATUTE-ID>.yaml`
Use one of the four launch statutes as a template:
- `arche/policy/_data/NDPA-2023.yaml` (Nigeria)
- `arche/policy/_data/POPIA.yaml` (South Africa)
- `arche/policy/_data/KENYA-DPA.yaml` (Kenya)
- `arche/policy/_data/GHANA-DPA.yaml` (Ghana)

Required top-level keys: `id`, `version`, `jurisdiction` (ISO 3166-1 alpha-2), `regulator`, `policy_mappings`.

`policy_mappings` must cover **every PII category the detection layer can emit**. Use `.github/instructions/policy-and-statutes.instructions.md` for the six closed actions. Each mapping needs `action`, `statute_reference`, `sensitivity_tier`, `rationale`.

## 2. Per-country detectors — `arche/detect/<cc>/`
See `new-detector.prompt.md`. At minimum: `ids.py` for national IDs, `phones.py` if the country isn't already well-served by libphonenumber defaults.

## 3. Wire into `Pipeline` — `arche/workflow/_primitive.py`
- Add the country to `Pipeline._STATUTE_FOR_JURISDICTION` so `Pipeline(jurisdiction="<CC>")` auto-loads the statute.
- Add an `elif pkg == "<cc>":` branch in `_run_detectors`.
- Add the country to the `{"NG", "KE", "ZA", "GH"}` set in `_default_detectors` (or extend the set's name to reflect the new launch set).

## 4. Jurisdiction pack (v0.1 shim) — `arche/jurisdictions/<country>.py`
Only if you're maintaining the v0.1 governance surface. New countries can skip this and go statute-YAML-only.

## 5. Tests — `tests/test_jurisdiction_<country>.py`
Copy `tests/test_jurisdiction_nigeria.py` as a template. Required cases:
- `Pipeline(jurisdiction="<CC>").process(text_with_national_id)` redacts the ID and cites the statute section.
- `Pipeline(jurisdiction="<CC>").process(text_with_phone)` handles country-format and E.164 numbers.
- A negative test: `Pipeline(jurisdiction="<CC>").process(text_with_no_pii)` returns zero detections.
- A boundary test: text containing IDs from two countries; only the configured jurisdiction's detector finds its own.

## 6. Documentation
- Update `packages/arche-core/README.md` — the jurisdiction table and the "Four launch jurisdictions" line.
- Update `CHANGELOG.md` with a one-line entry under the upcoming version.

## 7. PR checklist
- [ ] New statute YAML reviewed against published regulator guidance.
- [ ] Every category in `policy_mappings` is one the detection layer actually emits (grep `PII-*` in `arche/detect/`).
- [ ] `Pipeline(jurisdiction="<CC>")` works end-to-end in `tests/test_jurisdiction_<country>.py`.
- [ ] `Pipeline._default_detectors` updated.
- [ ] README + CHANGELOG updated.
- [ ] Full test suite passes on Python 3.11, 3.12, 3.13 (CI matrix).
