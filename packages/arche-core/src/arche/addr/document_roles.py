# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Document address roles — which address on a business document is which.

``extract_document_address_roles(text)`` finds the addresses printed on an
invoice, remittance advice, purchase order, supplier form or letterhead and
labels each with the role it plays on that document:

* ``registered_office`` — the statutory address on the company register
* ``invoice_from``      — the issuer / seller / supplier address
* ``remit_to``          — where payment or remittance goes
* ``bill_to``           — the invoiced party
* ``ship_to``           — where goods are delivered
* ``trading_address``   — where the business operates
* ``unknown``           — no cue, a negated cue, or cues that disagree

It is the document analogue of :func:`arche.addr.extract_places` (spatial role
labelling) and shares its discipline: every committed role names the cue that
decided it, the rule id, and the pin of the cue vocabulary
(``document_address_roles.yaml``); absent or conflicting cues abstain rather
than guess. An extractor that files a remit-to address as the supplier's
trading site produces a false merge downstream; one that says ``unknown``
produces a review.

How it reads a document
-----------------------
Documents put addresses on several lines under a field label::

    Bill To:
    Example Buyer Ltd
    12 High Street
    London EC1A 1BB

The address parser works on comma-separated tails, so line breaks inside an
address block are read as commas. A line break stays a boundary where the next
line is blank, is a field label (``Tel:``, ``Invoice No:``, any ``Word:``), or
starts with document boilerplate (``VAT``, ``Company No``, ``IBAN`` ...). The
substitution is one character for one, so every offset still points into the
original text.

Cues come in two forms. A **label** sits at the start of a line and is
followed by ``:`` or a line end (``Ship to:``); a **prose** cue sits inside a
sentence ("please remit payment to"). Words that are ordinary prose elsewhere
(``from``, ``to``, ``supplier``, ``customer``) are ``label_only`` in the pack
and count only as labels. A cue binds the first address after it within
``max_gap`` characters and ``max_gap_lines`` line breaks, never across a blank
line, and never past another cue unless only separators lie between them
(``Bill to / Ship to:``), in which case both bind and the address abstains.

Not handled (abstains or misses, never guesses): two address columns side by
side on one line, addresses with no street, number, postcode or comma tail,
and tables that interleave labels and values.

Public API::

    from arche.addr import extract_document_address_roles

    for m in extract_document_address_roles(invoice_text):
        m.role, m.text, m.cue, m.cue_rule, m.confidence
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from arche.addr.parse import (
    _GB_POSTCODE,
    Address,
    AddressComponents,
    normalise_gb_postcode,
    parse_address,
    parse_addresses,
)
from arche.addr.roles import (
    _NEGATION_RE,
    GoldPlace,
    GoldSentence,
    PlaceGrade,
    RolePackError,
    _resolve_cue_fragment,
    _resolve_fragment,
    grade_places,
)

DocumentAddressRole = Literal[
    "registered_office", "invoice_from", "remit_to", "bill_to", "ship_to",
    "trading_address", "unknown",
]
DOCUMENT_ROLES: tuple[str, ...] = (
    "registered_office", "invoice_from", "remit_to", "bill_to", "ship_to",
    "trading_address",
)
_ROLES = frozenset(DOCUMENT_ROLES) | {"unknown"}

# (cue tier, span tier) -> ordinal confidence label, not a probability.
# cue tier: 2 label, 1 prose, 0 none/conflict/negated. span tier: 2 the
# address has a number, plot or postcode; 1 it does not.
_CONFIDENCE = {(2, 2): 0.95, (2, 1): 0.80, (1, 2): 0.80, (1, 1): 0.60}
_UNKNOWN_CONFIDENCE = 0.25

# A line that starts a new field rather than continuing an address block.
_LABEL_LINE_RE = re.compile(r"^\s*[A-Za-z][\w .'/&()#-]{0,40}:")
_BOILERPLATE_LINE_RE = re.compile(
    r"^\s*(?:tel|telephone|phone|mobile|fax|e-?mail|web|website|www\.|https?:"
    r"|vat|company\s+(?:no|number|reg)|registration|reg\.?\s+no|registered\s+in"
    r"|invoice|date|due|account|acct|sort\s+code|iban|swift|bic|bank"
    r"|reference|ref\b|po\b|p\.o\.\s+number|order|total|subtotal|amount"
    r"|page|description|qty|quantity|terms|payment\s+terms|thank)",
    re.IGNORECASE,
)
_BLANK_LINE_RE = re.compile(r"\n[ \t]*\n")
_SEPARATORS_RE = re.compile(r"^(?:[\s/&,:;|+-]|\band\b)*$", re.IGNORECASE)
_GB_POSTCODE_IN_TEXT_RE = re.compile(r"(?<![A-Za-z0-9])" + _GB_POSTCODE + r"\b")
_LINE_PREFIX_OK_RE = re.compile(r"^[\s*•·\-–>#\d.)]*$")


# ---------------------------------------------------------------------------
# The pack
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DocumentRoleRule:
    id: str
    role: str
    cues: tuple[str, ...]
    label_only: bool = False
    priority: int = 50


@dataclass(frozen=True)
class DocumentRolePack:
    name: str
    version: str
    rules: tuple[DocumentRoleRule, ...]
    max_gap: int = 120
    max_gap_lines: int = 3

    @property
    def pin(self) -> str:
        """``name@version:sha256:<16 hex>`` over the normalised rule list."""
        from arche.ids import canonical_json

        payload = {
            "pack": self.name, "version": self.version,
            "max_gap": self.max_gap, "max_gap_lines": self.max_gap_lines,
            "rules": [
                {"id": r.id, "role": r.role, "cues": list(r.cues),
                 "label_only": r.label_only, "priority": r.priority}
                for r in self.rules
            ],
        }
        digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:16]
        return f"{self.name}@{self.version}:sha256:{digest}"


_PACK_CACHE: dict[str, DocumentRolePack] = {}


def load_document_role_pack(path: str | Path | None = None) -> DocumentRolePack:
    """Load and validate a document-address cue pack (module-cached).

    A malformed pack raises :class:`RolePackError` naming the offending rule;
    a silently skipped rule would change role assignments without a trace.
    """
    if path is None:
        path = Path(__file__).resolve().parent / "document_address_roles.yaml"
    path = Path(path)
    key = str(path)
    if key in _PACK_CACHE:
        return _PACK_CACHE[key]
    import yaml

    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except OSError as exc:
        raise RolePackError(f"cannot read document role pack {path}: {exc}") from exc
    for req in ("pack", "version", "rules"):
        if req not in data:
            raise RolePackError(f"{path}: missing required key {req!r}")

    rules: list[DocumentRoleRule] = []
    seen: set[str] = set()
    for i, raw in enumerate(data["rules"]):
        where = f"{path}: rules[{i}]"
        rid = raw.get("id")
        if not rid:
            raise RolePackError(f"{where}: missing id")
        if rid in seen:
            raise RolePackError(f"{where}: duplicate rule id {rid!r}")
        seen.add(rid)
        role = raw.get("role")
        if role not in DOCUMENT_ROLES:
            raise RolePackError(
                f"{where} ({rid}): unknown role {role!r}; valid: {list(DOCUMENT_ROLES)}")
        cues = tuple(str(c).strip().lower() for c in (raw.get("cues") or ()) if str(c).strip())
        if not cues:
            raise RolePackError(f"{where} ({rid}): missing cues")
        rules.append(DocumentRoleRule(
            id=str(rid), role=str(role), cues=cues,
            label_only=bool(raw.get("label_only", False)),
            priority=int(raw.get("priority", 50)),
        ))

    # One phrase, one form, two roles at one priority: the pack contradicts
    # itself, which is a pack bug and not a document ambiguity.
    claim: dict[tuple[str, bool, int], tuple[str, str]] = {}
    for r in rules:
        for cue in r.cues:
            k = (cue, r.label_only, r.priority)
            prev = claim.get(k)
            if prev and prev[1] != r.role:
                raise RolePackError(
                    f"{path}: cue {cue!r} maps to {prev[1]!r} (rule {prev[0]}) and "
                    f"{r.role!r} (rule {r.id}) at priority {r.priority}")
            claim[k] = (r.id, r.role)

    pack = DocumentRolePack(
        name=str(data["pack"]), version=str(data["version"]), rules=tuple(rules),
        max_gap=int(data.get("max_gap", 120)),
        max_gap_lines=int(data.get("max_gap_lines", 3)),
    )
    _PACK_CACHE[key] = pack
    return pack


# ---------------------------------------------------------------------------
# Output shape
# ---------------------------------------------------------------------------


@dataclass
class DocumentAddressMention:
    """One address on a document, its role, and the cue that decided it.

    ``text`` is the original slice (line breaks kept). ``cue_form`` is
    ``label`` or ``prose``. Invariant: ``source[cue_span[0]:cue_span[1]] ==
    cue`` whenever ``cue`` is not None.
    """

    role: DocumentAddressRole
    text: str
    span: tuple[int, int]
    cue: str | None
    cue_span: tuple[int, int] | None
    cue_rule: str | None
    cue_phrase: str | None
    cue_form: str | None
    confidence: float
    evidence: tuple[str, ...]
    address: Address | None
    jurisdiction: str
    jurisdiction_confidence: float
    pack: str = ""

    @property
    def components(self) -> AddressComponents | None:
        return self.address.components if self.address else None

    def to_dict(self, *, reveal: bool = True) -> dict[str, Any]:
        """JSON-ready dict. ``reveal=False`` carries offsets, the canonical cue
        phrase and component *names*, never the address text or values."""
        base: dict[str, Any] = {
            "role": self.role, "start": self.span[0], "end": self.span[1],
            "cue": self.cue_phrase,
            "cue_start": self.cue_span[0] if self.cue_span else None,
            "cue_end": self.cue_span[1] if self.cue_span else None,
            "cue_rule": self.cue_rule, "cue_form": self.cue_form,
            "confidence": self.confidence, "evidence": list(self.evidence),
            "jurisdiction": self.jurisdiction,
            "jurisdiction_confidence": self.jurisdiction_confidence,
            "pack": self.pack,
        }
        comps = {k: v for k, v in vars(self.components).items() if v} \
            if self.components else {}
        if reveal:
            base["text"] = self.text
            base["cue"] = self.cue
            base["components"] = comps
        else:
            base["components_present"] = sorted(comps)
        return base


# ---------------------------------------------------------------------------
# Spans
# ---------------------------------------------------------------------------


def _shadow(text: str) -> str:
    """``text`` with in-block line breaks read as commas, offsets preserved."""
    chars = list(text.replace("\r", " "))
    lines = text.replace("\r", " ").split("\n")
    pos = 0
    for i, line in enumerate(lines[:-1]):
        pos += len(line)                     # index of this "\n"
        nxt = lines[i + 1]
        if (line.strip() and nxt.strip()
                and not _LABEL_LINE_RE.match(nxt)
                and not _BOILERPLATE_LINE_RE.match(nxt)
                and not _BOILERPLATE_LINE_RE.match(line)):
            chars[pos] = ","
        pos += 1
    return "".join(chars)


@dataclass
class _Span:
    start: int
    end: int
    tier: int
    address: Address | None


def _detect_spans(text: str, shadow: str, cue_ends: Sequence[int]) -> list[_Span]:
    spans: list[_Span] = []
    for addr in parse_addresses(shadow):
        start, end = addr.span
        # A remaining line break is a real boundary; never run across it.
        nl = shadow.find("\n", start, end)
        if nl != -1:
            end = nl
        while end > start and shadow[end - 1] in " ,\t":
            end -= 1
        if end <= start:
            continue
        if (start, end) != addr.span:
            addr = parse_address(shadow[start:end]) or addr
            addr.span = (start, end)
        c = addr.components
        strong = bool(c.street_number or c.plot or c.postal_code)
        if not strong and "," not in shadow[start:end]:
            continue                          # a bare "High Street"
        spans.append(_Span(start, end, 2 if strong else 1, addr))

    # A GB postcode the parser could not anchor (no street suffix: "Unit 4,
    # Trafford Park, Manchester M17 1AB") still marks an address block. The
    # block runs back to the line break, label colon or cue before it.
    for m in _GB_POSTCODE_IN_TEXT_RE.finditer(shadow):
        if any(s.start <= m.start() < s.end for s in spans):
            continue
        floor = max(shadow.rfind("\n", 0, m.start()), shadow.rfind(":", 0, m.start()),
                    max((e for e in cue_ends if e <= m.start()), default=-1) - 1,
                    m.start() - 160)
        start = floor + 1
        while start < m.start() and shadow[start] in " ,\t":
            start += 1
        addr = parse_address(shadow[start:m.end()])
        if addr is None:
            addr = Address(raw=text[start:m.end()], span=(start, m.end()),
                           components=AddressComponents(), confidence=0.3)
        addr.span = (start, m.end())
        if addr.components.postal_code is None:
            addr.components.postal_code = normalise_gb_postcode(m.group(0))
            if addr.country_inferred is None:
                addr.country_inferred, addr.country_confidence = "GB", 0.95
        spans.append(_Span(start, m.end(), 2, addr))

    spans.sort(key=lambda s: (s.start, -(s.end - s.start)))
    kept: list[_Span] = []
    for s in spans:
        if any(s.start < k.end and k.start < s.end for k in kept):
            continue
        kept.append(s)
    return kept


# ---------------------------------------------------------------------------
# Cues
# ---------------------------------------------------------------------------


@dataclass
class _Cue:
    start: int
    end: int
    phrase: str
    form: str                        # label | prose
    rule: DocumentRoleRule


def _scan_cues(text: str, pack: DocumentRolePack) -> list[_Cue]:
    by_phrase: dict[str, list[DocumentRoleRule]] = {}
    for r in pack.rules:
        for c in r.cues:
            by_phrase.setdefault(c, []).append(r)
    phrases = sorted(by_phrase, key=len, reverse=True)
    # Words of a phrase may be separated by any run of spaces or tabs, never
    # by a line break: "INVOICE\nFrom:" is a title and a label, not the
    # phrase "invoice from".
    words = [[re.escape(w) for w in p.split()] for p in phrases]
    pattern = re.compile(
        r"(?<![\w])(?:" + "|".join(r"[ \t]+".join(ws) for ws in words)
        + r")(?![\w])", re.IGNORECASE)
    out: list[_Cue] = []
    for m in pattern.finditer(text):
        phrase = re.sub(r"\s+", " ", m.group(0).lower())
        rules = by_phrase.get(phrase)
        if not rules:
            continue
        line_start = text.rfind("\n", 0, m.start()) + 1
        after = text[m.end():]
        is_label = bool(_LINE_PREFIX_OK_RE.match(text[line_start:m.start()])) and bool(
            re.match(r"[ \t]*(?::|-\s|\n|$)", after))
        chosen = None
        if is_label:
            chosen = next((r for r in rules if r.label_only), None)
        if chosen is None:
            chosen = next((r for r in rules if not r.label_only), None)
        if chosen is None:
            continue                          # a label-only word used as prose
        out.append(_Cue(m.start(), m.end(), phrase, "label" if is_label else "prose",
                        chosen))
    return out


def _gap_ok(text: str, cue: _Cue, span: _Span, cues: Sequence[_Cue],
            pack: DocumentRolePack) -> bool:
    if span.start < cue.end:
        return False
    gap = text[cue.end:span.start]
    if len(gap) > pack.max_gap or gap.count("\n") > pack.max_gap_lines:
        return False
    if _BLANK_LINE_RE.search(gap):
        return False
    between = [c for c in cues if cue.end <= c.start and c.end <= span.start]
    if between:
        # Only separators may lie between this cue and the next ones
        # ("Bill to / Ship to:"); then they all bind and the address abstains.
        cursor, rest = cue.end, []
        for c in between:
            rest.append(text[cursor:c.start])
            cursor = c.end
        if not all(_SEPARATORS_RE.match(r) for r in rest):
            return False
    return True


@dataclass
class _Binding:
    cue: _Cue
    negated: bool


# ---------------------------------------------------------------------------
# extract_document_address_roles
# ---------------------------------------------------------------------------


def extract_document_address_roles(
    text: str, *, rules: DocumentRolePack | None = None,
) -> list[DocumentAddressMention]:
    """Every address on a business document, with its role and deciding cue.

    Returns mentions sorted by offset; spans never overlap. A mention whose
    cue is absent, negated or contradicted carries ``role="unknown"`` and
    floor confidence.
    """
    if not text or not text.strip():
        return []
    pack = rules or load_document_role_pack()
    shadow = _shadow(text)
    cues = _scan_cues(text, pack)
    spans = _detect_spans(text, shadow, [c.end for c in cues])
    # A cue inside an address ("Delivery Road") is part of the address.
    cues = [c for c in cues if not any(s.start <= c.start < s.end for s in spans)]

    bindings: dict[int, list[_Binding]] = {}
    for cue in cues:
        target = None
        for i, s in enumerate(spans):
            if _gap_ok(text, cue, s, cues, pack) and (
                    target is None or s.start < spans[target].start):
                target = i
        if target is None:
            continue
        line_start = text.rfind("\n", 0, cue.start) + 1
        before = text[max(line_start, cue.start - 32):cue.start]
        bindings.setdefault(target, []).append(
            _Binding(cue, bool(_NEGATION_RE.search(before))))

    out = [_resolve(text, s, bindings.get(i, []), pack) for i, s in enumerate(spans)]
    out.sort(key=lambda m: m.span[0])
    return out


def _resolve(text: str, s: _Span, cands: list[_Binding],
             pack: DocumentRolePack) -> DocumentAddressMention:
    evidence = ["span:parsed" if s.tier == 2 else "span:weak"]
    role: str = "unknown"
    chosen: _Binding | None = None
    cue_tier = 0
    if cands:
        top = max(b.cue.rule.priority for b in cands)
        kept = [b for b in cands if b.cue.rule.priority == top]
        roles = {b.cue.rule.role for b in kept}
        chosen = max(kept, key=lambda b: b.cue.end)      # the nearest cue
        if len(roles) > 1:
            ids = "|".join(sorted({b.cue.rule.id for b in kept}))
            evidence.append(f"cue_conflict:{ids}")
        elif chosen.negated:
            evidence.append("cue:negated")
        else:
            role = chosen.cue.rule.role
            cue_tier = 2 if chosen.cue.form == "label" else 1
            evidence.append(f"cue:{chosen.cue.form}")
    else:
        evidence.append("cue:absent")

    confidence = _CONFIDENCE[(cue_tier, s.tier)] if cue_tier else _UNKNOWN_CONFIDENCE
    addr = s.address
    juris = (addr.country_inferred if addr else None) or "XX"
    juris_conf = addr.country_confidence if addr else 0.0
    cue = chosen.cue if chosen else None
    return DocumentAddressMention(
        role=role,  # type: ignore[arg-type]
        text=text[s.start:s.end], span=(s.start, s.end),
        cue=text[cue.start:cue.end] if cue else None,
        cue_span=(cue.start, cue.end) if cue else None,
        cue_rule=cue.rule.id if cue else None,
        cue_phrase=cue.phrase if cue else None,
        cue_form=cue.form if cue else None,
        confidence=confidence, evidence=tuple(evidence), address=addr,
        jurisdiction=juris, jurisdiction_confidence=juris_conf, pack=pack.pin,
    )


# ---------------------------------------------------------------------------
# Gold set and grader
# ---------------------------------------------------------------------------


def load_document_gold(name: str = "document_address_roles_v1") -> list[GoldSentence]:
    """The labelled synthetic document set shipped in the wheel.

    Each entry is a :class:`GoldSentence` whose ``text`` is a whole document
    and whose ``places`` are its addresses. Fragments are substrings; the
    loader resolves them to spans and rejects absent or ambiguous ones.
    """
    import yaml

    path = Path(__file__).resolve().parent / "_eval" / f"{name}.yaml"
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    docs: list[GoldSentence] = []
    for raw in data.get("documents", []):
        did, text = raw["id"], raw["text"]
        places: list[GoldPlace] = []
        for a in raw.get("addresses") or []:
            if a["role"] not in _ROLES:
                raise RolePackError(f"gold {did}: unknown role {a['role']!r}")
            span = _resolve_fragment(text, a["text"], did, "address")
            cue = a.get("cue")
            cue_span = _resolve_cue_fragment(text, cue, span, did) if cue else None
            places.append(GoldPlace(role=a["role"], text=a["text"], span=span,
                                    cue=cue, cue_span=cue_span))
        docs.append(GoldSentence(id=did, text=text, register=raw.get("register", ""),
                                 jurisdiction=raw.get("jurisdiction", ""),
                                 places=tuple(places), note=raw.get("note", "")))
    return docs


def grade_document_addresses(
    gold: Sequence[GoldSentence],
    predictions: Mapping[str, Sequence[Any]],
    *,
    match: Literal["overlap", "exact"] = "overlap",
    pack: str | None = None,
) -> PlaceGrade:
    """Score any extractor's document-address output against a gold set.

    Same refusal accounting as :func:`arche.addr.grade_places`: ``unknown``
    where gold committed is ``missed_by_abstention`` (a non-answer); a
    committed role where gold is ``unknown`` is ``over_guess`` and a false
    positive. Predictions are mentions or plain dicts with
    ``start``/``end``/``role``.
    """
    return grade_places(gold, predictions, match=match, pack=pack, roles=DOCUMENT_ROLES)


__all__ = [
    "DOCUMENT_ROLES", "DocumentAddressMention", "DocumentAddressRole",
    "DocumentRolePack", "DocumentRoleRule", "extract_document_address_roles",
    "grade_document_addresses", "load_document_gold", "load_document_role_pack",
]
