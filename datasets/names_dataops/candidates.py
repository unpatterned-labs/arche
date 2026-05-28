"""Candidate generation for naming equivalences."""

from __future__ import annotations

import hashlib
import math
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import yaml

from .constants import EAST_AFRICA_ISO2, WEST_AFRICA_ISO2
from .schemas import CandidateEquivalenceV1, NormalizedNameV1


def load_existing_equivalences(yaml_dir: Path) -> dict[str, Any]:
    """Load canonical groups and reverse lookup maps from YAML files."""
    canonical_to_file: dict[str, str] = {}
    canonical_to_variants: dict[str, set[str]] = {}
    key_to_canonicals: dict[str, set[str]] = defaultdict(set)

    for yaml_file in sorted(yaml_dir.glob("*.yaml")):
        with open(yaml_file, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        for group in data.get("groups", []):
            canonical = str(group.get("canonical", "")).strip()
            if not canonical:
                continue
            canonical_to_file[canonical] = yaml_file.stem
            variants = {str(v).strip() for v in group.get("variants", []) if str(v).strip()}
            canonical_to_variants[canonical] = variants
            key_to_canonicals[_ascii_key(canonical)].add(canonical)
            for variant in variants:
                key_to_canonicals[_ascii_key(variant)].add(canonical)

    return {
        "canonical_to_file": canonical_to_file,
        "canonical_to_variants": canonical_to_variants,
        "key_to_canonicals": key_to_canonicals,
    }


def generate_candidates(
    normalized_rows: list[dict[str, Any]],
    existing: dict[str, Any],
) -> list[dict[str, Any]]:
    """Generate deterministic review candidates from normalized evidence."""
    typed_rows = [NormalizedNameV1.model_validate(row) for row in normalized_rows]
    clusters: dict[tuple[str, str], list[NormalizedNameV1]] = defaultdict(list)

    for row in typed_rows:
        clusters[(row.name_ascii_key, row.name_type)].append(row)

    out: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str, str]] = set()
    key_to_canonicals: dict[str, set[str]] = existing["key_to_canonicals"]
    canonical_to_file: dict[str, str] = existing["canonical_to_file"]
    canonical_to_variants: dict[str, set[str]] = existing["canonical_to_variants"]

    for (ascii_key, name_type), records in sorted(clusters.items()):
        counts = _count_forms(records)
        if len(counts) < 2 and ascii_key not in key_to_canonicals:
            continue

        known_canonicals = key_to_canonicals.get(ascii_key, set())
        conflict_flag = len(known_canonicals) > 1
        if known_canonicals:
            canonical = sorted(known_canonicals)[0]
        else:
            canonical = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]

        suggested_tradition = canonical_to_file.get(
            canonical,
            _infer_tradition(records),
        )

        for variant, variant_count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
            if variant == canonical:
                continue
            if canonical in canonical_to_variants and variant in canonical_to_variants[canonical]:
                continue

            key = (canonical, variant, name_type)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)

            confidence = _score_candidate(
                canonical=canonical,
                variant=variant,
                total_count=sum(counts.values()),
                variant_count=variant_count,
                conflict_flag=conflict_flag,
            )
            candidate = CandidateEquivalenceV1(
                candidate_id=_candidate_id(canonical, variant, name_type),
                canonical=canonical,
                variant=variant,
                name_type=name_type,
                suggested_tradition=suggested_tradition,
                confidence=confidence,
                evidence_summary=_build_evidence_summary(records, variant_count),
                wikidata_qids=sorted({r.source_id for r in records if r.source == "wikidata"}),
                countries=sorted({r.country_iso2 for r in records}),
                languages=sorted({r.language_tag for r in records}),
                status="pending",
                source="|".join(sorted({r.source for r in records})),
                source_license="|".join(sorted({r.source_license for r in records})),
                conflict_flag=conflict_flag,
            )
            out.append(candidate.model_dump(mode="json"))

    _add_similarity_candidates(
        out=out,
        seen_pairs=seen_pairs,
        typed_rows=typed_rows,
        key_to_canonicals=key_to_canonicals,
        canonical_to_file=canonical_to_file,
        canonical_to_variants=canonical_to_variants,
    )

    return sorted(out, key=lambda row: row["candidate_id"])


def _count_forms(records: list[NormalizedNameV1]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for record in records:
        counts[record.name_nfc] += record.evidence_count
    return dict(counts)


def _score_candidate(
    *,
    canonical: str,
    variant: str,
    total_count: int,
    variant_count: int,
    conflict_flag: bool,
) -> float:
    similarity = SequenceMatcher(None, _ascii_key(canonical), _ascii_key(variant)).ratio()
    support = min(1.0, math.log1p(total_count) / 4)
    variant_support = min(1.0, math.log1p(variant_count) / 3)
    score = (0.5 * similarity) + (0.3 * support) + (0.2 * variant_support)
    if conflict_flag:
        score -= 0.2
    return max(0.0, min(0.99, round(score, 4)))


def _build_evidence_summary(records: list[NormalizedNameV1], variant_count: int) -> str:
    countries = sorted({r.country_iso2 for r in records})
    sources = sorted({r.source for r in records})
    return (
        f"variant_count={variant_count}; total_records={len(records)}; "
        f"countries={','.join(countries)}; sources={','.join(sources)}"
    )


def _candidate_id(canonical: str, variant: str, name_type: str) -> str:
    digest = hashlib.sha1(f"{canonical}|{variant}|{name_type}".encode()).hexdigest()
    return f"cand_{digest[:16]}"


def _infer_tradition(records: list[NormalizedNameV1]) -> str:
    country_set = {r.country_iso2 for r in records}
    if country_set & WEST_AFRICA_ISO2 and not country_set & EAST_AFRICA_ISO2:
        return "west_african"
    if country_set & EAST_AFRICA_ISO2 and not country_set & WEST_AFRICA_ISO2:
        return "east_african"
    if country_set & WEST_AFRICA_ISO2 and country_set & EAST_AFRICA_ISO2:
        return "cross_linguistic"
    return "cross_linguistic"


def _add_similarity_candidates(
    *,
    out: list[dict[str, Any]],
    seen_pairs: set[tuple[str, str, str]],
    typed_rows: list[NormalizedNameV1],
    key_to_canonicals: dict[str, set[str]],
    canonical_to_file: dict[str, str],
    canonical_to_variants: dict[str, set[str]],
) -> None:
    """Add candidates for near-miss spellings not caught by exact ascii-key clusters."""
    canonical_keys = {
        canonical: _ascii_key(canonical)
        for canonical in canonical_to_file
    }
    by_variant: dict[tuple[str, str], list[NormalizedNameV1]] = defaultdict(list)
    for row in typed_rows:
        if row.name_ascii_key in key_to_canonicals:
            continue
        by_variant[(row.name_nfc, row.name_type)].append(row)

    for (variant, name_type), records in sorted(by_variant.items()):
        variant_key = _ascii_key(variant)
        if not variant_key:
            continue

        best_canonical = ""
        best_similarity = 0.0
        for canonical, canonical_key in canonical_keys.items():
            sim = SequenceMatcher(None, variant_key, canonical_key).ratio()
            if sim > best_similarity:
                best_similarity = sim
                best_canonical = canonical

        if best_similarity < 0.72 or not best_canonical:
            continue
        if variant == best_canonical:
            continue
        if variant in canonical_to_variants.get(best_canonical, set()):
            continue

        key = (best_canonical, variant, name_type)
        if key in seen_pairs:
            continue
        seen_pairs.add(key)

        candidate = CandidateEquivalenceV1(
            candidate_id=_candidate_id(best_canonical, variant, name_type),
            canonical=best_canonical,
            variant=variant,
            name_type=name_type,
            suggested_tradition=canonical_to_file.get(best_canonical, "cross_linguistic"),
            confidence=max(0.7, round(best_similarity * 0.95, 4)),
            evidence_summary=(
                f"similarity_bootstrap={best_similarity:.4f}; "
                f"records={len(records)}"
            ),
            wikidata_qids=sorted({r.source_id for r in records if r.source == "wikidata"}),
            countries=sorted({r.country_iso2 for r in records}),
            languages=sorted({r.language_tag for r in records}),
            status="pending",
            source="|".join(sorted({r.source for r in records})),
            source_license="|".join(sorted({r.source_license for r in records})),
            conflict_flag=False,
        )
        out.append(candidate.model_dump(mode="json"))


def _ascii_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return "".join(ch for ch in without_marks if ch.isalnum())
