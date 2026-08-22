# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Policy layer - jurisdiction-aware enforcement of data protection statutes.

Per Stage 1 PRD §6. Loads machine-readable YAML statute files for the four
launch jurisdictions (NDPA-2023, POPIA, Kenya DPA, Ghana DPA), routes each
detection through the applicable statute, and applies one of six closed
actions:

    mask         - replace with category-label placeholder
    tokenize     - replace with deterministic non-reversible token
    drop         - remove span entirely
    generalize   - replace with less-specific value
    audit        - leave in place but record audit event
    retain       - leave in place without audit event

The action set is deliberately closed and small. Each action is unambiguous
and testable. The statute files (under `statutes/`) are versioned, community-
reviewable, and editable without code changes.

Public API:
    from arche.policy import load_statute, apply_policy, PolicyOutcome, Statute
    from arche.policy import ACTIONS, list_available_statutes
"""

from dataclasses import dataclass

from arche.policy.engine import (
    ACTIONS,
    PolicyOutcome,
    Statute,
    apply_policy,
    list_available_statutes,
    load_statute,
)

# Which statute pack governs a jurisdiction, and why nothing does when nothing
# does. Lives here rather than on `Pipeline` because it is policy data, not
# pipeline mechanics, and because callers outside the pipeline need it: an agent
# deciding whether to proceed has to know a jurisdiction is unpoliced *before*
# it hands over a document, not by receiving a refusal that reads like a bug.
STATUTE_FOR_JURISDICTION: dict[str, str] = {
    "NG": "NDPA-2023",
    "ZA": "POPIA",
    "KE": "KENYA-DPA",
    "GH": "GHANA-DPA",
    # The UK is its own regime post-Brexit: retained UK GDPR plus DPA 2018,
    # ICO oversight, IDTA transfers, digital consent at 13. Close enough to
    # the EU's category actions to be safe to ship, different enough that
    # pointing at EU instruments would cite the wrong law.
    "GB": "UK-GDPR",
    # EU / EEA member states -> GDPR. Sectoral or stricter-national regimes
    # use the explicit escape hatch instead, e.g.
    # Pipeline(jurisdiction="US", statute="HIPAA-SAFE-HARBOR").
    **dict.fromkeys(
        (
            "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR",
            "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL",
            "PL", "PT", "RO", "SK", "SI", "ES", "SE",  # EU-27
            "IS", "LI", "NO",                            # EEA
        ),
        "GDPR",
    ),
    # The Union itself, not a member state. `arche.jurisdictions.infer` emits
    # "EU" from a VAT number or a euro amount, which identifies the regime
    # without identifying the country — and GDPR is the Union-wide instrument,
    # so it is the correct answer rather than a fallback. This row was missing,
    # and its absence meant a document that inferred EU with confidence 1.0 then
    # met a refusal saying no statute was configured. "EU" is an ISO 3166-1
    # exceptional reservation, not an alpha-2 country code; that is why it did
    # not arrive with the member states.
    "EU": "GDPR",
}

# Jurisdictions with no pack, and the reason, so a refusal can explain itself.
# A jurisdiction absent from BOTH mappings gets the generic message.
_NO_STATUTE_REASON: dict[str, str] = {
    "US": (
        "the United States has no omnibus federal privacy statute, so there is "
        "no single pack to apply. This is a fact about US law rather than a gap "
        "in arche"
    ),
    "IN": (
        "India's DPDP Act 2023 is in force but its rules were still being "
        "finalised when this shipped, and a pack citing sections that may move "
        "would be worse than none"
    ),
    "BR": "no LGPD pack ships yet",
    "CN": "no PIPL pack ships yet",
}

# Offered when nothing governs. BASELINE applies category actions with no
# statutory citation, which is honest about being a floor rather than a law.
_FALLBACK_STATUTES: tuple[str, ...] = ("BASELINE",)
_US_ALTERNATIVES: tuple[str, ...] = ("HIPAA-SAFE-HARBOR", "BASELINE")


@dataclass(frozen=True)
class StatuteChoice:
    """Which statute governs a jurisdiction, and what to do when none does."""

    jurisdiction: str | None
    statute_id: str | None
    #: True when a pack governs this jurisdiction. False is not an error: most
    #: of the world has no pack here, and some of it has no law to pack.
    available: bool
    #: One sentence a caller can show a person. Empty when a pack was found.
    reason: str = ""
    #: Statutes a caller could pass explicitly instead, most specific first.
    alternatives: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "jurisdiction": self.jurisdiction,
            "statute_id": self.statute_id,
            "available": self.available,
            "reason": self.reason,
            "alternatives": list(self.alternatives),
        }


def statute_for(jurisdiction: str | None) -> StatuteChoice:
    """The statute governing ``jurisdiction``, or an explained absence.

    The absence is the point. `arche.jurisdictions.infer` can name a country
    with confidence 1.0 that no pack covers, and until this existed the next
    step was a refusal reading "no statute configured on the pipeline", which
    describes arche's state rather than the caller's problem and reads as a bug.

    An agent should call this *before* handing over a document, so an unpoliced
    jurisdiction is a decision it makes rather than a wall it hits.
    """
    if not jurisdiction:
        return StatuteChoice(
            jurisdiction=None, statute_id=None, available=False,
            reason="no jurisdiction given, so no statute can be chosen",
            alternatives=_FALLBACK_STATUTES,
        )

    code = jurisdiction.upper()
    found = STATUTE_FOR_JURISDICTION.get(code)
    if found:
        return StatuteChoice(code, found, True)

    reason = _NO_STATUTE_REASON.get(
        code, f"no statute pack ships for {code}")
    return StatuteChoice(
        jurisdiction=code, statute_id=None, available=False, reason=reason,
        alternatives=_US_ALTERNATIVES if code == "US" else _FALLBACK_STATUTES,
    )


__all__ = [
    "statute_for",
    "StatuteChoice",
    "STATUTE_FOR_JURISDICTION",
    "ACTIONS",
    "PolicyOutcome",
    "Statute",
    "apply_policy",
    "list_available_statutes",
    "load_statute",
]
