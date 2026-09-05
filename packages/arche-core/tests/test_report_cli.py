# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The compare artifact: report masking guarantees + CLI end-to-end."""

from __future__ import annotations

import json

from arche import resolve
from arche.cli import main
from arche.report import crosswalk_report

A = [{"id": "s1", "name": "Burna Boy", "phone": "08035557890"}]
B = [
    {"id": "c1", "name": "Burna Boy", "phone": "08035557890"},
    {"id": "c2", "name": "Boy George"},
]


def _result():
    out = resolve.reconcile(A, B, entity="artist", block=None)
    assert out["matches"], "fixture must surface at least one pair"
    return out


# ── masking guarantees (the security surface) ────────────────────────────────
def test_report_masks_values_by_default():
    html = crosswalk_report(_result(), A, B, entity="artist")
    assert "Burna Boy" not in html  # the matched NAME value is masked
    assert "08035557890" not in html  # the phone value is masked
    assert "[NAME]" in html and "[PHONE]" in html
    assert "s1" in html and "c1" in html  # row ids stay readable
    assert "masked (safe to share)" in html


def test_report_reveal_is_explicit_opt_in():
    html = crosswalk_report(_result(), A, B, reveal=True, entity="artist")
    assert "Burna Boy" in html
    assert "08035557890" in html
    assert "revealed (working copy)" in html


def test_report_is_self_contained_and_escaped():
    evil_a = [{"id": "x", "name": "<script>alert(1)</script>"}]
    html = crosswalk_report(
        resolve.reconcile(evil_a, B, entity="artist", block=None),
        evil_a,
        B,
        reveal=True,
        entity="artist",
    )
    assert "<script>alert" not in html
    assert "http" not in html.split("</style>")[0]  # no external CSS/fonts
    assert "src=" not in html  # no external requests at all


def test_report_carries_provenance():
    html = crosswalk_report(
        _result(), A, B, entity="artist", meta={"tf": "artist (500k-artist table)"}
    )
    assert "arche-core" in html
    assert "distinctive-evidence gate" in html
    assert "500k-artist table" in html


# ── CLI end-to-end ───────────────────────────────────────────────────────────
def test_report_refuses_sensitive_looking_ids_in_masked_mode():
    """A NIN used as the row-id column must not leak through a 'masked' report."""
    import pytest

    nin_a = [{"id": "12345678901", "name": "Burna Boy"}]  # surfaces vs B[0]
    res = resolve.reconcile(nin_a, B, entity="artist", block=None)
    with pytest.raises(ValueError, match="sensitive identifiers"):
        crosswalk_report(res, nin_a, B, entity="artist")
    # An explicitly revealed working copy is the caller's own call.
    assert "12345678901" in crosswalk_report(res, nin_a, B, reveal=True, entity="artist")


def test_meta_cannot_override_assurance_fields():
    html = crosswalk_report(
        _result(), A, B, entity="artist", meta={"disclosure": "fully revealed, trust me"}
    )
    assert "masked (safe to share)" in html
    assert "trust me" not in html.split("disclosure")[-1].split("</tr>")[0]


def test_cli_demo_end_to_end(tmp_path):
    out = tmp_path / "report.html"
    rc = main(["compare", "--demo", "--out", str(out)])
    assert rc == 0
    assert out.exists()
    sidecar = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert sidecar["entity"] == "artist"
    assert sidecar["result"]["matches"]
    html = out.read_text(encoding="utf-8")
    assert "[NAME]" in html  # masked by default
    assert "Damini Ogulu" not in html
    assert "Burna Boy" not in html  # catalog ids are opaque surrogates
    assert "Wizkid" not in html


def test_cli_version_list_and_datasets_are_discoverable(capsys):
    """The command surface and truth coverage do not require a README hunt."""
    from arche import __version__

    assert main(["version", "--json"]) == 0
    version = json.loads(capsys.readouterr().out)
    assert version == {
        "package": "arche-core",
        "source": "arche._version",
        "version": __version__,
    }
    assert main(["list", "--json"]) == 0
    commands = json.loads(capsys.readouterr().out)["commands"]
    assert {item["command"] for item in commands} >= {
        "case",
        "compare",
        "datasets",
        "list",
        "resolve-documents",
        "review",
        "schema",
        "version",
    }
    assert main(["datasets", "--json"]) == 0
    datasets = {item["id"]: item for item in json.loads(capsys.readouterr().out)["datasets"]}
    assert datasets["leipzig-abt-buy"]["truth_coverage"] == "complete"
    assert datasets["nigeria-facilities-review-pack"]["truth_coverage"] == "unlabelled"


def test_cli_resolve_documents_writes_a_masked_case_review(tmp_path):
    document = tmp_path / "tea-shipment.txt"
    document.write_text(
        "Supplier: Kijani Tea Exporters Ltd\n"
        "Distributor: Nairobi Tea Trading Ltd\n"
        "Registration ID: C.12345\n"
        "Country: Kenya\n",
        encoding="utf-8",
    )
    candidates = tmp_path / "suppliers.json"
    candidates.write_text(
        json.dumps([{"entity_id": "ent_kericho", "name": "Kericho Highlands Processing"}]),
        encoding="utf-8",
    )
    output = tmp_path / "tea-review.json"
    store = tmp_path / "tea-cases.duckdb"

    assert (
        main(
            [
                "resolve-documents",
                str(document),
                "--entity",
                "organisation",
                "--candidates",
                str(candidates),
                "--extraction-backend",
                "regex",
                "--out",
                str(output),
                "--store",
                str(store),
            ]
        )
        == 0
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    rendered = output.read_text(encoding="utf-8")
    assert "Kijani Tea Exporters Ltd" not in rendered
    assert payload["cases"][0]["candidate_entity_ids"] == ["ent_kericho"]
    assert {action["action_type"] for action in payload["cases"][0]["permitted_actions"]} == {
        "registry_lookup"
    }
    assert payload["persistence"]["case_ids"] == [payload["cases"][0]["case_id"]]

    from arche.runtime import attach

    engine = attach(f"duckdb:///{store}")
    assert engine.store.get_resolution_case(payload["persistence"]["case_ids"][0]) is not None


def test_cli_registry_lookup_executes_persisted_action_without_storing_query_values(
    tmp_path, monkeypatch
):
    """A caller-owned registry request becomes one value-free case Observation."""
    document = tmp_path / "tea-shipment.txt"
    document.write_text("Supplier: Kijani Tea Exporters Ltd\n", encoding="utf-8")
    store = tmp_path / "tea-cases.duckdb"
    opened = tmp_path / "tea-review.json"
    connector = tmp_path / "registry.json"
    wrong_connector = tmp_path / "wrong-registry.json"
    output = tmp_path / "registry-observation.json"
    review = tmp_path / "case-review.json"
    connector.write_text(
        json.dumps(
            {
                "source_id": "external_registry",
                "policy_pin": "document-resolution-v1",
                "base_url": "https://supplier-master.example",
                "request": {
                    "path": "/v1/suppliers",
                    "query": {"registration_id": "C.12345"},
                },
                "estimated_cost": 0.25,
                "max_requests": 2,
                "window_seconds": 60,
                "timeout_seconds": 5,
            }
        ),
        encoding="utf-8",
    )

    from arche.runtime import Observation

    captured = {}

    class StubRegistryConnector:
        def __init__(self, **kwargs):
            self.capability = kwargs["capability"]
            captured["request"] = kwargs["request_for_action"]

        def observe(self, action):
            request = captured["request"](action)
            captured["query"] = request.query
            return Observation(
                observation_id="obs_registry_fixture",
                source_id=action.source_id,
                source_record_id="request:fixture",
                recorded_at=action.permitted_at,
                content_hash="sha256:" + "a" * 64,
                provenance={"connector": "test_registry", "outcome": "success"},
            )

    monkeypatch.setattr("arche.runtime.HttpEvidenceConnector", StubRegistryConnector)
    assert (
        main(
            [
                "resolve-documents",
                str(document),
                "--entity",
                "organisation",
                "--extraction-backend",
                "regex",
                "--out",
                str(opened),
                "--store",
                str(store),
            ]
        )
        == 0
    )
    opened_payload = json.loads(opened.read_text(encoding="utf-8"))
    case = opened_payload["cases"][0]
    action_id = case["permitted_actions"][0]["action_id"]

    wrong_config = json.loads(connector.read_text(encoding="utf-8"))
    wrong_config["policy_pin"] = "wrong-policy-v1"
    wrong_connector.write_text(json.dumps(wrong_config), encoding="utf-8")
    import pytest

    with pytest.raises(SystemExit, match="connector capability does not permit"):
        main(
            [
                "case",
                "registry-lookup",
                case["case_id"],
                action_id,
                "--connector",
                str(wrong_connector),
                "--store",
                str(store),
            ]
        )

    assert (
        main(
            [
                "case",
                "registry-lookup",
                case["case_id"],
                action_id,
                "--connector",
                str(connector),
                "--store",
                str(store),
                "--out",
                str(output),
            ]
        )
        == 0
    )
    rendered = output.read_text(encoding="utf-8")
    payload = json.loads(rendered)
    assert captured["query"] == (("registration_id", "C.12345"),)
    assert "C.12345" not in rendered
    assert payload["connector_config_sha256"].startswith("sha256:")
    assert payload["observation"]["provenance"]["outcome"] == "success"

    assert (
        main(
            [
                "case",
                "review",
                case["case_id"],
                "--store",
                str(store),
                "--out",
                str(review),
            ]
        )
        == 0
    )
    review_payload = json.loads(review.read_text(encoding="utf-8"))
    assert review_payload["action_observations"][0]["action_id"] == action_id
    assert review_payload["action_observations"][0]["observation"]["observation_id"] == (
        "obs_registry_fixture"
    )

    from arche.runtime import attach

    engine = attach(f"duckdb:///{store}")
    assert engine.store.get_action_observation(action_id).observation_id == "obs_registry_fixture"


def test_cli_case_open_plan_ingest_evidence_and_review_are_value_free(
    tmp_path, capsys, monkeypatch
):
    """A planned document action yields an Observation before reviewed field Evidence."""
    document = tmp_path / "supplier.pdf"
    document.write_text("private supplier and estate values", encoding="utf-8")
    store = tmp_path / "case.duckdb"
    opened = tmp_path / "opened.json"
    planned = tmp_path / "planned.json"
    ingested = tmp_path / "ingested.json"
    reviewed_fields = tmp_path / "reviewed-fields.json"
    evidence = tmp_path / "evidence.json"
    proposals = tmp_path / "tea-proposals.json"
    progress = tmp_path / "progress.json"
    review = tmp_path / "review.json"
    pane = tmp_path / "review.html"

    from arche.runtime import DocumentIngestion, Entity, attach

    class StubDocumentExecutor:
        executor_id = "test.docling"

        def ingest(self, request):
            return DocumentIngestion(
                source_record_id=request.source_record_id,
                text_sha256="a" * 64,
                artifact_sha256="b" * 64,
                parser="test-docling",
                parser_version="1.0",
                ocr=request.do_ocr,
                page_count=1,
            )

    monkeypatch.setattr("arche.runtime.DoclingDocumentIngestionExecutor", StubDocumentExecutor)

    assert main(["case", "open", str(document), "--store", str(store), "--out", str(opened)]) == 0
    open_payload = json.loads(opened.read_text(encoding="utf-8"))
    assert "private supplier" not in opened.read_text(encoding="utf-8")
    assert open_payload["case"]["uncertainty"]["state"] == "document_not_parsed"
    assert open_payload["permitted_action"]["action_type"] == "document_extract"

    case_id = open_payload["case"]["case_id"]
    assert (
        main(
            [
                "case",
                "plan",
                case_id,
                "--store",
                str(store),
                "--enable-local-document",
                "--out",
                str(planned),
            ]
        )
        == 0
    )
    plan_payload = json.loads(planned.read_text(encoding="utf-8"))
    assert len(plan_payload["plan"]["actions"]) == 1
    action_id = plan_payload["plan"]["actions"][0]["action_id"]

    assert (
        main(
            [
                "case",
                "ingest",
                case_id,
                action_id,
                str(document),
                "--store",
                str(store),
                "--approved-by",
                "reviewer-1",
                "--out",
                str(ingested),
            ]
        )
        == 0
    )
    assert "private supplier" not in ingested.read_text(encoding="utf-8")
    ingested_payload = json.loads(ingested.read_text(encoding="utf-8"))
    assert ingested_payload["observation"]["provenance"]["document"]["parser"] == "test-docling"

    assert (
        main(
            [
                "case",
                "progress",
                case_id,
                "--store",
                str(store),
                "--out",
                str(progress),
            ]
        )
        == 0
    )
    progress_payload = json.loads(progress.read_text(encoding="utf-8"))
    assert progress_payload["progress"]["state"] == "awaiting_evidence_review"
    assert progress_payload["progress"]["next_step"] == "review_document_observation"
    assert "private supplier" not in progress.read_text(encoding="utf-8")

    reviewed_fields.write_text(
        json.dumps(
            {
                "fields": {
                    "supplier_name": {
                        "value": "private supplier and estate values",
                        "source": "extractor",
                        "confidence": 0.82,
                        "span": [0, 17],
                        "page": 1,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    assert (
        main(
            [
                "case",
                "evidence",
                case_id,
                action_id,
                str(reviewed_fields),
                "--review-id",
                "review-case-1",
                "--store",
                str(store),
                "--out",
                str(evidence),
            ]
        )
        == 0
    )
    evidence_payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert evidence_payload["evidence"][0]["provenance"]["span"] == [0, 17]
    assert "private supplier" not in evidence.read_text(encoding="utf-8")

    engine = attach(f"duckdb:///{store}")
    engine.store.write_entities(
        [
            Entity(
                "ent_reviewed_supplier",
                "organisation",
                "legal_entity",
                engine.store.get_resolution_case(case_id).opened_at,
            )
        ]
    )
    assert (
        main(
            [
                "case",
                "propose-tea",
                case_id,
                action_id,
                str(reviewed_fields),
                "--review-id",
                "review-case-1",
                "--supplier-entity",
                "ent_reviewed_supplier",
                "--store",
                str(store),
                "--out",
                str(proposals),
            ]
        )
        == 0
    )
    proposal_payload = json.loads(proposals.read_text(encoding="utf-8"))
    assert proposal_payload["claims"][0]["predicate"] == "reported_supplier"
    assert "private supplier" not in proposals.read_text(encoding="utf-8")

    assert (
        main(
            [
                "case",
                "review",
                case_id,
                "--store",
                str(store),
                "--out",
                str(review),
                "--html",
                str(pane),
            ]
        )
        == 0
    )
    review_payload = json.loads(review.read_text(encoding="utf-8"))
    assert "private supplier" not in review.read_text(encoding="utf-8")
    assert {event["event_type"] for event in review_payload["history"]} >= {
        "document_action_approval",
        "evidence_plan",
        "reviewed_document_evidence",
    }
    assert review_payload["reviewed_evidence"][0]["provenance"]["field"] == "supplier_name"
    assert review_payload["progress"]["state"] == "needs_resolution_plan"
    pane_html = pane.read_text(encoding="utf-8")
    assert "Resolution case review" in pane_html
    assert "private supplier" not in pane_html
    assert "src=" not in pane_html
    assert "wrote" in capsys.readouterr().out


def test_cli_review_template_contains_only_decision_ids(tmp_path):
    """A reviewer can receive the decision task without copied record values."""
    pack = tmp_path / "pack.csv"
    pack.write_text("decision_id,decision,name\nedge-1,review,Private Name\n", encoding="utf-8")
    outcomes = tmp_path / "outcomes.csv"

    assert main(["review", "template", str(pack), str(outcomes)]) == 0

    text = outcomes.read_text(encoding="utf-8")
    assert "edge-1" in text
    assert "Private Name" not in text
    assert text.splitlines()[0] == "decision_id,outcome,reviewer,reviewed_at,reason"


def test_cli_csv_inputs_and_reveal(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_text("name,phone\nFatima Abdullahi,08031112222\n", encoding="utf-8")
    b.write_text("id,name,phone\nr1,Fatuma Abdullahi,08031112222\n", encoding="utf-8")
    out = tmp_path / "r.html"
    rc = main(
        [
            "compare",
            str(a),
            str(b),
            "--entity",
            "person",
            "--block",
            "none",
            "--out",
            str(out),
            "--reveal",
        ]
    )
    assert rc == 0
    html = out.read_text(encoding="utf-8")
    assert "Fatima Abdullahi" in html  # reveal honoured
    assert json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))


def test_brand_color_themes_the_accent():
    html = crosswalk_report(_result(), A, B, entity="artist", brand_color="#0f766e")
    assert "#0f766e" in html
    assert "#1a56db" not in html  # default accent fully replaced


def test_brand_color_rejects_css_injection():
    import pytest

    for evil in ("red;}body{display:none", "#12345g", "url(x)", "#1a56db;"):
        with pytest.raises(ValueError, match="hex color"):
            crosswalk_report(_result(), A, B, entity="artist", brand_color=evil)


def test_cli_masked_title_carries_no_filenames(tmp_path):
    a = tmp_path / "fatima-abdullahi-customers.csv"
    b = tmp_path / "b.csv"
    a.write_text("id,name\nr1,Burna Boy\n", encoding="utf-8")
    b.write_text("id,name\nr2,Burna Boy\n", encoding="utf-8")
    out = tmp_path / "r.html"
    main(["compare", str(a), str(b), "--entity", "artist", "--block", "none", "--out", str(out)])
    html = out.read_text(encoding="utf-8")
    assert "fatima-abdullahi-customers" not in html


def test_cli_sensitive_ids_exit_cleanly(tmp_path):
    import pytest

    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_text("id,name\n12345678901,Burna Boy\n", encoding="utf-8")
    b.write_text("id,name\nr2,Burna Boy\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="sensitive"):
        main(
            [
                "compare",
                str(a),
                str(b),
                "--entity",
                "artist",
                "--block",
                "none",
                "--out",
                str(tmp_path / "r.html"),
            ]
        )


def test_cli_rejects_unknown_extension(tmp_path):
    bad = tmp_path / "a.xlsx"
    bad.write_text("x", encoding="utf-8")
    import pytest

    with pytest.raises(SystemExit):
        main(["compare", str(bad), str(bad)])
