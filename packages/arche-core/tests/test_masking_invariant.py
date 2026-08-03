# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Step 5 (engine reconciliation): the one-directional masking invariant.

Display/egress must NEVER be more permissive than the strictest shipped statute:
if ANY statute applies a protective action (mask/tokenize/drop/generalize) to a
category, the attribute that category maps to must be PII in the display
vocabulary (masked by default in render, subject-claim-gated in attest).
Display *stricter* than law is fine (that direction is safe by design).
"""

from pathlib import Path

from arche.canonical import (
    CATEGORY_TO_ATTRIBUTE,
    SAFE_DESCRIPTOR_NAMES,
    attribute_for_category,
    is_pii_attribute,
)
from arche.policy import load_statute

_STATUTES_DIR = (
    Path(__file__).resolve().parents[1] / "src" / "arche" / "policy" / "statutes"
)
_PROTECTIVE = {"mask", "tokenize", "drop", "generalize", "redact"}


def _all_statutes():
    return [load_statute(p.stem) for p in _STATUTES_DIR.glob("*.yaml")]


def test_render_never_more_permissive_than_strictest_statute():
    statutes = _all_statutes()
    assert statutes, "no shipped statutes found"
    violations = []
    for statute in statutes:
        for category, mapping in statute.policy_mappings.items():
            action = (mapping or {}).get("action", statute.default_action)
            if action not in _PROTECTIVE:
                continue  # retain/audit: the law permits it in the clear
            attr = attribute_for_category(category)
            if attr is None:
                continue  # excluded from references entirely — strictest outcome
            if not is_pii_attribute(attr):
                violations.append((statute.statute_id, category, attr, action))
    assert not violations, (
        "display vocabulary is MORE permissive than the law for: "
        f"{violations} — these attributes must be PII (masked by default)"
    )


def test_statute_drop_categories_never_map_to_disclosable_attributes():
    # The strictest legal action: for every shipped statute, a drop-actioned
    # category either never enters a reference (table-excluded) or its
    # attribute is PII — never a safe descriptor.
    for statute in _all_statutes():
        for category, mapping in statute.policy_mappings.items():
            if (mapping or {}).get("action") != "drop":
                continue
            attr = attribute_for_category(category)
            assert attr is None or is_pii_attribute(attr), (
                f"{statute.statute_id}:{category} is drop-actioned but maps to "
                f"non-PII attribute {attr!r}"
            )


def test_safe_descriptor_list_is_reviewed_canary():
    # The allowlist is the load-bearing PII default; additions must be
    # deliberate. This canary fails if someone casually widens it.
    assert SAFE_DESCRIPTOR_NAMES <= {
        "country", "source_system", "entity_type", "category",
        "jurisdiction", "type", "id_type",
    }


def test_every_mapped_category_attribute_is_pii_or_location():
    # Every attribute the bridge can produce is PII by the display vocabulary
    # (nothing the detectors emit renders in the clear by default).
    non_pii = {
        attr for attr in CATEGORY_TO_ATTRIBUTE.values() if not is_pii_attribute(attr)
    }
    assert not non_pii, f"bridge-producible attributes not PII: {non_pii}"
