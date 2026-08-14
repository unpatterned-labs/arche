# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Progress reporting for long document runs.

`resolve_documents` on three PDFs takes about three minutes and, until this
existed, printed nothing at all. It was indistinguishable from a hang. That is
a bug we introduced ourselves: the library silences docling, RapidOCR and
HuggingFace so the answer is not buried in an OCR banner, and having taken the
user's output channel away it owes them a signal back.

**Progress writes to a stream, never through `logging`.** This is the design
constraint everything else follows from. `_quiet()` calls
`logging.disable(logging.INFO)`, which is global — anything built on `logging`
would be swallowed by our own silencer. A stream sidesteps that entirely, and
the two mechanisms stop fighting.

One protocol, four environments, no dependency:

* a terminal gets in-place updates (``\\r``) because it can;
* a CI log, a file, or a notebook gets one line per event, because ``\\r``
  there produces an unreadable smear;
* an agent loop sets ``ARCHE_PROGRESS=jsonl`` and parses structured events;
* anything that wants silence passes ``progress=False`` or sets
  ``ARCHE_PROGRESS=0``.

`tqdm` is never imported. A user who wants it writes a three-line adapter,
because :class:`ProgressHandler` is just a callable taking an :class:`Event`.

Output goes to **stderr**, so a piped stdout and `report.to_json()` stay clean.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

__all__ = [
    "Event",
    "JsonlProgress",
    "ProgressHandler",
    "TextProgress",
    "Timing",
    "null_handler",
    "resolve_handler",
]

Stage = Literal[
    "start", "parse", "metadata", "detect", "extract", "resolve", "document", "done",
]


@dataclass(frozen=True)
class Event:
    """One thing that happened, with enough context to render or parse it."""

    stage: Stage
    document: str = ""
    index: int = 0
    total: int = 0
    elapsed_s: float = 0.0
    message: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def line(self) -> str:
        """A human-readable one-liner."""
        where = f"[{self.index}/{self.total}] " if self.total else ""
        what = self.message or self.stage
        doc = f" {self.document}" if self.document else ""
        return f"{where}{what}{doc} ({self.elapsed_s:.1f}s)"


class ProgressHandler(Protocol):
    """Anything callable with an :class:`Event`. That is the whole contract."""

    def __call__(self, event: Event) -> None: ...


def null_handler(event: Event) -> None:
    """Discard every event. The default everywhere except `resolve_documents`."""


class TextProgress:
    """Human-readable progress on a stream.

    Uses ``\\r`` only when the stream is a TTY. A notebook, a CI log and a file
    all get newline-delimited output, because carriage returns there produce a
    single unreadable smeared line — the most common way progress bars break
    when they leave the terminal they were written for.
    """

    def __init__(self, stream: Any = None, *, isatty: bool | None = None) -> None:
        self._stream = stream if stream is not None else sys.stderr
        if isatty is None:
            try:
                isatty = bool(self._stream.isatty())
            except Exception:  # noqa: BLE001 — a stream without isatty is not a TTY
                isatty = False
        self._tty = isatty
        self._width = 0

    def __call__(self, event: Event) -> None:
        text = event.line()
        if self._tty and event.stage != "done":
            pad = " " * max(0, self._width - len(text))
            self._stream.write("\r" + text + pad)
            self._width = len(text)
        else:
            if self._tty and self._width:
                self._stream.write("\n")
                self._width = 0
            self._stream.write(text + "\n")
        with_flush = getattr(self._stream, "flush", None)
        if callable(with_flush):
            with_flush()


class JsonlProgress:
    """One JSON object per line — for agent loops and machine consumers."""

    def __init__(self, stream: Any = None) -> None:
        self._stream = stream if stream is not None else sys.stderr

    def __call__(self, event: Event) -> None:
        self._stream.write(json.dumps({
            "stage": event.stage, "document": event.document,
            "index": event.index, "total": event.total,
            "elapsed_s": round(event.elapsed_s, 3),
            "message": event.message, "detail": event.detail,
        }) + "\n")
        with_flush = getattr(self._stream, "flush", None)
        if callable(with_flush):
            with_flush()


def resolve_handler(
    progress: ProgressHandler | bool | str | None,
) -> ProgressHandler:
    """Turn the ``progress=`` argument into a handler.

    ``ARCHE_PROGRESS`` overrides the argument, so a CI job or an agent can force
    a mode without editing the call site: ``0``/``off``/``false`` silences,
    ``jsonl`` selects structured output, anything else truthy selects text.
    """
    override = os.environ.get("ARCHE_PROGRESS")
    if override is not None:
        lowered = override.strip().lower()
        if lowered in ("0", "off", "false", "no", ""):
            return null_handler
        if lowered == "jsonl":
            return JsonlProgress()
        return TextProgress()
    if progress is None or progress is False:
        return null_handler
    if progress is True:
        return TextProgress()
    if isinstance(progress, str):
        lowered = progress.strip().lower()
        if lowered == "jsonl":
            return JsonlProgress()
        if lowered in ("text", "on", "true"):
            return TextProgress()
        raise ValueError(
            f"unknown progress mode {progress!r}; use True, False, 'text', "
            "'jsonl', or pass a callable"
        )
    if callable(progress):
        return progress
    raise TypeError(f"progress must be bool, str or callable, got {type(progress)!r}")


@dataclass
class Timing:
    """How long a run took, and where it went.

    Progress answers "is it stuck?" while a run is happening; this answers
    "what was slow?" afterwards, and gives a regression baseline that a
    changelog number can be held to.
    """

    started_at: str = ""
    total_s: float = 0.0
    resolve_s: float = 0.0
    per_document: dict[str, dict[str, float]] = field(default_factory=dict)

    @property
    def slowest(self) -> tuple[str, float]:
        """The document that cost the most, and its seconds. ``("", 0.0)`` if none."""
        if not self.per_document:
            return "", 0.0
        name, stages = max(
            self.per_document.items(), key=lambda kv: sum(kv[1].values()),
        )
        return name, round(sum(stages.values()), 3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "total_s": round(self.total_s, 3),
            "resolve_s": round(self.resolve_s, 3),
            "slowest_document": self.slowest[0],
            "slowest_seconds": self.slowest[1],
            "per_document": {
                doc: {k: round(v, 3) for k, v in stages.items()}
                for doc, stages in self.per_document.items()
            },
        }


class _Run:
    """Internal bookkeeping: emits events and records timings together.

    Kept as one object so the two cannot drift — every stage that reports
    progress also contributes its duration to the report.
    """

    def __init__(self, handler: ProgressHandler, total: int) -> None:
        self._handler = handler
        self._total = total
        self._t0 = time.monotonic()
        self.timing = Timing(
            started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._t0

    def emit(self, stage: Stage, *, document: str = "", index: int = 0,
             message: str = "", **detail: Any) -> None:
        self._handler(Event(
            stage=stage, document=document, index=index, total=self._total,
            elapsed_s=self.elapsed, message=message, detail=detail,
        ))

    def stage(self, document: str, name: str, seconds: float) -> None:
        self.timing.per_document.setdefault(document, {})[name] = seconds

    def finish(self) -> Timing:
        self.timing.total_s = self.elapsed
        return self.timing
