# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Evaluate local benchmark artifacts and save vNext-plannable result bundles.

The destination is always explicit and caller-owned.  A complete mapping can
produce a qualification through :func:`qualification_from_evaluated_result`;
review packs are intentionally recorded with partial or unlabelled truth and
never become method qualifications.

Examples
--------
    uv run --no-sync python data/scripts/benchmark_vnext_artifacts.py abt-buy \
        --output data/_cache/vnext-benchmarks/abt-buy.json \
        --bundle-id local-abt-buy-20260903

    uv run --no-sync python data/scripts/benchmark_vnext_artifacts.py review-pack \
        --pack data/review_packs/nigeria_facilities_2026-08-19 \
        --output data/_cache/vnext-benchmarks/nigeria-facilities.json \
        --bundle-id local-nigeria-facilities-20260903
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "packages" / "arche-core" / "src"))


def _sha256_file(path: Path) -> str:
    return "sha256:" + sha256(path.read_bytes()).hexdigest()


def _pin(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return "sha256:" + sha256(encoded).hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as handle:
        return list(csv.DictReader(handle))


def _write(bundle, output: Path) -> None:
    from arche.runtime import write_benchmark_result_bundle

    if not output.parent.is_dir():
        raise SystemExit(f"output parent does not exist: {output.parent}")
    result_hash = write_benchmark_result_bundle(output, bundle)
    print(f"bundle: {output}")
    print(f"result_hash: {result_hash}")
    print(f"truth_coverage: {bundle.truth_coverage}")


def run_abt_buy(args: argparse.Namespace) -> int:
    from arche.resolve import ENTITY_PACKS, reconcile
    from arche.runtime import BenchmarkResultBundle

    root = REPO / "data" / "er_bench" / "products"
    abt = _read_csv(root / "Abt.csv")
    buy = _read_csv(root / "Buy.csv")
    mapping = _read_csv(root / "abt_buy_perfectMapping.csv")
    truth = {(row["idAbt"], row["idBuy"]) for row in mapping}
    left = [{"id": row["id"], "name": row["name"]} for row in abt]
    right = [{"id": row["id"], "name": row["name"]} for row in buy]

    result = reconcile(
        left,
        right,
        comparators=ENTITY_PACKS["product_electronics"],
        tf=None,
        id_field="id",
    )
    edges = {(edge["a_id"], edge["b_id"]): edge for edge in result["matches"]}
    automatic = {pair for pair, edge in edges.items() if edge["decision"] == "match"}
    reviews = {pair for pair, edge in edges.items() if edge["decision"] == "review"}
    true_automatic = automatic & truth
    true_reviews = reviews & truth
    bundle = BenchmarkResultBundle(
        bundle_id=args.bundle_id,
        method_id="arche-product-electronics-crosswalk-v1",
        resolver="arche",
        configuration_pin=_pin(result["pins"]),
        benchmark_id="leipzig-abt-buy-v1",
        dataset_id="leipzig-abt-buy",
        evaluator_pin="arche.crosswalk.complete-mapping.v1",
        completed_at=datetime.now(UTC),
        truth_coverage="complete",
        candidate_pairs=result["blocking"]["candidate_pairs"],
        auto_match_count=len(automatic),
        review_count=len(reviews),
        true_pair_count=len(truth),
        blocking_true_pair_count=len(set(edges) & truth),
        true_positive_count=len(true_automatic),
        false_positive_count=len(automatic - truth),
        reviewed_true_pair_count=len(true_reviews),
        provenance={
            "inputs": {
                "Abt.csv": _sha256_file(root / "Abt.csv"),
                "Buy.csv": _sha256_file(root / "Buy.csv"),
                "abt_buy_perfectMapping.csv": _sha256_file(root / "abt_buy_perfectMapping.csv"),
            },
            "result_pins": result["pins"],
            "blocking": result["blocking"],
        },
    )
    _write(bundle, args.output)
    print(
        "raw_counts: "
        f"candidates={bundle.candidate_pairs} auto_matches={bundle.auto_match_count} "
        f"reviews={bundle.review_count} true_pairs={bundle.true_pair_count} "
        f"blocking_true_pairs={bundle.blocking_true_pair_count} "
        f"true_positives={bundle.true_positive_count} "
        f"false_positives={bundle.false_positive_count} "
        f"reviewed_true_pairs={bundle.reviewed_true_pair_count}"
    )
    return 0


def _splink_dblp_acm_settings():
    """Caller-owned bibliographic configuration with bounded title-prefix blocks."""
    import splink.comparison_library as cl
    from splink import SettingsCreator, block_on

    return SettingsCreator(
        link_type="link_only",
        comparisons=[
            cl.NameComparison("title").configure(term_frequency_adjustments=True),
            cl.NameComparison("authors").configure(term_frequency_adjustments=True),
            cl.ExactMatch("year").configure(term_frequency_adjustments=True),
        ],
        blocking_rules_to_generate_predictions=[
            block_on("year", "substr(title,1,4)"),
            block_on("substr(title,1,8)"),
        ],
        retain_intermediate_calculation_columns=False,
    )


def _train_splink_dblp_acm(linker) -> None:
    """Train each comparison under a rule that leaves that comparison variable."""
    from splink import block_on

    deterministic = block_on("year", "authors")
    linker.training.estimate_probability_two_random_records_match([deterministic], recall=0.6)
    linker.training.estimate_u_using_random_sampling(max_pairs=2e6, seed=20260903)
    # `title` cannot learn inside a title-prefix block; these complementary
    # rules ensure title, authors, and year each vary in at least one EM run.
    for rule in (
        deterministic,
        block_on("year", "substr(title,1,4)"),
        block_on("substr(title,1,8)"),
    ):
        linker.training.estimate_parameters_using_expectation_maximisation(rule)


def run_splink_dblp_acm(args: argparse.Namespace) -> int:
    """Evaluate one explicit Splink configuration against the local complete mapping."""
    from arche.resolve import reconcile
    from arche.runtime import BenchmarkResultBundle

    root = REPO / "data" / "er_bench"
    dblp = _read_csv(root / "DBLP2.csv")
    acm = _read_csv(root / "ACM.csv")
    mapping = _read_csv(root / "DBLP-ACM_perfectMapping.csv")
    truth = {(row["idDBLP"], row["idACM"]) for row in mapping}
    fields = ("title", "authors", "year")
    left = [{"id": row["id"], **{field: row[field] for field in fields}} for row in dblp]
    right = [{"id": row["id"], **{field: row[field] for field in fields}} for row in acm]
    # With the review margin equal to the threshold, the adapter requests every
    # Splink prediction at probability >= 0.  That makes the emitted edge set
    # the evaluated candidate set, so blocking recall is not inferred from a
    # post-threshold decision list.
    result = reconcile(
        left,
        right,
        id_field="id",
        backend="splink",
        splink_settings=_splink_dblp_acm_settings(),
        splink_train=_train_splink_dblp_acm,
        threshold=args.threshold,
        review_margin=args.threshold,
    )
    edges = {(edge["a_id"], edge["b_id"]): edge for edge in result["matches"]}
    automatic = {pair for pair, edge in edges.items() if edge["decision"] == "match"}
    reviews = {pair for pair, edge in edges.items() if edge["decision"] == "review"}
    bundle = BenchmarkResultBundle(
        bundle_id=args.bundle_id,
        method_id="splink-dblp-acm-bibliographic-v1",
        resolver="splink",
        configuration_pin=_pin(result["pins"]),
        benchmark_id="leipzig-dblp-acm-v1",
        dataset_id="leipzig-dblp-acm",
        evaluator_pin="arche.splink.complete-mapping.v1",
        completed_at=datetime.now(UTC),
        truth_coverage="complete",
        candidate_pairs=len(edges),
        auto_match_count=len(automatic),
        review_count=len(reviews),
        true_pair_count=len(truth),
        blocking_true_pair_count=len(set(edges) & truth),
        true_positive_count=len(automatic & truth),
        false_positive_count=len(automatic - truth),
        reviewed_true_pair_count=len(reviews & truth),
        provenance={
            "inputs": {
                "DBLP2.csv": _sha256_file(root / "DBLP2.csv"),
                "ACM.csv": _sha256_file(root / "ACM.csv"),
                "DBLP-ACM_perfectMapping.csv": _sha256_file(root / "DBLP-ACM_perfectMapping.csv"),
            },
            "candidate_definition": "all Splink predictions emitted at probability >= 0",
            "result_pins": result["pins"],
        },
    )
    _write(bundle, args.output)
    print(
        "raw_counts: "
        f"candidates={bundle.candidate_pairs} auto_matches={bundle.auto_match_count} "
        f"reviews={bundle.review_count} true_pairs={bundle.true_pair_count} "
        f"blocking_true_pairs={bundle.blocking_true_pair_count} "
        f"true_positives={bundle.true_positive_count} "
        f"false_positives={bundle.false_positive_count} "
        f"reviewed_true_pairs={bundle.reviewed_true_pair_count}"
    )
    return 0


def _dblp_acm_inputs() -> tuple[
    Path, list[dict[str, str]], list[dict[str, str]], set[tuple[str, str]]
]:
    """Load the local complete bibliographic mapping once for comparable runners."""
    root = REPO / "data" / "er_bench"
    dblp = _read_csv(root / "DBLP2.csv")
    acm = _read_csv(root / "ACM.csv")
    mapping = _read_csv(root / "DBLP-ACM_perfectMapping.csv")
    truth = {(row["idDBLP"], row["idACM"]) for row in mapping}
    return root, dblp, acm, truth


def _dblp_acm_provenance(root: Path) -> dict[str, str]:
    return {
        "DBLP2.csv": _sha256_file(root / "DBLP2.csv"),
        "ACM.csv": _sha256_file(root / "ACM.csv"),
        "DBLP-ACM_perfectMapping.csv": _sha256_file(root / "DBLP-ACM_perfectMapping.csv"),
    }


def _print_raw_counts(bundle) -> None:
    print(
        "raw_counts: "
        f"candidates={bundle.candidate_pairs} auto_matches={bundle.auto_match_count} "
        f"reviews={bundle.review_count} true_pairs={bundle.true_pair_count} "
        f"blocking_true_pairs={bundle.blocking_true_pair_count} "
        f"true_positives={bundle.true_positive_count} "
        f"false_positives={bundle.false_positive_count} "
        f"reviewed_true_pairs={bundle.reviewed_true_pair_count}"
    )


def run_arche_dblp_acm(args: argparse.Namespace) -> int:
    """Evaluate the explicit deterministic Arche bibliographic baseline."""
    from arche.resolve import reconcile
    from arche.runtime import BenchmarkResultBundle

    root, dblp, acm, truth = _dblp_acm_inputs()
    fields = ("title", "authors", "year")
    left = [{"id": row["id"], **{field: row[field] for field in fields}} for row in dblp]
    right = [{"id": row["id"], **{field: row[field] for field in fields}} for row in acm]
    comparators = [
        {"field": "title", "kind": "name", "weight": 3.0},
        {"field": "title", "kind": "tftoken", "weight": 2.0},
        {"field": "authors", "kind": "name", "weight": 2.0},
        {"field": "year", "kind": "date", "weight": 0.5, "refutes_below": 0.99},
    ]
    result = reconcile(left, right, comparators=comparators, tf=None, id_field="id")
    edges = {(edge["a_id"], edge["b_id"]): edge for edge in result["matches"]}
    automatic = {pair for pair, edge in edges.items() if edge["decision"] == "match"}
    reviews = {pair for pair, edge in edges.items() if edge["decision"] == "review"}
    bundle = BenchmarkResultBundle(
        bundle_id=args.bundle_id,
        method_id="arche-dblp-acm-bibliographic-v1",
        resolver="arche",
        configuration_pin=_pin(result["pins"]),
        benchmark_id="leipzig-dblp-acm-v1",
        dataset_id="leipzig-dblp-acm",
        evaluator_pin="arche.crosswalk.complete-mapping.v1",
        completed_at=datetime.now(UTC),
        truth_coverage="complete",
        candidate_pairs=result["blocking"]["candidate_pairs"],
        auto_match_count=len(automatic),
        review_count=len(reviews),
        true_pair_count=len(truth),
        blocking_true_pair_count=len(set(edges) & truth),
        true_positive_count=len(automatic & truth),
        false_positive_count=len(automatic - truth),
        reviewed_true_pair_count=len(reviews & truth),
        provenance={
            "inputs": _dblp_acm_provenance(root),
            "result_pins": result["pins"],
            "blocking": result["blocking"],
        },
    )
    _write(bundle, args.output)
    _print_raw_counts(bundle)
    return 0


def run_recordlinkage_dblp_acm(args: argparse.Namespace) -> int:
    """Evaluate a label-free RecordLinkage ECM baseline on the same mapping.

    RecordLinkage is intentionally an ephemeral benchmark dependency, rather
    than an Arche runtime dependency.  The ECM classifier is its unsupervised
    Fellegi--Sunter-style option, so the benchmark's perfect mapping is used
    only for evaluation and never for fitting.
    """
    try:
        import pandas as pd
        import recordlinkage
    except ImportError as error:
        raise SystemExit(
            "recordlinkage benchmark dependency missing; run with "
            "`uv run --no-sync --with recordlinkage python data/scripts/"
            "benchmark_vnext_artifacts.py recordlinkage-dblp-acm ...`"
        ) from error

    from arche.runtime import BenchmarkResultBundle

    root, dblp, acm, truth = _dblp_acm_inputs()
    left = pd.DataFrame(dblp).set_index("id")
    right = pd.DataFrame(acm).set_index("id")
    indexer = recordlinkage.Index()
    indexer.block(left_on="year", right_on="year")
    candidate_index = indexer.index(left, right)

    compare = recordlinkage.Compare()
    compare.string("title", "title", method="jarowinkler", threshold=0.85, label="title")
    compare.string("authors", "authors", method="jarowinkler", threshold=0.85, label="authors")
    features = compare.compute(candidate_index, left, right)
    classifier = recordlinkage.ECMClassifier(binarize=0.5)
    matches = classifier.fit_predict(features)
    candidates = {(str(a_id), str(b_id)) for a_id, b_id in candidate_index}
    automatic = {(str(a_id), str(b_id)) for a_id, b_id in matches}
    configuration = {
        "library": "recordlinkage",
        "library_version": recordlinkage.__version__,
        "index": {"kind": "block", "left_on": "year", "right_on": "year"},
        "comparisons": [
            {"field": "title", "kind": "jarowinkler", "threshold": 0.85},
            {"field": "authors", "kind": "jarowinkler", "threshold": 0.85},
        ],
        "classifier": {"kind": "ECMClassifier", "binarize": 0.5},
        "training": "unsupervised; complete mapping excluded from fitting",
    }
    bundle = BenchmarkResultBundle(
        bundle_id=args.bundle_id,
        method_id="recordlinkage-dblp-acm-ecm-v1",
        resolver="recordlinkage",
        configuration_pin=_pin(configuration),
        benchmark_id="leipzig-dblp-acm-v1",
        dataset_id="leipzig-dblp-acm",
        evaluator_pin="recordlinkage.ecm.complete-mapping.v1",
        completed_at=datetime.now(UTC),
        truth_coverage="complete",
        candidate_pairs=len(candidates),
        auto_match_count=len(automatic),
        review_count=0,
        true_pair_count=len(truth),
        blocking_true_pair_count=len(candidates & truth),
        true_positive_count=len(automatic & truth),
        false_positive_count=len(automatic - truth),
        reviewed_true_pair_count=0,
        provenance={
            "inputs": _dblp_acm_provenance(root),
            "configuration": configuration,
            "candidate_definition": "RecordLinkage exact year block",
        },
    )
    _write(bundle, args.output)
    _print_raw_counts(bundle)
    return 0


def run_review_pack(args: argparse.Namespace) -> int:
    from arche.runtime import BenchmarkResultBundle

    pack_dir = args.pack.resolve()
    manifest_path = pack_dir / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"missing review-pack manifest: {manifest_path}")
    csv_paths = [pack_dir / name for name in ("pack.csv", "adjudication_pack.csv")]
    pack_path = next((path for path in csv_paths if path.is_file()), None)
    if pack_path is None:
        raise SystemExit(f"missing pack.csv or adjudication_pack.csv in {pack_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = _read_csv(pack_path)
    decisions = Counter(row.get("decision", "") for row in rows)
    outcomes = Counter(
        row.get("review_outcome", "") for row in rows if row.get("review_outcome", "")
    )
    truth_coverage = "unlabelled" if not outcomes else "partial"
    bundle = BenchmarkResultBundle(
        bundle_id=args.bundle_id,
        method_id=f"review-pack:{pack_dir.name}",
        resolver="arche.review-pack",
        configuration_pin=_pin(manifest.get("pins", {})),
        benchmark_id=f"review-pack-{pack_dir.name}-v1",
        dataset_id=f"review-pack-{pack_dir.name}",
        evaluator_pin=str(manifest.get("schema", "arche.review-pack.v1")),
        completed_at=datetime.now(UTC),
        truth_coverage=truth_coverage,
        candidate_pairs=len(rows),
        auto_match_count=decisions["match"],
        review_count=decisions["review"],
        provenance={
            "manifest_sha256": _sha256_file(manifest_path),
            "pack_sha256": _sha256_file(pack_path),
            "decision_counts": dict(decisions),
            "review_outcome_counts": dict(outcomes),
            "truth_note": (
                "review packs contain selected candidate decisions, not a complete mapping of "
                "matches and non-matches; they cannot qualify a method"
            ),
        },
    )
    _write(bundle, args.output)
    print(
        "raw_counts: "
        f"candidates={bundle.candidate_pairs} auto_matches={bundle.auto_match_count} "
        f"reviews={bundle.review_count} labelled_outcomes={sum(outcomes.values())}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    abt_buy = commands.add_parser(
        "abt-buy", help="evaluate the local complete-mapping product benchmark"
    )
    abt_buy.add_argument("--output", type=Path, required=True)
    abt_buy.add_argument("--bundle-id", required=True)
    abt_buy.set_defaults(func=run_abt_buy)

    splink_dblp_acm = commands.add_parser(
        "splink-dblp-acm", help="evaluate an explicit Splink configuration on DBLP-ACM"
    )
    splink_dblp_acm.add_argument("--output", type=Path, required=True)
    splink_dblp_acm.add_argument("--bundle-id", required=True)
    splink_dblp_acm.add_argument("--threshold", type=float, default=0.9)
    splink_dblp_acm.set_defaults(func=run_splink_dblp_acm)

    arche_dblp_acm = commands.add_parser(
        "arche-dblp-acm", help="evaluate the deterministic Arche configuration on DBLP-ACM"
    )
    arche_dblp_acm.add_argument("--output", type=Path, required=True)
    arche_dblp_acm.add_argument("--bundle-id", required=True)
    arche_dblp_acm.set_defaults(func=run_arche_dblp_acm)

    recordlinkage_dblp_acm = commands.add_parser(
        "recordlinkage-dblp-acm",
        help="evaluate the label-free RecordLinkage ECM configuration on DBLP-ACM",
    )
    recordlinkage_dblp_acm.add_argument("--output", type=Path, required=True)
    recordlinkage_dblp_acm.add_argument("--bundle-id", required=True)
    recordlinkage_dblp_acm.set_defaults(func=run_recordlinkage_dblp_acm)

    review_pack = commands.add_parser("review-pack", help="record a local review-pack evaluation")
    review_pack.add_argument("--pack", type=Path, required=True)
    review_pack.add_argument("--output", type=Path, required=True)
    review_pack.add_argument("--bundle-id", required=True)
    review_pack.set_defaults(func=run_review_pack)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
