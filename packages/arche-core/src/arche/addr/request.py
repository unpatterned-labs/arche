# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""A place request: from a sentence to verified endpoints, one question, or a refusal.

    import arche

    result = arche.resolve_place_request(
        "Send my package tomorrow from 123 Maple Street to the blue gate "
        "behind Elim Pharmacy, 124 Elim Streat.",
        action="create_delivery",
        sources=[arche.addr.request.MasterSheet(customer_locations)],
    )
    result.destination.status          # "verified" | "clarification_required" | "refused"
    result.destination.question        # "Is the destination 124 Elim Street, next to ...?"
    result.to_dict()                   # the response an application renders

The behaviour this module exists for
------------------------------------
A high-confidence endpoint passes through. A close contest between two
candidates becomes **one short question**. Weak evidence becomes an honest
refusal with the alternatives that were considered. The action is blocked
until every endpoint the policy requires is verified. Nothing here guesses:
an endpoint the text does not mention is ``missing``, and a landmark the
sources cannot place is ``refused`` with what was tried.

The three layers, and which is which
------------------------------------
1. **Mentions** -- :func:`spatial_mentions` reads the sentence. Roles come
   from :func:`arche.extract_places` (origin / destination / via, with the
   cue that decided each); on top of that this module reads the *relation*
   (`behind`, `opposite`, `after the bridge`), the *reference* it is relative
   to (`Elim Pharmacy`), the *access hint* (`the blue gate`) and the target
   address, typo-tolerantly. That is a :class:`SpatialMention`. Deterministic,
   offline, no model.
2. **Sources** -- a :class:`PlaceSource` turns a mention into candidates with
   evidence. :class:`MasterSheet` is the caller's own list (a customer's
   locations, a facility register) and needs nothing. :class:`Nominatim` is
   OpenStreetMap's geocoder and is opt-in: it is a network call to a third
   party under a usage policy. Any verified address layer with an id space is
   another source, and that is the seam a commercial verification service
   plugs into.
3. **Policy** -- :class:`Policy` turns candidates into a status. Its numbers
   are declared, not learned, and every status carries the evidence and the
   candidates it was decided on.

What ``confidence`` is here
---------------------------
A weighted agreement over named pieces of evidence -- number, street, a
landmark nearby, an exact display-name match -- in ``[0, 1]``. It orders
candidates and drives the policy; it is not a calibrated probability, and
the policy thresholds are the place to be conservative.
"""

from __future__ import annotations

import datetime as _dt
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from arche.addr.parse import _STREET_SUFFIXES, parse_address
from arche.addr.roles import PlaceMention, extract_places

Status = Literal["verified", "clarification_required", "refused", "missing"]

# ------------------------------------------------------------- mentions ------

_RELATIONS = (
    "behind", "opposite", "next to", "beside", "near", "in front of", "across from",
    "after", "before", "adjacent to", "next door to", "across the street from",
    "at the back of", "inside", "off", "by",
)
_RELATION_RE = re.compile(
    r"\b(?P<relation>" + "|".join(re.escape(r) for r in
                                  sorted(_RELATIONS, key=len, reverse=True)) + r")\s+"
    r"(?:the\s+)?(?P<reference>[A-Z][\w'’\-]*(?:\s+[A-Z][\w'’\-]*){0,4})",
)
_ACCESS_WORDS = ("gate", "door", "entrance", "kiosk", "stall", "shop", "counter",
                 "reception", "lobby", "bay", "dock", "window")
_ACCESS_RE = re.compile(
    r"\b(?:the\s+)?(?P<hint>(?:[a-z][\w\-]*\s+){0,2}(?:" + "|".join(_ACCESS_WORDS) + r"))\b",
    re.IGNORECASE,
)
# A street address at the end of a clause, tolerant of a misspelt suffix:
# `124 Elim Streat` is a number and two capitalised words, and the parser's
# suffix list does not know `Streat`. The suffix decision is made afterwards.
_LOOSE_ADDRESS_RE = re.compile(
    r"(?P<number>\b\d{1,4}[A-Za-z]?)\s+(?P<street>[A-Z][\w'’\-]*(?:\s+[A-Z][\w'’\-]*){0,3})"
)
_CLAUSE_END_RE = re.compile(r"[.;!?\n]| to | from | via ")
_SUFFIXES_LOWER = {s.casefold() for s in _STREET_SUFFIXES}


@dataclass(frozen=True)
class SpatialMention:
    """One endpoint as the sentence gave it: role, target, relation, reference, access."""

    action_role: str                     # origin | destination | via | location | unknown
    target_text: str                     # the whole endpoint clause
    span: tuple[int, int]
    confidence: float
    relation_kind: str | None = None     # behind | opposite | after ...
    reference_text: str | None = None    # Elim Pharmacy
    access_hint: str | None = None       # blue gate
    street_number: str | None = None
    street: str | None = None            # as written, typo and all
    street_suffix_known: bool = True     # False for `Streat`
    cue: str | None = None
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


def _clause_after(text: str, start: int) -> tuple[str, int]:
    """The endpoint clause from ``start`` to the next boundary."""
    m = _CLAUSE_END_RE.search(text, start)
    end = m.start() if m else len(text)
    return text[start:end].strip(" ,"), end


def _from_place_mention(text: str, m: PlaceMention) -> SpatialMention:
    # The clause is what follows the role cue, so a `to the blue gate behind
    # Elim Pharmacy, 124 Elim Streat` mention keeps everything after `to`.
    start = m.cue_span[1] if m.cue_span else m.span[0]
    clause, end = _clause_after(text, start)
    clause_start = start + (len(text[start:end]) - len(text[start:end].lstrip(" ,")))
    evidence = list(m.evidence)

    relation = reference = access = None
    rel = _RELATION_RE.search(clause)
    if rel:
        relation, reference = rel.group("relation").casefold(), rel.group("reference")
        evidence.append("relation:" + relation.replace(" ", "_"))
        before = clause[:rel.start()]
        acc = _ACCESS_RE.search(before)
        if acc:
            access = acc.group("hint").strip()
            evidence.append("access_hint")

    number = street = None
    suffix_known = True
    # Prefer the parser (it knows suffixes); fall back to the loose pattern,
    # which is what catches the misspelt suffix.
    parsed = parse_address(clause)
    comps = parsed.components if parsed else None
    if comps and comps.street_number and comps.street:
        number, street = comps.street_number, comps.street
        evidence.append("address:parsed")
    else:
        tail = clause[rel.end():] if rel else clause
        loose = _LOOSE_ADDRESS_RE.search(tail)
        if loose:
            number, street = loose.group("number"), loose.group("street")
            last = street.split()[-1].casefold()
            suffix_known = last in _SUFFIXES_LOWER
            evidence.append("address:loose" if suffix_known else "address:loose_suffix")

    return SpatialMention(
        action_role=m.role, target_text=clause,
        span=(clause_start, clause_start + len(clause)),
        confidence=m.confidence, relation_kind=relation, reference_text=reference,
        access_hint=access, street_number=number, street=street,
        street_suffix_known=suffix_known, cue=m.cue, evidence=tuple(evidence),
    )


def spatial_mentions(text: str) -> list[SpatialMention]:
    """Every endpoint in ``text`` with its role, relation, reference and access hint."""
    out = []
    seen_roles: set[str] = set()
    for m in extract_places(text):
        sm = _from_place_mention(text, m)
        # One clause per role: the extractor can emit both the landmark and the
        # street of a single endpoint as separate mentions.
        if sm.action_role in seen_roles and sm.action_role != "unknown":
            continue
        seen_roles.add(sm.action_role)
        out.append(sm)
    return out


# ----------------------------------------------------------- time window ----

_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_TIME_RE = re.compile(
    r"\b(?P<word>today|tomorrow|day after tomorrow|tonight|"
    r"(?:next|this|on)\s+(?:" + "|".join(_WEEKDAYS) + r"))\b", re.IGNORECASE)


@dataclass(frozen=True)
class TimeWindow:
    date: str | None
    confidence: Literal["high", "medium", "none"]
    phrase: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"date": self.date, "confidence": self.confidence, "phrase": self.phrase}


def time_window(text: str, *, now: _dt.date | None = None) -> TimeWindow:
    """A date from a relative phrase. Absent phrase, absent date -- never today by default."""
    today = now or _dt.date.today()
    m = _TIME_RE.search(text)
    if not m:
        return TimeWindow(None, "none")
    word = m.group("word").casefold()
    if word in ("today", "tonight"):
        return TimeWindow(today.isoformat(), "high", word)
    if word == "tomorrow":
        return TimeWindow((today + _dt.timedelta(days=1)).isoformat(), "high", word)
    if word == "day after tomorrow":
        return TimeWindow((today + _dt.timedelta(days=2)).isoformat(), "high", word)
    qualifier, day = word.split(None, 1)
    target = _WEEKDAYS.index(day)
    ahead = (target - today.weekday()) % 7
    if qualifier == "next" or ahead == 0:
        ahead = ahead or 7
        if qualifier == "next" and ahead < 7:
            ahead += 7 if (target - today.weekday()) % 7 <= today.weekday() else 0
    return TimeWindow((today + _dt.timedelta(days=ahead)).isoformat(),
                      "high" if qualifier != "next" else "medium", word)


# -------------------------------------------------------------- sources ------

@dataclass(frozen=True)
class PlaceCandidate:
    place_id: str
    display_name: str
    confidence: float
    evidence: tuple[str, ...]
    source: str
    lat: float | None = None
    lon: float | None = None
    record: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"place_id": self.place_id, "display_name": self.display_name,
                "confidence": round(self.confidence, 2), "evidence": list(self.evidence),
                "source": self.source}


@runtime_checkable
class PlaceSource(Protocol):
    name: str

    def candidates(self, mention: SpatialMention, *, limit: int = 5) -> list[PlaceCandidate]: ...


def _jw(a: str, b: str) -> float:
    from arche.resolve._matcher import _jaro_winkler

    return _jaro_winkler(a.casefold(), b.casefold())


def _norm(s: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (s or "").casefold()))


def _street_stem(s: str | None) -> str:
    """A street without its suffix, so `Elim Streat` and `Elim Street` compare on `elim`.

    A trailing token that is a known suffix is dropped. One that is *nearly*
    a known suffix (`Streat`) is dropped too, so the misspelling does not
    count against the stem; the typo is charged once, in the evidence label,
    not twice.
    """
    toks = _norm(s or "").split()
    if len(toks) > 1:
        last = toks[-1]
        if last in _SUFFIXES_LOWER or any(_jw(last, suf) >= 0.85 for suf in _SUFFIXES_LOWER):
            toks = toks[:-1]
    return " ".join(toks)


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    import math

    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass
class MasterSheet:
    """The caller's own places: a list of records with an id, a name and an address.

    Fields read: ``id``, ``name`` (or ``display_name``), ``address`` (free
    text) or ``street_number`` + ``street``, ``lat``/``lon`` optional. A
    landmark is a record too -- `Elim Pharmacy` with coordinates -- which is
    what lets `behind Elim Pharmacy` count as evidence for a candidate 60 m
    away.
    """

    records: Sequence[Mapping[str, Any]]
    name: str = "master_sheet"
    id_field: str = "id"
    landmark_radius_m: float = 250.0

    def _fields(self, r: Mapping[str, Any]) -> tuple[str, str | None, str | None]:
        display = str(r.get("display_name") or r.get("name") or r.get("address") or "")
        number, street = r.get("street_number"), r.get("street")
        if not street:
            parsed = parse_address(str(r.get("address") or display))
            if parsed and parsed.components:
                number = number or parsed.components.street_number
                street = parsed.components.street
        return display, (str(number) if number else None), street

    def candidates(self, mention: SpatialMention, *, limit: int = 5) -> list[PlaceCandidate]:
        out: list[PlaceCandidate] = []
        landmarks = [r for r in self.records
                     if mention.reference_text
                     and _jw(str(r.get("name") or ""), mention.reference_text) >= 0.9
                     and r.get("lat") is not None]
        for r in self.records:
            display, number, street = self._fields(r)
            evidence: list[str] = []
            score = 0.0
            if (mention.street_number and number
                    and mention.street_number.casefold() == number.casefold()):
                evidence.append("street-number match")
                score += 0.4
            if mention.street and street:
                sim = _jw(_street_stem(mention.street), _street_stem(street))
                # A stem that matches exactly under a misspelt suffix is still
                # a typo the user wrote; it is labelled as one.
                if sim >= 0.999 and mention.street_suffix_known:
                    evidence.append("street match")
                    score += 0.5
                elif sim >= 0.85:
                    evidence.append("typo-tolerant street match")
                    score += 0.3 if sim < 0.999 else 0.4
            if (not evidence and mention.target_text and display
                    and _jw(_norm(mention.target_text), _norm(display)) >= 0.95):
                evidence.append("display-name match")
                score += 0.7
            if not evidence:
                continue
            if landmarks and r.get("lat") is not None:
                for lm in landmarks:
                    if lm is r:
                        continue
                    d = _haversine_m(float(r["lat"]), float(r["lon"]),
                                     float(lm["lat"]), float(lm["lon"]))
                    if d <= self.landmark_radius_m:
                        evidence.append("nearby landmark match")
                        score += 0.2
                        break
            if mention.street_number and number and mention.street_number != number:
                score -= 0.15
            out.append(PlaceCandidate(
                place_id=str(r.get(self.id_field, display)), display_name=display,
                confidence=max(0.0, min(1.0, score)), evidence=tuple(evidence),
                source=self.name, lat=r.get("lat"), lon=r.get("lon"), record=r))
        out.sort(key=lambda c: -c.confidence)
        return out[:limit]


@dataclass
class Nominatim:
    """OpenStreetMap's geocoder as a source. Opt-in, rate-limited, off when offline.

    Nominatim's usage policy: at most one request a second and a User-Agent
    that identifies the application. Both are honoured. Set ``ARCHE_OFFLINE``
    and this source answers nothing rather than failing the request.
    """

    name: str = "nominatim"
    user_agent: str = "arche-core (https://github.com/unpatterned-labs/arche)"
    endpoint: str = "https://nominatim.openstreetmap.org/search"
    country_codes: str | None = None
    _last: float = 0.0

    def _get(self, params: dict[str, str]) -> list[dict]:
        import json
        import os
        import time
        import urllib.parse
        import urllib.request

        if os.environ.get("ARCHE_OFFLINE"):
            return []
        wait = 1.05 - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        url = self.endpoint + "?" + urllib.parse.urlencode({**params, "format": "jsonv2"})
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        with urllib.request.urlopen(req, timeout=20) as fh:
            self._last = time.monotonic()
            return json.load(fh)

    def candidates(self, mention: SpatialMention, *, limit: int = 5) -> list[PlaceCandidate]:
        query = " ".join(x for x in (mention.street_number, mention.street) if x) \
            or mention.reference_text or mention.target_text
        params = {"q": query, "limit": str(limit), "addressdetails": "1"}
        if self.country_codes:
            params["countrycodes"] = self.country_codes
        out = []
        for hit in self._get(params):
            addr = hit.get("address", {})
            evidence = ["geocoder hit"]
            score = 0.4
            if mention.street_number and str(addr.get("house_number", "")) == mention.street_number:
                evidence.append("street-number match")
                score += 0.3
            if mention.street and addr.get("road"):
                sim = _jw(_street_stem(mention.street), _street_stem(addr["road"]))
                if sim >= 0.999:
                    evidence.append("street match")
                    score += 0.3
                elif sim >= 0.85:
                    evidence.append("typo-tolerant street match")
                    score += 0.2
            out.append(PlaceCandidate(
                place_id=f"osm:{hit.get('osm_type', '?')}:{hit.get('osm_id', '?')}",
                display_name=str(hit.get("display_name", query)),
                confidence=min(1.0, score), evidence=tuple(evidence), source=self.name,
                lat=float(hit["lat"]) if hit.get("lat") else None,
                lon=float(hit["lon"]) if hit.get("lon") else None, record=hit))
        return out[:limit]


# --------------------------------------------------------------- policy ------

@dataclass(frozen=True)
class Policy:
    """When an endpoint is verified, when it becomes a question, when it is refused."""

    verified_at: float = 0.85          # top candidate at or above: verified
    clarify_margin: float = 0.15       # two candidates within this of each other: ask
    minimum: float = 0.40              # top candidate below: refused
    require: tuple[str, ...] = ("origin", "destination")
    candidates_shown: int = 3
    #: An endpoint reached through a typo-tolerant match is a question, never
    #: a verification: the user wrote something else, and the one sentence
    #: it costs to confirm is cheaper than a parcel at the wrong door.
    confirm_typo_matches: bool = True


@dataclass(frozen=True)
class Endpoint:
    role: str
    status: Status
    mention: SpatialMention | None
    candidates: tuple[PlaceCandidate, ...] = ()
    question: str | None = None

    @property
    def chosen(self) -> PlaceCandidate | None:
        return self.candidates[0] if self.status == "verified" and self.candidates else None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"status": self.status}
        if self.status == "verified" and self.chosen:
            c = self.chosen
            d.update({"place_id": c.place_id, "display_name": c.display_name,
                      "confidence": round(c.confidence, 2), "evidence": list(c.evidence),
                      "source": c.source})
        elif self.status in ("clarification_required", "refused"):
            d["candidates"] = [c.to_dict() for c in self.candidates]
            d["evidence"] = sorted({e for c in self.candidates for e in c.evidence})
            if self.question:
                d["question"] = self.question
        if self.mention:
            d["mention"] = {k: v for k, v in self.mention.to_dict().items()
                            if k in ("target_text", "relation_kind", "reference_text",
                                     "access_hint", "street_number", "street")}
        return d


@dataclass(frozen=True)
class PlaceRequest:
    action: str
    text: str
    time_window: TimeWindow
    endpoints: dict[str, Endpoint]
    policy: Policy
    mentions: tuple[SpatialMention, ...]

    @property
    def origin(self) -> Endpoint:
        return self.endpoints["origin"]

    @property
    def destination(self) -> Endpoint:
        return self.endpoints["destination"]

    @property
    def status(self) -> str:
        blocking = [r for r in self.policy.require
                    if self.endpoints[r].status != "verified"]
        if not blocking:
            return "ready"
        worst = self.endpoints[blocking[0]].status
        if worst == "clarification_required":
            return f"blocked_pending_{blocking[0]}_confirmation"
        return f"blocked_{blocking[0]}_{worst}"

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action, "time_window": self.time_window.to_dict(),
                **{role: ep.to_dict() for role, ep in self.endpoints.items()},
                "request": {"status": self.status}}


def _question(role: str, mention: SpatialMention, top: PlaceCandidate) -> str:
    where = top.display_name
    if mention.reference_text and "nearby landmark match" in top.evidence:
        where += f", next to {mention.reference_text}"
    return f"Is the {role} {where}?"


def _decide(role: str, mention: SpatialMention | None, cands: list[PlaceCandidate],
            policy: Policy) -> Endpoint:
    if mention is None:
        return Endpoint(role, "missing", None)
    shown = tuple(cands[:policy.candidates_shown])
    if not cands or cands[0].confidence < policy.minimum:
        return Endpoint(role, "refused", mention, shown)
    top = cands[0]
    contested = len(cands) > 1 and cands[0].confidence - cands[1].confidence < policy.clarify_margin
    typo = policy.confirm_typo_matches and "typo-tolerant street match" in top.evidence
    if top.confidence >= policy.verified_at and not contested and not typo:
        return Endpoint(role, "verified", mention, shown)
    return Endpoint(role, "clarification_required", mention, shown,
                    question=_question(role, mention, top))


def resolve_place_request(text: str, *, action: str, sources: Sequence[PlaceSource],
                          policy: Policy | None = None, now: _dt.date | None = None,
                          ) -> PlaceRequest:
    """Read the request, resolve each endpoint against the sources, apply the policy."""
    policy = policy or Policy()
    mentions = tuple(spatial_mentions(text))
    by_role = {m.action_role: m for m in mentions}
    endpoints: dict[str, Endpoint] = {}
    for role in dict.fromkeys((*policy.require, *(m.action_role for m in mentions))):
        if role == "unknown":
            continue
        mention = by_role.get(role)
        cands: list[PlaceCandidate] = []
        if mention is not None:
            for source in sources:
                cands.extend(source.candidates(mention))
            # One entry per place id, best confidence wins.
            best: dict[str, PlaceCandidate] = {}
            for c in cands:
                if c.place_id not in best or c.confidence > best[c.place_id].confidence:
                    best[c.place_id] = c
            cands = sorted(best.values(), key=lambda c: -c.confidence)
        endpoints[role] = _decide(role, mention, cands, policy)
    return PlaceRequest(action=action, text=text, time_window=time_window(text, now=now),
                        endpoints=endpoints, policy=policy, mentions=mentions)


__all__ = ["Endpoint", "MasterSheet", "Nominatim", "PlaceCandidate", "PlaceRequest",
           "PlaceSource", "Policy", "SpatialMention", "Status", "TimeWindow",
           "resolve_place_request", "spatial_mentions", "time_window"]
