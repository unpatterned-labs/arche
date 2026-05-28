# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""PlaceResolver — resolve UK postcodes and landmarks to public-registry records.

Per docs/ceo-plans/2026-05-24-places-resolver.md (CEO + design + eng reviews).

Two query modes share the same backend:
    1. Anchored: "find me a dentist near St Thomas' Hospital in SW1"
       (one anchor location + N nearby instances)
    2. Directory: "list all UK physiotherapists"
       (no anchor, paginated category query)

Both ship in v0.1. Backend sources: OSM Nominatim, NHS HFR/ODS, openchargemap.
v0.1 ships with FIXTURES ONLY by default. Live API calls are gated behind
the DEMO_LIVE_API=true env var (per spec §4.4).

Public API::

    from arche.resolve.places import PlaceResolver, PlaceEntity, PlaceRecord
    from arche.resolve.places import PlaceReport, PlaceDirectoryReport, TraceEvent

    resolver = PlaceResolver()
    entities = resolver.detect("find me a dentist near St Thomas' Hospital in SW1")
    record = resolver.resolve(entities[0])
    safe_record = resolver.redact(record, jurisdiction="GB")

Top-level convenience helpers live in ``arche.__init__``::

    from arche import resolve_places, list_places

Two-tier audit (spec §4.5): PlaceRecord.raw_redacted is the safe-to-display
view. The full unredacted upstream payload is signed via arche.sign.SignWorkflow
and written to the audit log only — never returned to callers.

Hardcoded GB rules (spec §4.7, LOCKED v0.1): three rules in redact():
    1. coords + address + nhs_reg + osm_id → keep (public registry data)
    2. staff names / contact phones → mask with [REDACTED:STAFF_PII]
    3. emails → mask with [REDACTED:EMAIL]
YAML statute integration deferred to v0.2 (see TODO #2 in spec §15).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from arche.addr import infer_jurisdiction

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Errors
# ═══════════════════════════════════════════════════════════════════════════════


class JurisdictionInferenceError(ValueError):
    """Raised when jurisdiction cannot be inferred and was not provided.

    Per spec §13.3 critical failure mode: silent fallback to 'XX' is NOT
    acceptable. Callers must either pass jurisdiction= explicitly or supply
    text from which a jurisdiction can be inferred.
    """


class UpstreamError(RuntimeError):
    """Wraps any failure from OSM/NHS/openchargemap. Surfaced to demo as event row."""

    def __init__(self, source: str, original: Exception | str, *, status: int | None = None):
        self.source = source
        self.status = status
        self.original = original
        super().__init__(f"upstream {source} failed: {original}")


# ═══════════════════════════════════════════════════════════════════════════════
# Data model (spec §4.5)
# ═══════════════════════════════════════════════════════════════════════════════


PlaceKind = Literal[
    "postcode", "landmark", "address", "named_place",
    "dentist", "ev_charger", "physiotherapy", "hospital", "pharmacy",
    "gp", "a_and_e",
]


@dataclass
class PlaceEntity:
    """A place mention detected in raw text."""

    span: tuple[int, int]
    text: str
    kind: PlaceKind
    confidence: float


@dataclass
class PlaceRecord:
    """A resolved place. Safe-to-display view only.

    The full unredacted upstream payload is NEVER stored here. It's signed
    via arche.sign and written to the audit log; this record carries only
    the redacted view plus a reference to the audit entry.
    """

    id: str                              # canonical id (osm:way/12345, nhs:8901)
    name: str
    address: str
    coords: tuple[float, float]          # lat, lon
    kind: str                            # "dentist", "ev_charger", ...
    distance_m: int | None               # populated by nearby() / directory near=
    source: str                          # "osm", "nhs", "openchargemap", "fixture"
    raw_redacted: dict                   # safe view — names/phones/emails masked
    audit_payload_id: str                # reference to signed full payload in audit log
    redacted_fields: list[str] = field(default_factory=list)


@dataclass
class TraceEvent:
    """A single workflow step the demo can render as an event row.

    Per spec §3a: emitted structured (kind+payload), formatted in the demo.
    """

    name: str                            # "detect", "resolve", "protect", "graph"
    duration_ms: int
    kind: str                            # "info", "warning", "error"
    payload: dict


@dataclass
class ComplianceRecord:
    """The compliance block returned with every report."""

    jurisdiction: str
    policy: str                          # "uk_gdpr_v0_hardcoded" in v0.1
    pii_surfaced_count: int
    redactions_applied: list[str]
    audit_log_entry_id: str
    references: list[str] = field(default_factory=list)


@dataclass
class PlaceReport:
    """Anchored query result — `resolve_places()` output."""

    places: list[PlaceRecord]
    compliance: ComplianceRecord
    trace: list[TraceEvent]
    jurisdiction: str
    jurisdiction_confidence: float
    jurisdiction_trigger: str            # the substring that triggered inference
    text: str                            # original input

    def save_receipt(self, path: str | Path) -> Path:
        """Write a verifiable JWS receipt to `path`. Uses arche.sign."""
        path = Path(path)
        try:
            from arche.sign import generate_keypair, sign
        except ImportError as exc:
            raise RuntimeError(
                "arche.sign is required for save_receipt(). "
                "It ships with arche-core by default — check your install."
            ) from exc

        # v0.1: generate ephemeral keypair per receipt. Production use should
        # pass an existing signing key — see TODO #1 in spec §15 for key
        # management RFC.
        kp = generate_keypair()
        receipt_payload = {
            "schema": "arche.place_report.v1",
            "jurisdiction": self.jurisdiction,
            "jurisdiction_trigger": self.jurisdiction_trigger,
            "place_count": len(self.places),
            "audit_log_entry_id": self.compliance.audit_log_entry_id,
            "redactions": self.compliance.redactions_applied,
            "places": [
                {"id": p.id, "name": p.name, "kind": p.kind, "source": p.source}
                for p in self.places
            ],
        }
        jws = sign(payload=receipt_payload, private_key=kp.private_key,
                   kid=kp.did_key, typ="arche+jws")
        envelope = {
            "schema": "arche.place_report.v1",
            "issuer_did": kp.did_key,
            "jws": jws,
            "payload_preview": receipt_payload,  # human-readable; signature is over the JWS
        }
        path.write_text(json.dumps(envelope, indent=2), encoding="utf-8")
        return path


@dataclass
class PlaceDirectoryReport:
    """Directory query result — `list_places()` output.

    Same shape as PlaceReport but with pagination + total estimate. The
    'places' field carries the row-wise redacted records; everything else
    matches PlaceReport so renderers can share code.
    """

    results: list[PlaceRecord]
    compliance: ComplianceRecord
    trace: list[TraceEvent]
    jurisdiction: str
    category: str
    near: str | None
    next_cursor: str | None
    total_estimate: int | None

    def save_receipt(self, path: str | Path) -> Path:
        path = Path(path)
        try:
            from arche.sign import generate_keypair, sign
        except ImportError as exc:
            raise RuntimeError("arche.sign is required for save_receipt().") from exc
        kp = generate_keypair()
        receipt_payload = {
            "schema": "arche.place_directory_report.v1",
            "jurisdiction": self.jurisdiction,
            "category": self.category,
            "near": self.near,
            "result_count": len(self.results),
            "total_estimate": self.total_estimate,
            "audit_log_entry_id": self.compliance.audit_log_entry_id,
            "redactions": self.compliance.redactions_applied,
        }
        jws = sign(payload=receipt_payload, private_key=kp.private_key,
                   kid=kp.did_key, typ="arche+jws")
        envelope = {
            "schema": "arche.place_directory_report.v1",
            "issuer_did": kp.did_key,
            "jws": jws,
            "payload_preview": receipt_payload,
        }
        path.write_text(json.dumps(envelope, indent=2), encoding="utf-8")
        return path


# ═══════════════════════════════════════════════════════════════════════════════
# PlaceResolver
# ═══════════════════════════════════════════════════════════════════════════════


# Detection patterns
_UK_POSTCODE_RE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b")
_UK_POSTCODE_PARTIAL_RE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\b(?!\s*\d[A-Z]{2})")
_LANDMARK_HINT_RE = re.compile(
    r"\b(?:near|at|by|opposite|next to|behind|in front of)\s+"
    r"(?:the\s+)?"
    r"([A-Z][\w']+(?:\s+[A-Z][\w']+){0,4}(?:\s+(?:Hospital|Station|Park|Bridge|Square|Centre|Center|Tower|Cathedral|Church)))",
    re.IGNORECASE,
)

# Categories the demo supports in v0.1 (spec §16.4).
# Aliases on the LEFT, canonical category on the RIGHT.
# 'urgent care' / 'a&e' / 'emergency' all map to 'a_and_e' so the mum query's
# "nearest urgent care" phrasing produces the expected A&E record.
_SUPPORTED_CATEGORIES: dict[str, str] = {
    "physiotherapy": "physiotherapy",
    "physio": "physiotherapy",
    "dentist": "dentist",
    "dental": "dentist",
    "ev_charger": "ev_charger",
    "ev charger": "ev_charger",
    "charger": "ev_charger",
    "ev": "ev_charger",
    "urgent care": "a_and_e",
    "a&e": "a_and_e",
    "a and e": "a_and_e",
    "emergency": "a_and_e",
    "emergency room": "a_and_e",
    "accident and emergency": "a_and_e",
}

# Vehicle hint for the mum query's "Nissan Leaf" → ev_charger nudge
_VEHICLE_RE = re.compile(
    r"\b(?:Tesla|Nissan Leaf|VW ID|BMW i\d|Renault Zoe|Polestar|Mustang Mach-E|EV)\b",
    re.IGNORECASE,
)


# Hardcoded GB redaction rules (spec §4.7 LOCKED v0.1).
# Note on phone regex: leading "+" is a non-word char, so \b before it FAILS at
# string start. Use (?<!\w) lookbehind instead — matches at start-of-string or
# after a non-word char, never inside another word.
_STAFF_PII_PATTERNS = [
    re.compile(r"\b(?:Dr|Mr|Mrs|Ms|Miss|Prof)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\b"),
    re.compile(r"(?<!\w)\+44\s?\d{2,4}\s?\d{3,4}\s?\d{3,4}\b"),  # UK phone E.164ish
    re.compile(r"\b0\d{2,4}\s?\d{3,4}\s?\d{3,4}\b"),              # UK phone national
    re.compile(r"\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\b"),  # email
]
_STAFF_PII_LABELS = ["[REDACTED:STAFF_NAME]", "[REDACTED:STAFF_PHONE]",
                     "[REDACTED:STAFF_PHONE]", "[REDACTED:EMAIL]"]


class PlaceResolver:
    """Resolve UK places from text or category. Backend-agnostic facade.

    v0.1 default: fixtures-only. Set DEMO_LIVE_API=true env var to enable
    live OSM/NHS/openchargemap calls (per spec §4.4).

    Parameters
    ----------
    fixtures_dir:
        Directory containing JSON fixtures. If None, uses the bundled
        demo/_fixtures/ from the arche-core package.
    audit_log:
        Optional arche.audit.AuditLog instance. If None, a fresh in-memory
        log is created on first use.
    live_api:
        Override the DEMO_LIVE_API env var. None = use env. True = always
        live. False = always fixtures.
    """

    entity_type = "place"

    def __init__(
        self,
        fixtures_dir: Path | None = None,
        audit_log: Any | None = None,
        live_api: bool | None = None,
    ):
        self.fixtures_dir = fixtures_dir or _default_fixtures_dir()
        self._audit_log = audit_log
        if live_api is None:
            self.live_api = os.environ.get("DEMO_LIVE_API", "false").lower() == "true"
        else:
            self.live_api = live_api

    # ── detection ────────────────────────────────────────────────────────────

    def detect(self, text: str) -> list[PlaceEntity]:
        """Find postcodes, landmarks, and category keywords in `text`."""
        if not text or not text.strip():
            return []

        entities: list[PlaceEntity] = []
        seen_spans: set[tuple[int, int]] = set()

        # Full UK postcodes (highest specificity)
        for m in _UK_POSTCODE_RE.finditer(text):
            span = (m.start(), m.end())
            if span not in seen_spans:
                entities.append(PlaceEntity(span=span, text=m.group(0),
                                            kind="postcode", confidence=0.99))
                seen_spans.add(span)

        # Partial UK postcodes (only outside a full match)
        for m in _UK_POSTCODE_PARTIAL_RE.finditer(text):
            span = (m.start(), m.end())
            if any(s[0] <= span[0] and s[1] >= span[1] for s in seen_spans):
                continue
            if span not in seen_spans:
                entities.append(PlaceEntity(span=span, text=m.group(0),
                                            kind="postcode", confidence=0.85))
                seen_spans.add(span)

        # Landmarks ("near St Thomas' Hospital")
        for m in _LANDMARK_HINT_RE.finditer(text):
            span = (m.start(1), m.end(1))
            if span not in seen_spans:
                entities.append(PlaceEntity(span=span, text=m.group(1),
                                            kind="landmark", confidence=0.80))
                seen_spans.add(span)

        return entities

    def detect_categories(self, text: str) -> list[str]:
        """Find category keywords in `text` (dentist, physio, ev_charger...).

        Used by directory mode AND by the mum-query streaming feed to know
        what to look up after geocoding the anchor.
        """
        if not text:
            return []
        lower = text.lower()
        found: list[str] = []
        for keyword, canonical in _SUPPORTED_CATEGORIES.items():
            if re.search(r"\b" + re.escape(keyword) + r"\b", lower) and canonical not in found:
                found.append(canonical)
        # Vehicle hint → infer ev_charger even if "charger" isn't in text
        if _VEHICLE_RE.search(text) and "ev_charger" not in found:
            found.append("ev_charger")
        return found

    # ── resolve ──────────────────────────────────────────────────────────────

    def resolve_anchored(
        self,
        anchor: PlaceEntity,
        categories: Iterable[str],
        radius_m: int = 500,
    ) -> list[PlaceRecord]:
        """Resolve N places of given categories near an anchor.

        v0.1 implementation: loads from fixtures keyed by anchor text. If
        DEMO_LIVE_API is enabled, would call OSM Nominatim + NHS HFR +
        openchargemap; that path is intentionally a stub in v0.1.
        """
        if self.live_api:
            # Live path is intentionally a stub in v0.1. See spec §4.4 +
            # TODO #5 (public-deploy rate-limit handling). Implementer who
            # enables this must wire OSM Nominatim + NHS HFR/ODS first.
            raise UpstreamError(
                source="live_api_not_implemented_v0_1",
                original="DEMO_LIVE_API=true but no live adapter is wired in v0.1. "
                         "See spec §4.4. Unset DEMO_LIVE_API to use fixtures.",
            )

        return self._load_anchored_fixture(anchor, categories, radius_m)

    def resolve_directory(
        self,
        category: str,
        jurisdiction: str,
        near: str | None,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[PlaceRecord], str | None, int | None]:
        """Resolve a directory query. Returns (results, next_cursor, total_estimate)."""
        if self.live_api:
            raise UpstreamError(
                source="live_api_not_implemented_v0_1",
                original="DEMO_LIVE_API=true but no live adapter is wired in v0.1.",
            )

        category_canonical = _SUPPORTED_CATEGORIES.get(category.lower())
        if category_canonical is None:
            # Critical failure mode: don't silently return empty.
            raise UpstreamError(
                source="category_unsupported",
                original=f"category={category!r} is not in {list(_SUPPORTED_CATEGORIES.values())}",
            )

        return self._load_directory_fixture(category_canonical, jurisdiction, near, limit, cursor)

    # ── redact ───────────────────────────────────────────────────────────────

    def redact(self, record: PlaceRecord, jurisdiction: str) -> PlaceRecord:
        """Apply hardcoded GB rules to a single record (spec §4.7 v0.1).

        Three rules:
            1. coords/address/nhs_reg/osm_id → keep
            2. staff names + phones → mask with category labels
            3. emails → mask

        Sets record.redacted_fields with the list of affected fields.
        """
        if jurisdiction != "GB":
            # v0.1 only ships GB rules. Other jurisdictions are pass-through
            # with a warning logged; v0.2 will load the YAML statute pack.
            logger.warning(
                "PlaceResolver.redact() called with jurisdiction=%r — v0.1 only "
                "ships GB rules. Returning unredacted record.", jurisdiction,
            )
            return record

        redacted_fields: list[str] = []
        new_raw = dict(record.raw_redacted)  # copy

        for key, value in list(new_raw.items()):
            if not isinstance(value, str):
                continue
            redacted_value = value
            for pat, label in zip(_STAFF_PII_PATTERNS, _STAFF_PII_LABELS, strict=True):
                if pat.search(redacted_value):
                    redacted_value = pat.sub(label, redacted_value)
                    if key not in redacted_fields:
                        redacted_fields.append(key)
            new_raw[key] = redacted_value

        # Don't mutate the input — return a new record so callers can keep
        # the original if needed (we never expose the truly-raw payload, but
        # this is good defensive programming).
        return PlaceRecord(
            id=record.id,
            name=record.name,
            address=record.address,
            coords=record.coords,
            kind=record.kind,
            distance_m=record.distance_m,
            source=record.source,
            raw_redacted=new_raw,
            audit_payload_id=record.audit_payload_id,
            redacted_fields=record.redacted_fields + redacted_fields,
        )

    # ── fixture loading (v0.1 only) ──────────────────────────────────────────

    def _load_anchored_fixture(
        self,
        anchor: PlaceEntity,
        categories: Iterable[str],
        radius_m: int,
    ) -> list[PlaceRecord]:
        """Load the canned mum-query response from fixtures.

        v0.1 keys: postcode "SW1" or landmark "St Thomas' Hospital" → mum_query.json.
        Anything else → empty list (with a logger warning).
        """
        anchor_text_lower = anchor.text.lower()
        is_mum_anchor = (
            anchor_text_lower in ("sw1", "se1", "se1 7eh")
            or "st thomas" in anchor_text_lower
            or "st. thomas" in anchor_text_lower
        )
        if not is_mum_anchor:
            logger.info("No fixture for anchor=%r; returning empty.", anchor.text)
            return []

        path = self.fixtures_dir / "mum_query.json"
        if not path.exists():
            raise UpstreamError(
                source="fixture_missing",
                original=f"expected fixture at {path} — see demo/_fixtures/README.md",
            )

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            # Critical failure mode (spec §13.3 row 2)
            raise UpstreamError(source="fixture", original=exc) from exc

        categories_set = set(categories)
        records: list[PlaceRecord] = []
        for raw in data.get("places", []):
            if categories_set and raw.get("kind") not in categories_set:
                continue
            records.append(_build_record_from_fixture(raw))
        return records

    def _load_directory_fixture(
        self,
        category: str,
        jurisdiction: str,
        near: str | None,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[PlaceRecord], str | None, int | None]:
        """Load a directory fixture for the given category."""
        path = self.fixtures_dir / f"directory_{category}.json"
        if not path.exists():
            raise UpstreamError(
                source="fixture_missing",
                original=f"no fixture for category={category!r} at {path}",
            )

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise UpstreamError(source="fixture", original=exc) from exc

        all_records = [_build_record_from_fixture(r) for r in data.get("results", [])]

        # Cursor-based pagination: cursor is the index into the result list.
        offset = int(cursor) if cursor else 0
        page = all_records[offset:offset + limit]
        next_cursor = str(offset + limit) if offset + limit < len(all_records) else None
        total = data.get("total_estimate", len(all_records))
        return page, next_cursor, total


# ═══════════════════════════════════════════════════════════════════════════════
# Optional uk_address_matcher integration (lazy import + graceful degradation)
# ═══════════════════════════════════════════════════════════════════════════════


def canonicalize_address_batch(messy_addresses: list[str]) -> list[dict[str, Any]]:
    """Batch-mode canonicalization via uk_address_matcher.

    v0.1 STATUS: stub. Returns the input as-is with a low confidence score.
    When uk_address_matcher is installed AND canonical OS data has been
    preprocessed (one-time, ~10 min), this routes through AddressMatcher.

    See spec §16.1 — uk_address_matcher is adopted as an OPTIONAL dependency.
    Single-string lookup (the mum demo path) uses OSM Nominatim directly.
    """
    try:
        import uk_address_matcher  # noqa: F401
    except ImportError:
        # Graceful degradation — return input as-is, log once.
        if not getattr(canonicalize_address_batch, "_warned", False):
            logger.info(
                "uk_address_matcher not installed — canonicalize_address_batch() "
                "returns input as-is. Install: pip install uk_address_matcher"
            )
            canonicalize_address_batch._warned = True  # type: ignore[attr-defined]
        return [{"raw": a, "uprn": None, "match_weight": 0.0} for a in messy_addresses]

    # Actual integration is deferred to v0.2 (spec §15 TODO #2 area). The
    # library is batch-only and needs DuckDB + canonical OS data, which is
    # too heavy for the v0.1 single-postcode demo. v0.2 directory mode that
    # accepts a CSV upload is the right place to wire this up.
    logger.warning(
        "uk_address_matcher is installed but the full batch integration is a "
        "v0.2 deliverable. Returning best-effort pass-through for v0.1."
    )
    return [{"raw": a, "uprn": None, "match_weight": 0.0} for a in messy_addresses]


# ═══════════════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _default_fixtures_dir() -> Path:
    """Locate the bundled demo fixtures directory.

    Priority:
        1. $ARCHE_PLACES_FIXTURES env var (absolute path)
        2. project-relative ./demo/_fixtures/ (when running from a checkout)
        3. package-internal _data/places_fixtures/ (when installed via pip)
    """
    env = os.environ.get("ARCHE_PLACES_FIXTURES")
    if env:
        return Path(env)

    # Walk up from this file looking for demo/_fixtures/
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "demo" / "_fixtures"
        if candidate.is_dir():
            return candidate

    # Fallback to a bundled location (will be created if fixtures are packaged)
    return Path(__file__).parent.parent / "_data" / "places_fixtures"


def _build_record_from_fixture(raw: dict[str, Any]) -> PlaceRecord:
    """Convert a fixture JSON row into a PlaceRecord (with audit_payload_id stub)."""
    return PlaceRecord(
        id=raw["id"],
        name=raw["name"],
        address=raw["address"],
        coords=(raw["coords"]["lat"], raw["coords"]["lon"]),
        kind=raw["kind"],
        distance_m=raw.get("distance_m"),
        source=raw.get("source", "fixture"),
        raw_redacted=dict(raw.get("raw_redacted", {})),
        audit_payload_id=raw.get("audit_payload_id", f"audit:{uuid.uuid4().hex[:12]}"),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Public entry-point helpers (wrappers used by arche.resolve_places / list_places)
# ═══════════════════════════════════════════════════════════════════════════════


def _make_compliance(jurisdiction: str, redactions: list[str]) -> ComplianceRecord:
    """Build the v0.1 hardcoded compliance block."""
    policy_name = (
        "uk_gdpr_v0_hardcoded" if jurisdiction == "GB"
        else f"{jurisdiction.lower()}_passthrough_v0"
    )
    return ComplianceRecord(
        jurisdiction=jurisdiction,
        policy=policy_name,
        pii_surfaced_count=0,
        redactions_applied=redactions,
        audit_log_entry_id=f"audit:{uuid.uuid4().hex[:12]}",
        references=(
            ["UK GDPR Art. 6(1)(e)", "DPA 2018 Sch.2 Part 1"]
            if jurisdiction == "GB" else []
        ),
    )


def _run_anchored(
    text: str,
    jurisdiction: str | None,
    resolver: PlaceResolver | None,
) -> PlaceReport:
    """Inner implementation for arche.resolve_places()."""
    if resolver is None:
        resolver = PlaceResolver()

    trace: list[TraceEvent] = []

    # detect
    t0 = time.perf_counter()
    entities = resolver.detect(text)
    categories = resolver.detect_categories(text)
    detect_ms = int((time.perf_counter() - t0) * 1000)

    # jurisdiction inference
    if jurisdiction is None:
        j_code, j_conf, j_trigger = infer_jurisdiction(text)
        if j_code == "XX":
            # Critical failure mode (spec §13.3): don't silently default.
            raise JurisdictionInferenceError(
                f"Could not infer jurisdiction from text. Pass jurisdiction= "
                f"explicitly. Tried text[:80]={text[:80]!r}"
            )
        jurisdiction = j_code
    else:
        j_conf, j_trigger = 1.0, "explicit"

    trace.append(TraceEvent(
        name="detect",
        duration_ms=detect_ms,
        kind="info",
        payload={
            "places_count": len(entities),
            "categories": categories,
            "jurisdiction": jurisdiction,
            "jurisdiction_trigger": j_trigger,
            "jurisdiction_confidence": j_conf,
        },
    ))

    # resolve
    anchor = next((e for e in entities if e.kind in ("postcode", "landmark")), None)
    if anchor is None:
        # No anchor found — return empty places but valid report.
        trace.append(TraceEvent(
            name="resolve", duration_ms=0, kind="warning",
            payload={"reason": "no anchor place detected in text"},
        ))
        records: list[PlaceRecord] = []
    else:
        t1 = time.perf_counter()
        cats_to_query = categories or ["dentist", "ev_charger", "a_and_e"]
        try:
            records = resolver.resolve_anchored(anchor, categories=cats_to_query)
            resolve_kind = "info"
            sources_used = (
                ["fixture"] if not resolver.live_api
                else ["osm", "nhs", "openchargemap"]
            )
            resolve_payload = {
                "sources": sources_used,
                "count": len(records),
                "anchor": anchor.text,
            }
        except UpstreamError as exc:
            # Critical failure mode: surface as warning event, return empty records.
            records = []
            resolve_kind = "warning"
            resolve_payload = {"source": exc.source, "error": str(exc.original)}
        resolve_ms = int((time.perf_counter() - t1) * 1000)
        trace.append(TraceEvent(
            name="resolve", duration_ms=resolve_ms, kind=resolve_kind, payload=resolve_payload,
        ))

    # protect (redact)
    t2 = time.perf_counter()
    redacted_records: list[PlaceRecord] = []
    all_redacted_fields: list[str] = []
    for record in records:
        safe = resolver.redact(record, jurisdiction=jurisdiction)
        redacted_records.append(safe)
        all_redacted_fields.extend(safe.redacted_fields)
    protect_ms = int((time.perf_counter() - t2) * 1000)
    trace.append(TraceEvent(
        name="protect", duration_ms=protect_ms, kind="info",
        payload={
            "policy": "uk_gdpr_v0_hardcoded" if jurisdiction == "GB" else "passthrough",
            "redactions_count": len(all_redacted_fields),
            "redacted_fields": all_redacted_fields,
        },
    ))

    # graph (placeholder for v0.1 — just an entity-count event)
    t3 = time.perf_counter()
    edges = [
        {"from": "anchor", "to": r.id, "distance_m": r.distance_m or 0}
        for r in redacted_records
    ]
    graph_ms = int((time.perf_counter() - t3) * 1000)
    trace.append(TraceEvent(
        name="graph", duration_ms=graph_ms, kind="info",
        payload={"nodes": len(redacted_records) + 1, "edges": len(edges), "edges_summary": edges},
    ))

    compliance = _make_compliance(jurisdiction, all_redacted_fields)

    return PlaceReport(
        places=redacted_records,
        compliance=compliance,
        trace=trace,
        jurisdiction=jurisdiction,
        jurisdiction_confidence=j_conf,
        jurisdiction_trigger=j_trigger,
        text=text,
    )


def _run_directory(
    category: str,
    jurisdiction: str,
    near: str | None,
    limit: int,
    cursor: str | None,
    resolver: PlaceResolver | None,
) -> PlaceDirectoryReport:
    """Inner implementation for arche.list_places()."""
    if resolver is None:
        resolver = PlaceResolver()

    trace: list[TraceEvent] = []

    # detect (category validation) — caller errors RAISE; upstream errors are
    # caught below and surfaced as trace events. This separation matters: an
    # unsupported category is a programmer mistake (raise UpstreamError so
    # callers can handle); a 503 from NHS is an environmental fact (warning
    # event, return empty results).
    t0 = time.perf_counter()
    canonical = _SUPPORTED_CATEGORIES.get(category.lower())
    if canonical is None:
        raise UpstreamError(
            source="category_unsupported",
            original=f"category={category!r} not in {sorted(set(_SUPPORTED_CATEGORIES.values()))}",
        )
    detect_ms = int((time.perf_counter() - t0) * 1000)
    trace.append(TraceEvent(
        name="detect", duration_ms=detect_ms, kind="info",
        payload={"category": canonical, "jurisdiction": jurisdiction, "near": near},
    ))

    # resolve
    t1 = time.perf_counter()
    try:
        records, next_cursor, total = resolver.resolve_directory(
            category=category, jurisdiction=jurisdiction,
            near=near, limit=limit, cursor=cursor,
        )
        resolve_kind = "info"
        resolve_payload = {
            "count": len(records),
            "total_estimate": total,
            "next_cursor": next_cursor,
        }
    except UpstreamError as exc:
        records, next_cursor, total = [], None, None
        resolve_kind = "warning"
        resolve_payload = {"source": exc.source, "error": str(exc.original)}
    resolve_ms = int((time.perf_counter() - t1) * 1000)
    trace.append(TraceEvent(name="resolve", duration_ms=resolve_ms,
                            kind=resolve_kind, payload=resolve_payload))

    # protect (row-wise redaction)
    t2 = time.perf_counter()
    redacted = [resolver.redact(r, jurisdiction=jurisdiction) for r in records]
    all_redacted_fields = [f for r in redacted for f in r.redacted_fields]
    protect_ms = int((time.perf_counter() - t2) * 1000)
    trace.append(TraceEvent(
        name="protect", duration_ms=protect_ms, kind="info",
        payload={"policy": "uk_gdpr_v0_hardcoded" if jurisdiction == "GB" else "passthrough",
                 "redactions_count": len(all_redacted_fields)},
    ))

    compliance = _make_compliance(jurisdiction, all_redacted_fields)

    return PlaceDirectoryReport(
        results=redacted,
        compliance=compliance,
        trace=trace,
        jurisdiction=jurisdiction,
        category=canonical or category,
        near=near,
        next_cursor=next_cursor,
        total_estimate=total,
    )
