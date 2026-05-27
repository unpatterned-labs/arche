# Copyright 2026 unpatterned.org
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""The arche pipeline — resolve(), detect(), match(), and link().

Level 3 (do-everything):
    from arche import resolve
    result = resolve("Janet Okafor, NIN 12345678901, called from +234 803 555 7890")

Level 2 (fine-grained control):
    from arche import detect, match, link
    entities = detect("your text here...")
    score = match("Mamadou Diallo", "Mohamed Diallo")
    graph = link(records_a + records_b)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ._review import ReviewQueue

from ..config import get_config
from ..extract import _PII_TYPES, Entity, extract
from ..locate import Location, locate
from ..protect import PIIDetection, detect_pii, redact
from ..resolve import ResolvedEntity, resolve_entities

# Signal detection was removed in v0.2.0a3 along with the arche-adapters
# package. The `signals` field on ResolutionResult is kept for backward
# compatibility (always empty list); FHIR/DPI integration is Stage 2 work.


@dataclass
class ResolutionResult:
    """Complete result from the arche pipeline."""

    text: str
    entities: list[Entity]
    resolved: list[ResolvedEntity]
    pii: list[PIIDetection]
    signals: list[Any]
    locations: list[Location]
    graph: Any = None  # networkx.Graph (optional)
    audit_entry: Any = None  # AuditEntry (optional)

    @property
    def entity_count(self) -> int:
        """Total number of extracted entities."""
        return len(self.entities)

    @property
    def duplicate_count(self) -> int:
        """Number of resolved entities that merged multiple mentions."""
        return sum(1 for r in self.resolved if r.sources > 1)

    @property
    def pii_count(self) -> int:
        """Total number of PII detections."""
        return len(self.pii)

    def to_dict(self) -> dict:
        """Serialise the entire result to a plain dictionary."""
        return {
            "text": self.text,
            "entities": [
                {
                    "text": e.text,
                    "entity_type": e.entity_type,
                    "confidence": e.confidence,
                    "start": e.start,
                    "end": e.end,
                    "source": e.source,
                    "metadata": e.metadata,
                }
                for e in self.entities
            ],
            "resolved": [
                {
                    "canonical_name": r.canonical_name,
                    "entity_type": r.entity_type,
                    "aliases": r.aliases,
                    "confidence": r.confidence,
                    "sources": r.sources,
                    "match_reasons": r.match_reasons,
                }
                for r in self.resolved
            ],
            "pii": [
                {
                    "text": p.text,
                    "pii_type": p.pii_type,
                    "confidence": p.confidence,
                    "start": p.start,
                    "end": p.end,
                    "country": p.country,
                }
                for p in self.pii
            ],
            "signals": [
                {
                    "signal_type": s.signal_type,
                    "severity": s.severity,
                    "description": s.description,
                    "evidence": s.evidence,
                    "confidence": s.confidence,
                    "related_entities": s.related_entities,
                }
                for s in self.signals
            ],
            "locations": [
                {
                    "name": loc.name,
                    "country": loc.country,
                    "country_name": loc.country_name,
                    "region": loc.region,
                    "lat": loc.lat,
                    "lng": loc.lng,
                    "confidence": loc.confidence,
                    "source": loc.source,
                }
                for loc in self.locations
            ],
            "summary": {
                "entity_count": self.entity_count,
                "duplicate_count": self.duplicate_count,
                "pii_count": self.pii_count,
            },
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialise the result to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def export(self, path: str, format: str = "json") -> None:
        """Export the result to a file.

        Parameters
        ----------
        path:
            Output file path.
        format:
            ``"json"`` — JSON (default).
            ``"csv"`` — Flattened CSV of entities.
        """
        if format == "json":
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.to_json())
        elif format == "csv":
            import csv

            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "text", "entity_type", "confidence", "start", "end", "source",
                    ],
                )
                writer.writeheader()
                for e in self.entities:
                    writer.writerow(
                        {
                            "text": e.text,
                            "entity_type": e.entity_type,
                            "confidence": e.confidence,
                            "start": e.start,
                            "end": e.end,
                            "source": e.source,
                        }
                    )
        else:
            raise ValueError(f"Unknown export format: {format!r}. Use 'json' or 'csv'.")

    def sanitize_for_logging(self) -> dict:
        """Return a dict safe for logging — all PII text replaced with type labels."""
        d = self.to_dict()
        # Mask entity text for PII-sensitive types
        for ent in d.get("entities", []):
            if ent.get("entity_type") in _PII_TYPES:
                ent["text"] = f"<{ent['entity_type']}>"
        # Mask all PII detection text
        for pii in d.get("pii", []):
            pii["text"] = f"<{pii.get('pii_type', 'PII')}>"
        # Mask the raw input text
        d["text"] = f"<input:{len(self.text)}_chars>"
        return d

    def __repr__(self) -> str:
        return (
            f"ResolutionResult(entities={self.entity_count}, "
            f"duplicates={self.duplicate_count}, pii={self.pii_count}, "
            f"signals={len(self.signals)}, locations={len(self.locations)})"
        )


# ===================================================================
# The resolve() function — primary entry point
# ===================================================================


def resolve(
    text: str,
    *,
    extract_entities: bool = True,
    resolve_identities: bool = True,
    detect_pii_flag: bool = True,
    detect_signals_flag: bool = True,
    enrich_locations: bool = True,
    build_knowledge_graph: bool = False,
    redact_output: bool = False,
    backend: str = "auto",
    llm_config: object | None = None,
    review_queue: ReviewQueue | None = None,
) -> ResolutionResult:
    """Run the full arche pipeline on text.

    This is the primary entry point. Three lines of code::

        from arche import resolve
        result = resolve("your text here...")
        print(result.entities, result.resolved, result.pii)

    Parameters
    ----------
    text:
        Free-form input text to process.
    extract_entities:
        Run entity extraction (default True).
    resolve_identities:
        Run entity resolution / deduplication (default True).
    detect_pii_flag:
        Run PII detection (default True).
    detect_signals_flag:
        Run signal detection (default True).
    enrich_locations:
        Enrich LOCATION entities with coordinates (default True).
    build_knowledge_graph:
        Build a NetworkX knowledge graph (default False).
    redact_output:
        If True, redact PII from the result text and mask PII entity values.
    backend:
        Entity extraction backend: ``"auto"`` (default, offline),
        ``"auto+llm"`` (best accuracy, needs API key),
        ``"gliner"``, or ``"regex"`` (air-gapped).
    llm_config:
        An :class:`~arche.llm.LLMConfig` instance for the LLM proposer.
        Required when ``backend="auto+llm"`` unless LLM defaults are set
        via :func:`~arche.config.configure`.
    review_queue:
        Optional :class:`~arche.review.ReviewQueue`. When provided, resolved
        matches in the queue's confidence band are routed to the review
        queue instead of being auto-accepted.

    Returns
    -------
    ResolutionResult
        Complete pipeline result with entities, resolved identities, PII,
        signals, locations, and optionally a knowledge graph.
    """
    t0 = time.perf_counter()

    # Input validation
    max_len = get_config().max_text_length
    if len(text) > max_len:
        raise ValueError(f"Input text exceeds maximum length ({max_len:,} chars)")

    # 1. Extract entities
    entities: list[Entity] = []
    if extract_entities:
        entities = extract(text, backend=backend, llm_config=llm_config)

    # 2. Resolve identities
    resolved: list[ResolvedEntity] = []
    if resolve_identities and entities:
        resolved = resolve_entities(entities)

    # 2b. Route matches to review queue if provided
    if review_queue is not None and resolved:
        review_queue.ingest(entities, resolved)

    # 3. Detect PII
    pii: list[PIIDetection] = []
    if detect_pii_flag:
        pii = detect_pii(text)

    # 4. Signal detection removed in v0.2.0a3 — the heuristic risk/churn/fraud
    # signal layer was an example-tier capability that didn't carry its weight
    # for a framework. See CHANGELOG for the removal note.
    signals: list = []

    # 5. Enrich locations
    locations: list[Location] = []
    if enrich_locations and entities:
        locations = locate(entities)

    # 6. Build knowledge graph
    graph = None
    if build_knowledge_graph and entities:
        from ..graph import build_graph

        graph = build_graph(entities, resolved=resolved, locations=locations)

    result = ResolutionResult(
        text=text,
        entities=entities,
        resolved=resolved,
        pii=pii,
        signals=signals,
        locations=locations,
        graph=graph,
    )

    # 7. Redact output if requested
    if redact_output and pii:
        result.text = redact(text, pii)
        for e in result.entities:
            if e.entity_type in _PII_TYPES:
                e.text = e.text[:3] + "***" if len(e.text) > 3 else "***"

    # 8. Audit trail
    from ..audit import create_audit_entry

    confidences = [r.confidence for r in resolved]
    all_reasons: list[str] = []
    for r in resolved:
        all_reasons.extend(r.match_reasons)
    result.audit_entry = create_audit_entry(
        action="resolve",
        input_text=text,
        entity_count=len(entities),
        resolved_count=len(resolved),
        pii_count=len(pii),
        confidences=confidences,
        match_reasons=list(set(all_reasons)),
        start_time=t0,
    )

    return result


# ===================================================================
# Level 2 API: detect(), link()
# match() is in arche.match — re-exported from __init__
# ===================================================================


def detect(
    text: str,
    *,
    backend: str = "auto",
    entity_types: list[str] | None = None,
    include_pii: bool = True,
    enrich_locations: bool = True,
    llm_config: object | None = None,
) -> list[Entity]:
    """Extract identity entities and PII from text.

    This is the Level 2 detection API.  It combines entity extraction,
    PII detection, and location enrichment into a single call with typed
    entities ready for matching or linking.

    Examples::

        from arche import detect

        # Extract everything
        entities = detect("Fatima Abdullahi, NIN 12345678901, +234 803 555 7890")

        # Extract with file ingestion
        from arche import extract_text
        entities = detect(extract_text("invoice.pdf"))

        # Extract only specific types
        entities = detect(text, entity_types=["PERSON", "NATIONAL_ID"])

    Parameters
    ----------
    text:
        Free-form input text to process.
    backend:
        Extraction backend: ``"auto"`` (default, offline),
        ``"auto+llm"`` (best accuracy, needs API key),
        ``"gliner"``, or ``"regex"`` (air-gapped).
    entity_types:
        Optional filter -- only return entities of these types.
    include_pii:
        If ``True`` (default), also detect PII and include as entities
        with source ``"pii"``.  PII detections that overlap with
        already-extracted entities are skipped.
    enrich_locations:
        If ``True`` (default), enrich LOCATION entities with coordinates
        from the African gazetteer.
    llm_config:
        An :class:`~arche.llm.LLMConfig` instance for the LLM proposer.
        Required when ``backend="auto+llm"`` unless LLM defaults are set
        via :func:`~arche.config.configure`.

    Returns
    -------
    list[Entity]
        Typed, validated entities sorted by position in the text.
    """
    max_len = get_config().max_text_length
    if len(text) > max_len:
        raise ValueError(f"Input text exceeds maximum length ({max_len:,} chars)")

    # 1. Extract entities via NER + regex (+ optional LLM)
    entities = extract(text, entity_types=entity_types, backend=backend, llm_config=llm_config)

    # 2. Merge PII detections as entities (non-overlapping)
    if include_pii:
        pii_detections = detect_pii(text)
        existing_spans = {(e.start, e.end) for e in entities}
        for p in pii_detections:
            # Skip if this span already covered by an extracted entity
            overlaps = any(
                not (p.end <= s[0] or p.start >= s[1])
                for s in existing_spans
            )
            if not overlaps:
                entities.append(
                    Entity(
                        text=p.text,
                        entity_type=p.pii_type,
                        confidence=p.confidence,
                        start=p.start,
                        end=p.end,
                        source="pii",
                        metadata={"country": p.country} if p.country else {},
                    )
                )

    # 3. Enrich locations
    if enrich_locations:
        loc_entities = locate(entities)
        # Attach location metadata to LOCATION entities
        loc_by_name = {loc.name.lower(): loc for loc in loc_entities}
        for e in entities:
            if e.entity_type == "LOCATION":
                loc = loc_by_name.get(e.text.lower())
                if loc and loc.lat != 0.0:
                    e.metadata = {
                        **e.metadata,
                        "lat": loc.lat,
                        "lng": loc.lng,
                        "country": loc.country,
                        "h3": getattr(loc, "h3_cell", ""),
                    }

    # 4. Filter by type if requested
    if entity_types:
        type_set = set(entity_types)
        entities = [e for e in entities if e.entity_type in type_set]

    # Sort by position
    entities.sort(key=lambda e: (e.start, e.end))
    return entities


@dataclass
class IdentityGraph:
    """Result of linking identity records across sources.

    Contains resolved identities, match scores, and provenance.
    """

    resolved: list[ResolvedEntity]
    entities: list[Entity]
    match_scores: list[dict]  # pairwise match info
    graph: Any = None  # networkx.Graph

    @property
    def identity_count(self) -> int:
        """Number of distinct resolved identities."""
        return len(self.resolved)

    @property
    def duplicate_count(self) -> int:
        """Number of identities formed by merging multiple mentions."""
        return sum(1 for r in self.resolved if r.sources > 1)

    @property
    def entity_count(self) -> int:
        """Total raw entity count."""
        return len(self.entities)

    def to_dict(self) -> dict:
        """Serialise to a plain dictionary."""
        return {
            "identities": [
                {
                    "canonical_name": r.canonical_name,
                    "entity_type": r.entity_type,
                    "aliases": r.aliases,
                    "confidence": r.confidence,
                    "sources": r.sources,
                    "match_reasons": r.match_reasons,
                }
                for r in self.resolved
            ],
            "match_scores": self.match_scores,
            "summary": {
                "identity_count": self.identity_count,
                "duplicate_count": self.duplicate_count,
                "entity_count": self.entity_count,
            },
        }

    def __repr__(self) -> str:
        return (
            f"IdentityGraph(identities={self.identity_count}, "
            f"duplicates={self.duplicate_count}, "
            f"entities={self.entity_count})"
        )


def link(
    *record_sets: list[Entity],
    threshold: float = 0.80,
    use_splink: bool = False,
    build_knowledge_graph: bool = False,
    jurisdiction: str = "default",
    review_queue: ReviewQueue | None = None,
) -> IdentityGraph:
    """Link entity records across sources into unified identities.

    This is the Level 2 linking API.  It takes one or more lists of
    entities (from :func:`detect` or :func:`extract`) and resolves them
    into a unified identity graph.

    Examples::

        from arche import detect, link

        # Link entities from two sources
        entities_a = detect(text_from_system_a)
        entities_b = detect(text_from_system_b)
        graph = link(entities_a, entities_b)

        for identity in graph.resolved:
            if identity.sources > 1:
                print(f"DUPLICATE: {identity.canonical_name}")

    Parameters
    ----------
    *record_sets:
        One or more lists of Entity objects to link across.
    threshold:
        Similarity threshold for matching (0.0–1.0).  Default 0.80.
    use_splink:
        If ``True``, use Splink for probabilistic record linkage
        (requires ``splink`` and ``duckdb`` packages).  Default ``False``
        — uses the built-in Fellegi-Sunter matcher.
    build_knowledge_graph:
        If ``True``, build a NetworkX graph of entity relationships.
    jurisdiction:
        ISO 3166-1 alpha-2 code for jurisdiction-specific matching priors.
    review_queue:
        Optional :class:`~arche.review.ReviewQueue` for uncertain matches.

    Returns
    -------
    IdentityGraph
        Resolved identities with match scores and provenance.
    """

    # Flatten all record sets into a single list with source tags
    all_entities: list[Entity] = []
    for i, record_set in enumerate(record_sets):
        for ent in record_set:
            # Tag with source index if not already tagged
            if "link_source" not in ent.metadata:
                ent.metadata = {**ent.metadata, "link_source": f"source_{i}"}
            all_entities.append(ent)

    if not all_entities:
        return IdentityGraph(resolved=[], entities=[], match_scores=[])

    # Use Splink for large datasets, own matcher for small
    if use_splink and len(all_entities) >= 10:
        resolved = resolve_entities(all_entities, use_splink=True)
    else:
        resolved = _link_with_matcher(all_entities, threshold, jurisdiction)

    # Compute pairwise match scores for resolved groups.
    # (Earlier versions instantiated an IdentityMatcher here for pairwise scoring,
    # but the loop below reports cluster metadata directly from `resolved` —
    # the matcher was never invoked. Removed.)
    match_scores: list[dict] = []
    for r in resolved:
        if r.sources > 1:
            # Report the match info for this cluster
            match_scores.append({
                "canonical_name": r.canonical_name,
                "entity_type": r.entity_type,
                "member_count": r.sources,
                "confidence": r.confidence,
                "match_reasons": r.match_reasons,
                "aliases": r.aliases,
            })

    # Route to review queue
    if review_queue is not None and resolved:
        review_queue.ingest(all_entities, resolved)

    # Build graph
    graph = None
    if build_knowledge_graph:
        from ..graph import build_graph
        graph = build_graph(all_entities, resolved=resolved)

    return IdentityGraph(
        resolved=resolved,
        entities=all_entities,
        match_scores=match_scores,
        graph=graph,
    )


def _link_with_matcher(
    entities: list[Entity],
    threshold: float,
    jurisdiction: str,
) -> list[ResolvedEntity]:
    """Link entities using the built-in Fellegi-Sunter matcher.

    Uses blocking + pairwise comparison + union-find clustering,
    but with Fellegi-Sunter weights instead of raw string similarity.
    """
    import unicodedata as _ud
    from collections import defaultdict

    from ..resolve import _build_resolved, _single_entity_to_resolved
    from ..resolve._matcher import IdentityMatcher

    matcher = IdentityMatcher(jurisdiction=jurisdiction)
    n = len(entities)
    if n == 0:
        return []
    if n == 1:
        return [_single_entity_to_resolved(entities[0])]

    # Union-Find
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    # Group by entity type
    groups: dict[str, list[int]] = defaultdict(list)
    for i, ent in enumerate(entities):
        groups[ent.entity_type].append(i)

    # Blocking key
    def _bkey(ent: Entity) -> str:
        if ent.entity_type in ("PHONE", "NATIONAL_ID", "EMAIL"):
            import re
            return re.sub(r"[^a-zA-Z0-9]", "", ent.text).lower()
        text = ent.text.strip().lower()
        nfkd = _ud.normalize("NFKD", text)
        stripped = "".join(c for c in nfkd if not _ud.combining(c))
        return stripped[:2] if len(stripped) >= 2 else stripped

    # Within-type matching using Fellegi-Sunter
    for etype, indices in groups.items():
        blocks: dict[str, list[int]] = defaultdict(list)
        for idx in indices:
            blocks[_bkey(entities[idx])].append(idx)

        seen: set[tuple[int, int]] = set()
        block_keys = list(blocks.keys())

        for bk in block_keys:
            candidates = list(blocks[bk])
            for other_bk in block_keys:
                if other_bk != bk and other_bk[:1] == bk[:1]:
                    candidates.extend(blocks[other_bk])

            for ii in range(len(candidates)):
                for jj in range(ii + 1, len(candidates)):
                    i, j = candidates[ii], candidates[jj]
                    pair = (min(i, j), max(i, j))
                    if pair in seen:
                        continue
                    seen.add(pair)

                    a, b = entities[i], entities[j]

                    # Build field dicts for the matcher
                    if etype in ("PERSON", "ORGANIZATION", "LOCATION"):
                        score = matcher.compare_fields(name_a=a.text, name_b=b.text)
                    elif etype == "PHONE":
                        score = matcher.compare_fields(phone_a=a.text, phone_b=b.text)
                    elif etype == "NATIONAL_ID":
                        score = matcher.compare_fields(
                            national_id_a=a.text, national_id_b=b.text,
                        )
                    elif etype == "EMAIL":
                        score = matcher.compare_fields(email_a=a.text, email_b=b.text)
                    elif etype == "ISBN":
                        score = matcher.compare_fields(isbn_a=a.text, isbn_b=b.text)
                    else:
                        score = matcher.compare_fields(name_a=a.text, name_b=b.text)

                    if score.score >= threshold:
                        union(i, j)

    # Cross-type linking via shared patient_id (FHIR records)
    person_indices = groups.get("PERSON", [])
    patient_to_persons: dict[str, list[int]] = defaultdict(list)
    for pi in person_indices:
        pid = entities[pi].metadata.get("patient_id", "")
        if pid:
            patient_to_persons[pid].append(pi)

    for i, ent in enumerate(entities):
        pid = ent.metadata.get("patient_id", "")
        if not pid:
            continue
        if ent.entity_type in ("PHONE", "NATIONAL_ID"):
            for person_idx in patient_to_persons.get(pid, []):
                union(i, person_idx)

    # Collect clusters
    clusters: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        clusters[find(i)].append(i)

    resolved: list[ResolvedEntity] = []
    for members in clusters.values():
        member_entities = [entities[i] for i in members]
        resolved.append(_build_resolved(member_entities))

    return resolved


# ===================================================================
# ArchePipeline — power-user class
# ===================================================================


class ArchePipeline:
    """Configurable pipeline for power users who need fine-grained control.

    Usage::

        pipeline = ArchePipeline(backend="regex", pii_redact=True)
        result = pipeline.run("Janet Okafor, NIN 12345678901")
        print(result.entities)
        print(result.pii)

        # Batch processing
        results = pipeline.run_batch(["text one...", "text two..."])
    """

    def __init__(
        self,
        backend: str = "auto",
        african_context: bool = True,
        pii_redact: bool = False,
        pii_redact_strategy: str = "mask",
        resolve_identities: bool = True,
        detect_pii_flag: bool = True,
        detect_signals_flag: bool = True,
        enrich_locations: bool = True,
        build_knowledge_graph: bool = False,
        review_queue: ReviewQueue | None = None,
        llm_config: object | None = None,
    ) -> None:
        """Initialise the pipeline.

        Parameters
        ----------
        backend:
            Entity extraction backend (``"auto"``, ``"auto+llm"``,
            ``"gliner"``, ``"regex"``).
        african_context:
            Enable African context layer (name equivalences, ID patterns, etc.).
        pii_redact:
            If ``True``, redact PII from text in the result.
        pii_redact_strategy:
            Redaction strategy (``"mask"``, ``"hash"``, ``"remove"``, ``"placeholder"``).
        resolve_identities:
            Run identity resolution.
        detect_pii_flag:
            Run PII detection.
        detect_signals_flag:
            Run signal detection.
        enrich_locations:
            Enrich locations with coordinates.
        build_knowledge_graph:
            Build a NetworkX knowledge graph.
        review_queue:
            Optional :class:`~arche.review.ReviewQueue` for routing
            uncertain matches to human/agent review.
        llm_config:
            An :class:`~arche.llm.LLMConfig` for the LLM proposer.
            Only used when ``backend="auto+llm"``.
        """
        self.backend = backend
        self.african_context = african_context
        self.pii_redact = pii_redact
        self.pii_redact_strategy = pii_redact_strategy
        self.resolve_identities = resolve_identities
        self.detect_pii_flag = detect_pii_flag
        self.detect_signals_flag = detect_signals_flag
        self.enrich_locations = enrich_locations
        self.build_knowledge_graph = build_knowledge_graph
        self.review_queue = review_queue
        self.llm_config = llm_config

    def run(self, text: str) -> ResolutionResult:
        """Run the pipeline on a single text input.

        Parameters
        ----------
        text:
            Free-form text to process.

        Returns
        -------
        ResolutionResult
            Complete pipeline result.
        """
        result = resolve(
            text,
            extract_entities=True,
            resolve_identities=self.resolve_identities,
            detect_pii_flag=self.detect_pii_flag,
            detect_signals_flag=self.detect_signals_flag,
            enrich_locations=self.enrich_locations,
            build_knowledge_graph=self.build_knowledge_graph,
            backend=self.backend,
            llm_config=self.llm_config,
            review_queue=self.review_queue,
        )

        # Optionally redact PII from the text stored in the result
        if self.pii_redact and result.pii:
            result.text = redact(text, result.pii, strategy=self.pii_redact_strategy)

        return result

    def run_batch(self, texts: list[str]) -> list[ResolutionResult]:
        """Run the pipeline on multiple texts.

        Parameters
        ----------
        texts:
            List of free-form text inputs.

        Returns
        -------
        list[ResolutionResult]
            One result per input text.
        """
        return [self.run(text) for text in texts]

    def __repr__(self) -> str:
        return (
            f"ArchePipeline(backend={self.backend!r}, "
            f"african_context={self.african_context}, "
            f"pii_redact={self.pii_redact})"
        )
