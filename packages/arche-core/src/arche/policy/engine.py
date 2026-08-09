# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Jurisdiction-aware policy enforcement engine.

Per Stage 1 PRD §6. Loads machine-readable YAML statute files from
``arche/policy/statutes/`` and applies one of six closed actions to each
detection per the configured jurisdiction:

    mask        - replace span with category-label placeholder ([NIN], [NAME])
    tokenize    - replace span with a deterministic non-reversible token
    drop        - remove the span entirely from the output
    generalize  - replace with a less-specific value (1985-03-14 -> 1985)
    audit       - leave the span in place but emit an audit event
    retain      - leave the span in place without an audit event

The action set is closed and small. Each action is unambiguous and testable.
Future actions can be added without breaking the framework.

Public API::

    from arche.policy import load_statute, apply_policy, PolicyOutcome

    statute = load_statute("NDPA-2023")
    redacted, outcomes = apply_policy(text, detections, statute)
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

from arche._types import SensitivityTier

# ---------------------------------------------------------------------------
# Action set 
# ---------------------------------------------------------------------------

ACTIONS: frozenset[str] = frozenset(
    {"mask", "tokenize", "drop", "generalize", "audit", "retain"}
)

# Who vouches for a statute pack's mappings. Deliberately separate from the
# pack's ``version`` (completeness/stability): shipping a complete mapping is
# our work; a regulator having reviewed it is a fact about the world, and the
# two must never be conflated in a product whose promise is statute citation.
_REVIEW_STATUSES: frozenset[str] = frozenset(
    {"self-reviewed", "regulator-reviewed"}
)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class _HasSpan(Protocol):
    """Anything with a ``start``, ``end``, ``text``, and ``category`` (or
    similar) attribute can be policy-routed.  Detection records from
    ``arche.detect.*`` all satisfy this informally."""

    start: int
    end: int


@dataclass
class PolicyOutcome:
    """Outcome of applying a statute policy to a single detection.

    Per PRD §10.2 ``PolicyOutcome`` type definition. ``applied_value`` holds
    the text that ended up in the redacted output (or the original text if
    the action was retain/audit).
    """

    detection_id: str
    category: str
    action: str
    statute_reference: str
    statute_id: str
    statute_version: str
    rationale: str | None
    applied_value: str
    span: tuple[int, int]


@dataclass
class Statute:
    """A loaded statute, ready for policy application."""

    statute_id: str
    jurisdiction: str
    version: str
    effective_date: str
    authority: str
    policy_mappings: dict[str, dict[str, Any]]
    # Who vouches for the mappings — orthogonal to ``version`` (which means
    # "complete and stable"). ``self-reviewed``: arche's own mapping against
    # the cited sections, no external review. ``regulator-reviewed``: the
    # named authority reviewed it (``reviewed_by`` / ``reviewed_on`` say who
    # and when). Never claim the latter without a citable review.
    review_status: str = "self-reviewed"
    reviewed_by: str = ""
    reviewed_on: str = ""
    default_action: str = "mask"
    default_statute_reference: str = ""
    breach_notification_window_hours: int | None = None
    retention_limits: dict[str, Any] = field(default_factory=dict)
    cross_border_transfer: dict[str, Any] = field(default_factory=dict)
    penalties: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def action_for(self, category: str) -> tuple[str, str, str | None]:
        """Return (action, statute_reference, rationale) for a PII category.

        Falls back to ``default_action`` for unmapped categories.
        """
        mapping = self.policy_mappings.get(category)
        if mapping is None:
            return (
                self.default_action,
                self.default_statute_reference or f"{self.statute_id} (default)",
                None,
            )
        action = mapping.get("action", self.default_action)
        if action not in ACTIONS:
            raise ValueError(
                f"Statute {self.statute_id} maps {category} to unknown action "
                f"{action!r}. Allowed: {sorted(ACTIONS)}"
            )
        return (
            action,
            mapping.get("statute_reference", self.default_statute_reference),
            mapping.get("rationale"),
        )

    def tier_for(self, category: str) -> SensitivityTier:
        """Return the sensitivity tier the statute assigns to ``category``.

        Falls back to :attr:`SensitivityTier.MODERATE` when the category is
        unmapped or the mapping omits the ``tier:`` field. MODERATE is the
        conservative default: it triggers audit logging but no automatic
        elevated handling. Statutes may assign HIGH for biometric or
        foundational-ID categories and LOW for public-record categories
        such as company registration numbers.

        Raises:
            ValueError: when the YAML ``tier:`` value is not one of
                ``"high"`` / ``"moderate"`` / ``"low"``. Load-time
                validation in :func:`load_statute` catches this earlier
                for all categories, so this path is only reached if the
                statute's :attr:`policy_mappings` dict is mutated
                post-load.
        """
        mapping = self.policy_mappings.get(category)
        if mapping is None:
            return SensitivityTier.MODERATE
        tier_str = mapping.get("tier")
        if tier_str is None:
            return SensitivityTier.MODERATE
        try:
            return SensitivityTier(tier_str)
        except ValueError as exc:
            valid = [t.value for t in SensitivityTier]
            raise ValueError(
                f"Statute {self.statute_id} maps {category} to unknown "
                f"tier {tier_str!r}. Allowed: {valid}"
            ) from exc


# ---------------------------------------------------------------------------
# Statute loading
# ---------------------------------------------------------------------------

_STATUTES_DIR = Path(__file__).resolve().parent / "statutes"
_STATUTE_CACHE: dict[str, Statute] = {}


def list_available_statutes() -> list[str]:
    """Return the statute IDs that ship with this arche-core install."""
    if not _STATUTES_DIR.exists():
        return []
    return sorted(p.stem for p in _STATUTES_DIR.glob("*.yaml"))


def load_statute(statute_id: str) -> Statute:
    """Load a YAML statute file from ``arche/policy/statutes/``.

    Parameters
    ----------
    statute_id:
        Statute identifier (filename without ``.yaml``), e.g. ``"NDPA-2023"``.

    Raises
    ------
    FileNotFoundError
        If no statute file matches.
    ValueError
        If the statute file is structurally invalid.
    """
    if statute_id in _STATUTE_CACHE:
        return _STATUTE_CACHE[statute_id]

    path = _STATUTES_DIR / f"{statute_id}.yaml"
    if not path.exists():
        available = ", ".join(list_available_statutes()) or "(none shipped)"
        raise FileNotFoundError(
            f"Statute {statute_id!r} not found at {path}. Available: {available}"
        )

    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    if not isinstance(raw, dict):
        raise ValueError(f"Statute file {path} did not parse to a mapping")

    required_keys = {"statute_id", "jurisdiction", "version", "policy_mappings"}
    missing = required_keys - raw.keys()
    if missing:
        raise ValueError(
            f"Statute file {path} is missing required keys: {sorted(missing)}"
        )
        
    review_status = raw.get("review_status", "self-reviewed")
    if review_status not in _REVIEW_STATUSES:
        raise ValueError(
            f"Statute file {path} declares review_status={review_status!r}; "
            f"allowed: {sorted(_REVIEW_STATUSES)}"
        )
    if review_status == "regulator-reviewed" and not raw.get("reviewed_by"):
        # Fail closed on the claim that matters most: a pack may not assert
        # regulator review without naming the reviewer.
        raise ValueError(
            f"Statute file {path} claims review_status='regulator-reviewed' "
            "but names no reviewed_by. Regulator review must be attributable."
        )

    statute = Statute(
        statute_id=raw["statute_id"],
        jurisdiction=raw["jurisdiction"],
        version=raw["version"],
        effective_date=raw.get("effective_date", ""),
        authority=raw.get("authority", ""),
        policy_mappings=raw["policy_mappings"] or {},
        review_status=review_status,
        reviewed_by=raw.get("reviewed_by", ""),
        reviewed_on=str(raw.get("reviewed_on", "")),
        default_action=raw.get("default_action", "mask"),
        default_statute_reference=raw.get("default_statute_reference", ""),
        breach_notification_window_hours=raw.get("breach_notification_window_hours"),
        retention_limits=raw.get("retention_limits", {}),
        cross_border_transfer=raw.get("cross_border_transfer", {}),
        penalties=raw.get("penalties", {}),
        raw=raw,
    )

    # Validate every mapped action AND tier is in its closed set up front so
    # we fail at load time rather than mid-pipeline. Missing tier is
    # allowed and defaults to MODERATE; only malformed values raise.
    _valid_tiers = {t.value for t in SensitivityTier}
    for category, mapping in statute.policy_mappings.items():
        action = mapping.get("action", statute.default_action)
        if action not in ACTIONS:
            raise ValueError(
                f"Statute {statute_id} maps {category} to unknown action "
                f"{action!r}. Allowed: {sorted(ACTIONS)}"
            )
        tier = mapping.get("tier")
        if tier is not None and tier not in _valid_tiers:
            raise ValueError(
                f"Statute {statute_id} maps {category} to unknown tier "
                f"{tier!r}. Allowed: {sorted(_valid_tiers)} or omit for "
                f"the MODERATE default."
            )

    _STATUTE_CACHE[statute_id] = statute
    return statute


# ---------------------------------------------------------------------------
# Action implementations
# ---------------------------------------------------------------------------

def _mask(category: str, original: str) -> str:
    """Replace span with category-label placeholder."""
    # PII-2-NIN -> [NIN] ; PII-3-PHONE -> [PHONE] ; PII-1-NAME -> [NAME]
    parts = category.split("-")
    label = parts[-1] if parts else "PII"
    return f"[{label}]"


def _tokenize(category: str, original: str, salt: str = "") -> str:
    """Return a deterministic-but-non-reversible token for this span.

    Same input plus same salt -> same token. Different deployments use
    different salts so tokens don't leak across organizations. PRD §6.3:
    "same input always produces same token within a deployment for join
    consistency."
    """
    parts = category.split("-")
    label = parts[-1] if parts else "PII"
    digest = hashlib.blake2b(
        (salt + original).encode("utf-8"), digest_size=4
    ).hexdigest()
    return f"{label}_{digest}"


def _drop(category: str, original: str) -> str:
    """Remove the span entirely from output (empty string)."""
    return ""


_DATE_RE = re.compile(r"^(\d{4})[-/](\d{2})[-/](\d{2})$")


def _generalize(category: str, original: str) -> str:
    """Replace with a less-specific value.

    - Dates ``YYYY-MM-DD`` collapse to the year ``YYYY``.
    - IPv4 addresses (``a.b.c.d``) truncate to the /24 (``a.b.c.0/24``).
    - Free-form addresses are not generalized here at the engine layer;
      ``arche.addr`` does jurisdiction-aware address generalization.
    Otherwise we return a category placeholder (same as ``mask``).
    """
    cleaned = original.strip()
    m = _DATE_RE.match(cleaned)
    if m:
        return m.group(1)
    ipv4 = re.match(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$", cleaned)
    if ipv4:
        return f"{ipv4.group(1)}.{ipv4.group(2)}.{ipv4.group(3)}.0/24"
    return _mask(category, original)


def _audit(category: str, original: str) -> str:
    """Leave the span in place. Audit event is emitted by the caller."""
    return original


def _retain(category: str, original: str) -> str:
    """Leave the span in place. No audit event."""
    return original


_ACTION_HANDLERS = {
    "mask": _mask,
    "tokenize": _tokenize,
    "drop": _drop,
    "generalize": _generalize,
    "audit": _audit,
    "retain": _retain,
}

# How much of the original each action removes, most-removing first. Used to
# resolve OVERLAPPING detections: over any region two detections both claim,
# the more restrictive action wins.
#
# The ordering is a safety property, not a preference. Detectors legitimately
# nest — a NAME inside an ADDRESS, a LOCATION inside an ADDRESS — and the
# shipped NDPA pack gives those different actions (ADDRESS generalize, NAME
# tokenize, LOCATION retain). Letting the *outer* span win would emit a
# generalized address still containing a NIN the pack said to mask; letting
# the *inner* win would leave the rest of the address in clear text. Only
# "most restrictive over the union" is safe in both directions.
_ACTION_SEVERITY: dict[str, int] = {
    "drop": 5,
    "mask": 4,
    "tokenize": 3,
    "generalize": 2,
    "audit": 1,
    "retain": 0,
}


# ---------------------------------------------------------------------------
# Apply policy to a document
# ---------------------------------------------------------------------------

def apply_policy(
    text: str,
    detections: list[Any],
    statute: Statute,
    *,
    tokenize_salt: str = "",
    detection_category_attr: str = "category",
) -> tuple[str, list[PolicyOutcome]]:
    """Apply a loaded statute to a document and its detections.

    Detections are expected to have ``start``, ``end``, and either a
    ``category`` attribute or whatever attribute name is passed in
    ``detection_category_attr``. They may optionally have ``id`` or ``text``
    attributes; sensible defaults are used otherwise.

    Returns
    -------
    tuple[str, list[PolicyOutcome]]
        The redacted text and the per-detection policy outcomes.
        Outcomes are in the same order as the input detections list (which
        the caller should typically have sorted by ``start``).

    Notes
    -----
    Overlapping detections are resolved before any text is rewritten. Spans
    that overlap are grouped, and the group's whole extent is replaced once
    using the **most restrictive** action any member asked for
    (:data:`_ACTION_SEVERITY`).

    Splicing each detection independently — which this function used to do —
    is only correct for disjoint spans. Detectors nest routinely, and the
    second splice then applied original-text offsets to an already-resized
    string. On ordinary Nigerian address text with the shipped detector set
    that produced ``'[ADDRESS]o Road, [ADDRESS].'`` — plaintext leaked out of
    a span the statute said to remove — and left ``Lagos`` in clear inside a
    masked ADDRESS span.

    Every input detection still gets its own outcome, in input order, carrying
    its own category, action and citation: those are facts about the category
    and stay true whether or not the span won its overlap. ``applied_value``
    reports what actually reached the text.
    """
    # ---- 1. resolve each detection to an action, keeping input order ------
    resolved: list[tuple[int, int, int, str, str, str, str, str]] = []
    for original_index, det in enumerate(detections):
        start = getattr(det, "start", None)
        end = getattr(det, "end", None)
        if start is None or end is None:
            continue
        category = getattr(det, detection_category_attr, None) or "PII-1-UNKNOWN"
        det_id = getattr(det, "id", None) or f"det:{start}:{end}"
        action, statute_ref, rationale = statute.action_for(category)
        resolved.append(
            (start, end, original_index, category, det_id, action, statute_ref, rationale)
        )

    # ---- 2. group overlapping spans into disjoint regions -----------------
    # Sorted by start, then widest first, so a container is seen before what
    # it contains.
    groups: list[dict] = []
    for item in sorted(resolved, key=lambda r: (r[0], -r[1])):
        start, end = item[0], item[1]
        if groups and start < groups[-1]["end"]:
            g = groups[-1]
            g["end"] = max(g["end"], end)
            g["members"].append(item)
        else:
            groups.append({"start": start, "end": end, "members": [item]})

    # ---- 3. one replacement per region, most restrictive action wins ------
    applied_by_index: dict[int, str] = {}
    for g in groups:
        # Two different members decide two different things. The ACTION comes
        # from the most restrictive member, because that is the safety
        # property. The LABEL comes from the widest member, because that is
        # what the region *is*: an address containing a name is still an
        # address, and rendering it `NAME_…` would misdescribe the span even
        # though it would be equally safe.
        action = max(g["members"], key=lambda r: _ACTION_SEVERITY.get(r[5], 0))[5]
        category = max(g["members"], key=lambda r: (r[1] - r[0]))[3]
        # The region's original text, not any single detection's `.text` —
        # the replacement stands in for everything the group covers.
        original = text[g["start"]:g["end"]]
        handler = _ACTION_HANDLERS[action]
        if action == "tokenize":
            replacement = handler(category, original, salt=tokenize_salt)
        else:
            replacement = handler(category, original)
        g["replacement"] = replacement
        for member in g["members"]:
            applied_by_index[member[2]] = replacement

    # ---- 4. splice the now-disjoint regions, rightmost first --------------
    redacted = text
    for g in sorted(groups, key=lambda g: -g["start"]):
        redacted = redacted[:g["start"]] + g["replacement"] + redacted[g["end"]:]

    outcomes_by_index: dict[int, PolicyOutcome] = {}
    for start, end, original_index, category, det_id, action, statute_ref, rationale in resolved:
        outcomes_by_index[original_index] = PolicyOutcome(
            detection_id=det_id,
            category=category,
            action=action,
            statute_reference=statute_ref,
            statute_id=statute.statute_id,
            statute_version=statute.version,
            rationale=rationale,
            applied_value=applied_by_index.get(original_index, ""),
            span=(start, end),
        )

    outcomes = [
        outcomes_by_index[i]
        for i in range(len(detections))
        if i in outcomes_by_index
    ]
    return redacted, outcomes
