# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The v0.2 framework primitive: `Pipeline` and `Result`.

Per PRD §7.3. A slim composition class that wires together detection,
address parsing, jurisdiction-aware policy, and audit into a single
`process(text)` call. Replaces the v0.1 monolithic `resolve()` god-function
without breaking it (the legacy function lives on via the deprecation
shim on `arche.resolve` / `arche.pipeline`).

Public API per PRD §10:

    from arche import Pipeline, Result

    pipeline = Pipeline(
        jurisdiction="NG",
        statute="NDPA-2023",
        detectors=["ng", "core"],
        address_parsing=True,
        audit=True,
    )
    result = pipeline.process(text)
    # result.detections      -> list[Detection]
    # result.addresses       -> list[Address]
    # result.policy_outcomes -> list[PolicyOutcome]
    # result.redacted_text   -> str
    # result.audit_log       -> list[AuditEvent]
    # result.metadata        -> dict

The v0.2 Pipeline is deliberately small (~150 LOC). The heavy lifting -
the per-country detectors, the policy engine, the address parser - lives
in their own modules. Pipeline is the *composition* layer.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from arche._types import SensitivityTier

# ---------------------------------------------------------------------------
# Result schema (PRD §10.2)
# ---------------------------------------------------------------------------

@dataclass
class Detection:
    """A single detection record. Per PRD §10.2.

    This is a minimal shape that the v0.2 Pipeline emits. Existing detectors
    (`arche.detect.ng.ids.detect_nigerian_ids`, etc.) return their own
    richer records (`NationalID`, etc.); the Pipeline normalizes those into
    this canonical shape.

    Two fields populated by the statute-aware enrichment step (which runs
    inside Pipeline.process after detectors emit, before policy applies):

    -   ``sensitivity_tier`` — the per-jurisdiction PII tier the loaded
        statute assigns to this category. Defaults to MODERATE for
        standalone detector calls that bypass Pipeline (no statute
        loaded means no tier mapping).
    -   ``regulatory_citation`` — the specific statute section
        (``"NDPA-2023 s.29"``) the loaded statute cites for this
        category. ``None`` for standalone detector calls.
    """

    id: str
    category: str
    text: str
    start: int
    end: int
    confidence: float
    detector: str
    identity_class: str = "inferred"  # foundational | functional | federated | inferred
    sensitivity_tier: SensitivityTier = SensitivityTier.MODERATE
    regulatory_citation: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Result:
    """The output of `Pipeline.process(text)`. Per PRD §10.2."""

    document_hash: str
    detections: list[Detection] = field(default_factory=list)
    addresses: list[Any] = field(default_factory=list)  # arche.addr.Address (Week 3)
    policy_outcomes: list[Any] = field(default_factory=list)  # arche.policy.PolicyOutcome
    redacted_text: str = ""
    audit_log: list[Any] = field(default_factory=list)  # arche.graph.audit.AuditEvent (Week 3)
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Pipeline (PRD §7.3)
# ---------------------------------------------------------------------------

class Pipeline:
    """Compose detection + policy + audit for one jurisdiction.

    This is the framework primitive. Reference workflows
    (`arche.workflow.redact.RedactionWorkflow`,
    `arche.workflow.dsar.DSARWorkflow`) build on top of it.

    Parameters
    ----------
    jurisdiction:
        ISO 3166-1 alpha-2 code (e.g. ``"NG"``). When provided, only the
        per-country detector(s) for that jurisdiction run, and the matching
        statute is loaded automatically if ``statute`` is not given.
    statute:
        Statute identifier (e.g. ``"NDPA-2023"``). When omitted, inferred
        from ``jurisdiction``: NG -> NDPA-2023, ZA -> POPIA, KE -> KENYA-DPA,
        GH -> GHANA-DPA. If neither is given, no policy is applied (raw
        detections are returned).
    detectors:
        Which detector packages to run. Defaults to a sensible per-country
        set when ``jurisdiction`` is provided. Stage 1 base: rule-based
        government identifier detectors; ``arche-core[detect]`` adds
        GLiNER2-PII for multilingual soft-PII.
    address_parsing:
        Run ``arche.addr.parse_address`` over the text. Stage 1 / Week 3
        delivery; the field exists today as a forward-compatibility hook.
    audit:
        Emit ``arche.graph.audit.AuditEvent`` records into ``Result.audit_log``
        for each detection and policy decision. Stage 1 / Week 3 delivery.
    tokenize_salt:
        Per-deployment salt for the ``tokenize`` policy action. Different
        salts across organizations prevent token re-identification leaks
        when redacted documents cross trust boundaries.
    """

    _STATUTE_FOR_JURISDICTION = {
        "NG": "NDPA-2023",
        "ZA": "POPIA",
        "KE": "KENYA-DPA",
        "GH": "GHANA-DPA",
    }

    def __init__(
        self,
        jurisdiction: str | None = None,
        statute: str | None = None,
        detectors: list[str] | None = None,
        address_parsing: bool = False,
        audit: bool = True,
        tokenize_salt: str = "",
    ):
        self.jurisdiction = jurisdiction.upper() if jurisdiction else None
        self.statute_id = statute or (
            self._STATUTE_FOR_JURISDICTION.get(self.jurisdiction)
            if self.jurisdiction else None
        )
        self.detector_packages = detectors or self._default_detectors()
        self.address_parsing = address_parsing
        self.audit = audit
        self.tokenize_salt = tokenize_salt

        # Lazy-load the statute so importing `Pipeline` doesn't read YAML
        # at module load time. Loaded on first `process()` call.
        self._statute: Any | None = None

    def _default_detectors(self) -> list[str]:
        """Pick a sensible default detector set based on jurisdiction.

        Default routing per the 2026-05-22 detection-scope expansion CEO
        plan: every jurisdiction gets the per-country IDs PLUS the
        cross-cutting names + locations + ip + digital_id + addr.

        Callers who want narrower routing override via
        ``Pipeline(detectors=["ng"])`` — opt-out preserved for backward
        compatibility.
        """
        cross_cutting = ["names", "locations", "ip", "digital_id", "addr", "core"]
        if self.jurisdiction in {"NG", "KE", "ZA", "GH"}:
            return [self.jurisdiction.lower(), *cross_cutting]
        return ["africa", *cross_cutting]  # multi-country fallback

    def _ensure_statute(self) -> Any | None:
        if self._statute is None and self.statute_id:
            from arche.policy import load_statute
            self._statute = load_statute(self.statute_id)
        return self._statute

    # -----------------------------------------------------------------------
    # Main entry point
    # -----------------------------------------------------------------------

    def process(self, text: str) -> Result:
        """Run the configured pipeline over a document.

        Detection sources are composed according to ``detector_packages``;
        policy is applied via ``arche.policy.apply_policy`` if a statute
        is configured.

        Parameters
        ----------
        text:
            Input document.

        Returns
        -------
        Result
            Document hash, detections, addresses, policy outcomes, redacted
            text, audit log, and metadata.
        """
        doc_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

        # 1. Detection
        raw_detections = self._run_detectors(text)
        detections = [self._to_detection(d) for d in raw_detections]

        # 2. Statute-aware enrichment (Lane A 1B, 2026-05-22 detection-first
        # reposition). When a statute is loaded, walk each Detection and
        # populate sensitivity_tier + regulatory_citation from the statute
        # YAML. Standalone detector callers that bypass Pipeline get the
        # MODERATE / None defaults (documented in Detection docstring).
        statute = self._ensure_statute()
        if statute and detections:
            self._enrich_detections(detections, statute)

        # 3. Address parsing (Week 3 delivery - placeholder hook)
        addresses: list[Any] = []
        if self.address_parsing:
            try:
                from arche.addr import parse_address  # noqa: F401
                # Stage 1 address parser not yet implemented; placeholder for hook.
            except ImportError:
                pass

        # 4. Policy enforcement
        if statute and detections:
            from arche.policy import apply_policy
            redacted_text, policy_outcomes = apply_policy(
                text,
                detections,
                statute,
                tokenize_salt=self.tokenize_salt,
            )
        else:
            redacted_text = text
            policy_outcomes = []

        # 5. Audit (Week 3 SQLite delivery - in-memory record for now)
        audit_log: list[dict] = []
        if self.audit:
            for det in detections:
                audit_log.append({
                    "event_type": "detection",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "document_hash": doc_hash,
                    "detection_id": det.id,
                    "category": det.category,
                    "span": (det.start, det.end),
                    "confidence": det.confidence,
                    "detector": det.detector,
                    "sensitivity_tier": det.sensitivity_tier.value,
                    "regulatory_citation": det.regulatory_citation,
                })
            for out in policy_outcomes:
                audit_log.append({
                    "event_type": "policy",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "document_hash": doc_hash,
                    "detection_id": out.detection_id,
                    "category": out.category,
                    "action": out.action,
                    "statute_id": out.statute_id,
                    "statute_reference": out.statute_reference,
                })

        return Result(
            document_hash=doc_hash,
            detections=detections,
            addresses=addresses,
            policy_outcomes=policy_outcomes,
            redacted_text=redacted_text,
            audit_log=audit_log,
            metadata={
                "jurisdiction": self.jurisdiction,
                "statute_id": self.statute_id,
                "statute_version": statute.version if statute else None,
                "detectors": list(self.detector_packages),
                "address_parsing": self.address_parsing,
                "audit": self.audit,
                "pipeline_version": "v0.2",
            },
        )

    # -----------------------------------------------------------------------
    # File-aware entry point (delegates to arche.doc)
    # -----------------------------------------------------------------------

    def process_file(self, source: str | Any) -> Result:
        """Parse a file via ``arche.doc`` then run ``process()`` over its text.

        Requires the ``arche-core[doc]`` extra. See ``arche.doc`` for the
        full docling-backed parsing pipeline (PDF, DOCX, PPTX, XLSX, HTML,
        images, with optional OCR via ``[doc-ocr]``).

        Returns the same :class:`Result` as :meth:`process` plus
        ``metadata["source_file"]`` and ``metadata["num_pages"]`` for
        provenance.
        """
        from arche.doc import parse  # raises DoclingNotInstalledError if missing

        parsed = parse(source)
        result = self.process(parsed.text)
        result.metadata["source_file"] = parsed.source
        result.metadata["num_pages"] = parsed.num_pages
        return result

    # -----------------------------------------------------------------------
    # Introspection (PRD FR-WF-8)
    # -----------------------------------------------------------------------

    def describe(self) -> dict[str, Any]:
        """Return a structured description of what this pipeline will do."""
        return {
            "jurisdiction": self.jurisdiction,
            "statute": self.statute_id,
            "detectors": list(self.detector_packages),
            "address_parsing": self.address_parsing,
            "audit": self.audit,
        }

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _run_detectors(self, text: str) -> list[Any]:
        """Dispatch to the configured detectors and concatenate results.

        The default detector set per jurisdiction (see ``_default_detectors``)
        runs the per-country IDs plus the cross-cutting names + locations +
        addresses + IPs + digital_ids. Callers can opt-out via the
        ``detectors=`` parameter on Pipeline.
        """
        results: list[Any] = []

        for pkg in self.detector_packages:
            if pkg == "ng":
                from arche.detect.ng.ids import detect_nigerian_ids
                results.extend(detect_nigerian_ids(text))
            elif pkg == "ke":
                from arche.detect.ke.ids import detect_kenyan_ids
                results.extend(detect_kenyan_ids(text))
            elif pkg == "za":
                from arche.detect.za.ids import detect_south_african_ids
                results.extend(detect_south_african_ids(text))
            elif pkg == "gh":
                from arche.detect.gh.ids import detect_ghanaian_ids
                results.extend(detect_ghanaian_ids(text))
            elif pkg == "africa":
                from arche.detect._africa.ids import detect_african_ids
                results.extend(detect_african_ids(text))
            elif pkg == "names":
                # African name lexicon (114 equivalence groups via YAML
                # dataset, 20-group bundled starter as fallback). Restores
                # the v0.1 "African names just work" default. Lazy-loads
                # the lexicon on first call (Lane A1/A2, 2026-05-22 eng
                # review §1 issue 4 locked decision).
                from arche.detect.names import detect_names
                results.extend(detect_names(text))
            elif pkg == "locations":
                # African city gazetteer (~104 cities + aliases). New
                # category PII-4-LOCATION (Pan-African PII Taxonomy v0.1.1).
                from arche.detect.locations import detect_locations
                results.extend(detect_locations(text))
            elif pkg == "ip":
                from arche.detect.ip import detect_ip
                results.extend(detect_ip(text))
            elif pkg == "digital_id":
                from arche.detect.digital_id import detect_digital_ids
                results.extend(detect_digital_ids(text))
            elif pkg == "addr":
                # Address parser (NG + ZA MVP). Stage 1 / Week 3 delivery;
                # full PRD §5 parser is Stage 2 grant work. Converts the
                # arche.addr.Address dataclass to canonical Detection with
                # street/city/region/country in metadata (Lane A7 from the
                # 2026-05-22 eng review §1 issue 6 locked decision).
                try:
                    from arche.addr import parse_addresses
                    for addr in parse_addresses(text):
                        comp = addr.components
                        meta = {
                            "street": comp.street or None,
                            "city": comp.city or None,
                            "region": comp.region or None,
                            "country": comp.country or addr.country_inferred or None,
                        }
                        results.append(Detection(
                            id=f"det:{addr.span[0]}:{addr.span[1]}",
                            category="PII-4-ADDRESS",
                            text=addr.raw,
                            start=addr.span[0],
                            end=addr.span[1],
                            confidence=addr.confidence,
                            detector="rule:addr_parser",
                            identity_class="inferred",
                            metadata={k: v for k, v in meta.items() if v is not None},
                        ))
                except ImportError:
                    # arche.addr not installed; skip gracefully
                    pass
            elif pkg == "core":
                # Phone numbers via the multi-country, prefix-validated
                # detector (PRD FR-DETECT-9). Emits PII-3-PHONE; local-format
                # numbers are interpreted against the active jurisdiction.
                from arche.detect.phones import detect_phones
                results.extend(
                    detect_phones(text, default_country=self.jurisdiction or "NG")
                )
            # Other detector packages (gliner, presidio) load lazily via their
            # own optional extras; pipeline doesn't fail if they're missing.

        return results

    @staticmethod
    def _to_detection(raw: Any) -> Detection:
        """Normalize per-country detector output into the canonical
        ``Detection`` shape.

        Two raw shapes accepted:

        1. :class:`arche.detect._base.NationalID` — the per-country
           pattern. Translates to ``PII-2-{id_type}`` with
           ``identity_class`` inferred from foundational ID list.

        2. :class:`Detection` itself — new-style cross-cutting detectors
           (``arche.detect.ip``, ``arche.detect.digital_id``) emit the
           canonical shape directly. Passes through unchanged so the
           detector controls its own category mapping.

        ``sensitivity_tier`` and ``regulatory_citation`` default to
        MODERATE / None here. They are populated by
        :meth:`_enrich_detections` immediately after this step when a
        statute is loaded.
        """
        # New-style: detector already emits canonical Detection. Pass through.
        if isinstance(raw, Detection):
            return raw

        # Old-style: NationalID → Detection conversion.
        category_id = getattr(raw, "id_type", None) or "UNKNOWN"
        identity_class = "foundational" if category_id in {
            "NIN", "NATIONAL_ID", "GHANA_CARD"
        } else "functional"
        return Detection(
            id=f"det:{raw.start}:{raw.end}",
            category=f"PII-2-{category_id}",
            text=raw.text,
            start=raw.start,
            end=raw.end,
            confidence=raw.confidence,
            detector=f"rule:{getattr(raw, 'country', 'xx').lower()}_{category_id.lower()}",
            identity_class=identity_class,
            metadata=getattr(raw, "metadata", {}) or {},
        )

    @staticmethod
    def _enrich_detections(detections: list[Detection], statute: Any) -> None:
        """Populate ``sensitivity_tier`` and ``regulatory_citation`` on each
        Detection from the loaded statute.

        Mutates the detections in place (Detection is a non-frozen dataclass).
        Called by :meth:`process` after detectors run, before policy applies,
        so policy actions have the enriched information available.

        Each detection's category is looked up in the statute's
        ``policy_mappings``. If the category is unmapped, the tier defaults
        to MODERATE and the citation remains None — consistent with the
        standalone-detector contract documented on :class:`Detection`.

        Per the 2026-05-22 detection-first reposition (Lane A 1B). The
        enrichment exposes the regulatory citation at detection time, not
        just policy time — the unique differentiator vs Presidio
        (CEO + eng review §1 issue 2, locked decision).
        """
        for det in detections:
            det.sensitivity_tier = statute.tier_for(det.category)
            # action_for returns (action, statute_reference, rationale).
            # We surface only the statute_reference as the citation.
            _, citation, _ = statute.action_for(det.category)
            det.regulatory_citation = citation or None
