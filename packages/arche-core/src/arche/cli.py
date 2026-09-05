# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The ``arche`` command — a small, discoverable front door.

``arche compare`` takes two record files (CSV or JSON) and emits the
shareable artifact: a masked-by-default HTML report plus a
machine-readable ``decisions.json`` sidecar. ``arche compare --demo``
needs no data at all — it resolves a messy artist royalty statement
against a catalog built from the shipped equivalence pack, so anyone
gets an artifact thirty seconds after ``pip install``.

``arche version`` reports the package's single-sourced release version,
``arche list`` exposes the supported command surface, and ``arche datasets``
describes benchmark and review artifacts without reading their record values.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from arche._version import __version__

_COMMANDS = (
    ("cases", "pairs a ledger still holds at review, and what would settle each"),
    ("compare", "are these the same? two record files, or two texts with --text"),
    ("datasets", "list benchmark and review datasets with their truth coverage"),
    ("decision", "a recorded decision, by its id"),
    ("entities", "what a ledger's decisions have linked together"),
    ("explain", "supporting, refuting and missing fields of a recorded decision"),
    ("list", "list supported CLI commands"),
    ("observe", "add evidence about a record and decide its open pairs again"),
    ("replay", "make a recorded decision again and report what moved"),
    ("resolve-documents", "extract document fields, compare explicit candidates, and open cases"),
    ("review", "validate, apply, share, or verify review-pack outcomes"),
    ("schema", "validate declarations or generate extraction/tool schemas"),
    ("version", "show the single-sourced arche-core version"),
)

_DATASETS = (
    {
        "id": "leipzig-abt-buy",
        "entity_type": "product_electronics",
        "truth_coverage": "complete",
        "purpose": "product linkage and false-merge measurement",
        "repository_path": "data/er_bench/products",
    },
    {
        "id": "leipzig-dblp-acm",
        "entity_type": "bibliographic_record",
        "truth_coverage": "complete",
        "purpose": "bibliographic linkage and false-merge measurement",
        "repository_path": "data/er_bench",
    },
    {
        "id": "nigeria-facilities-review-pack",
        "entity_type": "health_facility",
        "truth_coverage": "unlabelled",
        "purpose": "human adjudication; not eligible for method qualification",
        "repository_path": "data/review_packs/nigeria_facilities_2026-08-19",
    },
    {
        "id": "parrish-person-review-pack",
        "entity_type": "person",
        "truth_coverage": "unlabelled",
        "purpose": "human adjudication; not eligible for method qualification",
        "repository_path": "data/review_packs/parrish_person",
    },
)


def _repository_root() -> Path | None:
    """Return the source checkout root when this command runs from one."""
    root = Path(__file__).resolve().parents[4]
    return root if (root / "data").is_dir() else None


def _cmd_version(args: argparse.Namespace) -> int:
    """Show the single value Hatch uses when building arche-core."""
    payload = {"package": "arche-core", "version": __version__, "source": "arche._version"}
    print(json.dumps(payload, indent=2) if args.json else f"arche {__version__}")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    """List the small supported CLI surface rather than making users guess."""
    payload = {
        "package": "arche-core",
        "version": __version__,
        "commands": [
            {"command": command, "description": description} for command, description in _COMMANDS
        ],
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"arche {__version__}")
        for command, description in _COMMANDS:
            print(f"  {command:<10} {description}")
    return 0


def _cmd_datasets(args: argparse.Namespace) -> int:
    """Describe data truth coverage without opening any record payloads."""
    root = _repository_root()
    datasets = [
        {**dataset, "available": root is not None and (root / dataset["repository_path"]).exists()}
        for dataset in _DATASETS
    ]
    if args.available:
        datasets = [dataset for dataset in datasets if dataset["available"]]
    if args.json:
        print(json.dumps({"datasets": datasets}, indent=2))
    else:
        for dataset in datasets:
            availability = "available" if dataset["available"] else "not bundled"
            print(
                f"{dataset['id']:<34} {dataset['truth_coverage']:<11} "
                f"{availability:<11} {dataset['purpose']}"
            )
    return 0


def _load_records(
    path: Path,
    prefix: str,
    id_field: str = "id",
    *,
    require_explicit_id: bool = False,
) -> list[dict]:
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
            if require_explicit_id and not rec.get("entity_id"):
                raise SystemExit(f"{path}: candidate {i + 1} needs an 'entity_id' or 'id'")
            rec[id_field] = f"{prefix}-{i}"
    return records


def _ledger(store_path: str | None):
    """Open the caller-selected local ledger file, or the one ``ARCHE_LEDGER`` names."""
    import os

    from arche.ledger import attach

    path = store_path or os.environ.get("ARCHE_LEDGER")
    if not path:
        raise SystemExit(
            "arche: no ledger given. Pass --store FILE.duckdb or set ARCHE_LEDGER."
        )
    return attach(f"duckdb:///{Path(path)}")


def _mask(value: object, keep: int = 4) -> str:
    """Show the first characters of a value and star the rest.

    Enough to tell two values apart on a screen, not enough to copy one out.
    ``--reveal`` is the way to see a value; there is no masked mode that leaks
    by accident.
    """
    text = str(value)
    if len(text) <= keep:
        return "*" * max(len(text), 3)
    return text[:keep] + "*" * max(len(text) - keep, 3)


def _shown(value: object, reveal: bool) -> object:
    if reveal:
        return value
    if isinstance(value, dict):
        return {k: _shown(v, reveal) for k, v in value.items()}
    if isinstance(value, list):
        return [_shown(v, reveal) for v in value]
    return _mask(value)


def _emit(payload: dict, lines: list[str], args: argparse.Namespace) -> int:
    """JSON when asked (``--json`` or ``--out``), the readable lines otherwise."""
    if getattr(args, "json", False) or getattr(args, "out", None):
        _write_json_output(payload, getattr(args, "out", None))
    else:
        print("\n".join(lines))
    return 0


def _decision_payload(decision, reveal: bool) -> dict:
    return {
        "decision_id": decision.decision_id,
        "verb": decision.verb,
        "identity": decision.identity,
        "action": decision.action,
        "score": decision.score,
        "explanation": decision.explanation,
        "factors": decision.factors,
        "pins": decision.pins,
        "call": decision.call,
        "recorded_at": decision.recorded_at.isoformat(timespec="seconds"),
        "supersedes": decision.supersedes,
        "superseded_by": decision.superseded_by,
        "record_a": decision.record_a,
        "record_b": decision.record_b,
    }


def _record_payload(record, reveal: bool) -> dict:
    return {
        "record_id": record.record_id,
        "caller_id": record.caller_id,
        "entity_type": record.entity_type,
        "source": record.source,
        "attributes": _shown(record.attributes, reveal),
        "text": _shown(record.text, reveal) if record.text is not None else None,
    }


def _cmd_decision(args: argparse.Namespace) -> int:
    ledger = _ledger(args.store)
    try:
        decision = ledger.decision(args.decision_id)
    except KeyError as exc:
        raise SystemExit(f"arche decision: {exc.args[0]}") from exc
    a, b = ledger.record(decision.record_a), ledger.record(decision.record_b)
    payload = {**_decision_payload(decision, args.reveal),
               "records": [_record_payload(a, args.reveal), _record_payload(b, args.reveal)]}
    lines = [
        f"{decision.identity}  {decision.action}  ({decision.verb}, {decision.score:.4f})",
        f"  {decision.explanation}",
        f"  factors   {decision.factors}",
        f"  pinned    {decision.pins.get('engine')}  thresholds "
        f"{decision.pins.get('thresholds', decision.pins.get('threshold'))}",
        f"  recorded  {decision.recorded_at.isoformat(timespec='seconds')}",
        f"  a         {a.caller_id or a.record_id[:24]}  "
        f"{_shown(a.text if a.text is not None else a.attributes, args.reveal)}",
        f"  b         {b.caller_id or b.record_id[:24]}  "
        f"{_shown(b.text if b.text is not None else b.attributes, args.reveal)}",
    ]
    if decision.supersedes:
        lines.append(f"  supersedes    {decision.supersedes}")
    if decision.superseded_by:
        lines.append(f"  superseded by {decision.superseded_by}")
    if not args.reveal:
        lines.append("  (values masked; add --reveal to see them)")
    return _emit(payload, lines, args)


def _cmd_explain(args: argparse.Namespace) -> int:
    ledger = _ledger(args.store)
    try:
        why = ledger.explain(args.decision_id)
    except KeyError as exc:
        raise SystemExit(f"arche explain: {exc.args[0]}") from exc
    payload = {**why, "shared": _shown(why["shared"], args.reveal), "decision_id": args.decision_id}
    lines = [
        f"{why['identity']}  {why['action']}  - {why['explanation']}",
        f"  supporting  {why['supporting']}",
        f"  refuting    {why['refuting']}",
        f"  missing     {why['missing']}",
        f"  shared      {_shown(why['shared'], args.reveal)}",
    ]
    return _emit(payload, lines, args)


def _cmd_replay(args: argparse.Namespace) -> int:
    ledger = _ledger(args.store)
    try:
        replay = ledger.replay(args.decision_id)
    except (KeyError, ValueError) as exc:
        raise SystemExit(f"arche replay: {exc.args[0]}") from exc
    payload = {
        "decision_id": replay.decision_id,
        "reproduced": replay.reproduced,
        "then": {"identity": replay.then.identity, "action": replay.then.action,
                 "score": replay.then.score, "engine": replay.then.pins.get("engine")},
        "now": {"identity": replay.now["identity"], "action": replay.now["action"],
                "score": replay.now["score"], "engine": replay.now["pins"].get("engine"),
                "decision_id": replay.now["decision_id"]},
        "changed": replay.changed,
    }
    lines = [f"reproduced: {replay.reproduced}"]
    if replay.reproduced:
        lines.append(f"  {replay.then.identity} {replay.then.action} — "
                     "same decision_id, byte for byte")
    else:
        lines.append(f"  then {replay.then.identity} {replay.then.action}  ->  now "
                     f"{replay.now['identity']} {replay.now['action']}")
        for key, change in replay.changed.items():
            lines.append(f"  {key}: {change['then']}  ->  {change['now']}")
    return _emit(payload, lines, args)


def _cmd_entities(args: argparse.Namespace) -> int:
    ledger = _ledger(args.store)
    views = ledger.entities(args.type)
    payload = {"entities": [
        {
            "entity_id": v.entity_id, "entity_type": v.entity_type, "held": v.held,
            "records": [r.caller_id or r.record_id for r in v.records],
            "shared": _shown(v.shared, args.reveal),
            "conflicts": _shown(v.conflicts, args.reveal),
            "decisions": len(v.decision_ids),
        }
        for v in views
    ]}
    lines = [f"{len(views)} entit{'y' if len(views) == 1 else 'ies'}"]
    for v in views:
        lines.append(f"{v.entity_id}  {v.entity_type}  {len(v.records)} records  {v.held}")
        lines.append(f"  records   {[r.caller_id or r.record_id[:16] for r in v.records]}")
        lines.append(f"  shared    {_shown(v.shared, args.reveal)}")
        if v.conflicts:
            lines.append(f"  conflicts {_shown(v.conflicts, args.reveal)}")
    if views and not args.reveal:
        lines.append("(values masked; add --reveal to see them)")
    return _emit(payload, lines, args)


def _cmd_cases(args: argparse.Namespace) -> int:
    ledger = _ledger(args.store)
    cases = ledger.cases(args.type)
    payload = {"cases": [
        {
            "decision_id": c.decision.decision_id,
            "a": c.record_a.caller_id or c.record_a.record_id,
            "b": c.record_b.caller_id or c.record_b.record_id,
            "record_a": c.record_a.record_id, "record_b": c.record_b.record_id,
            "score": c.decision.score,
            "explanation": c.decision.explanation,
            "would_resolve": c.would_resolve,
            "supporting": c.why["supporting"], "refuting": c.why["refuting"],
        }
        for c in cases
    ]}
    lines = [f"{len(cases)} open case{'s' if len(cases) != 1 else ''}"]
    for c in cases:
        lines.append(f"{c.record_a.caller_id or c.record_a.record_id[:16]} <-> "
                     f"{c.record_b.caller_id or c.record_b.record_id[:16]}  "
                     f"({c.decision.score:.4f})  {c.decision.explanation}")
        lines.append(f"  would resolve: {c.would_resolve}")
        lines.append(f"  observe: arche observe {c.record_b.record_id} --evidence '{{...}}'")
    return _emit(payload, lines, args)


def _cmd_observe(args: argparse.Namespace) -> int:
    raw = args.evidence
    try:
        evidence = json.loads(Path(raw[1:]).read_text(encoding="utf-8")) if raw.startswith("@") \
            else json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"arche observe: evidence must be a JSON object or @file: {exc}") from exc
    if not isinstance(evidence, dict):
        raise SystemExit("arche observe: evidence must be a JSON object of field: value")
    ledger = _ledger(args.store)
    try:
        fresh = ledger.observe(args.record_id, evidence)
    except KeyError as exc:
        raise SystemExit(f"arche observe: {exc.args[0]}") from exc
    payload = {"record_id": args.record_id, "fields": sorted(evidence),
               "decisions": [_decision_payload(d, args.reveal) for d in fresh],
               "open_cases": len(ledger.cases())}
    plural = "s" if len(fresh) != 1 else ""
    lines = [f"{len(fresh)} decision{plural} made again with {sorted(evidence)}"]
    for d in fresh:
        lines.append(f"  {d.identity}  {d.action}  supersedes {d.supersedes}  - {d.explanation}")
    lines.append(f"open cases now: {payload['open_cases']}")
    return _emit(payload, lines, args)


def _cmd_compare_text(args: argparse.Namespace) -> int:
    """`arche compare --text A B`: the pairwise question, from the shell."""
    from arche import resolve

    ledger = _ledger(args.store) if (args.store or args.record) else None
    receipt = resolve.compare(
        args.a, args.b, entity=args.entity, jurisdiction=args.jurisdiction,
        backend=args.backend, store=ledger,
    )
    payload = {
        "identity": receipt.identity, "action": receipt.action, "basis": receipt.basis,
        "explanation": receipt.explanation, "score": receipt.score,
        "factors": receipt.factors, "decision_id": receipt.decision_id,
        "recorded": ledger is not None,
    }
    lines = [
        f"{receipt.identity}  {receipt.action}  - {receipt.explanation}",
        f"  factors     {receipt.factors}",
        f"  decision_id {receipt.decision_id}",
    ]
    if ledger is not None:
        lines.append("  recorded    yes  (arche decision / explain / replay <decision_id>)")
    # On this subcommand `--json` is a path (the sidecar of the file form); `-`
    # sends the JSON to stdout so a shell can read the decision_id back.
    if args.json == "-":
        print(json.dumps(payload, indent=2, default=str))
    elif args.json:
        Path(args.json).write_text(json.dumps(payload, indent=2, default=str) + "\n",
                                   encoding="utf-8")
        print("\n".join(lines))
        print(f"  json        {args.json}")
    else:
        print("\n".join(lines))
    return 0





def _write_json_output(payload: dict[str, object], output: str | None) -> None:
    """Print or write a machine-readable JSON artifact at an explicit path."""
    encoded = json.dumps(payload, indent=2, sort_keys=True, default=str)
    if output is None:
        print(encoded)
        return
    path = Path(output)
    if not path.parent.exists():
        raise SystemExit(f"arche: output parent does not exist: {path.parent}")
    path.write_text(encoded + "\n", encoding="utf-8")
    print(f"wrote {path}")


def _demo_records() -> tuple[list[dict], list[dict], str]:
    """A royalty statement vs an alias-expanded catalog, from the shipped pack."""
    from arche.resolve import artist_aliases

    statement = [
        {"id": f"ln-{i:02d}", "name": n}
        for i, n in enumerate(
            [
                "WIZKID",
                "Ayodeji Balogun",
                "Damini Ogulu",
                "Divine Ikubor",
                "Temilade Openiyi",
                "Tyla Seethal",
                "Aubrey Graham",
                "Ed Sheeran",
                "Selena Gomez",
                "Kiss Daniel",
            ],
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

    if args.text:
        if not (args.a and args.b):
            raise SystemExit("arche compare --text: provide the two texts")
        return _cmd_compare_text(args)

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
            if args.reveal
            else "arche compare"
        )

    kwargs: dict = {}
    if args.block == "none":
        kwargs["block"] = None
    if args.store:
        kwargs["store"] = _ledger(args.store)
    if decl is not None:
        out = resolve.reconcile(records_a, records_b, decl=decl, **kwargs)
        entity = decl.pin()
    else:
        out = resolve.reconcile(records_a, records_b, entity=entity, **kwargs)

    matches = [m for m in out["matches"] if m["decision"] == "match"]
    review = [m for m in out["matches"] if m["decision"] != "match"]

    out_path = Path(args.out)
    json_path = Path(args.json) if args.json else out_path.with_suffix(".json")
    sidecar = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "entity": entity,
        "inputs": {
            "a": args.a or "demo:statement",
            "b": args.b or "demo:catalog",
            "count_a": len(records_a),
            "count_b": len(records_b),
        },
        "result": out,
    }
    try:
        report_html = crosswalk_report(
            out,
            records_a,
            records_b,
            reveal=args.reveal,
            title=title,
            entity=entity,
            brand_color=args.brand_color,
            decl=decl,
        )
    except ValueError as exc:  # sensitive-looking ids in masked mode, bad color
        raise SystemExit(f"arche compare: {exc}") from exc
    json_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    out_path.write_text(report_html, encoding="utf-8")

    print(f"compared {len(records_a):,} x {len(records_b):,} records (entity pack: {entity})")
    print(f"  matched: {len(matches):,}   review: {len(review):,}")
    print(f"  report:    {out_path}   [{'REVEALED' if args.reveal else 'masked — safe to share'}]")
    print(f"  decisions: {json_path}")
    if not args.reveal:
        print("  (values masked by default; add --reveal for a working copy)")
    return 0


def _cmd_resolve_documents(args: argparse.Namespace) -> int:
    """Run the document-to-candidate front door without persisting raw fields."""
    from arche import resolve_documents

    candidates = (
        _load_records(Path(args.candidates), "candidate", require_explicit_id=True)
        if args.candidates
        else None
    )
    ledger = _ledger(args.store) if args.store else None
    try:
        report = resolve_documents(
            args.source,
            entity=args.entity,
            jurisdiction=args.jurisdiction,
            candidates=candidates,
            max_candidate_pairs=args.max_candidate_pairs,
            quiet=not args.verbose,
            progress=args.progress,
            extraction_backend=args.extraction_backend,
            store=ledger,
        )
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"arche resolve-documents: {exc}") from exc
    payload = report.review(reveal=args.reveal)
    if ledger is not None:
        # Value-free summary of what the ledger now holds: which documents and
        # candidates one entity gathers, and the *names* of the fields they agree
        # on. The values stay in the ledger file the caller chose.
        payload["entities"] = [
            {
                "entity_id": view.entity_id,
                "records": [r.caller_id or r.record_id for r in view.records],
                "shared_fields": sorted(view.shared),
                "conflicting_fields": sorted(view.conflicts),
            }
            for view in ledger.entities()
        ]
        payload["open_cases"] = len(ledger.cases())
    _write_json_output(payload, args.out)
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


def _cmd_review_validate(args: argparse.Namespace) -> int:
    """Is this the pack the matcher wrote?"""
    from arche.review import validate_pack

    report = validate_pack(args.pack)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"{report['path']}  {report['rows']} rows")
        if report.get("content_sha256"):
            print(f"content_sha256  {report['content_sha256']}")
        for problem in report["problems"]:
            print(f"  [{problem['severity']}] {problem['code']}: {problem['detail']}")
        print("OK" if report["ok"] else "NOT OK")
    return 0 if report["ok"] else 1


def _cmd_review_apply(args: argparse.Namespace) -> int:
    """Bind a file of outcomes to a pack and write the adjudication."""
    from arche.review import PackError, apply_outcomes, write_reviewed_csv

    try:
        adjudication = apply_outcomes(
            args.pack, args.outcomes, require_clean_pack=not args.allow_dirty_pack
        )
    except PackError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.write_text(json.dumps(adjudication, indent=2), encoding="utf-8")
    print(
        f"{adjudication['marked']} marked, {adjudication['unmarked']} unmarked"
        f"  {adjudication['outcomes']}"
    )
    print(f"outcomes_sha256  {adjudication['outcomes_sha256']}")
    print(f"-> {out}")
    if args.csv:
        written = write_reviewed_csv(args.pack, adjudication, args.csv)
        print(f"-> {written}")
    return 0


def _cmd_review_template(args: argparse.Namespace) -> int:
    """Write a value-free outcome sheet for a human reviewer to complete."""
    from arche.review import PackError, read_pack

    try:
        pack = read_pack(args.pack)
    except PackError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not pack.ok:
        print(
            "error: pack has validation errors; run `arche review validate` first",
            file=sys.stderr,
        )
        return 1
    out = Path(args.out)
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("decision_id", "outcome", "reviewer", "reviewed_at", "reason"),
        )
        writer.writeheader()
        writer.writerows({"decision_id": decision_id} for decision_id in pack.decision_ids)
    print(f"{len(pack.decision_ids)} decision IDs; no record values written")
    print(f"-> {out}")
    return 0


def _cmd_review_share(args: argparse.Namespace) -> int:
    """Derive the copy of a pack that is safe to send somebody."""
    from arche.review import PackError, share_artifact

    adjudication = None
    if args.adjudication:
        adjudication = json.loads(Path(args.adjudication).read_text(encoding="utf-8"))
    try:
        manifest = share_artifact(
            args.pack,
            args.out,
            adjudication=adjudication,
            include_reasons=args.include_reasons,
            id_columns=args.id_column or None,
        )
    except PackError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"{manifest['rows']} rows, masked")
    if not manifest["reasons_included"]:
        print("reviewer reasons dropped (free text; --include-reasons keeps them)")
    print(f"content_sha256   {manifest['content_sha256']}")
    print(f"from             {manifest['source_pack_content_sha256']}")
    print(f"-> {Path(args.out) / 'pack.csv'}")
    return 0


def _cmd_review_verify(args: argparse.Namespace) -> int:
    """Does this adjudication still hash to what it claims, and match its pack?"""
    from arche.review import verify_adjudication

    report = verify_adjudication(args.adjudication, args.pack)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"marked            {report['marked']}")
        print(f"outcomes_match    {report['outcomes_match']}")
        if report.get("pack_checked"):
            print(f"pack_matches      {report.get('pack_matches')}")
        for problem in report["problems"]:
            print(f"  [{problem['severity']}] {problem['code']}: {problem['detail']}")
        print("OK" if report["ok"] else "NOT OK")
    return 0 if report["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="arche",
        description="arche — know the real-world entity, prove the decision.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    version_p = sub.add_parser("version", help="show the arche-core version")
    version_p.add_argument("--json", action="store_true", help="machine-readable version metadata")
    version_p.set_defaults(func=_cmd_version)

    list_p = sub.add_parser("list", help="list supported CLI commands")
    list_p.add_argument("--json", action="store_true", help="machine-readable command catalog")
    list_p.set_defaults(func=_cmd_list)

    datasets_p = sub.add_parser("datasets", help="list benchmark and review datasets")
    datasets_p.add_argument(
        "--available",
        action="store_true",
        help="show only datasets present in this source checkout",
    )
    datasets_p.add_argument("--json", action="store_true", help="machine-readable dataset catalog")
    datasets_p.set_defaults(func=_cmd_datasets)

    cmp_p = sub.add_parser(
        "compare",
        help="link two record files and emit a shareable HTML report + JSON",
    )
    cmp_p.add_argument("a", nargs="?", help="left file (.csv or .json), or a text with --text")
    cmp_p.add_argument("b", nargs="?", help="right file (.csv or .json), or a text with --text")
    cmp_p.add_argument(
        "--text", action="store_true",
        help="A and B are two pieces of text about one person; answer the pairwise question",
    )
    cmp_p.add_argument("--jurisdiction", default="NG", help="with --text: priors (default NG)")
    cmp_p.add_argument(
        "--backend", default="regex",
        help="with --text: extractor, regex (default, offline) or auto",
    )
    cmp_p.add_argument("--store", default=None, help="record every decision in this ledger file")
    cmp_p.add_argument("--record", action="store_true",
                       help="with --text: record in the ARCHE_LEDGER file")
    cmp_p.add_argument(
        "--entity", default="person", help="entity pack: person, place, artist (default person)"
    )
    cmp_p.add_argument(
        "--schema",
        default=None,
        metavar="DECL.YAML",
        help="a declaration file: YOUR fields + role annotations (overrides --entity)",
    )
    cmp_p.add_argument(
        "--out", default="report.html", help="HTML report path (default report.html)"
    )
    cmp_p.add_argument("--json", default=None,
                       help="decisions sidecar path (default <out>.json); with --text, "
                            "a path or - for stdout")
    cmp_p.add_argument(
        "--reveal", action="store_true", help="show record values in the report (default: masked)"
    )
    cmp_p.add_argument(
        "--brand-color",
        default=None,
        metavar="#HEX",
        help="theme the report accent with your color (hex only, e.g. #0f766e)",
    )
    cmp_p.add_argument(
        "--block",
        choices=["auto", "none"],
        default="auto",
        help="candidate blocking (default auto; none = all pairs)",
    )
    cmp_p.add_argument(
        "--demo", action="store_true", help="run on the built-in artist demo, no data needed"
    )
    cmp_p.set_defaults(func=_cmd_compare)

    documents_p = sub.add_parser(
        "resolve-documents",
        help="extract document fields, compare explicit candidates, and open cases",
    )
    documents_p.add_argument("source", help="document path, directory, or glob owned by the caller")
    documents_p.add_argument(
        "--candidates",
        default=None,
        help="caller-owned JSON or CSV candidate records with entity_id or id",
    )
    documents_p.add_argument("--entity", default="person", help="entity pack (default person)")
    documents_p.add_argument(
        "--jurisdiction", default="auto", help="declared jurisdiction or auto (default)"
    )
    documents_p.add_argument(
        "--max-candidate-pairs",
        type=int,
        default=1_000,
        help="hard candidate comparison cap (default 1000)",
    )
    documents_p.add_argument(
        "--extraction-backend",
        choices=["auto", "regex"],
        default="regex",
        help="field extraction backend (default regex; auto may load local models)",
    )
    documents_p.add_argument(
        "--progress", action="store_true", help="emit progress while parsing instead of JSON only"
    )
    documents_p.add_argument(
        "--verbose", action="store_true", help="show parser diagnostics while resolving"
    )
    documents_p.add_argument(
        "--reveal", action="store_true", help="include document field values in output"
    )
    documents_p.add_argument(
        "--store",
        default=None,
        help="record every verdict and its records in this local DuckDB ledger",
    )
    documents_p.add_argument(
        "--out", default=None, help="write JSON review artifact instead of stdout"
    )
    documents_p.set_defaults(func=_cmd_resolve_documents)

    def ledger_args(parser, *, reveal: bool = True, entity_type: bool = False) -> None:
        parser.add_argument("--store", default=None,
                            help="ledger file (default: $ARCHE_LEDGER)")
        parser.add_argument("--json", action="store_true", help="machine-readable output")
        parser.add_argument("--out", default=None, help="write JSON to this path")
        if reveal:
            parser.add_argument("--reveal", action="store_true",
                                help="show record values (masked by default)")
        if entity_type:
            parser.add_argument("--type", default=None, help="only this entity type")

    dec_p = sub.add_parser("decision", help="a recorded decision, by its id")
    dec_p.add_argument("decision_id")
    ledger_args(dec_p)
    dec_p.set_defaults(func=_cmd_decision)

    exp_p = sub.add_parser("explain", help="why a recorded decision came out as it did")
    exp_p.add_argument("decision_id")
    ledger_args(exp_p)
    exp_p.set_defaults(func=_cmd_explain)

    rep_p = sub.add_parser("replay", help="make a recorded decision again; report what moved")
    rep_p.add_argument("decision_id")
    ledger_args(rep_p, reveal=False)
    rep_p.set_defaults(func=_cmd_replay)

    ent_p = sub.add_parser("entities", help="what the ledger's decisions have linked together")
    ledger_args(ent_p, entity_type=True)
    ent_p.set_defaults(func=_cmd_entities)

    cas_p = sub.add_parser("cases", help="pairs still at review, and what would settle each")
    ledger_args(cas_p, reveal=False, entity_type=True)
    cas_p.set_defaults(func=_cmd_cases)

    obs_p = sub.add_parser("observe", help="add evidence about a record; re-decide its open pairs")
    obs_p.add_argument("record_id", help="record id (from `arche cases` or `arche decision`)")
    obs_p.add_argument("--evidence", required=True,
                       help='JSON object of field: value, or @file.json')
    ledger_args(obs_p)
    obs_p.set_defaults(func=_cmd_observe)

    rev_p = sub.add_parser(
        "review",
        help="check a review pack, apply outcomes to it, verify the result",
    )
    rev_sub = rev_p.add_subparsers(dest="review_command", required=True)

    rv = rev_sub.add_parser("validate", help="is this the pack the matcher wrote?")
    rv.add_argument("pack", help="pack.csv, or the directory holding it")
    rv.add_argument("--json", action="store_true", help="machine-readable report")
    rv.set_defaults(func=_cmd_review_validate)

    ra = rev_sub.add_parser("apply", help="bind a file of outcomes to a pack")
    ra.add_argument("pack", help="pack.csv, or the directory holding it")
    ra.add_argument("outcomes", help="csv, jsonl or json of decision_id/outcome/reviewer")
    ra.add_argument(
        "--out",
        default="adjudication.json",
        help="where to write the adjudication (default adjudication.json)",
    )
    ra.add_argument(
        "--csv",
        default=None,
        metavar="PATH",
        help="also write the pack with its review columns filled in",
    )
    ra.add_argument(
        "--allow-dirty-pack",
        action="store_true",
        help="adjudicate a pack that does not match its manifest",
    )
    ra.set_defaults(func=_cmd_review_apply)

    rt = rev_sub.add_parser("template", help="write a value-free outcome sheet for human review")
    rt.add_argument("pack", help="pack.csv, or the directory holding it")
    rt.add_argument("out", help="CSV destination for decision IDs and review fields")
    rt.set_defaults(func=_cmd_review_template)

    rs = rev_sub.add_parser("share", help="write the masked copy of a pack, safe to send onward")
    rs.add_argument("pack", help="pack.csv, or the directory holding it")
    rs.add_argument("out", help="directory to write the masked pack into")
    rs.add_argument(
        "--adjudication",
        default=None,
        metavar="PATH",
        help="an adjudication.json whose outcomes to carry across",
    )
    rs.add_argument(
        "--include-reasons",
        action="store_true",
        help="keep the reviewers' free-text reasons (they are not "
        "masked, and can name the person the row does not)",
    )
    rs.add_argument(
        "--id-column",
        action="append",
        default=[],
        metavar="COL",
        help="column(s) to keep unmasked as the join key; repeatable. "
        "Default is each side's `_id`.",
    )
    rs.set_defaults(func=_cmd_review_share)

    rvf = rev_sub.add_parser("verify", help="re-check an adjudication against its pack")
    rvf.add_argument("adjudication", help="the adjudication.json")
    rvf.add_argument(
        "pack", nargs="?", default=None, help="the pack it was made against (optional)"
    )
    rvf.add_argument("--json", action="store_true", help="machine-readable report")
    rvf.set_defaults(func=_cmd_review_verify)

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
    gen_p.add_argument(
        "--format",
        default="json-schema",
        choices=["json-schema", "anthropic", "openai", "comparators"],
    )
    gen_p.set_defaults(func=_cmd_schema_gen)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
