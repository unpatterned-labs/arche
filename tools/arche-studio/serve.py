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

Two modes, one renderer
-----------------------
* **Compare** takes two records and shows the decision, the evidence behind it,
  and the gate that produced it. Ad hoc, no files needed.
* **Review** loads an adjudication pack and walks it, recording an outcome per
  row.

Both draw the same evidence panel, because a reviewer and an engineer should be
looking at the same thing.

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
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PACKS = REPO / "data" / "review_packs"
PORT = 8765

sys.path.insert(0, str(REPO / "packages" / "arche-core" / "src"))

OUTCOMES = ("same_entity", "different", "unresolved")


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
    # produced. The digest covers the decision ids, so an edited pack shows up.
    ids = [r.get("decision_id", "") for r in rows]
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
    marks = payload.get("marks") or {}
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
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
            else:
                self._json({"error": "not found"}, 404)
        except Exception as exc:  # surfaced in the UI rather than the console
            self._json({"error": f"{type(exc).__name__}: {exc}"}, 400)

    def do_POST(self) -> None:
        u = urlparse(self.path)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(n) or b"{}")
            if u.path == "/api/compare":
                self._json(_compare(payload))
            elif u.path == "/api/review":
                self._json(_save_review(payload))
            else:
                self._json({"error": "not found"}, 404)
        except Exception as exc:
            self._json({"error": f"{type(exc).__name__}: {exc}"}, 400)


def main() -> int:
    if not (HERE / "index.html").exists():
        print("index.html is missing next to serve.py", file=sys.stderr)
        return 1
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"  arche studio  ->  {url}")
    print(f"  review packs  ->  {PACKS}")
    print("  ctrl-c to stop")
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
