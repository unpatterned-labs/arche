# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Who a document is from and who it is to: parties with roles.

An extractor finds people, organisations and addresses; it does not know
which of them a document is *addressed to*. On an invoice that is the whole
question -- the issuer's letterhead address, a sales contact's email and a
second traveller's name all sit beside the customer's, and taking the
highest-confidence person can be the wrong one.

People read the role from layout, and so does this: the top of a document is
split into blocks at role cues --

* customer: ``To``, ``Bill To``, ``Billed To``, ``Sold To``, ``Invoice To``,
  ``Customer``, ``Client``, ``Guest``, ``Passenger``, ``Attn``, and an
  addressee line that opens with an honorific (``MRS ANDREA KROPP 227 N 5TH
  AVE ...``);
* issuer: ``From``, ``Issued by``, ``Seller``, ``Vendor``, ``Supplier``,
  ``Remit to``, and the letterhead (the first lines, before any cue);
* ship to: ``Ship To``;

-- and :func:`arche.extract` reads the name inside each block. A person named
on a line of their own straight after the letterhead (a hotel folio's guest)
is the customer. The party's address is the lines that follow its name in its
block while they look like address lines.

Everything not in a block is ``unassigned`` and yields no party; nothing is
guessed into a role. A block with no name from the extractor takes the first
line under its cue as the name, and calls it an organisation only when it ends
in a company suffix. These cues are a rule set, separate from (and broader
than) the address-only cues in ``arche.addr.document_roles``.
An email outside the customer's block is attached to the customer only when
its local part carries the customer's surname, and says so in ``evidence``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_CUSTOMER_CUE = re.compile(
    r"^\s*(bill(?:ed)?\s*to|sold\s*to|invoice\s*to|customer(?:\s*name)?|client|"
    r"guest(?:\s*name)?|passenger(?:\s*name)?|recipient|attn|attention|to)\b[\s.:]*", re.I)
_SHIP_CUE = re.compile(r"^\s*(ship(?:ped)?\s*to|deliver(?:y)?\s*to)\b[\s.:]*", re.I)
_ISSUER_CUE = re.compile(r"^\s*(from|issued\s*by|seller|vendor|supplier|remit\s*to)\b[\s.:]*",
                         re.I)
_HONORIFIC = re.compile(r"^\s*(mr|mrs|ms|miss|mx|dr|prof)\.?\s+[A-Za-z]", re.I)
#: A segment that reads as part of a postal address.
_ADDRESS_LINE = re.compile(
    r"(^\s*\d+[A-Za-z]?\s+[A-Za-z]"                       # 227 N 5th Ave
    r"|\bP\.?\s?O\.?\s*Box\b"                             # PO Box 1168
    r"|\b[A-Z]{2},?\s+(?:[A-Z]{2}-)?\d{5}(?:-\d{4})?\b"   # WA, 98642 / WA US-98642
    r"|^\s*\d{4,5}\s+[A-Z][a-z]"                          # 63263 Neu-Isenburg
    r"|^[^\W\d][\w .'\-]*\s\d{1,4}[a-z]?\s*$"             # An der Gehespitz 50
    r"|\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b)")           # UK postcode
_NOT_ADDRESS = re.compile(r"\b(tel|fax|phone|e-?mail|www|http|terms|payment|card|page|date|"
                          r"invoice|order|reference|tax|vat|ref|booking|no|number|account)\b", re.I)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_HEAD_LINES = 40
#: Non-address segments allowed between a name and its address (a repeated
#: name, an account label).
_ADDRESS_SKIP = 2


@dataclass(frozen=True)
class Party:
    """One party a document names, with the role its layout gives it."""

    role: str                    # "customer" | "issuer" | "ship_to"
    name: str | None
    kind: str | None             # "person" | "organisation"
    address: str | None
    email: str | None
    cue: str                     # what set the role: "bill to", "from", "letterhead", ...
    start: int                   # the block, as offsets into the document text
    end: int
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_record(self, **extra: Any) -> dict[str, Any]:
        """The party as a record for :func:`arche.compare` / a ledger."""
        rec = {"name": self.name, "address": self.address, "email": self.email}
        return {**{k: v for k, v in rec.items() if v}, **extra}


def _lines(text: str, limit: int) -> list[tuple[int, int, str]]:
    out, pos = [], 0
    for raw in text.splitlines(keepends=True):
        line = raw.rstrip("\r\n")
        if line.strip():
            out.append((pos, pos + len(line), line))
        pos += len(raw)
        if len(out) >= limit:
            break
    return out


def _cue(line: str) -> tuple[str, str, int] | None:
    """(role, cue, length of the cue text) when ``line`` opens a role block."""
    for role, pattern in (("ship_to", _SHIP_CUE), ("issuer", _ISSUER_CUE),
                          ("customer", _CUSTOMER_CUE)):
        m = pattern.match(line)
        if m:
            return role, re.sub(r"\s+", " ", m.group(1).lower()), m.end()
    return None


def _is_address(segment: str) -> bool:
    return bool(_ADDRESS_LINE.search(segment)) and not _NOT_ADDRESS.search(segment) \
        and not _EMAIL.search(segment)


def _blocks(text: str) -> list[dict[str, Any]]:
    """Role blocks over the head of the document, in order.

    A cue line opens a block that runs to the next cue. An addressee line
    (``MRS ...``) is a block of its own plus the address lines under it. Lines
    before any cue are the letterhead; lines after a closed addressee block are
    the letterhead if there has not been one, else unassigned.
    """
    lines = _lines(text, _HEAD_LINES)
    for i, (_, _, line) in enumerate(lines):   # a table row: the body starts
        if line.lstrip().startswith("|"):
            lines = lines[:i]
            break
    blocks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    letterhead = False

    def open_block(role: str, cue: str, start: int, end: int, line: str) -> dict[str, Any]:
        block = {"role": role, "cue": cue, "start": start, "end": end,
                 "lines": [(start, end, line)]}
        blocks.append(block)
        return block

    for start, end, line in lines:
        cue = _cue(line)
        if cue:
            current = open_block(cue[0], cue[1], start, end, line)
        elif _HONORIFIC.match(line):
            current = open_block("customer", "addressee", start, end, line)
        elif current is not None and current["cue"] == "addressee" and not _is_address(line):
            current = None
        if current is None:
            current = open_block("unassigned" if letterhead else "issuer",
                                 "unassigned" if letterhead else "letterhead", start, end, line)
            letterhead = True
        elif current["lines"][-1][0] != start:
            current["lines"].append((start, end, line))
            current["end"] = end
    return blocks


def _entities(text: str, backend: str) -> list[Any]:
    from arche.extract import extract

    return [e for e in extract(text, backend=backend)
            if e.entity_type in ("PERSON", "ORGANIZATION", "LOCATION", "EMAIL")]


def _tokens(name: str | None) -> list[str]:
    return [p for p in re.split(r"[^a-z]+", (name or "").lower()) if len(p) >= 3]


def _surname_in(email: str, name: str | None) -> bool:
    parts = _tokens(name)
    return bool(parts) and parts[-1] in email.split("@", 1)[0].lower()


def _alone_on_line(e: Any, block: dict[str, Any]) -> bool:
    return any(s <= e.start and e.end <= t and line.strip() == e.text.strip()
               for s, t, line in block["lines"])


def parties(document: Any, *, backend: str = "auto") -> list[Party]:
    """The parties a document names, each with a role from its layout.

    ``document`` is a :class:`arche.doc.ParsedDocument` or plain text.
    ``backend`` is passed to :func:`arche.extract` (``"basic"`` for rules only).
    Parties come in document order; unassigned text yields no party.
    """
    text = getattr(document, "text", document)
    if not isinstance(text, str):
        raise TypeError("parties() takes a ParsedDocument or a string")
    # PDF text often carries no-break spaces; one-for-one, so offsets hold.
    text = text.replace(" ", " ")
    blocks = _blocks(text)
    head_end = blocks[-1]["end"] if blocks else 0
    ents = _entities(text[:head_end], backend) if head_end else []
    out: list[Party] = []
    for block in blocks:
        if block["role"] == "unassigned":
            continue
        inside = [e for e in ents if block["start"] <= e.start and e.end <= block["end"]]
        names = [e for e in inside if e.entity_type in ("PERSON", "ORGANIZATION")]
        if block["cue"] == "letterhead":
            first_end = block["lines"][0][1]
            orgs = [e for e in names if e.entity_type == "ORGANIZATION"]
            out.append(_party("issuer", block, orgs[0] if orgs else None, inside, text))
            # A person alone on a line under the letterhead is who it is for.
            lone = [e for e in names if e.entity_type == "PERSON" and e.start >= first_end
                    and _alone_on_line(e, block)]
            if lone:
                out.append(_party("customer", block, lone[0], inside, text,
                                  cue="named under letterhead"))
            continue
        # Of the names in a block, the one with an address under it.
        if not names:
            labelled = _first_label(block)
            names = [labelled] if labelled else []
        drafts = [_party(block["role"], block, e, inside, text) for e in names] \
            or [_party(block["role"], block, None, inside, text)]
        out.append(next((d for d in drafts if d.address), drafts[0]))
    out = [p for p in out if p.name or p.address or p.email]
    customer = next((p for p in out if p.role == "customer" and p.name), None)
    if customer and customer.email is None:
        for m in _EMAIL.finditer(text):
            if _surname_in(m.group(0), customer.name):
                out[out.index(customer)] = Party(**{
                    **customer.__dict__, "email": m.group(0),
                    "evidence": {**customer.evidence,
                                 "email": "outside the block; carries the surname"}})
                break
    return out


_ORG_SUFFIX = re.compile(r"\b(llc|l\.l\.c\.|inc|ltd|limited|plc|gmbh|ag|sa|bv|nv|llp|lp|"
                         r"corp|corporation|company|co)\.?$", re.I)


@dataclass(frozen=True)
class _Label:
    """A name read from layout, not from a model: the first line under a cue."""

    text: str
    start: int
    end: int
    entity_type: str


def _first_label(block: dict[str, Any]) -> _Label | None:
    """With no name from the extractor, the first segment under a cue that is
    neither an address nor a field label. Only named as an organisation when it
    ends in a company suffix; otherwise the kind stays unknown."""
    for s, _end, line in block["lines"]:
        cue = _cue(line)
        offset = cue[2] if cue else 0
        segment = line[offset:].strip(" ,;:.")
        if not segment:
            continue
        if _is_address(segment) or _NOT_ADDRESS.search(segment) or _EMAIL.search(segment) \
                or not re.search(r"[A-Za-z]{2}", segment):
            return None
        start = s + line.index(segment, offset)
        kind = "ORGANIZATION" if _ORG_SUFFIX.search(segment) else "LABEL"
        return _Label(segment, start, start + len(segment), kind)
    return None


def _segments(block: dict[str, Any], after: int) -> list[str]:
    """The block's text after offset ``after``, one segment per line, cue
    words removed."""
    out = []
    for s, t, line in block["lines"]:
        if t <= after:
            continue
        segment = line[after - s:] if s < after else line
        cue = _cue(segment)
        if cue:
            segment = segment[cue[2]:]
        segment = segment.strip(" ,;:.")
        if segment:
            out.append(segment)
    return out


def _party(role: str, block: dict[str, Any], name_ent: Any, inside: list[Any], text: str,
           *, cue: str | None = None) -> Party:
    cue = cue or block["cue"]
    name = name_ent.text.strip() if name_ent is not None else None
    kind = {"PERSON": "person", "ORGANIZATION": "organisation"}.get(
        getattr(name_ent, "entity_type", None))
    if name and kind == "person":
        name = re.sub(r"^(mr|mrs|ms|miss|mx|dr|prof)\.?\s+", "", name, flags=re.I)
        half = name.split()
        if len(half) % 2 == 0 and half[: len(half) // 2] == half[len(half) // 2:]:
            name = " ".join(half[: len(half) // 2])   # "Andrea Kropp Andrea Kropp"
    # The address: the address-like segments straight after the name. A
    # repeat of the name, or a label, may sit between; another name may not
    # (the address under it is that name's).
    others = {e.text.strip().lower() for e in inside
              if e.entity_type in ("PERSON", "ORGANIZATION")} - {(name or "").lower()}
    pieces: list[str] = []
    skipped = 0
    for segment in _segments(block, name_ent.end if name_ent is not None else block["start"]):
        if _is_address(segment):
            pieces.append(segment)
            continue
        if pieces:
            break
        rest = segment.lower()
        if any(rest.startswith(o) for o in others if o):
            break
        skipped += 1
        if skipped > _ADDRESS_SKIP:
            break
    email = next((e.text for e in inside if e.entity_type == "EMAIL"
                  and (name is None or _surname_in(e.text, name))), None)
    return Party(role=role, name=name, kind=kind, address=", ".join(pieces) or None,
                 email=email, cue=cue, start=block["start"], end=block["end"],
                 evidence={"cue": cue, "block": [block["start"], block["end"]]})


__all__ = ["Party", "parties"]
