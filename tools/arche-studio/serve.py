#!/usr/bin/env python
# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""arche studio: compare two records, or work a review queue.

    python tools/arche-studio/serve.py

Then open http://127.0.0.1:8765 (it opens itself).

Why this is not a framework
---------------------------
The whole tool is three files and the standard library. No pip install, no
build step, no CDN. `index.html` is the entire interface and you can read it.

That matters because the people who most need to look at a match decision are
often not the people who can install a Python package. A reviewer with a laptop
and a browser is the audience.

Three modes, one renderer
-------------------------
* **Compare** takes two records and shows the decision, the evidence behind it,
  and the gate that produced it. Ad hoc, no files needed.
* **Spatial roles** reads pasted text or an attached document and marks which
  places are origins, destinations, waypoints and locations.
* **Review** loads an adjudication pack and walks it, recording an outcome per
  row.

All three draw the same evidence panel, because a reviewer and an engineer
should be looking at the same thing.

Typefaces
---------
`index.html` links Source Serif 4 and JetBrains Mono from Google Fonts. That is
the one external request the tool makes, and it is a real change from the
earlier version, which had none. Offline the page falls back to a local serif
stack and stays entirely usable; only the typography changes. If you need a
hard air gap, download the two families and swap the `<link>` for a
`@font-face` block.

Safety
------
The original pack is never written to. Saving produces a new labelled CSV
beside it, so the matcher output and its decision-ID manifest stay intact.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import webbrowser
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PACKS = REPO / "data" / "review_packs"
PORT = 8765

sys.path.insert(0, str(REPO / "packages" / "arche-core" / "src"))

OUTCOMES = ("same_entity", "different", "unresolved")

sys.path.insert(0, str(HERE))
from state import Store  # noqa: E402  (after sys.path is set)

# NOT under PACKS. `/api/pack?id=...` reads any file inside the pack directory
# and parses it as CSV, so anything kept there is readable over HTTP by anyone
# who can reach the port. The signing key was in there, and `_load_pack` handed
# back its PEM lines as two CSV rows.
STUDIO_STATE = REPO / "data" / "_studio"
STUDIO_STATE.mkdir(parents=True, exist_ok=True)
STATE = Store(STUDIO_STATE / "state.sqlite3")

# One key, created on first run and loaded thereafter. A fresh key per
# request produces signatures nobody can attribute, which is a checksum
# with extra steps.
KEY_PATH = STUDIO_STATE / "key.pem"


def _pack_suffixes() -> tuple[str, ...]:
    from arche.review import PACK_SUFFIXES

    return PACK_SUFFIXES


def _packs() -> list[dict]:
    """Every pack on offer, in any format the library can read.

    Row counts come from the library reader rather than from counting newlines,
    which was wrong for any quoted field containing one and meaningless for
    parquet.
    """
    from arche.review import PackError, read_pack

    out = []
    if not PACKS.exists():
        return out
    suffixes = _pack_suffixes()
    for d in sorted(PACKS.iterdir()):
        if d.is_dir():
            candidates = sorted(c for c in d.iterdir()
                                if c.is_file() and c.suffix.lower() in suffixes)
        else:
            candidates = [d] if d.suffix.lower() in suffixes else []
        for c in candidates:
            if c.name.endswith("_reviewed.csv"):
                continue
            try:
                rows = len(read_pack(c).rows)
            except (PackError, OSError):
                # A file that cannot be read is not offered. Listing it would
                # only produce a pack picker entry that fails on click.
                continue
            out.append({"id": str(c.relative_to(PACKS)).replace("\\", "/"),
                        "name": d.name if d.is_dir() else c.stem,
                        "format": c.suffix.lower().lstrip("."),
                        "rows": rows})
    return out


def _pack_path(pack_id: str) -> Path:
    """Resolve a pack id to a file, or refuse.

    Three things went wrong with the check this replaces. It compared resolved
    paths with `str.startswith`, so a sibling directory named `review_packs_evil`
    passed. It accepted any extension, so the signing key and the SQLite state
    were both readable through `/api/pack` and came back parsed as CSV rows. And
    it trusted an id the client made up rather than one this server had offered.

    So: containment by `is_relative_to`, an extension the library has a reader
    for, and the id has to be one `_packs()` actually lists. Widening the
    extension check from `.csv` to that set does not widen what is reachable,
    because the last check is the binding one: a file this server never offered
    cannot be named, whatever it is called.
    """
    resolved = (PACKS / pack_id).resolve()
    root = PACKS.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("pack path escapes the pack directory")
    if resolved.suffix.lower() not in _pack_suffixes():
        raise ValueError("a pack is a .csv, .parquet, .jsonl or .json file")
    if not resolved.is_file():
        raise ValueError(f"no pack {pack_id!r}")
    offered = {p["id"] for p in _packs()}
    if pack_id not in offered:
        raise ValueError(f"{pack_id!r} is not one of the packs on offer")
    return resolved


def _load_pack(pack_id: str) -> dict:
    """Read a pack through the library, and report what it says about itself.

    This used to run `csv.DictReader` here and infer the two sides here, which
    meant the studio had its own opinion about what a pack is. Two opinions is
    one too many: a parquet pack was unreadable, a quoted newline miscounted the
    rows, and the side inference could drift from the library's without either
    copy being wrong on its own.

    So the tool now asks `arche.review`. What is left here is presentation.
    """
    from arche.review import read_pack

    path = _pack_path(pack_id)
    pack = read_pack(path)

    # Integrity: a pack is only worth reviewing if it is the pack the matcher
    # produced. `content_digest` covers every column the matcher wrote, so an
    # edited name or a flipped decision shows up. `digest` is the short
    # id-membership one the header has always displayed; it notices a row
    # added or dropped and nothing inside a row, which is why both are here.
    digest = hashlib.sha256("\n".join(pack.decision_ids).encode()).hexdigest()[:16]

    from arche.review import OUTCOME_DECISION

    return {"rows": pack.rows, "fields": pack.fields, "digest": digest,
            "content_digest": pack.content_digest,
            "manifest": pack.manifest, "sides": _sides(pack.fields),
            "format": path.suffix.lower().lstrip("."),
            # What a reviewer's outcome means as a decision. Served rather than
            # hard-coded in the page, so the tool and the library cannot come to
            # disagree about what `same_entity` does.
            "outcome_decision": dict(OUTCOME_DECISION),
            # A pack that fails its own integrity check is still shown, because
            # refusing to display it helps nobody, but the reviewer is told
            # before they start rather than after they have marked forty rows.
            "problems": [p.as_dict() for p in pack.problems],
            "outcomes": list(OUTCOMES)}


def _sides(fields: list[str]) -> list[str]:
    """Which columns belong to which record, from the library's inference."""
    from arche.review import _infer_sides

    return _infer_sides(fields)


def _compare(payload: dict) -> dict:
    from arche.resolve import ENTITY_PACKS, crosswalk

    entity = payload.get("entity") or "person"
    if entity not in ENTITY_PACKS:
        raise ValueError(f"unknown entity pack: {entity}")
    a = {k: v for k, v in (payload.get("a") or {}).items() if str(v).strip()}
    b = {k: v for k, v in (payload.get("b") or {}).items() if str(v).strip()}
    if not a or not b:
        raise ValueError("both records need at least one non-empty field")

    res = crosswalk([{**a, "id": "a"}], [{**b, "id": "b"}],
                    entity=entity, id_field="id")
    if not res["matches"]:
        return {"decision": "no_candidate", "score": 0.0, "evidence": {},
                "note": ("Blocking never proposed this pair, so no comparator "
                         "ran. Nothing here agreed enough to be worth scoring."),
                "pins": res.get("pins", {})}
    e = res["matches"][0]

    from arche.resolve._gate import DISTINCTIVE_FLOOR
    return {"decision": e["decision"], "score": e["score"],
            "evidence": e.get("evidence", {}),
            "distinctive_max": e.get("distinctive_max"),
            "distinctive_floor": DISTINCTIVE_FLOOR,
            "decision_id": e.get("decision_id"),
            "pins": res.get("pins", {})}


def _extract(payload: dict) -> dict:
    """Spatial roles from pasted text, or from an attached document.

    A place mention is not just a place. "From Karfi to Kano" contains two
    mentions and the difference between them is the whole meaning of the
    sentence. Swapping origin and destination is the most literal way there is
    to get a delivery wrong.
    """
    from arche.addr import extract_places

    text = payload.get("text") or ""
    source = "pasted text"
    if payload.get("b64"):
        import base64
        import tempfile
        name = payload.get("filename") or "attachment"
        raw = base64.b64decode(payload["b64"])
        suffix = Path(name).suffix.lower()
        if suffix in (".txt", ".md", ".csv", ""):
            text = raw.decode("utf-8", "replace")
        else:
            from arche.doc import parse
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as fh:
                fh.write(raw)
                tmp = fh.name
            try:
                doc = parse(tmp)
                text = getattr(doc, "text", None) or str(doc)
            finally:
                Path(tmp).unlink(missing_ok=True)
        source = name
    if not text.strip():
        raise ValueError("nothing to read: paste some text or attach a file")

    out = []
    for m in extract_places(text):
        d = m.to_dict() if hasattr(m, "to_dict") else {}
        out.append({
            "text": m.text, "role": m.role,
            "confidence": round(float(m.confidence or 0), 3),
            "cue": m.cue, "cue_phrase": getattr(m, "cue_phrase", None),
            "cue_rule": getattr(m, "cue_rule", None),
            "span": list(m.span) if getattr(m, "span", None) else None,
            "cue_span": list(m.cue_span) if getattr(m, "cue_span", None) else None,
            "jurisdiction": getattr(m, "jurisdiction", None),
            "address": d.get("address"),
        })
    return {"source": source, "chars": len(text), "text": text, "mentions": out}


def _document_text(doc: dict) -> tuple[str, str]:
    """Text out of one uploaded document, and the name to call it.

    Factored out of `_extract`, which had the only copy. Plain text is decoded
    here; anything else goes through the document lane, which needs
    `arche-core[doc]` and says so when it is missing.
    """
    name = doc.get("name") or "document"
    if doc.get("b64"):
        import base64
        import tempfile

        raw = base64.b64decode(doc["b64"])
        suffix = Path(name).suffix.lower()
        if suffix in (".txt", ".md", ".csv", ""):
            return raw.decode("utf-8", "replace"), name
        from arche.doc import parse

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            handle.write(raw)
            tmp = handle.name
        try:
            parsed = parse(tmp)
            return (getattr(parsed, "text", None) or str(parsed)), name
        finally:
            Path(tmp).unlink(missing_ok=True)
    return doc.get("text") or "", name


# Entity types that name somebody, or address them, whether or not a statute in
# the chosen jurisdiction happens to have a rule about them. Used only to decide
# what to hide when no rule applies — see `_classify` for why that case exists.
_IDENTIFYING = {"PERSON", "NATIONAL_ID", "NIN", "BVN", "PHONE", "EMAIL",
                "ADDRESS", "PASSPORT", "DRIVERS_LICENSE", "CREDIT_CARD",
                "BANK_ACCOUNT", "DATE_OF_BIRTH", "MEDICAL", "IP_ADDRESS"}

# Policy actions that remove or replace a value. `retain` is the one that does
# not, and it is the interesting one: a statute permitting you to keep something
# is doing as much work as one telling you to drop it.
_REMOVING = {"mask", "tokenize", "generalize", "drop", "refuse"}


def _classify(entity, outcome: dict | None) -> dict:
    """Whether one detected entity is hidden, and on whose authority.

    Three cases, and the third is the one worth building the tab around.

    **A rule removed it.** The statute said so and the citation says which
    section. This is the ordinary case.

    **A rule kept it.** `retain` is a decision, not an absence of one.

    **No rule covered it.** The NG policy emits no outcome at all for a
    `PERSON`, so a name detected in a document is governed by nothing here. The
    tempting reading is that it must therefore be fine to show. That is exactly
    backwards: an uncovered detection is one nobody has decided about, and the
    safe default for a thing that names a person is to hide it and say plainly
    that no rule was the reason. A tool that showed it because no statute
    objected would be laundering a gap in coverage into a permission.
    """
    if outcome is not None:
        action = outcome.get("action") or ""
        return {"masked": action in _REMOVING,
                "action": action,
                "applied": outcome.get("applied"),
                "authority": outcome.get("citation") or outcome.get("statute") or "",
                "rationale": outcome.get("rationale") or ""}
    identifying = (getattr(entity, "entity_type", "") or "").upper() in _IDENTIFYING
    return {"masked": identifying,
            "action": "uncovered",
            "applied": None,
            "authority": "",
            "rationale": ("No rule in this jurisdiction covers this detection. "
                          "Hidden because it identifies a person, not because a "
                          "statute said to." if identifying else
                          "No rule covers this, and it does not identify anybody.")}


def _documents(payload: dict) -> dict:
    """Entities out of several documents at once, hidden by default.

    Two documents rather than one, because one document is a detector demo and
    two is the actual question: **is this the same person in both?** The linking
    at the end runs the real matcher over what was extracted, so what the tab
    shows is the engine's answer and not a summary of it.

    On revealing. The Redact tab holds a firm line — the detected value is never
    returned to that page — and this tab has a Reveal button, so the difference
    has to be stated rather than fudged. There, the point is to show what a
    compliant pipeline emits, and echoing the value would defeat the
    demonstration. Here, the document is one the person operating the tool just
    supplied from their own disk; they are not being shown anything they did not
    already have.

    So revealing is a **display** control, and it is built as one honestly: the
    values are not in the response at all unless `reveal` is set, so a page that
    has not asked cannot leak what it never received. The alternative — send
    everything and hide it in CSS — would make "redacted" a statement about
    styling, which is the kind of claim this project exists not to make.

    What is never revealed is the export. `share_artifact` masks whatever leaves
    here, on the same reasoning as everywhere else: the document you are reading
    and the document you send are not the same document.
    """
    import hashlib as _hashlib

    from arche import Pipeline, detect

    documents = payload.get("documents") or []
    if not documents:
        raise ValueError("nothing to read: attach at least one document")
    if len(documents) > 8:
        raise ValueError("eight documents at a time is the limit; this is a "
                         "reading tool, not a batch pipeline")
    jurisdiction = payload.get("jurisdiction") or "NG"
    reveal = bool(payload.get("reveal"))
    pipeline = Pipeline(jurisdiction=jurisdiction)

    out_docs = []
    for index, doc in enumerate(documents):
        text, name = _document_text(doc)
        if not text.strip():
            raise ValueError(f"{name} has no readable text in it")

        result = pipeline.process(text)
        # Index the policy outcomes by the span they cover, so each detection
        # can be joined to the rule that decided about it.
        outcomes: dict[tuple[int, int], dict] = {}
        for policy in getattr(result, "policy_outcomes", []) or []:
            span = getattr(policy, "span", None)
            if span and span[0] is not None:
                outcomes[(int(span[0]), int(span[1]))] = {
                    "action": getattr(policy, "action", None),
                    "citation": getattr(policy, "statute_reference", None),
                    "statute": getattr(policy, "statute_id", None),
                    "applied": getattr(policy, "applied_value", None),
                    "rationale": getattr(policy, "rationale", None)}

        entities = []
        for entity in detect(text):
            span = (int(entity.start), int(entity.end))
            verdict = _classify(entity, outcomes.get(span))
            kind = (entity.entity_type or "UNKNOWN").upper()
            # Content-addressed, but over the position and type rather than the
            # value: an id that hashed the text would be a way to confirm a
            # guess at what was hidden.
            eid = _hashlib.sha256(
                f"{index}:{span[0]}:{span[1]}:{kind}".encode()).hexdigest()[:16]
            shown = ((verdict.get("applied") or f"[{kind}]")
                     if verdict["masked"] else entity.text)
            entities.append({
                "id": eid, "type": kind, "span": list(span),
                "confidence": round(float(entity.confidence or 0), 3),
                "detector": entity.source,
                # `raw` never leaves this process unless `reveal` is set; it is
                # stripped at the boundary below. `shown` is what a page that
                # has not asked is allowed to see.
                "raw": entity.text,
                "shown": shown,
                "value": entity.text if (reveal or not verdict["masked"]) else None,
                "placeholder": f"[{kind}]",
                **verdict})
        out_docs.append({
            "name": name, "chars": len(text),
            # NOT `redacted_text`. The pipeline redacts what the statute covers,
            # and this tab additionally hides identity-bearing detections no
            # rule reached — so the two disagree, and the NG policy leaves a
            # PERSON in place. Showing the pipeline's text beside an entity list
            # that hides the name would print the name anyway, which is the
            # worst of both: a document that looks redacted and is not.
            "text": text if reveal else _hide_spans(text, entities),
            "entities": entities,
            "document_hash": getattr(result, "document_hash", None)})

    links = _link_documents(out_docs, reveal=reveal)
    if not reveal:
        # One place where the raw values are removed, after everything that
        # needed them has run. Masking at the boundary rather than at each
        # producer means a new field cannot quietly forget to do it.
        for doc in out_docs:
            for entity in doc["entities"]:
                entity.pop("raw", None)
    return {"jurisdiction": jurisdiction, "revealed": reveal,
            "documents": out_docs, "links": links,
            "counts": _entity_counts(out_docs)}


def _hide_spans(text: str, entities: list[dict]) -> str:
    """Replace every span this tab decided to hide, right to left.

    Right to left so earlier offsets stay valid as later ones are rewritten.
    Uses the statute's own replacement where there is one — a tokenised phone
    keeps its stable `PHONE_1b5b54b8` token, which is worth more than `[PHONE]`
    because it still tells you two mentions were the same number.
    """
    out = text
    for entity in sorted(entities, key=lambda e: -e["span"][0]):
        if not entity["masked"]:
            continue
        start, end = entity["span"]
        out = out[:start] + entity["shown"] + out[end:]
    return out


def _entity_counts(documents: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for doc in documents:
        for entity in doc["entities"]:
            counts[entity["type"]] = counts.get(entity["type"], 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


# Which entity pack answers "are these two mentions the same thing?" for each
# detected type. Types with no sensible pack are simply not linked.
_LINKABLE = {"PERSON": "person", "ORGANIZATION": "organisation",
             "ORGANISATION": "organisation", "LOCATION": "place",
             "GPE": "place", "FACILITY": "place"}


def _link_documents(documents: list[dict], *, reveal: bool) -> list[dict]:
    """Which mentions in one document are the same thing as in another.

    This is the reason the tab takes more than one file. Extraction on its own
    tells you a document mentions a person; two documents and a matcher tell you
    whether it is the *same* person, which is the question anybody comparing a
    register against a survey actually has.

    Runs the real `crosswalk` over the extracted mentions, so the decision, the
    score and the refusals are the engine's own. Pairs it declines to merge come
    back too — a held pair is the interesting output here, not a failure.
    """
    from arche.resolve import crosswalk

    if len(documents) < 2:
        return []
    links: list[dict] = []
    for i, left in enumerate(documents):
        for right in documents[i + 1:]:
            for kind, pack in sorted(set(_LINKABLE.items())):
                a = [e for e in left["entities"] if e["type"] == kind]
                b = [e for e in right["entities"] if e["type"] == kind]
                if not a or not b:
                    continue
                # Always the real values. Comparing `[PERSON]` against
                # `[PERSON]` is not a weaker answer, it is a different question
                # with a meaningless answer: every masked mention of a type is
                # byte-identical to every other, so the matcher would be scoring
                # the placeholder. The values are used here and never returned;
                # what comes back out is masked at the boundary instead.
                try:
                    result = crosswalk(
                        [{"id": e["id"], "name": e["raw"]} for e in a],
                        [{"id": e["id"], "name": e["raw"]} for e in b],
                        entity=pack, id_field="id")
                except Exception:  # noqa: BLE001 - one pack failing is not fatal
                    continue
                by_id = {e["id"]: e for e in a + b}
                for edge in result.get("matches", []):
                    left_entity = by_id.get(edge.get("a_id"), {})
                    right_entity = by_id.get(edge.get("b_id"), {})
                    links.append({
                        "type": kind,
                        "a_doc": left["name"], "b_doc": right["name"],
                        "a_id": edge.get("a_id"), "b_id": edge.get("b_id"),
                        "a": left_entity.get("raw") if reveal
                            else left_entity.get("shown"),
                        "b": right_entity.get("raw") if reveal
                            else right_entity.get("shown"),
                        "decision": edge.get("decision"),
                        "score": edge.get("score"),
                        "distinctive_max": edge.get("distinctive_max"),
                        "evidence": edge.get("evidence", {}),
                        "decision_id": edge.get("decision_id")})
    links.sort(key=lambda link: -(link["score"] or 0))
    return links


def _redact(payload: dict) -> dict:
    """Run a record through detect + policy and show what the statute removes.

    The interesting column is not the redaction, it is the citation. A system
    that removes a national ID without being able to say which section told it
    to has not complied with anything, it has just deleted a number.
    """
    from arche import Pipeline

    text = payload.get("text") or ""
    if not text.strip():
        raise ValueError("nothing to redact: paste some text first")
    juris = payload.get("jurisdiction") or "NG"
    res = Pipeline(jurisdiction=juris).process(text)

    # The policy outcome is the row worth showing: it names the action, the
    # statute and the section, and what was written in place of the value.
    # Join it back to its detection so the span can be highlighted in the text.
    by_id = {}
    for d in getattr(res, "detections", []) or []:
        by_id[getattr(d, "id", None)] = d

    rows = []
    for o in getattr(res, "policy_outcomes", []) or []:
        d = by_id.get(getattr(o, "detection_id", None))
        span = getattr(o, "span", None) or (getattr(d, "start", None), getattr(d, "end", None))
        tier = getattr(d, "sensitivity_tier", None)
        rows.append({
            "category": getattr(o, "category", None),
            "action": getattr(o, "action", None),
            "applied": getattr(o, "applied_value", None),
            "citation": getattr(o, "statute_reference", None),
            "statute": getattr(o, "statute_id", None),
            "statute_version": getattr(o, "statute_version", None),
            "rationale": getattr(o, "rationale", None),
            "span": list(span) if span and span[0] is not None else None,
            "detector": getattr(d, "detector", None),
            "identity_class": getattr(d, "identity_class", None),
            "sensitivity": getattr(tier, "value", tier),
            # The value itself is deliberately NOT returned. A redaction view
            # that echoes the thing it redacted has defeated its own purpose.
        })
    return {"jurisdiction": juris, "original": text,
            "redacted": getattr(res, "redacted_text", ""),
            "rows": rows,
            "document_hash": getattr(res, "document_hash", None)}


def _chat_ready() -> dict:
    """What is missing before an agent can run, named individually.

    Three things can be absent and they need different fixes, so a single
    "chat unavailable" would send someone looking in the wrong place. The tab
    renders either way and says which one it is.
    """
    missing = []
    try:
        import arche_mcp.server  # noqa: F401
    except ImportError:
        missing.append("arche-mcp is not importable (`uv sync --all-packages`)")
    try:
        import openai  # noqa: F401
    except ImportError:
        missing.append("the `openai` package is not installed (`uv pip install openai`)")
    if not _openai_key():
        missing.append("no OPENAI_API_KEY, in the environment or in .env at the repo root")
    return {"ready": not missing, "missing": missing,
            "model": os.environ.get("ARCHE_CHAT_MODEL", "gpt-4o-mini")}


def _openai_key() -> str:
    """The key from the environment, or from `.env`, without logging it.

    `.env` is gitignored. Read on demand rather than at import so a key added
    while the server is running is picked up on the next request, and so the
    file is never held in memory longer than the call that needs it.
    """
    key = os.environ.get("OPENAI_API_KEY", "")
    if key:
        return key
    path = REPO / ".env"
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("OPENAI_API_KEY=") and "=" in line:
            return line.partition("=")[2].strip().strip('"').strip("'")
    return ""


#: How many tool calls one turn may make before the loop gives up. High enough
#: for the four-call protection flow plus a correction, low enough that a model
#: stuck in a retry cycle costs a few seconds rather than a bill.
_CHAT_MAX_STEPS = 8


def _chat(payload: dict) -> dict:
    """One turn of an agent conversation, over arche's own MCP tool surface.

    **This is the MCP layer, not the MCP transport, and the difference is worth
    stating.** Tool schemas come from `arche_mcp.server.mcp.list_tools()` and
    calls are dispatched through `mcp.call_tool()`, which is the server's own
    dispatcher. So the descriptions, the enums and the results are identical to
    what a real client sees over stdio. What is skipped is the JSON-RPC framing
    and the subprocess.

    That trade is deliberate: a `ThreadingHTTPServer` managing an async stdio
    subprocess per request is a lot of machinery for a difference no viewer can
    observe, and the failure modes it adds are worse than the one it removes.
    `packages/arche-mcp/chat.py` speaks the real protocol for when the
    transport is what you want to prove.

    Returns the whole turn — every tool call, its arguments, its result, and the
    final answer — because the trace IS the demonstration. A chat that showed
    only the answer would hide the thing worth seeing: a model working out that
    it needs the jurisdiction before it can redact.
    """
    import asyncio

    ready = _chat_ready()
    if not ready["ready"]:
        raise ValueError("chat is not available: " + "; ".join(ready["missing"]))

    from arche_mcp.server import mcp as _mcp
    from openai import OpenAI

    history = payload.get("messages") or []
    if not history:
        raise ValueError("nothing to say: send at least one message")

    tools = asyncio.run(_mcp.list_tools())
    schema = [{"type": "function",
               "function": {"name": t.name,
                            "description": t.description or "",
                            "parameters": t.input_schema or
                                          {"type": "object", "properties": {}}}}
              for t in tools]

    messages = [{"role": "system", "content": _CHAT_SYSTEM}] + [
        {"role": m["role"], "content": m["content"]} for m in history
        if m.get("role") in {"user", "assistant"} and m.get("content")
    ]

    client = OpenAI(api_key=_openai_key())
    trace: list[dict] = []

    for _ in range(_CHAT_MAX_STEPS):
        reply = client.chat.completions.create(
            model=ready["model"], messages=messages, tools=schema,
            tool_choice="auto",
        ).choices[0].message

        if not reply.tool_calls:
            return {"reply": reply.content or "", "trace": trace,
                    "model": ready["model"]}

        messages.append(reply.model_dump(exclude_none=True))
        for call in reply.tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            step = {"tool": call.function.name, "arguments": args}
            try:
                result = asyncio.run(_mcp.call_tool(call.function.name, args))
                text = "".join(c.text for c in getattr(result, "content", [])
                               if getattr(c, "text", None))
                step["result"] = text
                step["error"] = None
            except Exception as exc:  # noqa: BLE001 — shown, never fatal
                # A failed tool is information for the model, not the end of the
                # turn. It usually recovers, and watching it recover is one of
                # the more useful things this tab shows.
                text = json.dumps({"error": str(exc)})
                step["result"] = text
                step["error"] = str(exc)
            trace.append(step)
            messages.append({"role": "tool", "tool_call_id": call.id,
                             "content": text})

    return {"reply": f"(stopped after {_CHAT_MAX_STEPS} tool calls)",
            "trace": trace, "model": ready["model"]}


_CHAT_SYSTEM = """You are connected to arche, which resolves entity references \
and protects personal data.

Use the tools rather than answering from your own knowledge. You cannot see a \
document the user describes unless you pass it to a tool.

Two flows exist and they share almost no tools:

RESOLUTION - are these two records the same thing?
  describe_pack -> compare_records

PROTECTION - what may leave this boundary, and on whose authority?
  infer_jurisdiction -> plan_protection -> guarded_scan

Choose the entity pack by what the records ARE. The pack decides which \
vocabulary rarity is measured against, so the same pair can be `match` under \
one pack and `review` under another.

Before redacting, find out which law governs the document. `infer_jurisdiction` \
returns `policy_available`; if that is false, no statute pack covers it and you \
must say so rather than proceeding.

Read the `coverage` block on any result that has one. A tool that found nothing \
may have found nothing to find, or may have had no detector able to look. Those \
are different and the block distinguishes them. Say which happened.

A `review` decision is a real answer. It means the records agree and nothing \
they agree on is distinctive enough to assert a match.

Be brief. Report what the tools returned, including what they refused."""


def _verify(payload: dict) -> dict:
    """Two independent checks on a signed decision, and one honest limit.

    * The **signature** says who issued it and that nothing changed since.
    * The **recomputed id** says the id is the honest address of *this*
      evidence rather than one lifted from a more favourable decision.

    They fail differently, which is what makes the pair worth having. The
    second check only works on a `pairwise` decision: a `crosswalk` edge
    carries `evidence` but not the `factors`/`gate`/`vetoes`/`jurisdiction`
    that `decision_id` hashes, so its id cannot be recomputed from the
    artifact alone. That is reported rather than glossed.
    """
    from arche.sign import verify as verify_jws

    token = (payload.get("jws") or "").strip()
    if not token:
        raise ValueError("paste a compact JWS to verify")

    # Tell the caller what they actually pasted. Handing a decision_id to a
    # signature check and answering "does not verify" is a confident wrong
    # answer, which is the failure mode this whole project argues against.
    bare = token.split(":")[-1]
    if token.startswith(("xwd:", "dec:", "ref:")) or (
            len(bare) == 64 and all(c in "0123456789abcdef" for c in bare.lower())):
        raise ValueError(
            "That is a decision id, not a signed decision. An id is the address "
            "of a decision; a JWS is the decision itself, signed. Ids cannot be "
            "verified on their own: there is nothing in them to check a "
            "signature against. Use 'Sign one to try', or pass an edge through "
            "sign_edges() and paste the 'jws' field.")
    if token.count(".") != 2:
        raise ValueError(
            "That is not a compact JWS. A compact JWS is three base64url "
            f"segments separated by dots (header.payload.signature); this has "
            f"{token.count('.') + 1}. If you have a signed edge, paste its "
            "'jws' field rather than the whole object.")

    out: dict = {"signature": {}, "recompute": {}}
    v = verify_jws(token, allow_did_key_from_kid=True)
    out["signature"] = {
        "valid": bool(getattr(v, "valid", False)),
        "trusted": bool(getattr(v, "trusted", False)),
        "key_source": getattr(v, "key_source", None),
        "kid": getattr(v, "kid", None),
    }
    body = dict(getattr(v, "payload", {}) or {})
    out["payload"] = body

    need = ("reference_id_a", "reference_id_b", "factors", "gate",
            "vetoes", "jurisdiction", "pins")
    missing = [k for k in need if k not in body]
    if missing:
        out["recompute"] = {
            "possible": False, "missing": missing,
            "note": ("This artifact does not carry the inputs the id is hashed "
                     "over, so the id cannot be recomputed from it. Crosswalk "
                     "edges have this shape; pairwise decisions do not."),
        }
        return out

    from arche.ids import decision_id
    claimed = body.get("decision_id")
    got = decision_id(
        reference_id_a=body["reference_id_a"], reference_id_b=body["reference_id_b"],
        decision=body.get("identity") or body.get("decision"),
        factors=body["factors"], gate=body["gate"], vetoes=body["vetoes"],
        jurisdiction=body["jurisdiction"], pins=body["pins"])
    out["recompute"] = {"possible": True, "claimed": claimed,
                        "recomputed": got, "agrees": got == claimed}
    return out


def _identity() -> dict:
    """What to publish so recipients can move from `valid` to `trusted`.

    The did:key is the public half and it is the whole identifier. There is no
    certificate authority and nothing to register: publish it wherever people
    already trust you to say things.
    """
    import keyring

    return keyring.public_identity(keyring.load_or_create(KEY_PATH))


def _sign_pack(payload: dict) -> dict:
    """One signature over a whole adjudicated pack.

    Binds every decision id to the outcome it was given, so a signature says
    which decisions were adjudicated which way rather than how many of each
    there were. See `keyring.sign_adjudication`.
    """
    import keyring

    pack = payload["pack"]
    loaded = _load_pack(pack)
    return keyring.sign_adjudication(
        keyring.load_or_create(KEY_PATH), pack=pack,
        # The CONTENT digest. Signing the id-membership digest let every name in
        # the pack be rewritten after signing without breaking the signature.
        content_digest=loaded["content_digest"],
        rows=len(loaded["rows"]),
        # Each decision and what it was marked, not a tally. Two adjudications
        # that disagree on every row used to sign identically.
        marks=STATE.current(pack))


def _sign_demo(_payload: dict) -> dict:
    """A signed edge, so Verify has something real to chew on.

    Signed with this installation's kept key, so the same `did:key` appears
    every time. A recipient who has pinned that key gets `trusted=True`; one
    who has not gets `valid=True, trusted=False`, which proves integrity and
    not authorship. Both are honest, and they are not the same claim.
    """
    import keyring
    from arche.resolve import crosswalk
    from arche.resolve.reconcile import sign_edges

    k = keyring.load_or_create(KEY_PATH)
    res = crosswalk([{"id": "a", "name": "Karfi Health Post", "lat": "12.0421", "lon": "8.5231"}],
                    [{"id": "b", "name": "Karfi Primary Health Centre", "lat": "12.0605",
                        "lon": "8.5188"}],
                    entity="place", id_field="id")
    edges = sign_edges(res, private_key=k.private_key, kid=k.did_key)
    if not edges:
        raise ValueError("nothing signable: the demo pair produced no edge")
    return {"jws": edges[0]["jws"], "decision_id": edges[0]["decision_id"]}


def _mark(payload: dict) -> dict:
    """One adjudication, appended. Survives a refresh, keeps its history.

    The pack digest and the membership of the decision are established HERE, not
    taken from the request. Before, a caller supplied `pack`, `pack_digest` and
    `decision_id` and all three were believed: a mark could be recorded against a
    decision that is not in the pack, or against a digest that does not describe
    it, and `sign_pack` would then sign those marks. An audit trail whose subject
    the client chooses is not an audit trail.
    """
    pack = payload["pack"]
    loaded = _load_pack(pack)                    # also validates the pack id
    decision_id = payload["decision_id"]
    known = {r.get("decision_id", "") for r in loaded["rows"]}
    if decision_id not in known:
        raise ValueError(
            f"decision {decision_id[:24]}... is not in {pack}; a mark has to be "
            "about a decision the pack actually contains")
    return STATE.mark(
        pack=pack,
        # Server-computed, and the CONTENT digest rather than the id-membership
        # one, so a mark records which version of the pack it was made against.
        pack_digest=loaded["content_digest"],
        decision_id=decision_id, outcome=payload.get("outcome", ""),
        reviewer=payload.get("reviewer", ""), reason=payload.get("reason", ""))


def _marks(pack: str) -> dict:
    """Standing outcomes, the toolbar counts, and how much work is left.

    `outstanding` is the number the reviewer actually cares about: rows the
    matcher held for a human that a human has not yet settled. Without it the
    only feedback for marking a row was a count going up, which is why working
    the queue felt like it did nothing.
    """
    current = STATE.current(pack)
    outstanding = None
    try:
        loaded = _load_pack(pack)
    except ValueError:
        loaded = None
    if loaded is not None:
        settled = {k for k, v in current.items() if v["outcome"] != "unresolved"}
        outstanding = sum(1 for r in loaded["rows"]
                          if r.get("decision") == "review"
                          and r.get("decision_id", "") not in settled)
    return {"current": {k: {"outcome": v["outcome"], "reason": v["reason"],
                            "reviewer": v["reviewer"], "marked_at": v["marked_at"]}
                        for k, v in current.items()},
            "outstanding": outstanding,
            "summary": STATE.summary(pack)}


def _shown(path: Path) -> str:
    """A path as the reviewer should read it: relative to the repo when it is
    inside it, absolute when it is not.

    `relative_to` raises rather than falling back, so a pack directory outside
    the checkout turned a successful save into an error about subpaths.
    """
    try:
        return str(path.relative_to(REPO)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _save_review(payload: dict) -> dict:
    """Write the two documents a finished review produces.

    Both come from `arche.review` rather than being assembled here. This
    function used to run its own `csv.DictWriter` over its own field list, which
    is how the reviewed copy ended up without the `effective_decision` column
    the library had already started writing: two writers, one of them updated.
    """
    from arche.review import share_artifact, write_reviewed_csv

    pack_id = payload["pack"]
    path = _pack_path(pack_id)

    reviewer = (payload.get("reviewer") or "").strip()
    if not reviewer:
        raise ValueError("a reviewer name is required; an unattributed "
                         "adjudication cannot be audited")

    # Read from the store, not from the browser. The store is what survived the
    # refresh and it is what carries the history.
    marks = STATE.current(pack_id)
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    for mark in marks.values():
        if mark.get("outcome") not in OUTCOMES:
            raise ValueError(f"outcome must be one of {OUTCOMES}")

    # One ledger, used for both documents, so the reviewed copy and the
    # shareable copy cannot disagree about what was decided.
    ledger = [{"decision_id": did,
               "outcome": mark["outcome"],
               "reviewer": mark.get("reviewer") or reviewer,
               "reason": (mark.get("reason") or "").strip(),
               "reviewed_at": mark.get("marked_at") or stamp,
               "marked_at": mark.get("marked_at") or stamp}
              for did, mark in sorted(marks.items())]
    adjudication = {"ledger": ledger}

    # Never write over the matcher's output.
    out = path.with_name(path.stem + "_reviewed.csv")
    write_reviewed_csv(path, adjudication, out)

    # Two artifacts, because they are for two different things. The one above is
    # the working document: it carries the names, because that is what the
    # reviewer was looking at, and it stays on this machine. The one below is
    # the one you send somebody, and it is masked.
    #
    # A save used to produce only the first, so the moment anybody attached the
    # output to an email the pack was as revealed as the day it was written.
    # Making the masked one a separate file that always exists is the point: if
    # sharing requires remembering to redact, it does not get redacted.
    shared: str | None = None
    warning: str | None = None
    share_dir = path.with_name(path.stem + "_shared")
    try:
        share_artifact(path, share_dir, adjudication=adjudication)
        shared = _shown(share_dir / "pack.csv")
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        # The commonest cause is a pack whose ids are national identifiers, which
        # `share_artifact` refuses on purpose. Say so rather than writing a file
        # that claims to be masked.
        warning = f"no shareable copy was written: {exc}"

    return {"written": _shown(out), "shared": shared, "warning": warning,
            "rows_marked": len(ledger)}


class Studio(ThreadingHTTPServer):
    # Default is True, which on Windows lets a second `serve.py` bind the same
    # port and sit behind the first one. The old process keeps answering, so an
    # edit to this file appears to do nothing. Fail loudly instead.
    allow_reuse_address = False
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def do_GET(self) -> None:
        u = urlparse(self.path)
        try:
            if u.path in ("/", "/index.html"):
                self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif u.path == "/api/chat_ready":
                self._json(_chat_ready())
            elif u.path == "/api/entities":
                # Names and what each one reads. Derived from the packs, so a
                # comparator added to the library shows up here without anybody
                # editing a list — the `person` pack gained a date comparator
                # and a hand-written one would already be wrong.
                from arche.resolve import describe_packs
                self._json(describe_packs())
            elif u.path == "/api/packs":
                self._json(_packs())
            elif u.path == "/api/pack":
                self._json(_load_pack(parse_qs(u.query).get("id", [""])[0]))
            elif u.path == "/api/identity":
                self._json(_identity())
            elif u.path == "/api/marks":
                self._json(_marks(parse_qs(u.query).get("pack", [""])[0]))
            else:
                self._json({"error": "not found"}, 404)
        except Exception as exc:  # surfaced in the UI rather than the console
            self._json({"error": str(exc) if isinstance(exc, ValueError)
                             else f"{type(exc).__name__}: {exc}"}, 400)

    def do_POST(self) -> None:
        u = urlparse(self.path)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(n) or b"{}")
            if u.path == "/api/compare":
                self._json(_compare(payload))
            elif u.path == "/api/extract":
                self._json(_extract(payload))
            elif u.path == "/api/documents":
                self._json(_documents(payload))
            elif u.path == "/api/chat":
                self._json(_chat(payload))
            elif u.path == "/api/redact":
                self._json(_redact(payload))
            elif u.path == "/api/verify":
                self._json(_verify(payload))
            elif u.path == "/api/sign_demo":
                self._json(_sign_demo(payload))
            elif u.path == "/api/mark":
                self._json(_mark(payload))
            elif u.path == "/api/sign_pack":
                self._json(_sign_pack(payload))
            elif u.path == "/api/review":
                self._json(_save_review(payload))
            else:
                self._json({"error": "not found"}, 404)
        except Exception as exc:
            self._json({"error": str(exc) if isinstance(exc, ValueError)
                             else f"{type(exc).__name__}: {exc}"}, 400)


def _warm() -> None:
    """Import arche and touch the packs before anyone clicks anything.

    The first call costs three to four seconds: importing the engine, then
    loading the shipped frequency tables. Paid at boot it is invisible. Paid on
    the first click it looks like a broken button, which is exactly how it read
    before this existed.
    """
    try:
        from arche.resolve import crosswalk
        crosswalk([{"id": "a", "name": "warm up"}], [{"id": "b", "name": "warm up"}],
                  entity="place", id_field="id")
        from arche.addr import extract_places
        extract_places("from a to b")
        print("  engine warm", flush=True)
    except Exception as exc:  # never let a warmup failure stop the server
        print(f"  warmup skipped: {exc}", flush=True)


def main() -> int:
    if not (HERE / "index.html").exists():
        print("index.html is missing next to serve.py", file=sys.stderr)
        return 1
    try:
        srv = Studio(("127.0.0.1", PORT), Handler)
    except OSError as exc:
        print(f"  port {PORT} is already in use: {exc}", file=sys.stderr)
        print("  another arche studio is probably running. Stop it first.", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{PORT}"
    print(f"  arche studio  ->  {url}")
    print(f"  review packs  ->  {PACKS}")
    print("  ctrl-c to stop")
    threading.Thread(target=_warm, daemon=True).start()
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
