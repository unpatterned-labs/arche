# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Does this bundle of documents show that a person lives at an address?

The question a bank, a landlord or an employer asks at onboarding, and the one
a pile of PDFs does not answer on its own. It decomposes into four, and only
the first is what people usually build:

1. **Is the subject named on this document?** Including when the document names
   several people -- a joint energy account reads ``A & B``, and an exact-name
   comparison fails on the strongest proof-of-address document there is.
2. **Which address on this document is the subject's?** Every document has at
   least two parties. An invoice carries the vendor's address in the letterhead
   and the customer's under "Bill to"; an energy statement carries the supply
   address, the supplier's registered office, and the ombudsman's PO box.
   Measured on a real E.ON statement, the *issuer's* postcode appears four
   times and the subject's three -- so "the most frequent postcode" picks the
   wrong one, and so does "the first".
3. **How old is it?** A twelve-month-old payslip is not evidence of where
   somebody lives now. Recency is the whole point of the exercise and is
   usually the field nobody extracts.
4. **How many independent sources is that really?** Three invoices from one
   vendor are one source, not three. Banks require documents from different
   issuers for exactly this reason, and counting documents instead of issuers
   is how a bundle looks stronger than it is.

This module answers all four and refuses to average them. A verdict of
``insufficient`` is a first-class outcome: it means the documents may well be
genuine and simply do not establish the claim, which is a different thing from
evidence against it.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from typing import Any

__all__ = ["ResidenceCheck", "assess_residence"]

#: UK postcode, tolerating the line breaks a PDF text layer inserts.
_POSTCODE = re.compile(
    r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*\n?\s*(\d[A-Z]{2})\b", re.I)

#: Dates in the forms these documents actually use.
#:
#: The comma after the month name is not decoration. A real termination letter
#: extracted as "9 June, 2026"; without `,?` that date failed to parse, the
#: document fell back to a contract date it merely *referenced*, and the letter
#: read as thirteen months older than it was. Found by running on real PDFs --
#: the synthetic fixture wrote "9 June 2026" and never reproduced it.
_DATES = [
    re.compile(r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
               r"[a-z]*,?\s+(\d{4})\b", re.I),
    re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+"
               r"(\d{1,2}),?\s+(\d{4})\b", re.I),
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
]
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

#: Phrases that introduce the SUBJECT's address rather than the issuer's.
#: Cue-anchored rather than positional, because position is a layout accident
#: and a cue is a statement by the document about what follows it.
_SUBJECT_CUES = (
    "bill to", "billed to", "supply address", "service address",
    "delivery address", "sold to", "customer address", "your address",
    "employee address", "site address",
)

#: Phrases that introduce the ISSUER's address. Present so a cue-matched block
#: can be ruled OUT, not merely ruled in.
_ISSUER_CUES = (
    "registered office", "registered in england", "vat", "company number",
    "ombudsman", "head office", "remit to", "pay to", "from:",
)


def _norm_postcode(match: re.Match) -> str:
    return f"{match.group(1).upper()} {match.group(2).upper()}"


def _postcodes_near(text: str, anchor: int, window: int = 260) -> list[str]:
    """Postcodes within ``window`` characters after ``anchor``.

    Forward-looking only: in every layout these documents use, an address
    follows the name or the cue that introduces it, never precedes it.
    """
    segment = text[anchor:anchor + window]
    return [_norm_postcode(m) for m in _POSTCODE.finditer(segment)]


#: Phrases that introduce the date the document was ISSUED, as opposed to a
#: billing period, a due date or a payment deadline.
#: `dated` is deliberately absent. On a contract-termination letter it matched
#: "dated August 1, 2025", the date of the contract BEING terminated -- a
#: reference to another document entirely, and thirteen months older than the
#: letter. A cue has to identify *this* document's issue date or it is worse
#: than no cue, because it wins over the fallback.
_DATE_CUES = (
    "date of issue", "issue date", "statement date", "bill date",
    "invoice date", "date:", "pay date", "period ending",
)


def _document_date(text: str) -> tuple[_dt.date | None, bool]:
    """When the document was issued, and whether a cue said so.

    A cued date wins over an uncued one, for the same reason a cued address
    does: the document is telling you what the date means. Taking the latest
    date instead makes documents look NEWER than they are -- a Cursor invoice
    covering "Feb 17 - Mar 17" would report March, a month of recency it has
    not earned, and recency is the entire point of the check.

    Dates beyond today are ignored throughout: a due date in the future says
    nothing about when the document was produced.
    """
    lowered = text.lower()
    for cue in _DATE_CUES:
        idx = lowered.find(cue)
        while idx != -1:
            # The FIRST date after the cue, not the smallest in the window.
            # "Date of issue 1 Jun 2026 / Service period 1 Jan 2026 to ..."
            # fits both inside one window, and taking the minimum answered
            # with the period start -- a date the cue was not pointing at.
            cued = _dates_in(text[idx:idx + 60])
            if cued:
                return cued[0], True
            idx = lowered.find(cue, idx + len(cue))

    # No cue: the first date in the document. Documents lead with their own
    # date and refer to other documents' dates later in the body -- a
    # termination letter opens "9 June 2026" and mentions the contract it ends
    # "dated August 1, 2025" further down. Taking the minimum answered with the
    # referenced contract, thirteen months out; taking the maximum would answer
    # with a period end and claim recency the document has not earned. First is
    # both more accurate here and conservative where it is wrong.
    every = _dates_in(text)
    return (every[0], False) if every else (None, False)


def _dates_in(text: str) -> list[_dt.date]:
    """Every parseable, non-future date in ``text``, in the order they appear.

    Document order, not pattern order: the caller relies on "the first date"
    meaning the first one a reader would see.
    """
    today = _dt.date.today()
    found: list[tuple[int, _dt.date]] = []
    for pattern in _DATES:
        for m in pattern.finditer(text):
            try:
                groups = m.groups()
                if groups[1].lower()[:3] in _MONTHS:          # 27 Aug 2026
                    day, month, year = (int(groups[0]),
                                        _MONTHS[groups[1].lower()[:3]],
                                        int(groups[2]))
                elif groups[0].lower()[:3] in _MONTHS:        # Aug 27, 2026
                    day, month, year = (int(groups[1]),
                                        _MONTHS[groups[0].lower()[:3]],
                                        int(groups[2]))
                else:                                          # 2026-08-27
                    year, month, day = (int(groups[0]), int(groups[1]),
                                        int(groups[2]))
                candidate = _dt.date(year, month, day)
            except (ValueError, KeyError, IndexError):
                continue
            if candidate <= today:
                found.append((m.start(), candidate))
    return [d for _, d in sorted(found)]


def _subject_addresses(text: str, name: str) -> tuple[list[str], str]:
    """Postcodes belonging to ``name``, and how they were identified.

    Three passes, most trustworthy first. The order matters: a cue is the
    document telling you whose address follows, a name is the next best thing,
    and anything else is a guess that should be labelled as one.
    """
    lowered = text.lower()
    surname = name.strip().split()[-1].lower() if name.strip() else ""

    # 1. An explicit cue. "Supply address:", "Bill to".
    for cue in _SUBJECT_CUES:
        start = 0
        while (idx := lowered.find(cue, start)) != -1:
            near = _postcodes_near(text, idx)
            if near:
                return near, f"cue:{cue}"
            start = idx + len(cue)

    # 2. The subject's own name, which an address block follows.
    if surname:
        start = 0
        while (idx := lowered.find(surname, start)) != -1:
            near = _postcodes_near(text, idx)
            if near:
                return near, "adjacent to the subject's name"
            start = idx + len(surname)

    # 3. Nothing anchored it. Report every postcode and say the anchor is
    # missing -- guessing here is how an issuer's registered office becomes
    # somebody's home address.
    every = [_norm_postcode(m) for m in _POSTCODE.finditer(text)]
    return (every, "unanchored") if every else ([], "none found")


#: Line openings that are document furniture rather than a name.
_NOT_AN_ISSUER = (
    "page ", "invoice", "receipt", "statement", "pay summary", "bill to",
    "billed to", "date", "tax", "vat", "total", "amount", "due", "ref",
    "account", "customer", "period", "summary", "description", "qty",
)


def _issuer_of(text: str) -> str:
    """A stable label for who produced the document.

    Deliberately rough: it exists to group documents by source so three
    invoices from one vendor stop counting as three pieces of evidence. It does
    not need to be a legal name, only the same string across one issuer's
    documents and a different one across another's.

    Rough is not the same as arbitrary, though. An earlier version returned the
    first line that was not obviously a heading, and on real documents that
    produced issuer labels of "9 June, 2026" and "Date of issue" -- a date is
    not a source, and two unrelated documents both opening with one would have
    been counted as a single issuer, understating the evidence.
    """
    for line in (ln.strip() for ln in text.splitlines()):
        if not line or len(line) < 3:
            continue
        low = line.lower()
        if any(low.startswith(x) for x in _NOT_AN_ISSUER):
            continue
        # A bare month name is a date fragment, not a source. Real PDFs break
        # a letterhead date across lines -- "9", "June,", "2026" each on their
        # own -- and "June," passes a plain letter count.
        if low.strip(" ,.")[:3] in _MONTHS and len(low.strip(" ,.")) <= 9:
            continue
        # A line that is mostly digits and punctuation is a reference number,
        # a total or a date, not a name.
        letters = sum(c.isalpha() for c in line)
        if letters < max(3, len(line) // 3):
            continue
        return line[:60]
    return "unknown"


@dataclass
class ResidenceCheck:
    """What the documents establish, and what they do not."""

    verdict: str                      # verified | insufficient | contradicted
    reason: str
    subject: str
    address: str | None
    independent_sources: int
    most_recent: _dt.date | None
    documents: list[dict[str, Any]] = field(default_factory=list)
    supporting: list[str] = field(default_factory=list)
    conflicting: list[dict[str, Any]] = field(default_factory=list)

    @property
    def age_days(self) -> int | None:
        if self.most_recent is None:
            return None
        return (_dt.date.today() - self.most_recent).days


def assess_residence(
    documents: dict[str, str],
    *,
    name: str,
    address: str | None = None,
    min_sources: int = 2,
    max_age_days: int = 90,
) -> ResidenceCheck:
    """Assess whether ``documents`` show ``name`` living at ``address``.

    ``documents`` maps a label to that document's extracted text.

    ``address`` may be a postcode or contain one; when omitted the address best
    supported by the evidence is inferred and reported rather than assumed.

    ``min_sources`` counts *issuers*, not documents. ``max_age_days`` is the
    recency rule -- 90 days is the common bank threshold for a utility bill,
    and it is a parameter because it is a policy, not a fact.

    The verdict is never a score. ``insufficient`` means the documents may be
    entirely genuine and simply fail to establish the claim; ``contradicted``
    means the most recent evidence points somewhere else.
    """
    claimed = None
    if address:
        m = _POSTCODE.search(address)
        claimed = _norm_postcode(m) if m else None

    per_doc: list[dict[str, Any]] = []
    for label, text in documents.items():
        postcodes, how = _subject_addresses(text, name)
        named = name.strip().split()[-1].lower() in text.lower() if name else False
        when, cued = _document_date(text)
        per_doc.append({
            "document": label,
            "names_subject": named,
            "postcodes": postcodes,
            "anchored_by": how,
            "issuer": _issuer_of(text),
            "date": when,
            "date_anchored": cued,
        })

    naming = [d for d in per_doc if d["names_subject"] and d["postcodes"]]
    if not naming:
        return ResidenceCheck(
            verdict="insufficient",
            reason=f"no document both names {name} and carries an address for them",
            subject=name, address=claimed, independent_sources=0,
            most_recent=None, documents=per_doc,
        )

    # Which address is best evidenced? Counted by ISSUER, because three
    # documents from one vendor are one source.
    by_address: dict[str, set] = {}
    for d in naming:
        for postcode in d["postcodes"]:
            by_address.setdefault(postcode, set()).add(d["issuer"])
    if claimed is None:
        claimed = max(by_address, key=lambda k: len(by_address[k]))

    supporting = [d for d in naming if claimed in d["postcodes"]]
    sources = {d["issuer"] for d in supporting}
    dates = [d["date"] for d in supporting if d["date"]]
    most_recent = max(dates) if dates else None

    conflicting = [
        {"document": d["document"], "postcodes": d["postcodes"],
         "date": d["date"], "issuer": d["issuer"]}
        for d in naming if claimed not in d["postcodes"]
    ]
    # A conflicting document only contradicts if it is NEWER. An older one
    # showing a different address is a previous address, which is the ordinary
    # case when somebody has moved -- and calling that a contradiction would
    # fail every honest applicant who moved house.
    newer = [c for c in conflicting
             if c["date"] and most_recent and c["date"] > most_recent]

    if newer:
        return ResidenceCheck(
            verdict="contradicted",
            reason=(f"{len(newer)} document(s) newer than the supporting "
                    f"evidence place {name} at a different address"),
            subject=name, address=claimed, independent_sources=len(sources),
            most_recent=most_recent, documents=per_doc,
            supporting=[d["document"] for d in supporting],
            conflicting=conflicting,
        )

    age = (_dt.date.today() - most_recent).days if most_recent else None
    problems = []
    if len(sources) < min_sources:
        problems.append(
            f"only {len(sources)} independent source(s), {min_sources} required"
            + (f" ({len(supporting)} documents, but from the same issuer)"
               if len(supporting) > len(sources) else ""))
    if age is None:
        problems.append("no document carries a readable date")
    elif age > max_age_days:
        problems.append(f"most recent supporting document is {age} days old, "
                        f"limit {max_age_days}")

    if problems:
        return ResidenceCheck(
            verdict="insufficient", reason="; ".join(problems),
            subject=name, address=claimed, independent_sources=len(sources),
            most_recent=most_recent, documents=per_doc,
            supporting=[d["document"] for d in supporting],
            conflicting=conflicting,
        )

    return ResidenceCheck(
        verdict="verified",
        reason=(f"{len(sources)} independent sources agree, most recent "
                f"{age} days old"),
        subject=name, address=claimed, independent_sources=len(sources),
        most_recent=most_recent, documents=per_doc,
        supporting=[d["document"] for d in supporting],
        conflicting=conflicting,
    )
