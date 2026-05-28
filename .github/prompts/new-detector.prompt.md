---
mode: agent
description: Add a new per-country or cross-cutting detector to arche.detect.
---

# Add a new detector

For a new **per-country** detector (e.g. Egyptian National ID): scaffold `arche/detect/<cc>/` and wire into `Pipeline`.
For a new **cross-cutting** detector (e.g. crypto wallet addresses): add a module under `arche/detect/` that emits canonical `Detection`.

## 1. Read first
- `.github/instructions/detection-layer.instructions.md` — the full detector contract, category naming, and the per-country checklist.
- The nearest existing detector — `arche/detect/ng/ids.py` for per-country, `arche/detect/ip/__init__.py` for cross-cutting.

## 2. Confirm scope
- **Which entity?** Be specific. "Egyptian National ID" not "Egyptian IDs".
- **Which category string?** Must match the PII taxonomy: `PII-2-NATIONAL_ID`, `PII-2-NIN`, `PII-3-PHONE`, `PII-4-ADDRESS`, etc. New top-level prefixes need an RFC.
- **Validation rule?** Length, checksum, prefix, character set. State it before coding.
- **Which jurisdiction?** Per-country detectors must map to a statute (or be explicitly fallback-only via `arche.detect._africa`).

## 3. Per-country implementation
1. Create `arche/detect/<cc>/__init__.py`, `arche/detect/<cc>/ids.py`, optionally `phones.py`.
2. Implement `detect_<country>_ids(text: str) -> list[NationalID]` — return every validated ID with `start`, `end`, `text`, `confidence`, `id_type`, `country`.
3. Wire into `Pipeline._run_detectors` in `arche/workflow/_primitive.py` — add an `elif pkg == "<cc>":` branch.
4. Add to `Pipeline._STATUTE_FOR_JURISDICTION` if there's a statute YAML for the country.
5. Add the statute YAML in `arche/policy/_data/<STATUTE-ID>.yaml` with `policy_mappings` for every category your detector emits.

## 4. Cross-cutting implementation
1. Create `arche/detect/<thing>/__init__.py` with `def detect_<thing>(text: str) -> list[Detection]`.
2. Emit canonical `Detection` directly (not `NationalID`) — set `category` yourself, set `detector` to a stable string like `rule:<thing>` or `model:<thing>`.
3. Wire into `Pipeline._default_detectors` so it runs by default, then into `Pipeline._run_detectors` to dispatch.
4. Update every statute YAML to map the new category, or accept that it stays `MODERATE / None` until they do.

## 5. Test
- `tests/test_<your_country_or_cross_cut>.py` with:
  - happy path (clean text → expected detections).
  - text with the entity in the middle of other PII (span correctness).
  - invalid checksum / wrong length (rejected).
  - empty input.
  - Unicode / mixed-language input (does not crash).
- Per-country: extend `tests/test_jurisdiction_<country>.py` with end-to-end `Pipeline` assertions including the new category's `statute_reference`.

## 6. Performance
- Detectors run on every `Pipeline.process(text)` call. Hot path.
- Use compiled regex (module-level `re.compile(...)`). Do not compile inside the function.
- libphonenumber and the names lexicon are pre-loaded; respect that — your detector should add <1ms per call for a 1KB text.

## 7. PR
- One sentence: which entity, which jurisdiction, where it slots into the taxonomy.
- The validation rule, cited (e.g. "NIN spec: 11 digits, NIMC published format").
- Which statute YAMLs were updated.
- Test commands + outcomes.
