---
mode: agent
description: Add or update a statute YAML mapping for an existing jurisdiction.
---

# Statute YAML mapping

Use this when you need to change `arche/policy/_data/<STATUTE>.yaml`: adding a new PII category to the mapping, updating an action (e.g. mask → tokenize), or revising a statute reference.

## 1. Confirm the regulator's position
- Cite the **specific statute section** you are mapping to. "NDPA s.30" is good; "NDPA" alone is not.
- If the action is changing from what was there before, document **why** in the PR (regulator updated guidance? prior choice was wrong?).
- For a new category, confirm the **detection layer actually emits it** — grep `packages/arche-core/src/arche/detect/` for the category string. A mapping for a category nothing emits is dead code.

## 2. Edit the YAML
Open `packages/arche-core/src/arche/policy/_data/<STATUTE>.yaml` and add or update under `policy_mappings`:

```yaml
policy_mappings:
  PII-2-<NEW_CATEGORY>:
    action: mask              # one of: mask, tokenize, drop, generalize, audit, retain
    statute_reference: "<STATUTE> s.<N>, <supplementary citation if applicable>"
    sensitivity_tier: HIGH    # HIGH | MODERATE | LOW
    rationale: "<one sentence the regulator would recognise>"
```

The six actions are **closed**. If none fits, escalate to a design discussion — do not add a seventh.

## 3. Bump the statute `version`
- Patch bump (`1.0.0` → `1.0.1`) for added mappings or rationale clarifications.
- Minor bump (`1.0.0` → `1.1.0`) for action changes that change observable behaviour.
- Major bump (`1.0.0` → `2.0.0`) for regulator-issued amendments that reorganise sections (e.g. NDPA superseded by a new act).

## 4. Tests — `tests/test_jurisdiction_<country>.py`
Add or update:
- An assertion that `policy_outcomes[i].action == "<expected>"` for text containing the category.
- An assertion that `policy_outcomes[i].statute_reference` is the exact string you put in the YAML.
- If the action changes the redacted text shape, assert on `result.redacted_text` too.

## 5. Cross-check the alignment
Run for every category in the statute:
```bash
uv run python -c "from arche.policy import load_statute; s = load_statute('<STATUTE_ID>'); print(sorted(s.policy_mappings.keys()))"
```
Then grep `packages/arche-core/src/arche/detect/` for each category. Anything in the YAML that nothing emits is dead. Anything emitted that's not in the YAML stays unredacted with `MODERATE / None` defaults — usually a bug.

## 6. Documentation
- Update `CHANGELOG.md` under "Unreleased" with the statute id, the category, and the action.
- If the change is regulator-mandated (e.g. NDPC issued new guidance), link the regulator's document in the PR description.

## What not to do
- Do not edit a statute YAML to "make a test pass". The YAML reflects the regulator's position, not the code's convenience.
- Do not add `mask` everywhere out of caution — `retain` and `audit` are valid actions and over-masking destroys legitimate downstream use cases.
- Do not commit YAML with merged conflict markers. Statute files are particularly prone to silent merges.
