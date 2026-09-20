# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""``arche serve``: the same verbs over HTTP, on the machine that has the data.

    pip install "arche-core[service]"
    arche serve                      # http://127.0.0.1:8766

    POST /detect      {"text", "jurisdiction"?, "backend"?}          -> spans, no values
    POST /deidentify  {"text", "jurisdiction"?, "backend"?, "method"?, "salt"?}
                                                                    -> the masked copy + decision_id
    POST /compare     {"a", "b", "entity"?, "jurisdiction"?, "backend"?} -> the receipt
    POST /documents   multipart files + entity?, jurisdiction?, backend?, store?
                                                  -> one record per document, resolved, masked
    POST /places      {"text"}                    -> place mentions with their spatial role
    POST /extract     {"text", "entity_types"?, "backend"?}      -> proposed entities
    GET  /decision/{id}  /explain/{id}  /replay/{id}                  -> the ledger, by id
    GET  /livez  /capabilities

Documents. ``/documents`` is :func:`arche.resolve_documents` with a socket in
front: parse (plain text natively; PDF, DOCX and scanned pages through the
``doc`` / ``doc-ocr`` extras), detect under the document's own jurisdiction,
extract names and places, and resolve each document against the others -- or
against ``candidates`` -- into a verdict. Values come back masked unless
``reveal=true``, the CLI's default.

Warm start. Every model and parser loads lazily on first use, which on a
fresh container is a thirty-second first request. ``--warm`` (or
``ARCHE_WARM=1``) loads GLiNER 2, GLiNER2-PII and the docling converter at
startup so the first document is as fast as the hundredth; ``/livez`` reports
``warm: true`` once that has finished. :func:`warm` is public so an image
build can call it and ship the weights.

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


class PlacesRequest(BaseModel):
    """``POST /places``: free text; back come place mentions and their roles."""

    text: str


class ExtractRequest(BaseModel):
    """``POST /extract``: free text and the entity types to propose."""

    text: str
    entity_types: list[str] | None = None
    backend: str = "auto"


def warm(*, models: bool = True, parsers: bool = True) -> dict[str, Any]:
    """Load what the first request would otherwise load, and say what loaded.

    Each part is optional and each absence is reported rather than raised: a
    container without the ``detect2`` extra still serves the basic detectors,
    and a container without ``doc`` still parses plain text. The dictionary is
    what ``/capabilities`` reports under ``warm``.
    """
    import importlib.util
    import logging

    log = logging.getLogger("arche.serve")
    loaded: dict[str, Any] = {}
    if models and importlib.util.find_spec("gliner2") is not None:
        from arche._models import get_gliner2
        from arche.config import get_config

        cfg = get_config()
        for name in (cfg.gliner2_pii_model, cfg.gliner2_model):
            try:
                get_gliner2(name)
                loaded[name] = True
            except Exception as exc:  # noqa: BLE001 - a warm-up must not kill the service
                log.warning("warm: %s did not load: %s", name, exc)
                loaded[name] = f"{type(exc).__name__}: {exc}"
    if parsers and importlib.util.find_spec("docling") is not None:
        try:
            from docling.document_converter import DocumentConverter

            # Constructing the converter is what pulls docling's layout and
            # table models on first use; doing it here is the whole point.
            DocumentConverter()
            loaded["docling"] = True
        except Exception as exc:  # noqa: BLE001
            log.warning("warm: docling did not initialise: %s", exc)
            loaded["docling"] = f"{type(exc).__name__}: {exc}"
    return loaded


def _parsers() -> dict[str, bool]:
    """Which document parsers this installation has, by extra."""
    import importlib.util

    return {
        "text": True,
        "pdf": importlib.util.find_spec("pypdf") is not None
        or importlib.util.find_spec("fitz") is not None,
        "docx": importlib.util.find_spec("docx") is not None,
        "docling": importlib.util.find_spec("docling") is not None,
        "ocr": importlib.util.find_spec("rapidocr_onnxruntime") is not None,
    }


def _need_fastapi():
    try:
        import fastapi  # noqa: F401
    except ImportError as exc:  # pragma: no cover - exercised without the extra
        raise ImportError(
            "arche serve needs FastAPI. Install it with:\n"
            "    pip install 'arche-core[service]'"
        ) from exc


def create_app(ledger: str | None = None, signing_key: str | None = None,
               warm_start: bool | None = None):
    """The FastAPI application. ``ledger`` is a DuckDB path or URI; ``None``
    reads ``ARCHE_LEDGER``; without either the ledger endpoints answer 503.
    ``signing_key`` is a PEM path (``None`` reads ``ARCHE_SIGNING_KEY``); with
    one, POST responses carry an attestation. ``warm_start`` (``None`` reads
    ``ARCHE_WARM``) loads models and parsers at startup rather than on the
    first request."""
    _need_fastapi()
    from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile

    from arche import __version__
    from arche.attest import attest
    from arche.attest import signing_key as _load_key

    keypair = _load_key(signing_key)

    def _attested(tool: str, request: Request, body: dict, response: dict) -> dict:
        """The response, plus its envelope when this installation signs."""
        if keypair is None:
            return response
        caller = request.headers.get("x-arche-caller") or (
            request.client.host if request.client else None)
        return {**response, "attestation": attest(tool, body, response, keypair=keypair,
                                                  caller=caller)}

    from contextlib import asynccontextmanager

    if warm_start is None:
        warm_start = os.environ.get("ARCHE_WARM", "").lower() in ("1", "true", "yes")
    state: dict[str, Any] = {"ledger": None, "warm": None}

    @asynccontextmanager
    async def _lifespan(_app):
        if warm_start:
            state["warm"] = warm()
        yield

    app = FastAPI(title="arche", version=__version__,
                  description="Are these the same thing? Find the personal data. Keep the receipt.",
                  lifespan=_lifespan)
    uri = ledger or os.environ.get("ARCHE_LEDGER")
    if uri and not uri.startswith("duckdb:///"):
        uri = f"duckdb:///{uri}"

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
        return {"ok": True, "version": __version__,
                "warm": bool(state["warm"]) if warm_start else None}

    @app.get("/capabilities")
    def capabilities() -> dict:
        import importlib.util

        return {
            "version": __version__,
            "ledger": uri is not None,
            "model": importlib.util.find_spec("gliner2") is not None,
            "parsers": _parsers(),
            "warm": state["warm"],
            "attestation": {"signer": keypair.did_key} if keypair else None,
            "endpoints": ["/detect", "/deidentify", "/compare", "/documents", "/places",
                          "/extract", "/decision/{id}", "/explain/{id}", "/replay/{id}",
                          "/livez", "/capabilities"],
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

    @app.post("/documents")
    async def documents(request: Request,
                        files: list[UploadFile] = File(...),  # noqa: B008 - FastAPI's own idiom
                        entity: str = Form("person"),
                        jurisdiction: str = Form("auto"),
                        backend: str = Form("auto"),
                        store: bool = Form(False),
                        reveal: bool = Form(False)) -> dict:
        """Parse, detect, extract and resolve the uploaded documents.

        Files are written to a private temporary directory that is removed
        when the response is built; nothing is kept unless ``store`` records
        the decisions in the ledger. The suffix is preserved because it is
        what selects the parser.
        """
        import shutil
        import tempfile
        from pathlib import Path

        from arche.doc import resolve_documents
        from arche.doc.parse import DoclingNotInstalledError

        names = [Path(f.filename or f"document-{n}").name for n, f in enumerate(files)]
        if len(set(names)) != len(names):
            dupes = sorted({n for n in names if names.count(n) > 1})
            # `resolve_documents` keys every record by the file's name, so a
            # second `doc.txt` would silently replace the first in the report.
            # Refusing is the honest answer; renaming on the caller's behalf
            # would put a name they never sent into a signed receipt.
            raise HTTPException(400, f"two uploads share a name: {', '.join(dupes)}; "
                                     "rename one, the report is keyed by file name")
        tmp = Path(tempfile.mkdtemp(prefix="arche-docs-"))
        try:
            # One subdirectory per upload, so every document keeps the name
            # the caller sent: the report keys on `path.name`, and a numeric
            # prefix leaked into the decisions the first time this was written.
            paths = []
            for n, upload in enumerate(files):
                name = Path(upload.filename or f"document-{n}").name
                target = tmp / f"{n:03d}" / name
                target.parent.mkdir()
                target.write_bytes(await upload.read())
                paths.append(target)
            try:
                report = resolve_documents(
                    paths, entity=entity, jurisdiction=jurisdiction,
                    extraction_backend=backend, progress=False,
                    store=_ledger() if store else None)
            except (ValueError, ImportError, DoclingNotInstalledError) as exc:
                # An absent parser is raised once by `resolve_documents`
                # rather than reported per document, so it is a 400 naming
                # the extra rather than a report that reads as "found nothing".
                raise _bad(exc) from None
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        body = {"count": len(files), "entity": entity, "jurisdiction": jurisdiction,
                "backend": backend, "store": store, "reveal": reveal,
                "files": [Path(f.filename or "").name for f in files]}
        return _attested("documents", request, body, {
            "entity": report.entity,
            "jurisdiction": report.jurisdiction,
            "jurisdictions": report.jurisdictions,
            "documents": report.to_dicts(reveal=reveal),
            "decisions": report.decisions,
            "unlinked": report.unlinked(),
            "review": report.review(reveal=reveal),
            "errors": report.errors,
            "recorded": store,
        })

    @app.post("/places")
    def places(req: PlacesRequest, request: Request) -> dict:
        from arche import extract_places

        try:
            mentions = extract_places(req.text)
        except (ValueError, ImportError) as exc:
            raise _bad(exc) from None
        return _attested("places", request, req.model_dump(), {
            "count": len(mentions),
            "mentions": [m.to_dict() if hasattr(m, "to_dict") else
                         {k: getattr(m, k) for k in ("text", "start", "end", "role",
                                                     "confidence", "cue", "rule")
                          if hasattr(m, k)}
                         for m in mentions],
        })

    @app.post("/extract")
    def extract_(req: ExtractRequest, request: Request) -> dict:
        from arche import extract

        try:
            result = extract(req.text, req.entity_types, backend=req.backend)
        except (ValueError, ImportError) as exc:
            raise _bad(exc) from None
        import dataclasses

        entities = [dataclasses.asdict(e) if dataclasses.is_dataclass(e) else e
                    for e in result]
        return _attested("extract", request, req.model_dump(), {
            "backend": req.backend, "count": len(entities), "entities": entities,
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
          signing_key: str | None = None, warm_start: bool | None = None) -> int:
    """Run the service with uvicorn. Says what it binds and that there is no auth."""
    _need_fastapi()
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover
        raise ImportError("arche serve needs uvicorn: pip install 'arche-core[service]'") from exc
    app = create_app(ledger, signing_key, warm_start=warm_start)
    parsers = ", ".join(k for k, v in _parsers().items() if v)
    print(f"  arche serve   ->  http://{host}:{port}   (no authentication; keep it local "
          f"or put an auth proxy in front)")
    print(f"  ledger        ->  {ledger or os.environ.get('ARCHE_LEDGER') or 'none'}")
    key = signing_key or os.environ.get("ARCHE_SIGNING_KEY")
    print(f"  attestation   ->  {key or 'none (arche attest keygen FILE; ARCHE_SIGNING_KEY)'}")
    print(f"  parsers       ->  {parsers}")
    warm_flag = warm_start if warm_start is not None else os.environ.get("ARCHE_WARM", "")
    warm_on = str(warm_flag).lower() in ("1", "true", "yes")
    print(f"  warm start    ->  {'yes' if warm_on else 'no (--warm or ARCHE_WARM=1)'}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


__all__ = ["create_app", "serve", "warm"]
