"""CLI for Arche naming DataOps pipeline v1."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import export_hf
from .apply import apply_approved_candidates
from .candidates import generate_candidates, load_existing_equivalences
from .constants import (
    APPROVED_REGISTRY_PATH,
    BUNDLE_DIR,
    CANDIDATES_CSV_PATH,
    CANDIDATES_JSONL_PATH,
    CONTRIBUTIONS_DIR,
    COUNTRY_SCOPE_CORE16,
    DATASET_STATS_PATH,
    ENRICHED_CSV_PATH,
    ENRICHED_JSONL_PATH,
    LEXICON_CSV_PATH,
    LEXICON_JSONL_PATH,
    NAME_EQUIVALENCES_DIR,
    NORMALIZED_PATH,
    RAW_EVIDENCE_PATH,
    REVIEW_CSV_PATH,
    RUN_METADATA_PATH,
    SCHEMAS_DIR,
    UNIQUE_NAMES_CSV_PATH,
    UNIQUE_NAMES_JSONL_PATH,
)
from .export import build_enriched_rows, write_dataset_stats, write_enriched_exports
from .io_utils import dump_json, read_csv, read_jsonl, validate_rows, write_csv, write_jsonl
from .lexicon import build_lexicon_rows, build_minimal_unique_rows, make_run_summary
from .normalize import normalize_name
from .review import write_review_bundle
from .schemas import (
    AfricanNameLexiconV1,
    CandidateEquivalenceV1,
    CuratedContributionCSVV1,
    NormalizedNameV1,
    PublishedEquivalenceV1,
    RawNameEvidenceV1,
)
from .wikidata import fetch_wikidata_rows

SCHEMA_MODELS = {
    "raw": RawNameEvidenceV1,
    "normalized": NormalizedNameV1,
    "candidate": CandidateEquivalenceV1,
    "curated_csv": CuratedContributionCSVV1,
    "published": PublishedEquivalenceV1,
    "lexicon": AfricanNameLexiconV1,
}


def main(argv: list[str] | None = None) -> int:
    """Run the names DataOps command line interface."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Arche naming data pipeline v1")
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch_wikidata", help="Fetch raw name evidence from Wikidata")
    p_fetch.add_argument("--output", type=Path, default=RAW_EVIDENCE_PATH)
    p_fetch.add_argument("--page-limit", type=int, default=5000)
    p_fetch.add_argument("--max-pages", type=int, default=6)
    p_fetch.set_defaults(func=cmd_fetch_wikidata)

    p_ingest = sub.add_parser("ingest_csv", help="Ingest curated CSV contribution rows")
    p_ingest.add_argument("--pattern", default="*.csv")
    p_ingest.add_argument("--input-dir", type=Path, default=CONTRIBUTIONS_DIR)
    p_ingest.add_argument("--output", type=Path, default=RAW_EVIDENCE_PATH)
    p_ingest.add_argument("--append", action="store_true")
    p_ingest.set_defaults(func=cmd_ingest_csv)

    p_norm = sub.add_parser("normalize", help="Normalize raw name evidence")
    p_norm.add_argument("--input", type=Path, default=RAW_EVIDENCE_PATH)
    p_norm.add_argument("--output", type=Path, default=NORMALIZED_PATH)
    p_norm.set_defaults(func=cmd_normalize)

    p_cand = sub.add_parser("generate_candidates", help="Generate equivalence candidates")
    p_cand.add_argument("--input", type=Path, default=NORMALIZED_PATH)
    p_cand.add_argument("--yaml-dir", type=Path, default=NAME_EQUIVALENCES_DIR)
    p_cand.add_argument("--jsonl-output", type=Path, default=CANDIDATES_JSONL_PATH)
    p_cand.add_argument("--csv-output", type=Path, default=CANDIDATES_CSV_PATH)
    p_cand.set_defaults(func=cmd_generate_candidates)

    p_review = sub.add_parser("review_bundle", help="Build review bundle artifacts")
    p_review.add_argument("--input", type=Path, default=CANDIDATES_JSONL_PATH)
    p_review.add_argument("--bundle-dir", type=Path, default=BUNDLE_DIR)
    p_review.set_defaults(func=cmd_review_bundle)

    p_apply = sub.add_parser("apply_approved", help="Apply approved review candidates to YAML")
    p_apply.add_argument("--review-csv", type=Path, default=REVIEW_CSV_PATH)
    p_apply.add_argument("--yaml-dir", type=Path, default=NAME_EQUIVALENCES_DIR)
    p_apply.add_argument("--approved-registry", type=Path, default=APPROVED_REGISTRY_PATH)
    p_apply.set_defaults(func=cmd_apply_approved)

    p_export = sub.add_parser("export_publish", help="Export legacy + enriched publish artifacts")
    p_export.add_argument("--approved-registry", type=Path, default=APPROVED_REGISTRY_PATH)
    p_export.add_argument("--enriched-csv", type=Path, default=ENRICHED_CSV_PATH)
    p_export.add_argument("--enriched-jsonl", type=Path, default=ENRICHED_JSONL_PATH)
    p_export.add_argument("--stats-path", type=Path, default=DATASET_STATS_PATH)
    p_export.set_defaults(func=cmd_export_publish)

    p_validate = sub.add_parser("validate_schema", help="Validate JSONL/CSV rows against schema")
    p_validate.add_argument("--schema", choices=sorted(SCHEMA_MODELS.keys()), required=True)
    p_validate.add_argument("--input", type=Path, required=True)
    p_validate.set_defaults(func=cmd_validate_schema)

    p_schema = sub.add_parser("generate_schema_docs", help="Generate JSON Schema files")
    p_schema.add_argument("--output-dir", type=Path, default=SCHEMAS_DIR)
    p_schema.set_defaults(func=cmd_generate_schema_docs)

    p_lexicon = sub.add_parser(
        "build_lexicon",
        help="Fetch + clean + union + dedupe names into arche-ready CSV/JSONL",
    )
    p_lexicon.add_argument("--page-limit", type=int, default=5000)
    p_lexicon.add_argument("--max-pages", type=int, default=12)
    p_lexicon.add_argument(
        "--countries",
        default="",
        help="Optional comma-separated ISO2 list, e.g. NG,GH,KE",
    )
    p_lexicon.add_argument("--include-csv", action="store_true")
    p_lexicon.add_argument("--csv-input-dir", type=Path, default=CONTRIBUTIONS_DIR)
    p_lexicon.add_argument("--csv-pattern", default="*.csv")
    p_lexicon.add_argument("--raw-output", type=Path, default=RAW_EVIDENCE_PATH)
    p_lexicon.add_argument("--normalized-output", type=Path, default=NORMALIZED_PATH)
    p_lexicon.add_argument("--lexicon-csv", type=Path, default=LEXICON_CSV_PATH)
    p_lexicon.add_argument("--lexicon-jsonl", type=Path, default=LEXICON_JSONL_PATH)
    p_lexicon.add_argument("--unique-csv", type=Path, default=UNIQUE_NAMES_CSV_PATH)
    p_lexicon.add_argument("--unique-jsonl", type=Path, default=UNIQUE_NAMES_JSONL_PATH)
    p_lexicon.add_argument("--quiet", action="store_true")
    p_lexicon.set_defaults(func=cmd_build_lexicon)

    p_materialize = sub.add_parser(
        "materialize_lexicon",
        help="Materialize deduped lexicon from normalized rows (no network)",
    )
    p_materialize.add_argument("--input", type=Path, default=NORMALIZED_PATH)
    p_materialize.add_argument("--lexicon-csv", type=Path, default=LEXICON_CSV_PATH)
    p_materialize.add_argument("--lexicon-jsonl", type=Path, default=LEXICON_JSONL_PATH)
    p_materialize.add_argument("--unique-csv", type=Path, default=UNIQUE_NAMES_CSV_PATH)
    p_materialize.add_argument("--unique-jsonl", type=Path, default=UNIQUE_NAMES_JSONL_PATH)
    p_materialize.set_defaults(func=cmd_materialize_lexicon)

    return parser


def cmd_fetch_wikidata(args: argparse.Namespace) -> None:
    rows, metadata = fetch_wikidata_rows(
        COUNTRY_SCOPE_CORE16,
        page_limit=args.page_limit,
        max_pages=args.max_pages,
    )
    typed = validate_rows(RawNameEvidenceV1, rows)
    typed.sort(key=lambda row: (row["country_iso2"], row["name_type"], row["name_raw"].casefold()))
    write_jsonl(args.output, typed)
    _update_run_metadata(
        "fetch_wikidata",
        {
            "rows_written": len(typed),
            "output": str(args.output),
            "details": metadata,
        },
    )
    print(f"Wrote {len(typed)} raw rows to {args.output}")


def cmd_ingest_csv(args: argparse.Namespace) -> None:
    csv_files = sorted(args.input_dir.glob(args.pattern))
    rows: list[dict[str, Any]] = []
    for path in csv_files:
        if path.name.startswith("sample_"):
            continue
        rows.extend(read_csv(path))
    typed_contribs = validate_rows(CuratedContributionCSVV1, rows)
    raw_rows = [
        RawNameEvidenceV1(
            source=row["source"],
            source_id=row["source_id"],
            source_license=row["source_license"],
            name_raw=row["name_raw"],
            name_type=row["name_type"],
            country_iso2=row["country_iso2"],
            language_tag=row["language_tag"],
            evidence_count=row["evidence_count"],
            fetched_at=row["fetched_at"],
        ).model_dump(mode="json")
        for row in typed_contribs
    ]
    if args.append and args.output.exists():
        raw_rows = read_jsonl(args.output) + raw_rows
    deduped = _dedupe_raw_rows(raw_rows)
    write_jsonl(args.output, deduped)
    _update_run_metadata(
        "ingest_csv",
        {
            "rows_input": len(rows),
            "rows_written": len(deduped),
            "files": [str(p) for p in csv_files],
            "output": str(args.output),
        },
    )
    print(f"Wrote {len(deduped)} raw rows to {args.output}")


def cmd_normalize(args: argparse.Namespace) -> None:
    raw_rows = validate_rows(RawNameEvidenceV1, read_jsonl(args.input))
    typed_raw = [RawNameEvidenceV1.model_validate(row) for row in raw_rows]
    normalized = [normalize_name(row).model_dump(mode="json") for row in typed_raw]
    normalized.sort(key=lambda row: (row["name_ascii_key"], row["name_nfc"], row["country_iso2"]))
    write_jsonl(args.output, normalized)
    _update_run_metadata(
        "normalize",
        {
            "rows_input": len(raw_rows),
            "rows_written": len(normalized),
            "output": str(args.output),
        },
    )
    print(f"Wrote {len(normalized)} normalized rows to {args.output}")


def cmd_generate_candidates(args: argparse.Namespace) -> None:
    normalized_rows = validate_rows(NormalizedNameV1, read_jsonl(args.input))
    existing = load_existing_equivalences(args.yaml_dir)
    candidates = generate_candidates(normalized_rows, existing)
    write_jsonl(args.jsonl_output, candidates)
    if candidates:
        fieldnames = list(candidates[0].keys())
        write_csv(args.csv_output, candidates, fieldnames)
    else:
        write_csv(args.csv_output, [], list(CandidateEquivalenceV1.model_fields.keys()))
    _update_run_metadata(
        "generate_candidates",
        {
            "rows_input": len(normalized_rows),
            "rows_written": len(candidates),
            "jsonl_output": str(args.jsonl_output),
            "csv_output": str(args.csv_output),
        },
    )
    print(f"Wrote {len(candidates)} candidate rows")


def cmd_review_bundle(args: argparse.Namespace) -> None:
    candidates = validate_rows(CandidateEquivalenceV1, read_jsonl(args.input))
    summary = write_review_bundle(candidates, args.bundle_dir)
    _update_run_metadata(
        "review_bundle",
        {
            "summary": summary,
            "bundle_dir": str(args.bundle_dir),
        },
    )
    print(f"Review bundle created in {args.bundle_dir}")


def cmd_apply_approved(args: argparse.Namespace) -> None:
    rows = _read_rows_from_path(args.review_csv)
    summary = apply_approved_candidates(
        review_rows=rows,
        yaml_dir=args.yaml_dir,
        approved_registry_path=args.approved_registry,
    )
    _update_run_metadata(
        "apply_approved",
        {
            "summary": summary,
            "review_csv": str(args.review_csv),
            "yaml_dir": str(args.yaml_dir),
        },
    )
    print(f"Applied approved candidates: {summary}")


def cmd_export_publish(args: argparse.Namespace) -> None:
    legacy_rows = export_hf.load_all_groups()
    # Keep the current legacy compatibility flow unchanged.
    export_hf.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    export_hf.export_csv(legacy_rows, export_hf.OUTPUT_DIR / f"{export_hf.STEM}.csv")
    export_hf.export_jsonl(legacy_rows, export_hf.OUTPUT_DIR / f"{export_hf.STEM}.jsonl")
    export_hf.export_parquet(legacy_rows, export_hf.OUTPUT_DIR / f"{export_hf.STEM}.parquet")

    enriched = build_enriched_rows(legacy_rows, args.approved_registry)
    write_enriched_exports(
        enriched_rows=enriched,
        csv_path=args.enriched_csv,
        jsonl_path=args.enriched_jsonl,
    )
    write_dataset_stats(
        legacy_rows=legacy_rows,
        enriched_rows=enriched,
        stats_path=args.stats_path,
    )
    _update_run_metadata(
        "export_publish",
        {
            "legacy_rows": len(legacy_rows),
            "enriched_rows": len(enriched),
            "stats_path": str(args.stats_path),
        },
    )
    print(
        f"Export complete: legacy_rows={len(legacy_rows)}, enriched_rows={len(enriched)}",
    )


def cmd_validate_schema(args: argparse.Namespace) -> None:
    rows = _read_rows_from_path(args.input)
    model = SCHEMA_MODELS[args.schema]
    validate_rows(model, rows)
    print(f"Validated {len(rows)} row(s) against {model.__name__}")


def cmd_generate_schema_docs(args: argparse.Namespace) -> None:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for schema_name, model in SCHEMA_MODELS.items():
        path = args.output_dir / f"{schema_name}_v1.schema.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(model.model_json_schema(), f, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"Generated schema docs in {args.output_dir}")


def cmd_build_lexicon(args: argparse.Namespace) -> None:
    """Run the simplified no-review pipeline for African names."""
    progress = None if args.quiet else _progress
    countries = _resolve_countries(args.countries)
    if progress is not None:
        progress("Starting build_lexicon pipeline")
        progress(
            "Fetch config: "
            f"page_limit={args.page_limit}, "
            f"max_pages={args.max_pages}, include_csv={args.include_csv}",
        )
        progress(f"Country scope: {','.join(sorted(countries.keys()))}")

    wikidata_rows, wikidata_meta = fetch_wikidata_rows(
        countries,
        page_limit=args.page_limit,
        max_pages=args.max_pages,
        progress_callback=progress,
    )
    if progress is not None:
        progress(f"Wikidata stage complete: rows={len(wikidata_rows)}")

    merged_raw = wikidata_rows
    csv_rows_count = 0
    if args.include_csv:
        if progress is not None:
            progress(f"Scanning CSV contributions in {args.csv_input_dir}")
        csv_files = sorted(args.csv_input_dir.glob(args.csv_pattern))
        csv_rows: list[dict[str, Any]] = []
        for path in csv_files:
            if path.name.startswith("sample_"):
                continue
            csv_rows.extend(read_csv(path))
        if csv_rows:
            if progress is not None:
                progress(f"Loaded CSV rows: {len(csv_rows)}")
            validated_csv = validate_rows(CuratedContributionCSVV1, csv_rows)
            csv_raw = [
                RawNameEvidenceV1(
                    source=row["source"],
                    source_id=row["source_id"],
                    source_license=row["source_license"],
                    name_raw=row["name_raw"],
                    name_type=row["name_type"],
                    country_iso2=row["country_iso2"],
                    language_tag=row["language_tag"],
                    evidence_count=row["evidence_count"],
                    fetched_at=row["fetched_at"],
                ).model_dump(mode="json")
                for row in validated_csv
            ]
            merged_raw = merged_raw + csv_raw
            csv_rows_count = len(csv_raw)
            if progress is not None:
                progress(f"Merged CSV rows: {csv_rows_count}")

    if progress is not None:
        progress("Running raw schema validation + dedupe")
    raw_valid = validate_rows(RawNameEvidenceV1, merged_raw)
    raw_deduped = _dedupe_raw_rows(raw_valid)
    write_jsonl(args.raw_output, raw_deduped)
    if progress is not None:
        progress(f"Raw rows after dedupe: {len(raw_deduped)}")

    if progress is not None:
        progress("Normalizing names")
    normalized = [
        normalize_name(RawNameEvidenceV1.model_validate(row)).model_dump(mode="json")
        for row in raw_deduped
    ]
    normalized.sort(key=lambda row: (row["name_type"], row["name_ascii_key"], row["name_nfc"]))
    write_jsonl(args.normalized_output, normalized)
    if progress is not None:
        progress(f"Normalized rows: {len(normalized)}")

    if progress is not None:
        progress("Building lexicon rows")
    lexicon_rows = build_lexicon_rows(normalized)
    write_jsonl(args.lexicon_jsonl, lexicon_rows)
    fieldnames = list(AfricanNameLexiconV1.model_fields.keys())
    write_csv(args.lexicon_csv, lexicon_rows, fieldnames)
    if progress is not None:
        progress(f"Lexicon rows: {len(lexicon_rows)}")

    unique_rows = build_minimal_unique_rows(lexicon_rows)
    write_jsonl(args.unique_jsonl, unique_rows)
    write_csv(args.unique_csv, unique_rows, ["name", "name_type"])
    if progress is not None:
        progress(f"Unique rows: {len(unique_rows)}")

    summary = make_run_summary(lexicon_rows)
    _update_run_metadata(
        "build_lexicon",
        {
            "wikidata_rows": len(wikidata_rows),
            "csv_rows": csv_rows_count,
            "raw_rows_after_dedupe": len(raw_deduped),
            "normalized_rows": len(normalized),
            "lexicon_rows": len(lexicon_rows),
            "unique_rows": len(unique_rows),
            "lexicon_csv": str(args.lexicon_csv),
            "lexicon_jsonl": str(args.lexicon_jsonl),
            "unique_csv": str(args.unique_csv),
            "unique_jsonl": str(args.unique_jsonl),
            "wikidata": wikidata_meta,
            "summary": summary,
        },
    )
    print(
        "Built African name lexicon: "
        f"raw={len(raw_deduped)}, normalized={len(normalized)}, lexicon={len(lexicon_rows)}",
    )


def cmd_materialize_lexicon(args: argparse.Namespace) -> None:
    """Build lexicon output from normalized evidence without fetching new data."""
    normalized = validate_rows(NormalizedNameV1, read_jsonl(args.input))
    lexicon_rows = build_lexicon_rows(normalized)
    write_jsonl(args.lexicon_jsonl, lexicon_rows)
    fieldnames = list(AfricanNameLexiconV1.model_fields.keys())
    write_csv(args.lexicon_csv, lexicon_rows, fieldnames)
    unique_rows = build_minimal_unique_rows(lexicon_rows)
    write_jsonl(args.unique_jsonl, unique_rows)
    write_csv(args.unique_csv, unique_rows, ["name", "name_type"])
    _update_run_metadata(
        "materialize_lexicon",
        {
            "normalized_rows": len(normalized),
            "lexicon_rows": len(lexicon_rows),
            "unique_rows": len(unique_rows),
            "lexicon_csv": str(args.lexicon_csv),
            "lexicon_jsonl": str(args.lexicon_jsonl),
            "unique_csv": str(args.unique_csv),
            "unique_jsonl": str(args.unique_jsonl),
            "summary": make_run_summary(lexicon_rows),
        },
    )
    print(f"Materialized lexicon rows: {len(lexicon_rows)}")


def _read_rows_from_path(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        return read_jsonl(path)
    if path.suffix.lower() == ".csv":
        return read_csv(path)
    raise ValueError(f"Unsupported file extension for {path}")


def _dedupe_raw_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        typed = RawNameEvidenceV1.model_validate(row).model_dump(mode="json")
        key = (
            typed["source"],
            typed["source_id"],
            typed["name_raw"].casefold(),
            typed["name_type"],
            typed["country_iso2"],
        )
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = typed
            continue
        existing["evidence_count"] += int(typed["evidence_count"])
    return [deduped[key] for key in sorted(deduped.keys())]


def _update_run_metadata(stage: str, payload: dict[str, Any]) -> None:
    existing: dict[str, Any] = {}
    if RUN_METADATA_PATH.exists():
        with open(RUN_METADATA_PATH, encoding="utf-8") as f:
            existing = json.load(f)
    existing[stage] = {
        "updated_at": datetime.now(UTC).isoformat(),
        **payload,
    }
    dump_json(RUN_METADATA_PATH, existing)


def _progress(message: str) -> None:
    timestamp = datetime.now(UTC).isoformat(timespec="seconds")
    print(f"[{timestamp}] {message}", flush=True)


def _resolve_countries(raw: str) -> dict[str, str]:
    if not raw.strip():
        return COUNTRY_SCOPE_CORE16
    requested = [part.strip().upper() for part in raw.split(",") if part.strip()]
    selected: dict[str, str] = {}
    for iso2 in requested:
        if iso2 not in COUNTRY_SCOPE_CORE16:
            raise ValueError(
                f"Unsupported country code '{iso2}'. "
                f"Allowed: {','.join(sorted(COUNTRY_SCOPE_CORE16.keys()))}",
            )
        selected[iso2] = COUNTRY_SCOPE_CORE16[iso2]
    if not selected:
        raise ValueError("No valid country codes provided.")
    return selected
