# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The ``arche`` command — v0.2-aware CLI, returning with one subcommand.

``arche compare`` takes two record files (CSV or JSON) and emits the
shareable artifact: a masked-by-default HTML report plus a
machine-readable ``decisions.json`` sidecar. ``arche compare --demo``
needs no data at all — it resolves a messy artist royalty statement
against a catalog built from the shipped equivalence pack, so anyone
gets an artifact thirty seconds after ``pip install``.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import UTC, datetime
from pathlib import Path


def _load_records(path: Path, prefix: str, id_field: str = "id") -> list[dict]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise SystemExit(f"{path}: JSON input must be a list of objects")
        records = [dict(r) for r in data]
    elif path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as fh:
            records = [dict(r) for r in csv.DictReader(fh)]
    else:
        raise SystemExit(f"{path}: unsupported input (use .csv or .json)")
    for i, rec in enumerate(records):
        if not rec.get(id_field):
            rec[id_field] = f"{prefix}-{i}"
    return records


def _demo_records() -> tuple[list[dict], list[dict], str]:
    """A royalty statement vs an alias-expanded catalog, from the shipped pack."""
    from arche.resolve import artist_aliases

    statement = [
        {"id": f"ln-{i:02d}", "name": n}
        for i, n in enumerate(
            ["WIZKID", "Ayodeji Balogun", "Damini Ogulu", "Divine Ikubor",
             "Temilade Openiyi", "Tyla Seethal", "Aubrey Graham", "Ed Sheeran",
             "Selena Gomez", "Kiss Daniel"],
            start=1,
        )
    ]
    # Opaque catalog ids on purpose: even in a public-figure demo, the masked
    # report should model the right pattern — ids are surrogate keys, values
    # live in fields (and get masked).
    catalog = [
        {"id": f"c-{i:04d}", "artist": artist, "name": form}
        for i, (artist, form) in enumerate(
            (artist, form)
            for artist, forms in sorted(artist_aliases().items())
            for form in (artist, *forms)
        )
    ]
    return statement, catalog, "artist"


def _cmd_compare(args: argparse.Namespace) -> int:
    from arche import resolve
    from arche.report import crosswalk_report

    decl = None
    if args.schema:
        from arche.declare import Declaration, DeclarationError

        try:
            decl = Declaration.from_yaml(args.schema)
        except DeclarationError as exc:
            raise SystemExit(f"arche compare: {exc}") from exc

    if args.demo:
        records_a, records_b, entity = _demo_records()
        title = "arche compare — demo (artist royalty statement vs catalog)"
    else:
        if not (args.a and args.b):
            raise SystemExit("arche compare: provide two input files, or --demo")
        id_field = decl.id_field if decl is not None else "id"
        records_a = _load_records(Path(args.a), "a", id_field)
        records_b = _load_records(Path(args.b), "b", id_field)
        entity = None if decl is not None else args.entity
        # Filenames often contain names/identifiers; they only appear in the
        # title of an explicitly revealed working copy.
        title = (
            f"arche compare — {Path(args.a).name} vs {Path(args.b).name}"
            if args.reveal else "arche compare"
        )

    kwargs: dict = {}
    if args.block == "none":
        kwargs["block"] = None
    if decl is not None:
        out = resolve.crosswalk(records_a, records_b, decl=decl, **kwargs)
        entity = decl.pin()
    else:
        out = resolve.crosswalk(records_a, records_b, entity=entity, **kwargs)

    matches = [m for m in out["matches"] if m["decision"] == "match"]
    review = [m for m in out["matches"] if m["decision"] != "match"]

    out_path = Path(args.out)
    json_path = Path(args.json) if args.json else out_path.with_suffix(".json")
    sidecar = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "entity": entity,
        "inputs": {"a": args.a or "demo:statement", "b": args.b or "demo:catalog",
                   "count_a": len(records_a), "count_b": len(records_b)},
        "result": out,
    }
    try:
        report_html = crosswalk_report(out, records_a, records_b,
                                       reveal=args.reveal, title=title,
                                       entity=entity,
                                       brand_color=args.brand_color,
                                       decl=decl)
    except ValueError as exc:  # sensitive-looking ids in masked mode, bad color
        raise SystemExit(f"arche compare: {exc}") from exc
    json_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    out_path.write_text(report_html, encoding="utf-8")

    print(f"compared {len(records_a):,} x {len(records_b):,} records "
          f"(entity pack: {entity})")
    print(f"  matched: {len(matches):,}   review: {len(review):,}")
    print(f"  report:    {out_path}   "
          f"[{'REVEALED' if args.reveal else 'masked — safe to share'}]")
    print(f"  decisions: {json_path}")
    if not args.reveal:
        print("  (values masked by default; add --reveal for a working copy)")
    return 0


def _cmd_schema_validate(args: argparse.Namespace) -> int:
    from arche.declare import Declaration, DeclarationError

    try:
        decl = Declaration.from_yaml(args.decl)
    except DeclarationError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    print(f"valid: {decl.pin()}")
    for w in decl.load_warnings:
        print(f"  warning: {w}")
    return 0


def _cmd_schema_gen(args: argparse.Namespace) -> int:
    from arche.declare import Declaration, DeclarationError

    try:
        decl = Declaration.from_yaml(args.decl)
    except DeclarationError as exc:
        raise SystemExit(f"arche schema gen: {exc}") from exc
    if args.format == "comparators":
        print(json.dumps(decl.comparators(), indent=2))
    else:
        print(json.dumps(decl.tool_def(args.format), indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="arche",
        description="arche — know the real-world entity, prove the decision.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    cmp_p = sub.add_parser(
        "compare",
        help="link two record files and emit a shareable HTML report + JSON",
    )
    cmp_p.add_argument("a", nargs="?", help="left file (.csv or .json)")
    cmp_p.add_argument("b", nargs="?", help="right file (.csv or .json)")
    cmp_p.add_argument("--entity", default="person",
                       help="entity pack: person, place, artist (default person)")
    cmp_p.add_argument("--schema", default=None, metavar="DECL.YAML",
                       help="a declaration file: YOUR fields + role "
                            "annotations (overrides --entity)")
    cmp_p.add_argument("--out", default="report.html",
                       help="HTML report path (default report.html)")
    cmp_p.add_argument("--json", default=None,
                       help="decisions sidecar path (default <out>.json)")
    cmp_p.add_argument("--reveal", action="store_true",
                       help="show record values in the report (default: masked)")
    cmp_p.add_argument("--brand-color", default=None, metavar="#HEX",
                       help="theme the report accent with your color "
                            "(hex only, e.g. #0f766e)")
    cmp_p.add_argument("--block", choices=["auto", "none"], default="auto",
                       help="candidate blocking (default auto; none = all pairs)")
    cmp_p.add_argument("--demo", action="store_true",
                       help="run on the built-in artist demo, no data needed")
    cmp_p.set_defaults(func=_cmd_compare)

    sch_p = sub.add_parser(
        "schema",
        help="validate a declaration or generate LLM tool-definitions from it",
    )
    sch_sub = sch_p.add_subparsers(dest="schema_command", required=True)
    val_p = sch_sub.add_parser("validate", help="validate a declaration file")
    val_p.add_argument("decl", help="path to the declaration YAML")
    val_p.set_defaults(func=_cmd_schema_validate)
    gen_p = sch_sub.add_parser(
        "gen", help="generate an extraction schema / tool-def / comparator pack"
    )
    gen_p.add_argument("decl", help="path to the declaration YAML")
    gen_p.add_argument("--format", default="json-schema",
                       choices=["json-schema", "anthropic", "openai",
                                "comparators"])
    gen_p.set_defaults(func=_cmd_schema_gen)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
