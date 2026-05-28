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

"""CLI entry point for the arche SDK.

Usage:
    arche resolve "Janet Okafor, NIN 12345678901"
    arche resolve --input file.txt
    arche resolve --input records.csv --output resolved.json
    arche version
"""

from __future__ import annotations

import argparse
import json
import sys


def main() -> None:
    """CLI entry point: ``arche resolve --input file.txt``."""
    parser = argparse.ArgumentParser(
        prog="arche",
        description=(
            "arche — the identity workflow framework. "
            "Extract entities, resolve identities, detect PII."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- resolve command ---
    resolve_parser = subparsers.add_parser(
        "resolve",
        help="Run the full pipeline on text or a file.",
    )
    resolve_parser.add_argument(
        "text",
        nargs="?",
        default=None,
        help="Text to resolve (inline). Omit if using --input.",
    )
    resolve_parser.add_argument(
        "--input", "-i",
        dest="input_file",
        default=None,
        help="Path to input file (.txt or .csv).",
    )
    resolve_parser.add_argument(
        "--output", "-o",
        dest="output_file",
        default=None,
        help="Path to output file (.json). Prints to stdout if omitted.",
    )
    resolve_parser.add_argument(
        "--backend",
        default="auto",
        choices=["auto", "gliner", "regex"],
        help="Entity extraction backend (default: auto).",
    )
    resolve_parser.add_argument(
        "--no-resolve",
        action="store_true",
        help="Skip identity resolution.",
    )
    resolve_parser.add_argument(
        "--no-pii",
        action="store_true",
        help="Skip PII detection.",
    )
    resolve_parser.add_argument(
        "--no-signals",
        action="store_true",
        help="Skip signal detection.",
    )
    resolve_parser.add_argument(
        "--no-locations",
        action="store_true",
        help="Skip location enrichment.",
    )
    resolve_parser.add_argument(
        "--graph",
        action="store_true",
        help="Build knowledge graph.",
    )
    resolve_parser.add_argument(
        "--redact",
        action="store_true",
        help="Redact PII in output text.",
    )
    resolve_parser.add_argument(
        "--redact-strategy",
        default="mask",
        choices=["mask", "hash", "remove", "placeholder"],
        help="PII redaction strategy (default: mask).",
    )

    # --- extract command ---
    extract_parser = subparsers.add_parser(
        "extract",
        help="Extract text from a file and run identity extraction.",
    )
    extract_parser.add_argument(
        "file",
        help="Path to the file to extract from (PDF, DOCX, TXT, CSV, JSON, images).",
    )
    extract_parser.add_argument(
        "--format", "-f",
        dest="output_format",
        default="table",
        choices=["table", "json"],
        help="Output format (default: table).",
    )
    extract_parser.add_argument(
        "--backend",
        default="auto",
        choices=["auto", "gliner", "regex"],
        help="Entity extraction backend (default: auto).",
    )

    # --- review command ---
    review_parser = subparsers.add_parser(
        "review",
        help="Manage the human review queue for identity match candidates.",
    )
    review_subparsers = review_parser.add_subparsers(
        dest="review_command",
        help="Review queue actions",
    )

    # review pending
    review_subparsers.add_parser(
        "pending",
        help="Show pending review candidates.",
    )

    # review approve <id>
    approve_parser = review_subparsers.add_parser(
        "approve",
        help="Approve a match candidate.",
    )
    approve_parser.add_argument("id", help="Candidate UUID to approve.")
    approve_parser.add_argument(
        "--notes", "-n", default="", help="Reviewer notes.",
    )
    approve_parser.add_argument(
        "--reviewer", "-r", default="cli", help="Reviewer identifier (default: cli).",
    )

    # review reject <id>
    reject_parser = review_subparsers.add_parser(
        "reject",
        help="Reject a match candidate.",
    )
    reject_parser.add_argument("id", help="Candidate UUID to reject.")
    reject_parser.add_argument(
        "--notes", "-n", default="", help="Reviewer notes.",
    )
    reject_parser.add_argument(
        "--reviewer", "-r", default="cli", help="Reviewer identifier (default: cli).",
    )

    # review escalate <id>
    escalate_parser = review_subparsers.add_parser(
        "escalate",
        help="Escalate a match candidate for further review.",
    )
    escalate_parser.add_argument("id", help="Candidate UUID to escalate.")
    escalate_parser.add_argument(
        "--notes", "-n", default="", help="Reviewer notes.",
    )
    escalate_parser.add_argument(
        "--reviewer", "-r", default="cli", help="Reviewer identifier (default: cli).",
    )

    # review stats
    review_subparsers.add_parser(
        "stats",
        help="Show review queue statistics.",
    )

    # review export <path>
    export_parser = review_subparsers.add_parser(
        "export",
        help="Export review decisions to a JSON file.",
    )
    export_parser.add_argument("path", help="Output file path.")

    # review import <path>
    import_parser = review_subparsers.add_parser(
        "import",
        help="Import review decisions from a JSON file.",
    )
    import_parser.add_argument("path", help="Input file path.")

    # --- review command options ---
    review_parser.add_argument(
        "--queue-file",
        default=".arche-review-queue.json",
        help="Path to the review queue persistence file (default: .arche-review-queue.json).",
    )

    # --- version command ---
    subparsers.add_parser("version", help="Print the SDK version.")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "version":
        from ._version import __version__

        print(f"arche {__version__}")
        sys.exit(0)

    if args.command == "extract":
        _handle_extract(args)

    if args.command == "review":
        _handle_review(args)

    if args.command == "resolve":
        _handle_resolve(args)


def _handle_extract(args: argparse.Namespace) -> None:
    """Handle the ``extract`` CLI command — ingest a file and extract identity evidence."""
    from .ensemble import detect_sensitive_spans, extract_identity_evidence
    from .workflow._ingest import extract_text

    # Step 1: Extract text from the file
    try:
        text = extract_text(args.file)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except ImportError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if not text.strip():
        print("Warning: File is empty or contains no extractable text.", file=sys.stderr)
        sys.exit(0)

    # Step 2: Extract identity evidence
    evidence = extract_identity_evidence(text, backend=args.backend)
    pii_spans = detect_sensitive_spans(text)
    signals: list = []  # signal detection removed in v0.2.0a3 with arche-adapters

    if args.output_format == "json":
        output = {
            "file": args.file,
            "text_length": len(text),
            "entities": [
                {"label": e.label, "text": e.text, "confidence": e.confidence}
                for e in evidence
            ],
            "pii": [
                {"label": s.label, "text": s.text, "start": s.start, "end": s.end}
                for s in pii_spans
            ],
            "signals": [
                {"signal": s.signal_type, "severity": s.severity, "description": s.description}
                for s in signals
            ],
        }
        print(json.dumps(output, indent=2, default=str))
    else:
        # Table format
        print(f"File: {args.file} ({len(text):,} chars extracted)\n")

        if evidence:
            print("ENTITIES")
            print("-" * 60)
            print(f"{'Label':<20} {'Text':<30} {'Conf':>6}")
            print("-" * 60)
            for e in evidence:
                val = e.text if len(e.text) <= 30 else e.text[:27] + "..."
                print(f"{e.label:<20} {val:<30} {e.confidence:>5.0%}")
        else:
            print("No entities found.")

        if pii_spans:
            print(f"\nPII DETECTIONS ({len(pii_spans)})")
            print("-" * 60)
            for s in pii_spans:
                val = s.text if len(s.text) <= 30 else s.text[:27] + "..."
                print(f"  {s.label:<20} {val}")

        if signals:
            print(f"\nSIGNALS ({len(signals)})")
            print("-" * 60)
            for s in signals:
                print(f"  [{s.severity}] {s.signal_type}: {s.description}")


def _handle_review(args: argparse.Namespace) -> None:
    """Handle the ``review`` CLI command — manage the human review queue."""
    from .review import ReviewQueue

    if args.review_command is None:
        print(
            "Error: No review action specified. Use: "
            "pending, approve, reject, escalate, stats, export, import.",
            file=sys.stderr,
        )
        sys.exit(1)

    queue = ReviewQueue(persistence_path=args.queue_file)

    if args.review_command == "pending":
        candidates = queue.pending()
        if not candidates:
            print("No pending review candidates.")
            sys.exit(0)
        print(f"PENDING REVIEW CANDIDATES ({len(candidates)})")
        print("-" * 80)
        print(f"{'ID':<38} {'Confidence':>10}  {'Record A':<20} {'Record B':<20}")
        print("-" * 80)
        for c in candidates:
            name_a = c.record_a.get("text", c.record_a.get("canonical_name", "?"))
            name_b = c.record_b.get("text", c.record_b.get("canonical_name", "?"))
            if len(name_a) > 20:
                name_a = name_a[:17] + "..."
            if len(name_b) > 20:
                name_b = name_b[:17] + "..."
            print(f"{c.id:<38} {c.confidence:>9.1%}  {name_a:<20} {name_b:<20}")
        print("\nUse 'arche review approve <id>' or 'arche review reject <id>' to review.")

    elif args.review_command == "approve":
        try:
            candidate = queue.approve(args.id, reviewer=args.reviewer, notes=args.notes)
            print(f"Approved: {candidate.id}")
        except (KeyError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

    elif args.review_command == "reject":
        try:
            candidate = queue.reject(args.id, reviewer=args.reviewer, notes=args.notes)
            print(f"Rejected: {candidate.id}")
        except (KeyError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

    elif args.review_command == "escalate":
        try:
            candidate = queue.escalate(args.id, reviewer=args.reviewer, notes=args.notes)
            print(f"Escalated: {candidate.id}")
        except (KeyError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

    elif args.review_command == "stats":
        s = queue.stats()
        print("REVIEW QUEUE STATISTICS")
        print("-" * 40)
        for key, value in s.items():
            print(f"  {key:<20} {value:>6}")

    elif args.review_command == "export":
        try:
            count = queue.export_decisions(args.path)
            print(f"Exported {count} decisions to {args.path}")
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

    elif args.review_command == "import":
        try:
            count = queue.import_decisions(args.path)
            print(f"Imported {count} decisions from {args.path}")
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)


def _handle_resolve(args: argparse.Namespace) -> None:
    """Handle the ``resolve`` CLI command."""
    from .pipeline import ArchePipeline

    # Collect input texts
    texts = _collect_texts(args)
    if not texts:
        print("Error: No input text provided. Use positional text or --input.", file=sys.stderr)
        sys.exit(1)

    # Configure pipeline
    pipeline = ArchePipeline(
        backend=args.backend,
        pii_redact=args.redact,
        pii_redact_strategy=args.redact_strategy,
        resolve_identities=not args.no_resolve,
        detect_pii_flag=not args.no_pii,
        detect_signals_flag=not args.no_signals,
        enrich_locations=not args.no_locations,
        build_knowledge_graph=args.graph,
    )

    # Run pipeline
    if len(texts) == 1:
        result = pipeline.run(texts[0])
        output = result.to_dict()
    else:
        results = pipeline.run_batch(texts)
        output = [r.to_dict() for r in results]

    # Write output
    json_str = json.dumps(output, indent=2, default=str)
    if args.output_file:
        with open(args.output_file, "w", encoding="utf-8") as f:
            f.write(json_str)
        print(f"Results written to {args.output_file}", file=sys.stderr)
    else:
        print(json_str)


def _collect_texts(args: argparse.Namespace) -> list[str]:
    """Collect input texts from CLI arguments or file."""
    texts: list[str] = []

    if args.text:
        texts.append(args.text)
    elif args.input_file:
        path = args.input_file
        if path.endswith(".csv"):
            texts.extend(_read_csv(path))
        else:
            # Plain text file — treat as a single document
            with open(path, encoding="utf-8") as f:
                texts.append(f.read())
    else:
        # Try reading from stdin if not a TTY
        if not sys.stdin.isatty():
            texts.append(sys.stdin.read())

    return texts


def _read_csv(path: str) -> list[str]:
    """Read a CSV file and return rows as text for batch processing.

    Concatenates all columns of each row into a single text string.
    """
    import csv

    texts: list[str] = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Join all values into a single text
            text = " | ".join(f"{k}: {v}" for k, v in row.items() if v)
            if text.strip():
                texts.append(text)
    return texts


if __name__ == "__main__":
    main()
