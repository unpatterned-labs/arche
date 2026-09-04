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
from hashlib import sha256
from pathlib import Path

from arche._version import __version__

_COMMANDS = (
    (
        "case",
        "open, plan, acquire evidence, ingest, review, or export a provenance-first case",
    ),
    ("compare", "link two record files and emit a masked report plus JSON"),
    ("datasets", "list benchmark and review datasets with their truth coverage"),
    ("list", "list supported CLI commands"),
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


def _file_sha256(path: Path) -> str:
    """Return a content address without retaining the caller's document bytes."""
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _case_engine(store_path: str):
    """Attach the caller-selected local runtime store for case commands."""
    from arche.runtime import attach

    path = Path(store_path)
    return attach(f"duckdb:///{path}")


def _case_value(value: object) -> object:
    """Make value-free runtime contracts safe to emit as CLI JSON."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_case_value(item) for item in value]
    if isinstance(value, list):
        return [_case_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _case_value(item) for key, item in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return {key: _case_value(getattr(value, key)) for key in value.__dataclass_fields__}
    return value


def _write_case_output(payload: dict[str, object], output: str | None) -> None:
    """Print or write a machine-reviewable case artifact at an explicit path."""
    encoded = json.dumps(payload, indent=2, sort_keys=True, default=str)
    if output is None:
        print(encoded)
        return
    path = Path(output)
    if not path.parent.exists():
        raise SystemExit(f"arche case: output parent does not exist: {path.parent}")
    path.write_text(encoded + "\n", encoding="utf-8")
    print(f"wrote {path}")


def _configured_registry_connector(config_path: Path):
    """Build one transient HTTPS registry connector from caller-owned configuration.

    Query values remain in the caller's file and only its content hash is returned
    to the CLI artifact.  The runtime still checks the connector capability against
    the persisted EvidenceAction before any request can be made.
    """
    from arche.runtime import ExternalEvidenceRequest, HttpEvidenceConnector, ToolCapability

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("registry connector configuration must be valid JSON") from error
    if not isinstance(config, dict):
        raise ValueError("registry connector configuration must be a JSON object")
    expected = {
        "source_id",
        "policy_pin",
        "base_url",
        "request",
        "estimated_cost",
        "max_requests",
        "window_seconds",
        "timeout_seconds",
    }
    if set(config) != expected:
        raise ValueError("registry connector configuration has an invalid field set")

    def required_text(name: str) -> str:
        value = config[name]
        if not isinstance(value, str) or not value:
            raise ValueError(f"registry connector configuration needs a non-empty {name}")
        return value

    source_id = required_text("source_id")
    policy_pin = required_text("policy_pin")
    base_url = required_text("base_url")
    request = config["request"]
    if not isinstance(request, dict) or set(request) != {"path", "query"}:
        raise ValueError("registry connector request needs exactly path and query")
    path = request["path"]
    query = request["query"]
    if not isinstance(path, str) or not isinstance(query, dict):
        raise ValueError("registry connector request path and query must be strings and an object")
    if any(
        not isinstance(key, str) or not key or not isinstance(value, str)
        for key, value in query.items()
    ):
        raise ValueError("registry connector query must contain non-empty string keys and values")
    try:
        request_template = ExternalEvidenceRequest(path, tuple(query.items()))
    except ValueError as error:
        raise ValueError("registry connector request is invalid") from error

    estimated_cost = config["estimated_cost"]
    max_requests = config["max_requests"]
    window_seconds = config["window_seconds"]
    timeout_seconds = config["timeout_seconds"]
    if (
        isinstance(estimated_cost, bool)
        or not isinstance(estimated_cost, (int, float))
        or isinstance(max_requests, bool)
        or not isinstance(max_requests, int)
        or isinstance(window_seconds, bool)
        or not isinstance(window_seconds, (int, float))
        or isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
    ):
        raise ValueError("registry connector limits must be numeric")
    try:
        connector = HttpEvidenceConnector(
            capability=ToolCapability(
                source_id=source_id,
                action_types=("registry_lookup",),
                policy_pin=policy_pin,
            ),
            base_url=base_url,
            request_for_action=lambda action: request_template,
            estimated_cost=float(estimated_cost),
            max_requests=max_requests,
            window_seconds=float(window_seconds),
            timeout_seconds=float(timeout_seconds),
        )
    except ValueError as error:
        raise ValueError("registry connector configuration is not permitted") from error
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
    return connector, f"sha256:{sha256(canonical).hexdigest()}"


def _cmd_case_open(args: argparse.Namespace) -> int:
    """Open an unresolved case from a hash-only local document reference."""
    from arche.runtime import (
        EvidenceAction,
        EvidenceGap,
        Observation,
        ResolutionCase,
        ResolutionIntent,
        new_evidence_action_id,
        new_ledger_id,
        new_resolution_case_id,
    )

    document = Path(args.document)
    if not document.is_file():
        raise SystemExit(f"arche case open: document does not exist: {document}")
    now = datetime.now(UTC)
    content_hash = _file_sha256(document)
    observation = Observation(
        observation_id=new_ledger_id("obs"),
        source_id="local-document",
        source_record_id=None,
        recorded_at=now,
        content_hash=content_hash,
        provenance={
            "kind": "document_reference",
            "suffix": document.suffix.lower(),
            "byte_length": document.stat().st_size,
            "document_name_hash": f"sha256:{sha256(document.name.encode()).hexdigest()}",
        },
    )
    policy_pin = args.policy_pin
    action_type = "document_ocr" if args.ocr else "document_extract"
    case = ResolutionCase(
        case_id=new_resolution_case_id(),
        question=args.question,
        observation_ids=(observation.observation_id,),
        candidate_entity_ids=(),
        opened_at=now,
        uncertainty={"state": "document_not_parsed", "content_hash": content_hash},
        evidence_gaps=(
            EvidenceGap(
                field="document_fields",
                reason="document reference has not produced reviewed extraction evidence",
                priority=0,
                permitted_action_types=(action_type,),
            ),
        ),
        intent=ResolutionIntent(
            entity_type=args.entity_type,
            operation=args.operation,
            available_fields=(),
            policy_pin=policy_pin,
        ),
    )
    action = EvidenceAction(
        action_id=new_evidence_action_id(),
        case_id=case.case_id,
        action_type=action_type,
        source_id="local-document",
        permitted_at=now,
        policy_pin=policy_pin,
        max_cost=args.max_extraction_cost,
        provenance={"document_observation_id": observation.observation_id},
    )
    engine = _case_engine(args.store)
    engine.store.write_observations([observation])
    engine.store.write_resolution_cases([case])
    engine.store.write_evidence_actions([action])
    _write_case_output(
        {
            "schema": "arche.case_open.v1",
            "case": _case_value(case),
            "permitted_action": _case_value(action),
            "note": "The document is a hash-only Observation; no parser or resolver ran.",
        },
        args.out,
    )
    return 0


def _cmd_case_plan(args: argparse.Namespace) -> int:
    """Record deterministic, bounded advice without executing a tool."""
    from arche.runtime import ResolutionBudget, ToolCapability

    engine = _case_engine(args.store)
    case = engine.store.get_resolution_case(args.case_id)
    if case is None:
        raise SystemExit(f"arche case plan: unknown case {args.case_id!r}")
    capabilities = ()
    if args.enable_local_document:
        capabilities = (
            ToolCapability(
                source_id="local-document",
                action_types=("document_extract", "document_ocr"),
                policy_pin=case.intent.policy_pin if case.intent is not None else args.policy_pin,
            ),
        )
    plan = engine.plan_case(
        case.case_id,
        capabilities=capabilities,
        budget=ResolutionBudget(max_actions=args.max_actions, max_cost=args.max_cost),
    )
    event = engine.record_case_plan(plan, recorded_at=datetime.now(UTC))
    _write_case_output(
        {
            "schema": "arche.case_plan.v1",
            "case_id": case.case_id,
            "plan_event_id": event.event_id,
            "plan": _case_value(plan),
            "note": (
                "Planning records permitted work only; it did not parse the document, "
                "run a resolver, or change entity state."
            ),
        },
        args.out,
    )
    return 0


def _planned_case_action(engine, case_id: str, action_id: str) -> None:
    """Require the caller to execute only an action selected in case history."""
    if not any(
        event.event_type == "evidence_plan" and action_id in event.references
        for event in engine.get_case_history(case_id)
    ):
        raise SystemExit(
            f"arche case: action {action_id!r} is not in a recorded plan for case {case_id!r}"
        )


def _reviewed_extraction(path: Path):
    """Read caller-owned reviewed values transiently and retain only their Evidence provenance."""
    from arche.doc import Extraction, FieldEvidence

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"arche case evidence: invalid reviewed fields JSON: {path}") from error
    fields_data = payload.get("fields") if isinstance(payload, dict) else None
    if not isinstance(fields_data, dict) or not fields_data:
        raise SystemExit(
            "arche case evidence: reviewed fields JSON needs a non-empty fields object"
        )
    fields: dict[str, FieldEvidence] = {}
    for name, item in fields_data.items():
        if not isinstance(name, str) or not name or any(char.isspace() for char in name):
            raise SystemExit("arche case evidence: field names must be non-empty identifiers")
        if not isinstance(item, dict) or "value" not in item:
            raise SystemExit(f"arche case evidence: field {name!r} needs a reviewed value")
        source = item.get("source", "extractor")
        confidence = item.get("confidence", 0.0)
        span = item.get("span")
        page = item.get("page")
        if source not in {"detector", "metadata", "extractor", "llm", "default"}:
            raise SystemExit(f"arche case evidence: field {name!r} has an unsupported source")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise SystemExit(f"arche case evidence: field {name!r} confidence must be numeric")
        if not 0.0 <= float(confidence) <= 1.0:
            raise SystemExit(f"arche case evidence: field {name!r} confidence must be in [0, 1]")
        if span is not None and (
            not isinstance(span, list)
            or len(span) != 2
            or any(isinstance(offset, bool) or not isinstance(offset, int) for offset in span)
            or span[0] < 0
            or span[1] < span[0]
        ):
            raise SystemExit(f"arche case evidence: field {name!r} span must be [start, end]")
        if page is not None and (isinstance(page, bool) or not isinstance(page, int) or page < 1):
            raise SystemExit(f"arche case evidence: field {name!r} page must be a positive integer")
        fields[name] = FieldEvidence(
            item["value"],
            source=source,
            confidence=float(confidence),
            span=tuple(span) if span is not None else None,
            page=page,
            detail=str(item.get("detail", "")),
        )
    return Extraction(data=None, fields=fields)


def _cmd_case_ingest(args: argparse.Namespace) -> int:
    """Execute one explicitly approved, previously planned Docling/OCR action."""
    from arche.runtime import (
        CaseEvent,
        DoclingDocumentIngestionExecutor,
        DocumentIngestionRequest,
        new_ledger_id,
    )

    document = Path(args.document)
    if not document.is_file():
        raise SystemExit(f"arche case ingest: document does not exist: {document}")
    engine = _case_engine(args.store)
    case = engine.store.get_resolution_case(args.case_id)
    if case is None:
        raise SystemExit(f"arche case ingest: unknown case {args.case_id!r}")
    action = engine.store.get_evidence_action(args.action_id)
    if action is None or action.case_id != case.case_id:
        raise SystemExit(f"arche case ingest: unknown document action {args.action_id!r}")
    _planned_case_action(engine, case.case_id, action.action_id)
    if engine.store.get_action_observation(action.action_id) is not None:
        raise SystemExit(f"arche case ingest: action {action.action_id!r} was already executed")
    expected_observation_id = action.provenance.get("document_observation_id")
    expected = (
        engine.store.get_observation(expected_observation_id)
        if isinstance(expected_observation_id, str)
        else None
    )
    if expected is None or expected.content_hash != _file_sha256(document):
        raise SystemExit(
            "arche case ingest: supplied document does not match the case document hash"
        )
    now = datetime.now(UTC)
    engine.store.write_case_events(
        [
            CaseEvent(
                event_id=new_ledger_id("evt"),
                case_id=case.case_id,
                event_type="document_action_approval",
                recorded_at=now,
                references=(action.action_id,),
                provenance={"approved_by": args.approved_by},
            )
        ]
    )
    link = engine.execute_document_ingestion_action(
        action.action_id,
        DocumentIngestionRequest(
            document,
            source_record_id=f"document:{expected.content_hash}",
            do_ocr=action.action_type == "document_ocr",
        ),
        DoclingDocumentIngestionExecutor(),
        observation_id=new_ledger_id("obs"),
        recorded_at=now,
    )
    observation = engine.store.get_observation(link.observation_id)
    _write_case_output(
        {
            "schema": "arche.case_ingestion.v1",
            "case_id": case.case_id,
            "action_id": action.action_id,
            "observation": _case_value(observation),
            "note": (
                "Parser/OCR output is an immutable Observation, not reviewed Evidence or a "
                "decision."
            ),
        },
        args.out,
    )
    return 0


def _cmd_case_evidence(args: argparse.Namespace) -> int:
    """Record caller-reviewed field spans as Evidence after a successful ingestion."""
    fields_path = Path(args.reviewed_fields)
    if not fields_path.is_file():
        raise SystemExit(f"arche case evidence: reviewed fields file does not exist: {fields_path}")
    engine = _case_engine(args.store)
    extraction = _reviewed_extraction(fields_path)
    evidence, event = engine.record_reviewed_document_evidence(
        args.case_id,
        args.action_id,
        extraction,
        review_id=args.review_id,
        recorded_at=datetime.now(UTC),
    )
    _write_case_output(
        {
            "schema": "arche.case_document_evidence.v1",
            "case_id": args.case_id,
            "review_event_id": event.event_id,
            "evidence": _case_value(evidence),
            "note": (
                "Reviewed values were consumed from the caller-owned file and are not stored in "
                "this artifact."
            ),
        },
        args.out,
    )
    return 0


def _cmd_case_registry_lookup(args: argparse.Namespace) -> int:
    """Execute one persisted registry lookup through its declared connector boundary."""
    config_path = Path(args.connector)
    if not config_path.is_file():
        raise SystemExit(
            f"arche case registry-lookup: connector file does not exist: {config_path}"
        )
    engine = _case_engine(args.store)
    case = engine.store.get_resolution_case(args.case_id)
    if case is None:
        raise SystemExit(f"arche case registry-lookup: unknown case {args.case_id!r}")
    action = engine.store.get_evidence_action(args.action_id)
    if action is None or action.case_id != case.case_id or action.action_type != "registry_lookup":
        raise SystemExit(
            f"arche case registry-lookup: unknown permitted registry action {args.action_id!r}"
        )
    try:
        connector, config_hash = _configured_registry_connector(config_path)
        link = engine.execute_evidence_action(action.action_id, connector)
    except ValueError as error:
        raise SystemExit(f"arche case registry-lookup: {error}") from error
    observation = engine.store.get_observation(link.observation_id)
    _write_case_output(
        {
            "schema": "arche.case_registry_observation.v1",
            "case_id": case.case_id,
            "action_id": action.action_id,
            "connector_config_sha256": config_hash,
            "observation": _case_value(observation),
            "note": (
                "The caller-owned connector configuration and query values were used only "
                "transiently. The registry result is an immutable Observation, not Evidence "
                "or a decision."
            ),
        },
        args.out,
    )
    return 0


def _cmd_case_review(args: argparse.Namespace) -> int:
    """Export a value-free case artifact for a UI or human review workflow."""
    engine = _case_engine(args.store)
    case = engine.store.get_resolution_case(args.case_id)
    if case is None:
        raise SystemExit(f"arche case review: unknown case {args.case_id!r}")
    actions = engine.store.list_evidence_actions(case.case_id)
    history = engine.get_case_history(case.case_id)
    action_observations = tuple(
        {
            "action_id": action.action_id,
            "observation": observation,
        }
        for action in actions
        if (link := engine.store.get_action_observation(action.action_id)) is not None
        if (observation := engine.store.get_observation(link.observation_id)) is not None
    )
    evidence_ids = tuple(
        reference
        for event in history
        if event.event_type == "reviewed_document_evidence"
        for reference in event.references
        if engine.store.get_evidence(reference) is not None
    )
    reviewed_evidence = tuple(
        evidence
        for evidence_id in dict.fromkeys(evidence_ids)
        if (evidence := engine.store.get_evidence(evidence_id)) is not None
    )
    _write_case_output(
        {
            "schema": "arche.case_review.v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "case": _case_value(case),
            "permitted_actions": _case_value(actions),
            "action_observations": _case_value(action_observations),
            "reviewed_evidence": _case_value(reviewed_evidence),
            "history": _case_value(history),
            "review_status": "awaiting_evidence" if not history else "review_case_history",
            "note": (
                "This artifact contains identifiers, hashes, and provenance only. A client can "
                "render it as a review pane; it cannot apply a decision by itself."
            ),
        },
        args.out,
    )
    return 0


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
        )
        persistence = None
        if args.store:
            persistence = report.persist(_case_engine(args.store))
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"arche resolve-documents: {exc}") from exc
    payload = report.review(reveal=args.reveal)
    if persistence is not None:
        payload["persistence"] = persistence
    _write_case_output(payload, args.out)
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

    case_p = sub.add_parser(
        "case",
        help="open, plan, and export an evidence-first resolution case",
    )
    case_sub = case_p.add_subparsers(dest="case_command", required=True)

    case_open = case_sub.add_parser(
        "open", help="record a hash-only document Observation and permitted extraction action"
    )
    case_open.add_argument(
        "document", help="PDF, image, scan, or text document owned by the caller"
    )
    case_open.add_argument("--store", default="arche.duckdb", help="local DuckDB runtime store")
    case_open.add_argument(
        "--question",
        default="Reconcile entities described by the supplied document.",
        help="the unresolved identity question (default is value-free)",
    )
    case_open.add_argument("--entity-type", default="organisation", help="requested entity type")
    case_open.add_argument(
        "--operation",
        choices=["compare", "reconcile", "dedupe", "find"],
        default="reconcile",
    )
    case_open.add_argument("--policy-pin", default="cli.document.v1", help="case policy pin")
    case_open.add_argument(
        "--ocr", action="store_true", help="permit document OCR instead of direct extraction"
    )
    case_open.add_argument(
        "--max-extraction-cost", type=float, default=0.0, help="permitted extraction cost ceiling"
    )
    case_open.add_argument("--out", default=None, help="write JSON instead of stdout")
    case_open.set_defaults(func=_cmd_case_open)

    case_plan = case_sub.add_parser(
        "plan", help="record deterministic, policy-bounded advice for an open case"
    )
    case_plan.add_argument("case_id", help="case identifier returned by arche case open")
    case_plan.add_argument("--store", default="arche.duckdb", help="local DuckDB runtime store")
    case_plan.add_argument(
        "--enable-local-document",
        action="store_true",
        help="declare the caller-owned local parser/OCR capability available for planning",
    )
    case_plan.add_argument("--max-actions", type=int, default=1, help="maximum permitted actions")
    case_plan.add_argument("--max-cost", type=float, default=0.0, help="total cost ceiling")
    case_plan.add_argument("--policy-pin", default="cli.document.v1", help=argparse.SUPPRESS)
    case_plan.add_argument("--out", default=None, help="write JSON instead of stdout")
    case_plan.set_defaults(func=_cmd_case_plan)

    case_ingest = case_sub.add_parser(
        "ingest", help="execute an approved planned Docling/OCR document action"
    )
    case_ingest.add_argument("case_id", help="case identifier returned by arche case open")
    case_ingest.add_argument("action_id", help="planned document action identifier")
    case_ingest.add_argument(
        "document", help="the same caller-owned document used to open the case"
    )
    case_ingest.add_argument("--store", default="arche.duckdb", help="local DuckDB runtime store")
    case_ingest.add_argument(
        "--approved-by", required=True, help="human or application identifier approving this action"
    )
    case_ingest.add_argument("--out", default=None, help="write JSON instead of stdout")
    case_ingest.set_defaults(func=_cmd_case_ingest)

    case_evidence = case_sub.add_parser(
        "evidence", help="record reviewed document fields and spans after ingestion"
    )
    case_evidence.add_argument("case_id", help="case identifier to update")
    case_evidence.add_argument("action_id", help="successful document action identifier")
    case_evidence.add_argument(
        "reviewed_fields", help="caller-owned reviewed fields JSON; values are not persisted"
    )
    case_evidence.add_argument("--review-id", required=True, help="caller-managed review reference")
    case_evidence.add_argument("--store", default="arche.duckdb", help="local DuckDB runtime store")
    case_evidence.add_argument("--out", default=None, help="write JSON instead of stdout")
    case_evidence.set_defaults(func=_cmd_case_evidence)

    case_registry_lookup = case_sub.add_parser(
        "registry-lookup",
        help="execute a persisted registry_lookup action through a configured HTTPS connector",
    )
    case_registry_lookup.add_argument("case_id", help="case identifier to update")
    case_registry_lookup.add_argument(
        "action_id", help="permitted registry_lookup action identifier"
    )
    case_registry_lookup.add_argument(
        "--connector",
        required=True,
        help="caller-owned connector JSON; request values stay outside the runtime store",
    )
    case_registry_lookup.add_argument(
        "--store", default="arche.duckdb", help="local DuckDB runtime store"
    )
    case_registry_lookup.add_argument("--out", default=None, help="write JSON instead of stdout")
    case_registry_lookup.set_defaults(func=_cmd_case_registry_lookup)

    case_review = case_sub.add_parser(
        "review", help="export a value-free case artifact for a review client"
    )
    case_review.add_argument("case_id", help="case identifier to inspect")
    case_review.add_argument("--store", default="arche.duckdb", help="local DuckDB runtime store")
    case_review.add_argument("--out", required=True, help="review artifact JSON destination")
    case_review.set_defaults(func=_cmd_case_review)

    cmp_p = sub.add_parser(
        "compare",
        help="link two record files and emit a shareable HTML report + JSON",
    )
    cmp_p.add_argument("a", nargs="?", help="left file (.csv or .json)")
    cmp_p.add_argument("b", nargs="?", help="right file (.csv or .json)")
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
    cmp_p.add_argument("--json", default=None, help="decisions sidecar path (default <out>.json)")
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
    documents_p.add_argument(
        "source", help="document path, directory, or glob owned by the caller"
    )
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
        help="persist unresolved value-free cases to this local DuckDB store",
    )
    documents_p.add_argument(
        "--out", default=None, help="write JSON review artifact instead of stdout"
    )
    documents_p.set_defaults(func=_cmd_resolve_documents)

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
