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

"""Entity resolution — deduplicate and merge entity mentions into canonical records.

Wraps Splink for probabilistic entity resolution when available. Falls back to
fuzzy matching with rapidfuzz + African name equivalences when Splink is not
installed.

Usage:
    from arche.extract import extract
    from arche.resolve import resolve_entities
    entities = extract("Janet Okafor ... also known as Jan Okafor ...")
    resolved = resolve_entities(entities)
"""

from __future__ import annotations

import logging
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..extract import Entity

if TYPE_CHECKING:
    from ..types import IdentityEvidence, IdentityRecord

_log = logging.getLogger("arche")


@dataclass
class ResolvedEntity:
    """A canonical entity formed by merging one or more raw ``Entity`` mentions."""

    canonical_name: str
    entity_type: str
    aliases: list[str]
    confidence: float
    sources: int  # number of distinct mentions / records merged
    match_reasons: list[str]  # e.g. ["name_similarity:0.92", "phone_match"]
    entities: list[Entity]  # original Entity objects that were merged

    def __repr__(self) -> str:
        return (
            f"ResolvedEntity(canonical={self.canonical_name!r}, type={self.entity_type!r}, "
            f"sources={self.sources}, confidence={self.confidence:.2f})"
        )


# ===================================================================
# Public API
# ===================================================================


def resolve_entities(
    entities: list[Entity],
    use_splink: bool = True,
) -> list[ResolvedEntity]:
    """Resolve a list of extracted entities into deduplicated canonical records.

    Parameters
    ----------
    entities:
        Raw entities from :func:`arche.extract.extract`.
    use_splink:
        If ``True`` (default) attempt to use Splink for probabilistic
        resolution. Falls back to fuzzy matching when Splink is not installed.

    Returns
    -------
    list[ResolvedEntity]
        Deduplicated, merged entity records.
    """
    if not entities:
        return []

    # Splink needs enough data to train EM parameters — skip for small inputs
    # to avoid noisy warnings and slow model estimation on tiny datasets
    if use_splink and len(entities) >= 10:
        try:
            return _resolve_splink(entities)
        except ImportError:
            pass
        except Exception as e:
            _log.warning("Splink resolution failed, falling back to fuzzy: %s", e)

    return _resolve_fuzzy(entities)


# ===================================================================
# Splink backend (optional)
# ===================================================================


def _resolve_splink(entities: list[Entity]) -> list[ResolvedEntity]:
    """Resolve entities using Splink probabilistic record linkage."""
    import pandas as pd  # noqa: F811
    import splink.comparison_library as cl
    from splink import DuckDBAPI, Linker, SettingsCreator, block_on

    # Build a DataFrame from entities ----------------------------------
    records = []
    for i, ent in enumerate(entities):
        records.append(
            {
                "unique_id": i,
                "name": ent.text if ent.entity_type in ("PERSON", "ORGANIZATION") else "",
                "entity_type": ent.entity_type,
                "phone": ent.text if ent.entity_type == "PHONE" else "",
                "national_id": ent.text if ent.entity_type == "NATIONAL_ID" else "",
                "raw_text": ent.text,
            }
        )
    df = pd.DataFrame(records)

    if len(df) < 2:
        return [_single_entity_to_resolved(entities[0])]

    # Splink settings --------------------------------------------------
    settings = SettingsCreator(
        link_type="dedupe_only",
        comparisons=[
            cl.JaroWinklerAtThresholds("name", [0.9, 0.7]),
            cl.ExactMatch("phone"),
            cl.ExactMatch("national_id"),
            cl.ExactMatch("entity_type"),
        ],
        blocking_rules_to_generate_predictions=[
            block_on("entity_type"),
        ],
    )

    db_api = DuckDBAPI()
    linker = Linker(df, settings, db_api)

    # Estimate model parameters ----------------------------------------
    linker.training.estimate_u_using_random_sampling(max_pairs=1e5)
    try:
        linker.training.estimate_parameters_using_expectation_maximisation(
            block_on("name"),
            fix_u_probabilities=False,
        )
    except Exception:
        pass  # May fail on tiny datasets — that's fine, we still predict

    # Predict and cluster ----------------------------------------------
    predictions = linker.inference.predict(threshold_match_probability=0.5)
    clusters = linker.clustering.cluster_pairwise_predictions_at_threshold(
        predictions, threshold_match_probability=0.5
    )

    cluster_df = clusters.as_pandas_dataframe()

    # Group entities by cluster ----------------------------------------
    resolved: list[ResolvedEntity] = []
    for cluster_id, group in cluster_df.groupby("cluster_id"):
        member_ids = group["unique_id"].tolist()
        member_entities = [entities[int(uid)] for uid in member_ids]
        resolved.append(_build_resolved(member_entities))

    # Entities not in any cluster (singletons) -------------------------
    clustered_ids = set(cluster_df["unique_id"].astype(int).tolist())
    for i, ent in enumerate(entities):
        if i not in clustered_ids:
            resolved.append(_single_entity_to_resolved(ent))

    return resolved


# ===================================================================
# Fuzzy-match fallback (always available)
# ===================================================================


def _resolve_fuzzy(entities: list[Entity]) -> list[ResolvedEntity]:
    """Resolve entities using fuzzy string matching and union-find clustering."""
    from rapidfuzz import fuzz

    # --- helpers: African name equivalence ---
    def _names_equivalent(a: str, b: str) -> tuple[bool, float]:
        """Return (is_equivalent, confidence) using cultural naming intelligence."""
        try:
            from ..detect._names.lexicon import are_names_equivalent

            return are_names_equivalent(a, b)
        except (ImportError, Exception):
            return (False, 0.0)

    # Group entities by type -------------------------------------------
    groups: dict[str, list[int]] = defaultdict(list)
    for i, ent in enumerate(entities):
        groups[ent.entity_type].append(i)

    # Union-Find -------------------------------------------------------
    parent = list(range(len(entities)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    # Block-based comparison within each type group --------------------
    # Uses blocking keys to reduce O(n²) to O(n*k) where k = block size
    similarity_threshold = 0.80

    for etype, indices in groups.items():
        # Build blocking index
        blocks: dict[str, list[int]] = defaultdict(list)
        for idx in indices:
            key = _blocking_key(entities[idx])
            blocks[key].append(idx)

        # Compare within blocks + adjacent blocks (same first char)
        seen_pairs: set[tuple[int, int]] = set()
        block_keys = list(blocks.keys())

        for bk in block_keys:
            # Collect: this block + blocks sharing first character
            candidate_indices = list(blocks[bk])
            for other_bk in block_keys:
                if other_bk != bk and other_bk[:1] == bk[:1]:
                    candidate_indices.extend(blocks[other_bk])

            for ii in range(len(candidate_indices)):
                for jj in range(ii + 1, len(candidate_indices)):
                    i, j = candidate_indices[ii], candidate_indices[jj]
                    pair = (min(i, j), max(i, j))
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)

                    ent_a, ent_b = entities[i], entities[j]
                    sim = 0.0

                    if etype in ("PERSON", "ORGANIZATION", "LOCATION"):
                        score = fuzz.token_sort_ratio(ent_a.text, ent_b.text) / 100.0
                        if score >= similarity_threshold:
                            sim = max(sim, score)
                        if etype == "PERSON":
                            equiv, equiv_score = _names_equivalent(ent_a.text, ent_b.text)
                            if equiv:
                                sim = max(sim, equiv_score)
                    elif etype in ("PHONE", "NATIONAL_ID", "EMAIL"):
                        norm_a = _normalise_for_match(ent_a.text)
                        norm_b = _normalise_for_match(ent_b.text)
                        if norm_a == norm_b:
                            sim = 1.0
                    else:
                        score = fuzz.token_sort_ratio(ent_a.text, ent_b.text) / 100.0
                        if score >= similarity_threshold:
                            sim = max(sim, score)

                    if sim >= similarity_threshold:
                        union(i, j)

    # Cross-type linking: merge PERSON entities that share the same
    # phone, national_id, or patient_id from FHIR data ────────────��───
    person_indices = groups.get("PERSON", [])
    phone_to_persons: dict[str, list[int]] = defaultdict(list)
    id_to_persons: dict[str, list[int]] = defaultdict(list)
    patient_to_persons: dict[str, list[int]] = defaultdict(list)

    # Build index: which entities share metadata with which persons
    for pi in person_indices:
        pid = entities[pi].metadata.get("patient_id", "")
        if pid:
            patient_to_persons[pid].append(pi)

    # For each phone/national_id entity, find persons from the same patient
    for i, ent in enumerate(entities):
        pid = ent.metadata.get("patient_id", "")
        if not pid:
            continue
        if ent.entity_type == "PHONE":
            norm = _normalise_for_match(ent.text)
            phone_to_persons[norm].extend(patient_to_persons.get(pid, []))
        elif ent.entity_type == "NATIONAL_ID":
            norm = _normalise_for_match(ent.text)
            id_to_persons[norm].extend(patient_to_persons.get(pid, []))

    # Merge persons that share the same phone number
    for _phone, person_list in phone_to_persons.items():
        unique_persons = list(set(person_list))
        for k in range(1, len(unique_persons)):
            union(unique_persons[0], unique_persons[k])

    # Merge persons that share the same national ID
    for _nid, person_list in id_to_persons.items():
        unique_persons = list(set(person_list))
        for k in range(1, len(unique_persons)):
            union(unique_persons[0], unique_persons[k])

    # Collect clusters -------------------------------------------------
    clusters: dict[int, list[int]] = defaultdict(list)
    for i in range(len(entities)):
        clusters[find(i)].append(i)

    resolved: list[ResolvedEntity] = []
    for members in clusters.values():
        member_entities = [entities[i] for i in members]
        resolved.append(_build_resolved(member_entities))

    return resolved


# ===================================================================
# Shared helpers
# ===================================================================


def _normalise_for_match(text: str) -> str:
    """Strip whitespace, dashes, parens, and lowercase for exact matching."""
    import re

    return re.sub(r"[\s\-\(\)\+]+", "", text).lower()


def _blocking_key(entity: Entity) -> str:
    """Compute a blocking key for an entity to reduce pairwise comparisons.

    Entities with the same blocking key are compared. Adjacent blocks
    (same first character) are also compared to handle transliteration
    variants (e.g., Coulibaly/Kulibali → "co"/"ku" share nothing, but
    African name equivalence catches them via adjacent-block expansion).
    """
    if entity.entity_type in ("PHONE", "NATIONAL_ID", "EMAIL"):
        # Exact-match types: full normalized value as key
        return _normalise_for_match(entity.text)

    # For names/locations: first 2 chars of normalized, diacritic-stripped text
    normalized = entity.text.strip().lower()
    nfkd = unicodedata.normalize("NFKD", normalized)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    return stripped[:2] if len(stripped) >= 2 else stripped


def _build_resolved(member_entities: list[Entity]) -> ResolvedEntity:
    """Build a ResolvedEntity from a cluster of raw entities."""
    # Pick the canonical name as the longest text (often most complete form)
    canonical = max(member_entities, key=lambda e: len(e.text))
    aliases = sorted({e.text for e in member_entities if e.text != canonical.text})
    avg_confidence = sum(e.confidence for e in member_entities) / len(member_entities)

    # Build match reasons
    reasons: list[str] = []
    if len(member_entities) > 1:
        reasons.append(f"merged_{len(member_entities)}_mentions")

        # Detect which types of matching were used
        sources = {e.source for e in member_entities}
        types_present = {e.entity_type for e in member_entities}
        patient_ids = {
            e.metadata.get("patient_id") for e in member_entities
            if e.metadata.get("patient_id")
        }

        if len(patient_ids) > 1:
            reasons.append(f"cross_system_match:{len(patient_ids)}_sources")
        if "fhir" in sources:
            reasons.append("fhir_resolved")
        if "PHONE" in types_present:
            reasons.append("phone_match")
        if "NATIONAL_ID" in types_present:
            reasons.append("national_id_match")

    return ResolvedEntity(
        canonical_name=canonical.text,
        entity_type=canonical.entity_type,
        aliases=aliases,
        confidence=round(avg_confidence, 4),
        sources=len(member_entities),
        match_reasons=reasons,
        entities=member_entities,
    )


def _single_entity_to_resolved(entity: Entity) -> ResolvedEntity:
    """Wrap a single entity as a ResolvedEntity with sources=1."""
    return ResolvedEntity(
        canonical_name=entity.text,
        entity_type=entity.entity_type,
        aliases=[],
        confidence=entity.confidence,
        sources=1,
        match_reasons=[],
        entities=[entity],
    )


# ===================================================================
# v2 API: Evidence → IdentityRecord resolution
# ===================================================================


def resolve_identity_records(
    evidence: list[IdentityEvidence],
    *,
    threshold: float = 0.80,
    use_splink: bool = True,
    jurisdiction: str = "auto",
) -> list[IdentityRecord]:
    """Resolve a list of IdentityEvidence into deduplicated IdentityRecords.

    This is the v2 API that works with rich typed evidence from the ensemble
    extractor. It bridges evidence → v1 Entity resolution → v2 IdentityRecord.

    Parameters
    ----------
    evidence:
        Extracted identity evidence (from ``extract_identity_evidence()``).
    threshold:
        Similarity threshold for matching (0.0–1.0).
    use_splink:
        If True, attempt Splink. Falls back to fuzzy matching.
    jurisdiction:
        ISO 3166-1 alpha-2 country code for jurisdiction-specific resolution
        defaults. ``"auto"`` infers from evidence country_hint fields.

    Returns
    -------
    list[IdentityRecord]
        Deduplicated canonical person/org records with evidence provenance.
    """
    from ..types import IdentityRecord as IdentityRecordDC

    if not evidence:
        return []

    # Map v2 IdentityEvidence → v1 Entity for the existing resolution engine
    v1_entities = _evidence_to_entities(evidence)

    # Run resolution through the proven v1 pipeline
    resolved = resolve_entities(v1_entities, use_splink=use_splink)

    # Infer jurisdiction if "auto"
    inferred_jurisdiction = jurisdiction
    if jurisdiction == "auto":
        country_counts: dict[str, int] = defaultdict(int)
        for ev in evidence:
            if ev.country_hint:
                country_counts[ev.country_hint] += 1
        if country_counts:
            inferred_jurisdiction = max(country_counts, key=country_counts.get)
        else:
            inferred_jurisdiction = ""

    # Convert v1 ResolvedEntity → v2 IdentityRecord with rich metadata
    records: list[IdentityRecord] = []
    for i, re_ent in enumerate(resolved):
        # Build structured fields from member entities
        identifiers: list[dict] = []
        telecom: list[dict] = []
        addresses: list[dict] = []
        demographics: dict = {}
        source_systems: set[str] = set()

        for ent in re_ent.entities:
            meta = ent.metadata or {}
            if ent.entity_type == "NATIONAL_ID":
                identifiers.append({
                    "system": meta.get("system", ""),
                    "value": ent.text,
                    "country": meta.get("country", inferred_jurisdiction),
                    "type": meta.get("id_type", "NATIONAL_ID"),
                })
            elif ent.entity_type == "PHONE":
                telecom.append({"system": "phone", "value": ent.text})
            elif ent.entity_type == "EMAIL":
                telecom.append({"system": "email", "value": ent.text})
            elif ent.entity_type == "LOCATION":
                addresses.append({"text": ent.text, **meta})
            elif ent.entity_type == "DATE" and meta.get("date_type") == "birth":
                demographics["birth_date"] = ent.text

            pid = meta.get("patient_id", "")
            if pid:
                source_systems.add(pid)

        # Build match decision for audit trail
        factor_breakdown = {}
        for reason in re_ent.match_reasons:
            if ":" in reason:
                key, val = reason.split(":", 1)
                try:
                    factor_breakdown[key] = float(val)
                except ValueError:
                    factor_breakdown[key] = 1.0
            else:
                factor_breakdown[reason] = 1.0

        # Map member entities back to their IdentityEvidence originals
        member_evidence = _find_matching_evidence(re_ent.entities, evidence)

        records.append(IdentityRecordDC(
            cluster_id=f"cluster-{i}",
            canonical_name=re_ent.canonical_name,
            names=[re_ent.canonical_name] + re_ent.aliases,
            identifiers=identifiers,
            telecom=telecom,
            addresses=addresses,
            demographics=demographics,
            source_systems=list(source_systems),
            evidence=member_evidence,
            confidence=re_ent.confidence,
            match_reasons=re_ent.match_reasons,
        ))

    return records


def _evidence_to_entities(evidence: list[IdentityEvidence]) -> list[Entity]:
    """Convert v2 IdentityEvidence list to v1 Entity list for resolution."""
    # Label → v1 entity type mapping
    _LABEL_TO_TYPE = {
        "person": "PERSON", "first_name": "PERSON", "last_name": "PERSON",
        "full_name": "PERSON", "title": "PERSON",
        "organization": "ORGANIZATION", "company": "ORGANIZATION",
        "employer": "ORGANIZATION",
        "location": "LOCATION", "street_address": "LOCATION", "city": "LOCATION",
        "state": "LOCATION", "postcode": "LOCATION", "country": "LOCATION",
        "address": "LOCATION",
        "phone": "PHONE", "phone_number": "PHONE",
        "email": "EMAIL",
        "national_id": "NATIONAL_ID", "nin": "NATIONAL_ID", "bvn": "NATIONAL_ID",
        "ghana_card": "NATIONAL_ID", "kenya_id": "NATIONAL_ID", "sa_id": "NATIONAL_ID",
        "tin": "NATIONAL_ID", "pvc": "NATIONAL_ID", "aadhaar": "NATIONAL_ID",
        "passport_number": "NATIONAL_ID", "ssn": "NATIONAL_ID",
        "money": "MONEY", "currency": "MONEY",
        "date": "DATE", "date_of_birth": "DATE", "time": "DATE",
        "account_number": "MONEY", "swift_bic": "MONEY",
        "occupation": "PERSON", "job_title": "PERSON",
    }

    entities: list[Entity] = []
    for ev in evidence:
        entity_type = _LABEL_TO_TYPE.get(ev.label.lower(), ev.label.upper())
        meta = dict(ev.metadata) if ev.metadata else {}
        if ev.country_hint:
            meta["country"] = ev.country_hint
        if ev.document_id:
            meta["patient_id"] = ev.document_id

        entities.append(Entity(
            text=ev.text,
            entity_type=entity_type,
            confidence=ev.confidence,
            start=ev.start,
            end=ev.end,
            source=ev.detector_source,
            metadata=meta,
        ))

    return entities


def _find_matching_evidence(
    v1_entities: list[Entity],
    all_evidence: list[IdentityEvidence],
) -> list[IdentityEvidence]:
    """Find the original IdentityEvidence objects that correspond to v1 entities."""
    matched = []
    used = set()
    for ent in v1_entities:
        for idx, ev in enumerate(all_evidence):
            if idx in used:
                continue
            if ev.start == ent.start and ev.end == ent.end and ev.text == ent.text:
                matched.append(ev)
                used.add(idx)
                break
    return matched
