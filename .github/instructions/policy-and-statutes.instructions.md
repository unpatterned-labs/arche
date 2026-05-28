---
applyTo:
  - "packages/arche-core/src/arche/policy/**/*.py"
  - "packages/arche-core/src/arche/policy/_data/**/*.yaml"
  - "packages/arche-core/src/arche/jurisdictions/**/*.py"
  - "packages/arche-core/src/arche/governance.py"
  - "packages/arche-core/tests/test_governance.py"
  - "packages/arche-core/tests/test_jurisdiction_*.py"
---

# Policy and statute YAML

## What this layer is
The policy layer turns **detections** into **enforceable, defensible actions** grounded in a specific data-protection statute. Every detection that flows through `Pipeline.process(text)` exits with two pieces of statute-attached metadata:

- `Detection.sensitivity_tier` — `HIGH | MODERATE | LOW`, set by the loaded statute.
- `Detection.regulatory_citation` — the actual statute section (`"NDPA-2023 s.30, NIMC Act s.27"`), set by the loaded statute.

The output of `apply_policy()` is a list of `PolicyOutcome` objects: one of six **closed** actions per detection, with the statute reference that decided it.

## The six closed actions (do not extend without an RFC)
- `mask` — replace span with `[CATEGORY]` placeholder
- `tokenize` — replace span with deterministic non-reversible hash (salted per deployment)
- `drop` — remove span entirely from the redacted text
- `generalize` — replace with a less-specific value (e.g. exact DOB → year only)
- `audit` — leave the span in place, emit an audit event
- `retain` — leave the span in place, no audit event

The action set is deliberately small and testable. Each new statute must map every PII category to one of these six. Do not add a seventh.

## Statute YAML files (`arche/policy/_data/`)
Files: `NDPA-2023.yaml` (Nigeria), `POPIA.yaml` (South Africa), `KENYA-DPA.yaml` (Kenya), `GHANA-DPA.yaml` (Ghana). Every file has the same shape:

```yaml
id: NDPA-2023
version: "1.0.0"
jurisdiction: NG
regulator: "Nigeria Data Protection Commission"
policy_mappings:
  PII-2-NIN:
    action: mask
    statute_reference: "NDPA-2023 s.30, NIMC Act s.27"
    sensitivity_tier: HIGH
    rationale: "..."
  PII-2-BVN:
    action: mask
    statute_reference: "NDPA-2023 s.30, CBN BVN policy 2014"
    sensitivity_tier: HIGH
    rationale: "..."
  # ... every PII-* category the detection layer can emit ...
```

Statutes are **versioned, community-reviewable, editable without code changes**. Treat each YAML as canonical source — a lawyer should be able to read it without reading Python.

## Adding or editing a statute mapping
1. Identify the category — must match exactly what the detection layer emits (see `detection-layer.instructions.md`).
2. Pick one of the six closed actions. If none fit, escalate; do not invent.
3. Pick the **specific statute section** for the `statute_reference`. "NDPA-2023" alone is not enough; cite the section.
4. Pick a sensitivity tier. NG/ZA/KE/GH definitions vary; use the regulator's published guidance, not a guess.
5. Add a one-line `rationale` explaining the choice. This is what the audit reader sees.
6. Add a regression test in `tests/test_jurisdiction_<country>.py` asserting `policy_outcomes[i].action == ...` and `policy_outcomes[i].statute_reference == ...` for the new category.

## Critical: category alignment between detect and policy
A category string in `policy_mappings` that does not match what a detector emits **silently disables policy enforcement** for that PII type — the detection ships unredacted with a `MODERATE / None` default. There is no error; the test simply fails to assert what you expected.

Whenever you change a detector category or add a new PII type:
1. Grep `packages/arche-core/src/arche/policy/_data/` for the old category and update every statute file.
2. Run `tests/test_jurisdiction_{ng,ke,za,gh}.py` — these are the smoke tests for this alignment.

## The `governance.py` and `jurisdictions/*` shims
- `arche.governance` — the v0.1 compliance-report layer. Kept for the deprecation window. Do not extend it; new compliance work goes through `arche.policy` + `arche.graph.audit`.
- `arche/jurisdictions/{nigeria,kenya,south_africa,ghana}.py` — v0.1 jurisdiction-pack helpers. Still used by `governance.py` and by the v0.2 statute YAMLs as a data source. Edits here should be paired with statute YAML edits.

## What this layer does NOT do
- No fraud / risk / churn / opportunity heuristics. That layer was removed in v0.2.0a3 — it was example-tier guessing without a statute behind it. Compliance signals come from `policy_outcomes` only.
- No "consent management" — that's a Stage 3 product. The audit log records what *happened*; consent capture happens upstream of the SDK.
