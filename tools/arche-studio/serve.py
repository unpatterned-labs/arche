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

import csv
import hashlib
import io
import json
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

STATE = Store(PACKS / "_studio.sqlite3")

# One key, created on first run and loaded thereafter. A fresh key per
# request produces signatures nobody can attribute, which is a checksum
# with extra steps.
KEY_PATH = PACKS / "_studio_key.pem"


def _packs() -> list[dict]:
    out = []
    if not PACKS.exists():
        return out
    for d in sorted(PACKS.iterdir()):
        csvs = sorted(d.glob("*.csv")) if d.is_dir() else ([d] if d.suffix == ".csv" else [])
        for c in csvs:
            if c.name.endswith("_reviewed.csv"):
                continue
            out.append({"id": str(c.relative_to(PACKS)).replace("\\", "/"),
                        "name": d.name if d.is_dir() else c.stem,
                        "rows": max(0, sum(1 for _ in c.open(encoding="utf-8")) - 1)})
    return out


def _load_pack(pack_id: str) -> dict:
    path = (PACKS / pack_id).resolve()
    if not str(path).startswith(str(PACKS.resolve())):
        raise ValueError("pack path escapes the pack directory")
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    fields = list(rows[0].keys()) if rows else []

    # Integrity: a pack is only worth reviewing if it is the pack the matcher
    # produced. `content_digest` covers every column the matcher wrote, so an
    # edited name or a flipped decision shows up. `digest` is the short
    # id-membership one the header has always displayed; it notices a row
    # added or dropped and nothing inside a row, which is why both are here.
    from arche.report import pack_content_digest

    ids = [r.get("decision_id", "") for r in rows]
    content_digest = pack_content_digest(rows, fields)
    digest = hashlib.sha256("\n".join(ids).encode()).hexdigest()[:16]

    manifest = None
    mpath = path.parent / "manifest.json"
    if mpath.exists():
        manifest = json.loads(mpath.read_text(encoding="utf-8"))

    # Guess which columns belong to which side, so any pack renders without
    # configuration. Columns sharing a prefix before the first underscore, where
    # exactly two such prefixes cover most fields, are the two sides.
    prefixes: dict[str, list[str]] = {}
    for f in fields:
        if "_" in f:
            prefixes.setdefault(f.split("_", 1)[0], []).append(f)
    sides = sorted((p for p, fs in prefixes.items() if len(fs) >= 2 and p != "review"),
                   key=lambda p: -len(prefixes[p]))[:2]

    return {"rows": rows, "fields": fields, "digest": digest,
            "content_digest": content_digest,
            "manifest": manifest, "sides": sides, "outcomes": list(OUTCOMES)}


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
    """One adjudication, appended. Survives a refresh, keeps its history."""
    return STATE.mark(
        pack=payload["pack"], pack_digest=payload.get("pack_digest", ""),
        decision_id=payload["decision_id"], outcome=payload.get("outcome", ""),
        reviewer=payload.get("reviewer", ""), reason=payload.get("reason", ""))


def _marks(pack: str) -> dict:
    """Standing outcomes plus the counts a reviewer wants in the toolbar."""
    return {"current": {k: {"outcome": v["outcome"], "reason": v["reason"],
                            "reviewer": v["reviewer"], "marked_at": v["marked_at"]}
                        for k, v in STATE.current(pack).items()},
            "summary": STATE.summary(pack)}


def _save_review(payload: dict) -> dict:
    pack_id = payload["pack"]
    path = (PACKS / pack_id).resolve()
    if not str(path).startswith(str(PACKS.resolve())):
        raise ValueError("pack path escapes the pack directory")
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    fields = list(rows[0].keys()) if rows else []
    for extra in ("review_outcome", "reviewer", "reviewed_at", "reason"):
        if extra not in fields:
            fields.append(extra)

    reviewer = (payload.get("reviewer") or "").strip()
    if not reviewer:
        raise ValueError("a reviewer name is required; an unattributed "
                         "adjudication cannot be audited")
    # Read from the store, not from the browser. The store is what survived
    # the refresh and it is what carries the history.
    marks = {k: {"outcome": v["outcome"], "reason": v["reason"]}
             for k, v in STATE.current(pack_id).items()} or (payload.get("marks") or {})
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    n = 0
    for r in rows:
        m = marks.get(r.get("decision_id", ""))
        if not m:
            continue
        if m.get("outcome") not in OUTCOMES:
            raise ValueError(f"outcome must be one of {OUTCOMES}")
        r["review_outcome"] = m["outcome"]
        r["reviewer"] = reviewer
        r["reviewed_at"] = stamp
        r["reason"] = (m.get("reason") or "").strip()
        n += 1

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    # Never write over the matcher's output.
    out = path.with_name(path.stem + "_reviewed.csv")
    out.write_text(buf.getvalue(), encoding="utf-8", newline="")
    return {"written": str(out.relative_to(REPO)).replace("\\", "/"), "rows_marked": n}


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
            elif u.path == "/api/entities":
                from arche.resolve import ENTITY_PACKS
                self._json(sorted(set(ENTITY_PACKS)))
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
