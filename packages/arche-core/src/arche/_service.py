# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""``arche serve``: the same verbs over HTTP, on the machine that has the data.

    pip install "arche-core[service]"
    arche serve                      # http://127.0.0.1:8766

    POST /detect      {"text", "jurisdiction"?, "backend"?}          -> spans, no values
    POST /deidentify  {"text", "jurisdiction"?, "backend"?, "method"?, "salt"?}
                                                                      -> the masked copy + decision_id
    POST /compare     {"a", "b", "entity"?, "jurisdiction"?, "backend"?} -> the receipt
    GET  /decision/{id}  /explain/{id}  /replay/{id}                  -> the ledger, by id
    GET  /livez  /capabilities

What this is and is not. It is the CLI's surface with a socket in front of
it, for a container, a sidecar, or a tool that speaks HTTP and not Python. It
binds ``127.0.0.1`` by default and has **no authentication**: like the studio,
it is meant for the machine holding the data, and exposing it further needs an
auth proxy in front of it -- that is said here rather than implied by a
``--host`` flag that accepts ``0.0.0.0``.

Values leave only where the caller already holds them. ``/detect`` returns
offsets, categories, confidence and citations and never the text of a span;
``/deidentify`` returns the masked copy, which is the point of the call; the
ledger endpoints follow the CLI's masked default and take ``?reveal=true`` to
show record values.

FastAPI is an extra so the base wheel stays a library; ``create_app`` raises
with the install line when it is missing.

Attested answers. With a signing key (``--signing-key`` or
``ARCHE_SIGNING_KEY``, made by ``arche attest keygen``) every POST response
carries ``attestation``: a JWS over the tool, a hash of the request body, a
hash of the rest of the response, the caller and the decision ids. The caller
is the ``X-Arche-Caller`` header when an auth proxy in front sets one, else
the client address. See :mod:`arche.attest` and ``arche attest verify``.
"""

# No `from __future__ import annotations` here: FastAPI resolves a handler's
# annotations by name, and `Request` is imported inside `create_app` so the
# base wheel never imports fastapi. As strings those names would not resolve
# and every body would be read as a query parameter (422 on every POST).
import os
from typing import Any

from pydantic import BaseModel


class DetectRequest(BaseModel):
    """``POST /detect``: the text and, ideally, its jurisdiction."""

    text: str
    jurisdiction: str | None = None
    backend: str = "auto"
    statute: str | None = None


class DeidentifyRequest(DetectRequest):
    """``POST /deidentify``: as ``/detect`` plus how to render, and whether to record."""

    method: str = "statute"
    salt: str = ""
    store: bool = False


class CompareRequest(BaseModel):
    """``POST /compare``: two dicts or two strings, the entity, and whether to record."""

    a: Any
    b: Any
    entity: str = "person"
    jurisdiction: str | None = None
    backend: str = "basic"
    store: bool = False


def _need_fastapi():
    try:
        import fastapi  # noqa: F401
    except ImportError as exc:  # pragma: no cover - exercised without the extra
        raise ImportError(
            "arche serve needs FastAPI. Install it with:\n"
            "    pip install 'arche-core[service]'"
        ) from exc


def create_app(ledger: str | None = None, signing_key: str | None = None):
    """The FastAPI application. ``ledger`` is a DuckDB path or URI; ``None``
    reads ``ARCHE_LEDGER``; without either the ledger endpoints answer 503.
    ``signing_key`` is a PEM path (``None`` reads ``ARCHE_SIGNING_KEY``); with
    one, POST responses carry an attestation."""
    _need_fastapi()
    from fastapi import FastAPI, HTTPException, Query, Request

    from arche import __version__
    from arche.attest import attest, signing_key as _load_key

    keypair = _load_key(signing_key)

    def _attested(tool: str, request: Request, body: dict, response: dict) -> dict:
        """The response, plus its envelope when this installation signs."""
        if keypair is None:
            return response
        caller = request.headers.get("x-arche-caller") or (
            request.client.host if request.client else None)
        return {**response, "attestation": attest(tool, body, response, keypair=keypair,
                                                  caller=caller)}

    app = FastAPI(title="arche", version=__version__,
                  description="Are these the same thing? Find the personal data. Keep the receipt.")
    uri = ledger or os.environ.get("ARCHE_LEDGER")
    if uri and not uri.startswith("duckdb:///"):
        uri = f"duckdb:///{uri}"
    state: dict[str, Any] = {"ledger": None}

    def _ledger():
        if uri is None:
            raise HTTPException(503, "no ledger configured: pass --ledger FILE or set ARCHE_LEDGER")
        if state["ledger"] is None:
            from arche.ledger import attach

            state["ledger"] = attach(uri)
        return state["ledger"]

    def _bad(exc: Exception) -> HTTPException:
        return HTTPException(400, str(exc))

    @app.get("/livez")
    def livez() -> dict:
        return {"ok": True, "version": __version__}

    @app.get("/capabilities")
    def capabilities() -> dict:
        import importlib.util

        return {
            "version": __version__,
            "ledger": uri is not None,
            "model": importlib.util.find_spec("gliner2") is not None,
            "attestation": {"signer": keypair.did_key} if keypair else None,
            "endpoints": ["/detect", "/deidentify", "/compare", "/decision/{id}",
                          "/explain/{id}", "/replay/{id}", "/livez", "/capabilities"],
        }

    @app.post("/detect")
    def detect(req: DetectRequest, request: Request) -> dict:
        from arche.protect import detect_pii

        try:
            found = detect_pii(req.text, req.jurisdiction, backend=req.backend,
                               statute=req.statute)
        except (ValueError, ImportError) as exc:
            raise _bad(exc) from None
        return _attested("detect", request, req.model_dump(), {
            "count": len(found),
            "detections": [
                {"category": d.category, "start": d.start, "end": d.end,
                 "confidence": round(float(d.confidence), 4),
                 "citation": d.regulatory_citation, "detector": d.detector}
                for d in found
            ],
        })

    @app.post("/deidentify")
    def deidentify(req: DeidentifyRequest, request: Request) -> dict:
        from arche.protect import deidentify as _deidentify

        try:
            safe = _deidentify(req.text, req.jurisdiction, backend=req.backend,
                               method=req.method, statute=req.statute, salt=req.salt,
                               store=_ledger() if req.store else None)
        except (ValueError, ImportError) as exc:
            raise _bad(exc) from None
        return _attested("deidentify", request, req.model_dump(), {
            "text": safe.text,
            "decision_id": safe.decision_id,
            "jurisdiction": safe.jurisdiction,
            "statute": safe.statute,
            "backend": safe.backend,
            "model": safe.pins.get("model"),
            "method": safe.method,
            "count": safe.count,
            "by_category": safe.by_category(),
            "spans": safe.spans(),
            "record": safe.record(),
            "recorded": req.store,
        })

    @app.post("/compare")
    def compare(req: CompareRequest, request: Request) -> dict:
        from arche.resolve import compare as _compare

        kwargs: dict[str, Any] = {"entity": req.entity}
        if req.jurisdiction:
            kwargs["jurisdiction"] = req.jurisdiction
        if isinstance(req.a, str) and isinstance(req.b, str):
            kwargs["backend"] = req.backend
        try:
            receipt = _compare(req.a, req.b, store=_ledger() if req.store else None, **kwargs)
        except (ValueError, TypeError, ImportError) as exc:
            raise _bad(exc) from None
        return _attested("compare", request, req.model_dump(), {
            "identity": receipt.identity, "action": receipt.action, "basis": receipt.basis,
            "explanation": receipt.explanation, "score": float(receipt.score),
            "factors": dict(receipt.factors), "decision_id": receipt.decision_id,
            "pins": dict(receipt.pins), "recorded": req.store,
        })

    @app.get("/decision/{decision_id}")
    def decision(decision_id: str, reveal: bool = Query(False)) -> dict:
        from arche.cli import _decision_payload

        try:
            found = _ledger().decision(decision_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from None
        return _decision_payload(found, reveal)

    @app.get("/explain/{decision_id}")
    def explain(decision_id: str, reveal: bool = Query(False)) -> dict:
        from arche.cli import _shown

        try:
            why = _ledger().explain(decision_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from None
        if "shared" in why:
            why = {**why, "shared": _shown(why["shared"], reveal)}
        return why

    @app.get("/replay/{decision_id}")
    def replay(decision_id: str) -> dict:
        try:
            result = _ledger().replay(decision_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from None
        except ValueError as exc:
            raise _bad(exc) from None
        return {"decision_id": decision_id, "reproduced": result.reproduced,
                "changed": result.changed,
                "now": {k: v for k, v in result.now.items() if k != "pins"}}

    return app


def serve(host: str = "127.0.0.1", port: int = 8766, ledger: str | None = None,
          signing_key: str | None = None) -> int:
    """Run the service with uvicorn. Says what it binds and that there is no auth."""
    _need_fastapi()
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover
        raise ImportError("arche serve needs uvicorn: pip install 'arche-core[service]'") from exc
    app = create_app(ledger, signing_key)
    print(f"  arche serve   ->  http://{host}:{port}   (no authentication; keep it local "
          f"or put an auth proxy in front)")
    print(f"  ledger        ->  {ledger or os.environ.get('ARCHE_LEDGER') or 'none'}")
    key = signing_key or os.environ.get("ARCHE_SIGNING_KEY")
    print(f"  attestation   ->  {key or 'none (arche attest keygen FILE; ARCHE_SIGNING_KEY)'}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


__all__ = ["create_app", "serve"]
