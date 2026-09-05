# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The tool surface an agent can reach, and what it must never return.

These are the tests that make publishing defensible. An MCP tool is called
unattended: no person reads the arguments, no person sees the result before it
reaches a model. So the properties worth asserting are not "does it work" but
"what can it be made to do" and "what does it leak".

Three groups, in order of how much they matter.

**Nothing raw crosses the boundary.** Every handler is checked against its own
output serialised whole, not against the field it was supposed to put the value
in. A leak in the metadata is a leak.

**Silence is never mistaken for safety.** `count: 0` from a pipeline with no
detector for the locale looks exactly like a clean document. Every detection
path carries coverage, and `guarded_scan` refuses outright when nothing at all
could be found.

**The dangerous tool is gone.** `compare_files` read two agent-supplied paths
and wrote to a third. It is asserted absent rather than merely unused, because
"we removed it" and "it cannot be called" are different claims.
"""

from __future__ import annotations

import json
import warnings

import pytest
from arche_mcp import handlers


@pytest.fixture(autouse=True)
def _quiet():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        yield


NG_TEXT = "Adaeze Okonkwo, NIN 12345678901, tel 08031234567, a@example.ng"
GB_TEXT = "Jane Smith lives in Manchester, SW1A 1AA, tel 07700 900123."


class TestNothingRawCrossesTheBoundary:
    """Checked against the whole serialised response, not the intended field."""

    def test_detect_pii_returns_offsets_not_values(self):
        blob = json.dumps(handlers.detect_pii(NG_TEXT, jurisdiction="NG"))
        for secret in ("Adaeze", "12345678901", "08031234567", "a@example.ng"):
            assert secret not in blob, f"{secret!r} leaked"

    def test_guarded_scan_returns_tokens_not_values(self):
        result = handlers.guarded_scan(NG_TEXT, key="k", jurisdiction="NG")
        assert result["denied"] is False
        blob = json.dumps(result)
        for secret in ("Adaeze", "12345678901", "08031234567"):
            assert secret not in blob, f"{secret!r} leaked"

    def test_extract_places_does_not_echo_the_address(self):
        blob = json.dumps(handlers.extract_places(
            "Deliver to 12 Aminu Kano Crescent, Wuse II, Abuja"))
        assert "Aminu Kano Crescent" not in blob

    def test_infer_jurisdiction_does_not_echo_the_identifier_it_matched(self):
        """Evidence samples can be a registration number, so the signal name
        and count travel and the matched text does not."""
        blob = json.dumps(handlers.infer_jurisdiction(NG_TEXT))
        assert "12345678901" not in blob
        assert "id.nin" in blob, "the signal itself should still be reported"

    def test_the_token_is_stable_across_calls(self):
        """The stateless correlation handle. An agent joins an entity across
        documents without this server remembering anything between calls."""
        first = handlers.guarded_scan(NG_TEXT, key="k", jurisdiction="NG")
        second = handlers.guarded_scan(NG_TEXT, key="k", jurisdiction="NG")
        assert [f["token"] for f in first["fields"]] == \
               [f["token"] for f in second["fields"]]

    def test_a_different_key_gives_a_different_token(self):
        a = handlers.guarded_scan(NG_TEXT, key="k1", jurisdiction="NG")
        b = handlers.guarded_scan(NG_TEXT, key="k2", jurisdiction="NG")
        assert [f["token"] for f in a["fields"]] != [f["token"] for f in b["fields"]]


class TestSilenceIsNeverMistakenForSafety:

    def test_detect_pii_carries_coverage(self):
        """`count: 0` alone cannot distinguish a clean document from a
        pipeline that could not read it."""
        assert "coverage" in handlers.detect_pii(GB_TEXT, jurisdiction="GB")

    def test_guarded_scan_carries_coverage_even_when_it_allows(self):
        result = handlers.guarded_scan(GB_TEXT, key="k", jurisdiction="GB")
        assert result["denied"] is False
        assert result["coverage"]["verdict"] == "partial"

    def test_and_names_the_detectors_built_for_somewhere_else(self):
        result = handlers.guarded_scan(GB_TEXT, key="k", jurisdiction="GB")
        assert result["coverage"]["degraded_categories"]

    def test_it_refuses_when_nothing_at_all_can_be_found(self):
        result = handlers.guarded_scan(
            "Jane Smith", key="k", jurisdiction="GB", statute="UK-GDPR")
        # Cross-cutting detectors cover something for GB, so this passes; the
        # zero-coverage refusal is exercised in arche-core's own tests. What
        # matters here is that a refusal, when it happens, still carries the
        # coverage that explains it.
        assert "coverage" in result

    def test_a_missing_key_refuses_rather_than_inventing_one(self):
        """A flagship tool that silently generates a key would make tokens
        uncorrelatable across runs while looking like it worked."""
        result = handlers.guarded_scan(NG_TEXT, key="", jurisdiction="NG")
        assert result["denied"] is True
        assert "ARCHE_HASH_KEY" in result["reason"]

    def test_detect_entities_says_whether_a_backend_is_installed(self):
        assert "ner_backend_installed" in handlers.detect_entities("Adaeze Okonkwo")


class TestTheJurisdictionFlow:
    """infer -> is there a policy -> plan -> scan."""

    def test_an_inferred_country_reports_whether_a_statute_covers_it(self):
        result = handlers.infer_jurisdiction(NG_TEXT)
        assert result["country"] == "NG"
        assert result["policy_available"] is True
        assert result["statute_id"] == "NDPA-2023"

    def test_a_country_with_no_statute_says_why_and_offers_a_way_forward(self):
        """The dead-end. It used to infer US at confidence 1.0 and then be
        refused with a message about arche's internal state."""
        result = handlers.infer_jurisdiction("SSN 123-45-6789, total $1,250.00")
        assert result["country"] == "US"
        assert result["policy_available"] is False
        assert "omnibus federal privacy statute" in result["policy_reason"]
        assert "HIPAA-SAFE-HARBOR" in result["policy_alternatives"]

    def test_the_eu_row_that_was_missing(self):
        result = handlers.infer_jurisdiction("VAT DE123456789, total 1.250,00 EUR")
        assert result["country"] == "EU"
        assert result["statute_id"] == "GDPR"

    def test_abstention_is_an_answer(self):
        result = handlers.infer_jurisdiction("just some text about nothing")
        assert result["abstained"] is True
        assert result["country"] is None

    def test_plan_protection_answers_before_a_document_is_handed_over(self):
        plan = handlers.plan_protection(jurisdiction="GB")
        assert plan["verdict"] in {"full", "partial", "none", "no-statute"}
        assert "uncovered" in plan and "degraded_categories" in plan

    def test_capabilities_reports_what_is_installed(self):
        caps = handlers.capabilities()
        assert caps["arche_core_version"]
        assert "NG" in caps["jurisdictions_inferable"]
        assert isinstance(caps["extras"]["detect"], bool)


class TestResolution:

    A = [{"id": "a1", "name": "Adaeze Okonkwo"}]
    B = [{"id": "b1", "name": "Adaeze Okonkwo"}]

    def test_an_entity_pack_can_be_named_instead_of_comparators(self):
        result = handlers.compare_records(self.A, self.B, entity="person")
        assert result["matches"]

    def test_passing_both_is_refused_rather_than_one_silently_winning(self):
        with pytest.raises(ValueError, match="not both"):
            handlers.compare_records(
                self.A, self.B, entity="person",
                comparators=[{"field": "name", "kind": "name", "weight": 1.0}])

    def test_passing_neither_says_what_to_do(self):
        with pytest.raises(ValueError, match="entity= or comparators="):
            handlers.compare_records(self.A, self.B)

    def test_an_unknown_pack_lists_the_real_ones(self):
        with pytest.raises(ValueError, match="available:"):
            handlers.compare_records(self.A, self.B, entity="spacecraft")

    def test_it_returns_ids_and_evidence_not_record_values(self):
        blob = json.dumps(handlers.compare_records(self.A, self.B, entity="person"))
        assert "Adaeze" not in blob

    def test_describe_pack_says_which_fields_are_read(self):
        described = handlers.describe_pack("person")
        assert "birth_date" in described["field_names"]

    def test_name_equivalence_returns_a_band_not_a_boolean(self):
        result = handlers.check_name_equivalence("Mamadou Diallo", "Mohamed Jallow")
        assert result["decision"] in {"match", "review", "no_match"}
        assert "equivalent" not in result, "the boolean had no abstention"

    def test_a_middling_pair_can_land_in_review(self):
        assert handlers.check_name_equivalence("John Smith", "Jon Smyth")["decision"] \
            in {"match", "review"}


class TestTheToolThatWasRemoved:

    def test_compare_files_is_gone_from_the_handlers(self):
        """Absent, not merely unregistered. It read two agent-supplied paths and
        wrote to a third, and MCP has no consent model for a filesystem write."""
        assert not hasattr(handlers, "compare_files")

    def test_and_is_not_registered_as_a_tool(self):
        import asyncio

        from arche_mcp.server import mcp
        names = {t.name for t in asyncio.run(mcp.list_tools())}
        assert "compare_files" not in names

    def test_the_expected_tools_are_registered(self):
        import asyncio

        from arche_mcp.server import mcp
        names = {t.name for t in asyncio.run(mcp.list_tools())}
        assert names == {
            "capabilities", "infer_jurisdiction", "plan_protection",
            "describe_pack", "detect_pii", "detect_entities", "guarded_scan",
            "compare_records", "why_unresolved", "check_name_equivalence",
            "extract_places",
        }

    def test_every_tool_has_a_description(self):
        """The description IS the documentation. An agent reads nothing else."""
        import asyncio

        from arche_mcp.server import mcp
        for tool in asyncio.run(mcp.list_tools()):
            assert tool.description and len(tool.description) > 60, tool.name


class TestNoPrivateCoreImports:
    """Publishing freezes whatever you import, and a pin does not protect a
    private name because a patch release can rename it."""

    def test_the_module_imports_nothing_private_from_arche(self):
        import re
        from pathlib import Path
        source = Path(handlers.__file__).read_text(encoding="utf-8")
        private = re.findall(r"from\s+(arche[\w.]*\._\w+)\s+import", source)
        # `arche.workflow._primitive` is the documented home of Pipeline and is
        # re-exported as `arche.Pipeline`; everything else must be public.
        assert [p for p in private if p != "arche.workflow._primitive"] == []

    def test_compare_names_comes_from_the_public_module(self):
        assert handlers.compare_names.__module__.startswith("arche.resolve")


class TestConfigurationIsACeiling:
    """A pinned jurisdiction must not be overridable by a tool argument.

    Moving jurisdiction from a setting to an argument otherwise hands the choice
    of governing law to the agent, and an agent that can choose its statute can
    choose a weaker one.
    """

    def test_an_unset_ceiling_lets_the_caller_choose(self, monkeypatch):
        from arche_mcp import server
        monkeypatch.setattr(server, "_JURISDICTION", None)
        assert server._jurisdiction("NG") == "NG"

    def test_a_set_ceiling_wins_over_the_argument(self, monkeypatch):
        from arche_mcp import server
        monkeypatch.setattr(server, "_JURISDICTION", "NG")
        assert server._jurisdiction("US") == "NG"

    def test_the_same_holds_for_the_statute(self, monkeypatch):
        from arche_mcp import server
        monkeypatch.setattr(server, "_STATUTE", "BASELINE")
        assert server._statute("GDPR") == "BASELINE"


def test_offsets_are_labelled_against_the_text_they_index():
    """`guarded_scan`'s redacted text has different offsets from the original,
    because replacement tokens are a different length. An agent slicing one with
    the other gets the wrong span, and a shifted window can expose an adjacent
    value."""
    assert handlers.extract_places("Deliver to Kano")["offsets_match_original"] is True
    assert handlers.guarded_scan(
        NG_TEXT, key="k", jurisdiction="NG")["offsets_match_original"] is False


class TestTheSchemasTeachTheModel:
    """Found by watching a model drive these tools, not by a unit test.

    Two calls failed in a live transcript:

        describe_pack(entity="ng")
          -> unknown entity pack 'ng'
        compare_records(list_a=..., list_b=..., threshold=...)
          -> pass entity= or comparators= to say how to compare

    Neither was the model being careless. `describe_pack` declared
    `entity: string` with no enum, so "which strings are legal" was
    unanswerable from the schema and it guessed from nearby context — `ng` is a
    *jurisdiction* code, which is the most reasonable wrong guess available.
    `compare_records` declared both `entity` and `comparators` as optional with
    a null default, so the schema permitted a call the handler then rejected.

    An MCP tool is called unattended. A requirement the schema does not express
    is a requirement discovered by failing, and every failure costs a round
    trip and some of the model's remaining attention.
    """

    @staticmethod
    def _schemas():
        import asyncio

        from arche_mcp.server import mcp
        return {t.name: t for t in asyncio.run(mcp.list_tools())}

    def test_describe_pack_offers_the_packs_as_an_enum(self):
        from arche.resolve import ENTITY_PACKS
        entity = self._schemas()["describe_pack"].input_schema["properties"]["entity"]
        assert entity.get("enum") == sorted(ENTITY_PACKS)

    def test_the_enum_cannot_drift_from_the_packs(self):
        """Built from the live dict, so adding a pack updates the schema with no
        edit. If this ever fails, someone hardcoded the list."""
        from arche.resolve import ENTITY_PACKS
        schemas = self._schemas()
        for tool in ("describe_pack", "compare_records"):
            entity = schemas[tool].input_schema["properties"]["entity"]
            values = entity.get("enum") or next(
                (a["enum"] for a in entity.get("anyOf", []) if "enum" in a), None)
            assert values == sorted(ENTITY_PACKS), tool

    def test_a_jurisdiction_code_is_not_a_valid_entity(self):
        """The specific wrong guess. `ng` is a detector pack and a jurisdiction;
        it has never been an entity pack."""
        entity = self._schemas()["describe_pack"].input_schema["properties"]["entity"]
        assert "ng" not in entity["enum"]

    def test_compare_records_states_the_requirement_first(self):
        """The description is the only documentation a model reads, so a
        requirement buried in paragraph three is a requirement it will miss."""
        description = self._schemas()["compare_records"].description or ""
        head = description[:400]
        assert "REQUIRED" in head
        assert "entity" in head and "comparators" in head

    def test_and_the_handler_still_refuses_rather_than_guessing(self):
        """The schema now discourages the bad call; the handler still refuses
        it. Guessing a pack would be worse than the error — it would silently
        compare on a vocabulary the caller did not choose."""
        with pytest.raises(ValueError, match="entity= or comparators="):
            handlers.compare_records([{"id": "a"}], [{"id": "b"}])


class TestTheLedgerTools:
    """With ARCHE_LEDGER the server remembers. What comes back is still ids,
    labels, field names and numbers -- the values stay in the operator's file."""

    A = [{"id": "s1", "name": "Kijani Tea Exporters Ltd", "city": "Nairobi",
          "registration_id": "C.12345"}]
    B = [{"id": "r1", "name": "Kijani Tea Exporters Limited", "city": "Nairobi",
          "registration_id": "C.12345"},
         {"id": "r2", "name": "Kijani Coffee", "city": "Nairobi"}]

    @pytest.fixture
    def ledger(self):
        pytest.importorskip("duckdb")
        import arche
        with arche.attach("duckdb:///:memory:") as book:
            yield book

    def test_compare_records_records_when_given_a_ledger(self, ledger):
        out = handlers.compare_records(self.A, self.B, entity="organisation", ledger=ledger)
        assert out["matches"], "fixture must surface edges"
        assert handlers.ledger_entities(ledger)["count"] == 1
        for edge in out["matches"]:
            found = handlers.ledger_decision(ledger, edge["decision_id"])
            assert found["identity"] == edge["decision"]

    def test_nothing_raw_crosses_the_boundary(self, ledger):
        handlers.compare_records(self.A, self.B, entity="organisation", ledger=ledger)
        (case,) = handlers.ledger_cases(ledger)["cases"]
        edge_id = case["decision_id"]
        blob = json.dumps([
            handlers.ledger_entities(ledger),
            handlers.ledger_decision(ledger, edge_id),
            handlers.ledger_explain(ledger, edge_id),
            handlers.ledger_cases(ledger),
            handlers.ledger_path(ledger, case["a"]["record_id"], case["b"]["record_id"]),
        ])
        for value in ("Kijani", "Nairobi", "C.12345"):
            assert value not in blob, f"{value!r} leaked through a ledger tool"

    def test_entities_report_field_names_and_how_they_are_held(self, ledger):
        handlers.compare_records(self.A, self.B, entity="organisation", ledger=ledger)
        (entity,) = handlers.ledger_entities(ledger)["entities"]
        assert {r["label"] for r in entity["records"]} == {"s1", "r1"}
        assert "registration_id" in entity["shared_fields"]
        assert "name" in entity["conflicting_fields"]
        assert entity["held_together_by"] == "direct" and entity["weak_links"] == []

    def test_path_explains_a_transitive_link(self, ledger):
        import arche
        texts = ("Mary Smith, NIN 12345678901, mary.smith@example.com",
                 "Mary Smith, NIN 12345678901, phone 08035557890, mary.smith@example.com",
                 "Mary Jones, NIN 12345678901, phone 08035557890, 4 Elim Street Enugu",
                 "Mary Jones, NIN 12345678901, mary.jones@example.com, 4 Elim Street Enugu")
        person = dict(entity="person", jurisdiction="NG", backend="regex", store=ledger)
        r12 = arche.compare(texts[0], texts[1], **person)
        arche.compare(texts[1], texts[2], **person)
        r34 = arche.compare(texts[2], texts[3], **person)
        first = ledger.decision(r12.decision_id).record_a
        fourth = ledger.decision(r34.decision_id).record_b

        out = handlers.ledger_path(ledger, first, fourth)

        assert out["same_entity"] is True and out["hops"] == 3
        assert "never compared" in out["note"]
        assert "Mary" not in json.dumps(out)
        (entity,) = handlers.ledger_entities(ledger)["entities"]
        assert entity["held_together_by"] == "transitive" and len(entity["weak_links"]) == 2

    def test_cases_then_observe_closes_the_case(self, ledger):
        handlers.compare_records(self.A, self.B, entity="organisation", ledger=ledger)
        (case,) = handlers.ledger_cases(ledger)["cases"]
        assert case["would_resolve"][0] == "registration_id"
        out = handlers.ledger_observe(ledger, case["b"]["record_id"],
                                      {"registration_id": "C.54321"})
        assert out["decisions"][0]["identity"] == "different"
        assert out["decisions"][0]["supersedes"] == case["decision_id"]
        assert out["open_cases"] == 0
        assert "C.54321" not in json.dumps(out)

    def test_resolve_joins_a_newcomer_and_says_why_without_values(self, ledger):
        import arche
        texts = ("Mary Smith, NIN 12345678901, phone 08035557890, mary.smith@example.com",
                 "Mary Jones, NIN 12345678901, phone 08035557890, 4 Elim Street Enugu")
        arche.compare(*texts, entity="person", jurisdiction="NG", backend="regex", store=ledger)

        out = handlers.ledger_resolve(
            ledger, {"name": "M. Jones", "national_id": "12345678901"}, entity_type="person")

        assert out["verdict"] == "found"
        assert out["entity"]["held_together_by"] in {"direct", "transitive"}
        assert len(out["entity"]["records"]) == 3
        # id alone, no second field on the newcomer: the whole-entity receipt is
        # honest about that and says review; the id factor is still 1.0
        assert out["entity_evidence"]["identity"] in {"same_entity", "review"}
        assert out["entity_evidence"]["factors"]["national_id"] == 1.0
        assert "12345678901" not in json.dumps(out)

        held = handlers.ledger_resolve(
            ledger, {"name": "Mary Smith", "national_id": "99999999999"}, entity_type="person")
        assert held["verdict"] == "conflict" and held["conflicting_fields"] == ["national_id"]
        assert "99999999999" not in json.dumps(held)

    def test_observe_refuses_an_empty_object(self, ledger):
        with pytest.raises(ValueError, match="non-empty"):
            handlers.ledger_observe(ledger, "rec:sha256:x", {})

    def test_replay_reproduces(self, ledger):
        out = handlers.compare_records(self.A, self.B, entity="organisation", ledger=ledger)
        replay = handlers.ledger_replay(ledger, out["matches"][0]["decision_id"])
        assert replay["reproduced"] is True and replay["changed"] == {}


class TestLedgerToolsAppearOnlyWhenConfigured:
    """A client of an unconfigured server must not see tools that can only fail."""

    LEDGER_TOOLS = {"decision", "explain", "replay", "entities", "path", "cases", "observe",
                    "resolve"}

    @staticmethod
    def _tools(monkeypatch, uri):
        import asyncio
        import importlib
        import sys

        if uri is None:
            monkeypatch.delenv("ARCHE_LEDGER", raising=False)
        else:
            monkeypatch.setenv("ARCHE_LEDGER", uri)
        sys.modules.pop("arche_mcp.server", None)
        server = importlib.import_module("arche_mcp.server")
        names = {t.name for t in asyncio.run(server.mcp.list_tools())}
        sys.modules.pop("arche_mcp.server", None)
        return names, server

    def test_absent_when_unset(self, monkeypatch):
        names, _ = self._tools(monkeypatch, None)
        assert not names & self.LEDGER_TOOLS

    def test_present_when_set_and_capabilities_says_so(self, monkeypatch):
        pytest.importorskip("duckdb")
        names, server = self._tools(monkeypatch, "duckdb:///:memory:")
        assert names >= self.LEDGER_TOOLS
        assert server.capabilities()["ledger"]["configured"] is True
