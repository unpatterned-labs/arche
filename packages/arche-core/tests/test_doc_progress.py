# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for document-run progress reporting.

`resolve_documents` silences docling, RapidOCR and HuggingFace so the answer is
not buried in an OCR banner. Having taken the output channel away, it owes the
user a signal back — before this, a three-minute run was indistinguishable from
a hang.

The load-bearing design decision: progress writes to a **stream**, never
through `logging`. `_quiet()` calls `logging.disable(logging.INFO)`, which is
global, so anything built on `logging` would be swallowed by our own silencer.
"""

from __future__ import annotations

import io
import json
import logging

import pytest

from arche.doc._progress import (
    Event,
    JsonlProgress,
    TextProgress,
    Timing,
    null_handler,
    resolve_handler,
)


class TestEvent:
    def test_the_line_carries_position_and_elapsed(self):
        line = Event(stage="parse", document="a.pdf", index=2, total=5,
                     elapsed_s=1.25, message="parsing").line()
        assert "[2/5]" in line and "a.pdf" in line and "1.2s" in line

    def test_a_run_level_event_has_no_position(self):
        assert "[" not in Event(stage="start", message="starting").line()


class TestHandlerSelection:
    @pytest.mark.parametrize("value", [None, False])
    def test_falsy_is_silence(self, value):
        assert resolve_handler(value) is null_handler

    def test_true_is_text(self):
        assert isinstance(resolve_handler(True), TextProgress)

    def test_jsonl_by_name(self):
        assert isinstance(resolve_handler("jsonl"), JsonlProgress)

    def test_a_callable_passes_through(self):
        # A plain function, not `list.append` — CPython creates a fresh bound
        # method object on every attribute access, so `x.append is x.append`
        # is False and the test would fail for a reason unrelated to the code.
        def handler(event):
            pass

        assert resolve_handler(handler) is handler

    def test_an_unknown_mode_raises(self):
        with pytest.raises(ValueError, match="unknown progress mode"):
            resolve_handler("fancy")

    def test_a_bad_type_raises(self):
        with pytest.raises(TypeError):
            resolve_handler(3.5)

    @pytest.mark.parametrize(("env", "expected"), [
        ("0", "null"), ("off", "null"), ("false", "null"),
        ("jsonl", "jsonl"), ("1", "text"),
    ])
    def test_the_environment_overrides_the_argument(self, monkeypatch, env, expected):
        """So CI and agents can force a mode without editing the call site."""
        monkeypatch.setenv("ARCHE_PROGRESS", env)
        got = resolve_handler(True)
        kind = ("null" if got is null_handler
                else "jsonl" if isinstance(got, JsonlProgress) else "text")
        assert kind == expected


class TestTextProgress:
    def test_a_non_tty_gets_newlines_not_carriage_returns(self):
        """The usual way progress bars break once they leave a terminal.

        A notebook, a CI log and a file all smear into one unreadable line if
        you write `\\r` at them.
        """
        buf = io.StringIO()
        handler = TextProgress(buf, isatty=False)
        handler(Event(stage="parse", document="a.pdf", index=1, total=2))
        handler(Event(stage="parse", document="b.pdf", index=2, total=2))
        out = buf.getvalue()
        assert "\r" not in out
        assert out.count("\n") == 2

    def test_a_tty_updates_in_place(self):
        buf = io.StringIO()
        handler = TextProgress(buf, isatty=True)
        handler(Event(stage="parse", document="a.pdf", index=1, total=2))
        assert buf.getvalue().startswith("\r")

    def test_a_tty_still_ends_on_its_own_line(self):
        buf = io.StringIO()
        handler = TextProgress(buf, isatty=True)
        handler(Event(stage="parse", document="a.pdf", index=1, total=2))
        handler(Event(stage="done", message="finished"))
        assert buf.getvalue().endswith("finished (0.0s)\n")

    def test_a_shorter_line_does_not_leave_debris(self):
        """In-place rewriting must clear what the previous, longer line wrote."""
        buf = io.StringIO()
        handler = TextProgress(buf, isatty=True)
        handler(Event(stage="parse", document="a-very-long-document-name.pdf"))
        handler(Event(stage="parse", document="b.pdf"))
        assert "  " in buf.getvalue().split("\r")[-1]


class TestJsonlProgress:
    def test_every_line_is_parseable(self):
        buf = io.StringIO()
        handler = JsonlProgress(buf)
        handler(Event(stage="parse", document="a.pdf", index=1, total=3,
                      elapsed_s=0.5, detail={"pages": 2}))
        handler(Event(stage="done", message="finished"))
        rows = [json.loads(line) for line in buf.getvalue().splitlines()]
        assert [r["stage"] for r in rows] == ["parse", "done"]
        assert rows[0]["detail"] == {"pages": 2}


class TestQuietDoesNotSwallowProgress:
    """The whole reason progress is a stream and not a logger."""

    def test_events_survive_logging_disable(self):
        from arche.doc._documents import _quiet

        buf = io.StringIO()
        handler = TextProgress(buf, isatty=False)
        with _quiet():
            handler(Event(stage="parse", document="a.pdf"))
        assert "a.pdf" in buf.getvalue()

    def test_a_logging_based_handler_would_have_been_swallowed(self):
        """Pins the reason, so nobody 'simplifies' this onto logging later.

        Deliberately not using pytest's `caplog`: `caplog.at_level` resets
        `logging.disable` so capture keeps working, which is exactly the
        mechanism under test. A handler attached directly to the logger shows
        the real production behaviour.
        """
        from arche.doc._documents import _quiet

        buf = io.StringIO()
        logger = logging.getLogger("arche.test.progress")
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler(buf)
        logger.addHandler(handler)
        try:
            with _quiet():
                logger.info("parsing a.pdf")
            swallowed = buf.getvalue()
            logger.info("after the context")
        finally:
            logger.removeHandler(handler)
        assert "parsing a.pdf" not in swallowed, "logging survives _quiet()"
        assert "after the context" in buf.getvalue(), "_quiet() must restore logging"


class TestTiming:
    def test_slowest_sums_the_stages(self):
        timing = Timing(per_document={
            "a.pdf": {"parse": 1.0, "detect": 0.5},
            "b.pdf": {"parse": 4.0, "detect": 0.25},
        })
        assert timing.slowest == ("b.pdf", 4.25)

    def test_slowest_on_an_empty_run(self):
        assert Timing().slowest == ("", 0.0)

    def test_to_dict_is_json_safe(self):
        timing = Timing(started_at="2026-08-13T00:00:00Z", total_s=1.23456,
                        per_document={"a.pdf": {"parse": 1.0}})
        json.dumps(timing.to_dict())
        assert timing.to_dict()["total_s"] == 1.235


class TestReportIntegration:
    def test_timing_is_in_the_json(self):
        from arche.doc._documents import DocumentReport

        report = DocumentReport()
        report.timing = Timing(started_at="2026-08-13T00:00:00Z", total_s=2.0)
        assert json.loads(report.to_json())["timing"]["total_s"] == 2.0

    def test_progress_defaults_to_on_for_resolve_documents(self):
        """It already manages the user's output; a silent 3-minute run is the bug."""
        import inspect

        from arche.doc._documents import resolve_documents

        assert inspect.signature(resolve_documents).parameters["progress"].default is True
