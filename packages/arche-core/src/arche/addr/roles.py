# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Spatial role labeling — extract places from free text, with their role.

``extract_places(text)`` finds address/place spans in free prose and labels
each with the role it plays — ``origin`` / ``destination`` / ``location`` /
``via`` — returning the **linguistic cue** that decided the role, so the
assignment is inspectable rather than magic. When cues are absent or
conflicting the role is ``unknown`` with floor confidence: the extractor
abstains rather than guesses (an agent that swaps pickup and drop-off has a
much worse day than one that asks).

Literature grounding: this is *spatial role labeling* (SemEval-2012 Task 3;
SemEval-2015 SpaceEval / ISO-Space 24617-7). ``origin``/``destination``/``via``
are MOVELINK ``source``/``goal``/``midPoint``; ``location`` is the ground of a
static relation; ``unknown`` mirrors SpRL's explicit ``undefined`` value. We
label the ground (the place); the figure (the mover) is out of scope.

Naming note: ``role`` here is a *spatial* role. It is unrelated to the
declaration-layer field role (``identifies``/``describes``/``ignore``) in
:mod:`arche.declare`.

The cue vocabulary lives in ``place_roles.yaml`` (data, not code — regional,
multilingual, contributor-extensible) and carries a content-hash **pin**, so
an evaluation result can name the exact vocabulary that produced it.

Evaluation is a first-class surface: ``load_gold()`` returns the labeled
sentence set shipped in the wheel, and ``grade_places()`` scores *any*
extractor's output (including an LLM's JSON) against it — per-role F1,
role-flip-relevant abstention accounting, and cue accuracy.

Public API::

    from arche.addr import extract_places, grade_places, load_gold

    mentions = extract_places(
        "Pick up the parcel from 7B Allen Avenue, Ikeja, Lagos "
        "and deliver to 12 Adeola Odeku Street, Victoria Island."
    )
    mentions[0].role        # "origin"
    mentions[0].cue         # "from"
    mentions[0].confidence  # 0.95
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from arche.addr.parse import (
    _ANCHOR_ARTICLES,
    _ANCHOR_PREPOSITIONS,
    _COMMERCIAL_KEYWORDS,
    _INFRASTRUCTURE_KEYWORDS,
    _POSTAL_PATTERNS,
    _RELIGIOUS_KEYWORDS,
    _TAIL_SEGMENT,
    Address,
    AddressComponents,
    infer_jurisdiction,
    parse_address,
    parse_addresses,
)

PlaceRole = Literal["origin", "destination", "location", "via", "unknown"]

_ROLES: frozenset[str] = frozenset(
    {"origin", "destination", "location", "via", "unknown"}
)
_COMMITTED_ROLES = ("origin", "destination", "location", "via")
_KINDS = frozenset({"single", "pair", "intrinsic"})

# Titles that veto a cue-licensed span: "from Alhaji Musa" is a person.
_TITLE_STOPLIST = frozenset(
    {"mr", "mrs", "ms", "miss", "dr", "prof", "alhaji", "alhaja", "chief",
     "engr", "mallam", "pastor", "imam", "rev", "sir", "madam", "oga"}
)

# Calendar words that veto a cue-licensed span: "on Tuesday" is a time.
_CALENDAR_STOPLIST = frozenset(
    {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
     "sunday", "january", "february", "march", "april", "may", "june",
     "july", "august", "september", "october", "november", "december",
     "today", "tomorrow", "tonight", "yesterday", "easter", "christmas"}
)

# Sentence boundaries a cue window can never cross.
_BOUNDARY_RE = re.compile(r"[.;!?\n]")

# Negation directly before a cue voids the role ("don't deliver to X anymore"
# names an address whose role the sentence explicitly cancels). The cue is
# still reported — with evidence "cue:negated" — but the role abstains.
_NEGATION_RE = re.compile(
    r"\b(?:don'?t|do not|doesn'?t|won'?t|never|no longer|stop|not)"
    r"\s+(?:[\w'’]+\s+){0,2}$",
    re.IGNORECASE,
)

# Confidence lookup: (cue_tier, span_tier) -> label. Ordinal labels, NOT
# probabilities — nothing in arche multiplies them. Cue tier 0 (absent or
# conflicting cue) structurally forces role="unknown".
_CONFIDENCE: dict[tuple[int, int], float] = {
    (2, 2): 0.95, (2, 1): 0.80, (2, 0): 0.60,
    (1, 2): 0.70, (1, 1): 0.55, (1, 0): 0.40,
    (0, 2): 0.25, (0, 1): 0.25, (0, 0): 0.25,
}

_SPAN_TIER_EVIDENCE = {2: "span:parsed", 1: "span:gazetteer",
                       0: "span:cue_licensed_unverified"}
_CUE_TIER_EVIDENCE = {2: "cue:adjacent", 1: "cue:windowed"}


class RolePackError(ValueError):
    """place_roles.yaml (or a user pack) failed validation."""


# ---------------------------------------------------------------------------
# The pack
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoleRule:
    id: str
    kind: str                      # single | pair | intrinsic
    roles: tuple[str, ...]         # one role for single/intrinsic, two for pair
    cues: tuple[str, ...]
    join: tuple[str, ...] = ()
    priority: int = 40
    min_span_tier: int = 0
    note: str = ""


@dataclass(frozen=True)
class RolePack:
    name: str
    version: str
    rules: tuple[RoleRule, ...]
    max_gap: int = 24
    fillers: tuple[str, ...] = ()

    @property
    def pin(self) -> str:
        """``name@version:sha256:<16 hex>`` over the normalized rule list."""
        from arche.ids import canonical_json

        payload = {
            "pack": self.name, "version": self.version,
            "max_gap": self.max_gap, "fillers": list(self.fillers),
            "rules": [
                {"id": r.id, "kind": r.kind, "roles": list(r.roles),
                 "cues": list(r.cues), "join": list(r.join),
                 "priority": r.priority, "min_span_tier": r.min_span_tier}
                for r in self.rules
            ],
        }
        digest = hashlib.sha256(
            canonical_json(payload).encode("utf-8")
        ).hexdigest()[:16]
        return f"{self.name}@{self.version}:sha256:{digest}"

    def vocabulary(self) -> frozenset[str]:
        """Every cue/join phrase in the pack (lowercased) — the closed set the
        MCP surface may emit."""
        out: set[str] = set()
        for r in self.rules:
            out.update(c.lower() for c in r.cues)
            out.update(j.lower() for j in r.join)
        out.update(p.lower() for p in _ANCHOR_PREPOSITIONS)
        return frozenset(out)


_PACK_CACHE: dict[str, RolePack] = {}


def load_role_pack(path: str | Path | None = None) -> RolePack:
    """Load and validate a role-cue pack (module-cached).

    Malformed packs raise :class:`RolePackError` naming the offending key —
    rules are structured records; silently ignoring a bad one would change
    role assignments without a trace.
    """
    if path is None:
        path = Path(__file__).resolve().parent / "place_roles.yaml"
    path = Path(path)
    key = str(path)
    if key in _PACK_CACHE:
        return _PACK_CACHE[key]

    import yaml

    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except OSError as exc:
        raise RolePackError(f"cannot read role pack {path}: {exc}") from exc

    for req in ("pack", "version", "rules"):
        if req not in data:
            raise RolePackError(f"{path}: missing required key {req!r}")

    rules: list[RoleRule] = []
    seen_ids: set[str] = set()
    for i, raw in enumerate(data["rules"]):
        where = f"{path}: rules[{i}]"
        rid = raw.get("id")
        if not rid:
            raise RolePackError(f"{where}: missing id")
        if rid in seen_ids:
            raise RolePackError(f"{where}: duplicate rule id {rid!r}")
        seen_ids.add(rid)
        kind = raw.get("kind", "single")
        if kind not in _KINDS:
            raise RolePackError(
                f"{where} ({rid}): unknown kind {kind!r}; valid: {sorted(_KINDS)}"
            )
        if kind == "pair":
            roles = tuple(raw.get("roles") or ())
            if len(roles) != 2 or not raw.get("join"):
                raise RolePackError(
                    f"{where} ({rid}): pair rules need roles: [a, b] and join:"
                )
        else:
            role = raw.get("role")
            roles = (role,) if role else ()
            if len(roles) != 1:
                raise RolePackError(f"{where} ({rid}): missing role")
        bad = set(roles) - (_ROLES - {"unknown"})
        if bad:
            raise RolePackError(
                f"{where} ({rid}): unknown role(s) {sorted(bad)}; valid: "
                f"{sorted(_ROLES - {'unknown'})}"
            )
        if kind == "intrinsic":
            source = raw.get("source")
            if source != "anchor_prepositions":
                raise RolePackError(
                    f"{where} ({rid}): intrinsic rules require "
                    "source: anchor_prepositions (the only legal value in v1)"
                )
            cues = tuple(p.lower() for p in _ANCHOR_PREPOSITIONS)
        else:
            cues = tuple(str(c).lower() for c in (raw.get("cues") or ()))
            if not cues:
                raise RolePackError(f"{where} ({rid}): missing cues")
        rules.append(RoleRule(
            id=str(rid), kind=kind, roles=roles, cues=cues,
            join=tuple(str(j).lower() for j in (raw.get("join") or ())),
            priority=int(raw.get("priority", 40)),
            min_span_tier=int(raw.get("min_span_tier", 0)),
            note=str(raw.get("note", "")),
        ))

    # A cue phrase mapping to two different roles at the same priority is a
    # pack bug (unresolvable at runtime), not a sentence ambiguity.
    claim: dict[tuple[str, int], tuple[str, str]] = {}
    for r in rules:
        if r.kind == "intrinsic":
            continue
        for cue in r.cues:
            prev = claim.get((cue, r.priority))
            if prev and prev[1] != r.roles[0]:
                raise RolePackError(
                    f"{path}: cue {cue!r} maps to role {prev[1]!r} (rule "
                    f"{prev[0]}) and {r.roles[0]!r} (rule {r.id}) at the same "
                    f"priority {r.priority} — a pack must not contradict itself"
                )
            claim[(cue, r.priority)] = (r.id, r.roles[0])

    pack = RolePack(
        name=str(data["pack"]), version=str(data["version"]),
        rules=tuple(rules),
        max_gap=int(data.get("max_gap", 24)),
        fillers=tuple(str(f).lower() for f in (data.get("fillers") or ())),
    )
    _PACK_CACHE[key] = pack
    return pack


# ---------------------------------------------------------------------------
# Output shape
# ---------------------------------------------------------------------------


@dataclass
class PlaceMention:
    """One place span with its spatial role and the evidence that decided it.

    Invariant: ``source_text[cue_span[0]:cue_span[1]] == cue`` whenever
    ``cue`` is not None. ``cue_phrase`` is the canonical (lowercased) pack
    phrase the cue matched — the only cue form the MCP surface emits.
    """

    role: PlaceRole
    text: str
    span: tuple[int, int]
    cue: str | None
    cue_span: tuple[int, int] | None
    cue_rule: str | None
    cue_phrase: str | None
    confidence: float
    evidence: tuple[str, ...]
    address: Address | None
    jurisdiction: str
    jurisdiction_confidence: float

    @property
    def components(self) -> AddressComponents | None:
        return self.address.components if self.address else None

    def to_dict(self, *, reveal: bool = True) -> dict[str, Any]:
        """JSON-ready dict. ``reveal=False`` (the MCP shape) carries offsets,
        the canonical cue phrase, and component *names* — never the address
        text or component values; the caller holds the source and can slice.
        """
        base: dict[str, Any] = {
            "role": self.role,
            "start": self.span[0], "end": self.span[1],
            "cue": self.cue_phrase,
            "cue_start": self.cue_span[0] if self.cue_span else None,
            "cue_end": self.cue_span[1] if self.cue_span else None,
            "cue_rule": self.cue_rule,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "jurisdiction": self.jurisdiction,
            "jurisdiction_confidence": self.jurisdiction_confidence,
            "has_address": self.address is not None,
        }
        comps = {
            k: v for k, v in vars(self.components).items() if v
        } if self.components else {}
        if reveal:
            base["text"] = self.text
            base["cue"] = self.cue
            base["components"] = comps
        else:
            base["components_present"] = sorted(comps)
        return base


# ---------------------------------------------------------------------------
# Span detection
# ---------------------------------------------------------------------------


@dataclass
class _Span:
    start: int
    end: int
    tier: int                       # 2 parsed | 1 gazetteer | 0 cue_licensed
    address: Address | None = None


_CAP_WORD = r"[A-Z][\w'’\-]*"
# A cue-licensed phrase: optional house number, then capitalized words with
# of/es/the connectors, then up to two comma-tail capitalized segments.
_LICENSE_RE = re.compile(
    r"^\s*"
    r"(?P<phrase>"
    r"(?:\d{1,4}[A-Za-z]?\s+)?"
    + _CAP_WORD + r"(?:\s+(?:" + _CAP_WORD + r"|of\b|es\b)){0,5}"
    r"(?:\s*,\s*" + _CAP_WORD + r"(?:\s+" + _CAP_WORD + r"){0,2}){0,2}"
    r")"
)
_LEADING_FILLER_RE = re.compile(
    r"^\s*(?:(?:the|a|an|our|your|my|their|its|that|this)\s+)+", re.IGNORECASE
)

_GB_POSTCODE_RE = _POSTAL_PATTERNS["GB"]

# Case-insensitive landmark fallback: the parser's anchor regex requires a
# capitalized landmark, but informal text is often uncased ("behind the
# central mosque"). Here a PLACE-TYPE KEYWORD replaces capitalization as the
# precision signal — the anchor only counts when the landmark names a mosque,
# market, junction, filling station, etc.
_PLACE_TYPE_KEYWORDS = (
    _COMMERCIAL_KEYWORDS | _RELIGIOUS_KEYWORDS | _INFRASTRUCTURE_KEYWORDS
)
# Case-insensitivity is scoped to the preposition/article via (?i:...) — a
# global IGNORECASE would also case-fold _TAIL_SEGMENT's [A-Z] classes and let
# the tail swallow lowercase prose ("Croydon, come through").
_INFORMAL_LANDMARK_RE = re.compile(
    r"\b(?i:" + "|".join(re.escape(p) for p in _ANCHOR_PREPOSITIONS) + r")\s+"
    r"(?:(?i:" + "|".join(re.escape(a) for a in _ANCHOR_ARTICLES) + r")\s+)?"
    r"(?P<landmark>[\w'’\-]+(?:[ ][\w'’\-]+){0,5})"
    r"(?P<tail>(?:\s*,\s*" + _TAIL_SEGMENT + r"){0,4})",
)
# Up to two capitalized words immediately left of a postcode ("London SE1 7EH").
_POSTCODE_PREFIX_RE = re.compile(
    r"(?:" + _CAP_WORD + r"\s+){1,2}$"
)


def _gazetteer_index() -> dict[str, int]:
    """``{lowercased name/alias: max token count}`` marker index, built lazily.

    Maps each known city name and alias to itself; value is unused beyond
    membership — kept as a dict for O(1) lookups.
    """
    global _GAZ_INDEX, _GAZ_MAX_TOKENS
    if _GAZ_INDEX is None:
        from arche.addr._gazetteer.cities import AFRICAN_CITIES

        index: dict[str, int] = {}
        max_tokens = 1
        for city in AFRICAN_CITIES:
            for name in (city.name, *city.aliases):
                key = name.lower()
                index[key] = 1
                max_tokens = max(max_tokens, len(key.split()))
        _GAZ_INDEX = index
        _GAZ_MAX_TOKENS = max_tokens
    return _GAZ_INDEX


_GAZ_INDEX: dict[str, int] | None = None
_GAZ_MAX_TOKENS: int = 1
_CAP_RUN_RE = re.compile(_CAP_WORD + r"(?:\s+" + _CAP_WORD + r"){0,3}")


# A bare street-suffix phrase with no number, no plot and no comma-tail is a
# known false-positive shape ("meet Grace Street" — a person). Such weak spans
# only survive when a locative word sits directly before them.
_NEARBY_LOCATIVE_RE = re.compile(
    r"\b(?:at|on|in|near|off|from|to|into|onto|opposite|behind|beside|along|"
    r"by|around|toward|towards)\s+(?:the\s+)?$",
    re.IGNORECASE,
)


def _detect_spans(text: str) -> list[_Span]:
    """Detectors 1-3: parsed addresses, GB postcodes, gazetteer cities."""
    spans: list[_Span] = []

    # 1. Full addresses via the existing parser (street / Box / landmark).
    for addr in parse_addresses(text):
        c = addr.components
        weak = (c.street_number is None and c.plot is None
                and "," not in addr.raw)
        if weak and not _NEARBY_LOCATIVE_RE.search(text[:addr.span[0]]):
            continue
        spans.append(_Span(addr.span[0], addr.span[1], tier=2, address=addr))

    # 1b. Case-insensitive landmark anchors, gated on a place-type keyword
    #     ("behind the central mosque, Ungwan Rimi" — uncased informal text).
    for m in _INFORMAL_LANDMARK_RE.finditer(text):
        landmark = m.group("landmark").lower()
        if not any(kw in landmark for kw in _PLACE_TYPE_KEYWORDS):
            continue
        spans.append(_Span(m.start(), m.end(), tier=1))

    # 2. UK postcodes. A postcode straddling a parsed span's end extends that
    #    span ("...London N7 8JG" — the parser's tail stops mid-postcode);
    #    otherwise it is its own span, extended left over adjacent
    #    capitalized words ("London SE1 7EH").
    for m in _GB_POSTCODE_RE.finditer(text):
        straddled = False
        for s in spans:
            if s.start < m.start(1) <= s.end < m.end(1):
                s.end = m.end(1)
                s.address = None  # boundary changed; re-parse at resolve time
                straddled = True
        if straddled:
            continue
        start = m.start(1)
        prefix = _POSTCODE_PREFIX_RE.search(text, 0, start)
        if prefix:
            start = prefix.start()
        spans.append(_Span(start, m.end(1), tier=2))

    # 3. Gazetteer cities/aliases inside capitalized runs.
    index = _gazetteer_index()
    for run in _CAP_RUN_RE.finditer(text):
        tokens = run.group(0).split()
        # longest sub-phrase first, scanning every start offset
        for i in range(len(tokens)):
            for j in range(min(len(tokens), i + _GAZ_MAX_TOKENS), i, -1):
                phrase = " ".join(tokens[i:j])
                if phrase.lower() in index:
                    start = run.start() + len(" ".join(tokens[:i]))
                    if i:
                        start += 1
                    spans.append(_Span(start, start + len(phrase), tier=1))
                    break

    return _dedup_spans(spans)


def _dedup_spans(spans: list[_Span]) -> list[_Span]:
    """Longest-wins over overlapping spans (tier breaks exact ties)."""
    spans.sort(key=lambda s: (s.start, -(s.end - s.start), -s.tier))
    kept: list[_Span] = []
    for s in spans:
        if any(s.start < k.end and k.start < s.end for k in kept):
            continue
        kept.append(s)
    return kept


def _license_span(text: str, after: int,
                  existing: list[_Span] | None = None) -> _Span | None:
    """Detector 4: a capitalized phrase right after a cue, tier 0.

    Only exists because the gazetteer is African-only — "from Manchester to
    Leeds" would otherwise yield nothing. Vetoed when the phrase starts with
    a personal title ("from Alhaji Musa" is a person) or a calendar word
    ("on Tuesday" is a time). With ``existing``, any overlap disqualifies;
    pass ``None`` when the caller handles overlap itself.
    """
    rest = text[after:]
    filler = _LEADING_FILLER_RE.match(rest)
    offset = after + (filler.end() if filler else 0)
    m = _LICENSE_RE.match(text[offset:])
    if not m:
        return None
    phrase = m.group("phrase")
    first = phrase.split()[0].rstrip(".").lower()
    if first in _TITLE_STOPLIST or first in _CALENDAR_STOPLIST:
        return None
    start = offset + m.start("phrase")
    end = start + len(phrase)
    if existing is not None:
        for k in existing:
            if start < k.end and k.start < end:
                return None
    return _Span(start, end, tier=0)


# ---------------------------------------------------------------------------
# Cue binding
# ---------------------------------------------------------------------------


@dataclass
class _CueOcc:
    start: int
    end: int
    phrase: str                     # canonical (lowercased) pack phrase
    rule: RoleRule


@dataclass
class _Binding:
    role: str
    rule: RoleRule
    cue_text: str
    cue_span: tuple[int, int]
    cue_phrase: str
    cue_tier: int                   # 2 adjacent | 1 windowed


def _cue_regex(pack: RolePack) -> re.Pattern[str]:
    phrases = sorted(
        {c for r in pack.rules if r.kind != "intrinsic" for c in r.cues},
        key=len, reverse=True,
    )
    return re.compile(
        r"\b(?:" + "|".join(re.escape(p) for p in phrases) + r")\b",
        re.IGNORECASE,
    )


def _scan_cues(text: str, pack: RolePack) -> list[_CueOcc]:
    """All cue occurrences, longest-match-first, each tagged with its rule."""
    by_phrase: dict[str, RoleRule] = {}
    for r in pack.rules:
        if r.kind == "intrinsic":
            continue
        for c in r.cues:
            by_phrase.setdefault(c, r)
    occs = []
    for m in _cue_regex(pack).finditer(text):
        phrase = m.group(0).lower()
        rule = by_phrase.get(phrase)
        if rule is not None:
            occs.append(_CueOcc(m.start(), m.end(), phrase, rule))
    return occs


def _gap_tier(text: str, cue_end: int, span_start: int,
              pack: RolePack) -> int | None:
    """Cue-window check: 2 adjacent, 1 windowed, None = does not bind."""
    if span_start < cue_end:
        return None
    gap = text[cue_end:span_start]
    if len(gap) > pack.max_gap:
        return None
    if _BOUNDARY_RE.search(gap):
        return None
    tokens = [t for t in re.split(r"[\s,:;–—-]+", gap) if t]
    if all(t.lower() in pack.fillers for t in tokens):
        return 2
    return 1


def _find_join(text: str, start: int, pack: RolePack,
               joins: tuple[str, ...]) -> tuple[int, int] | None:
    """Match a pair rule's join cue immediately after ``start`` (whitespace and
    commas allowed before it, word boundary required after it)."""
    m = re.match(r"[\s,]*", text[start:])
    at = start + m.end()
    for j in sorted(joins, key=len, reverse=True):
        end = at + len(j)
        if text[at:end].lower() != j:
            continue
        if end < len(text) and (text[end].isalnum() or text[end] == "_"):
            continue  # "and" must not match inside "android"
        return (at, end)
    return None


# ---------------------------------------------------------------------------
# extract_places
# ---------------------------------------------------------------------------


def extract_places(text: str, *,
                   rules: RolePack | None = None) -> list[PlaceMention]:
    """Extract place mentions from free text with their spatial role.

    Returns mentions sorted by span start; spans never overlap. A mention
    whose cues are absent or conflicting carries ``role="unknown"`` and floor
    confidence — the extractor abstains rather than guesses. Every committed
    role carries the cue text, its span, and the pack rule id that decided it.
    """
    if not text or not text.strip():
        return []
    pack = rules or load_role_pack()

    spans = _detect_spans(text)
    occs = _scan_cues(text, pack)
    # Cue occurrences inside a detected span are span-internal words
    # (anchor prepositions, "of", street tokens) — not external cues.
    occs = [o for o in occs
            if not any(s.start <= o.start and o.end <= s.end for s in spans)]

    # A cue straddling a span's start owns its opening words ("Drop off at
    # the shop opposite..." — the informal-landmark span must not swallow
    # "off at"); trim the span to begin after the cue.
    for s in spans:
        for o in occs:
            if o.start < s.start < o.end:
                new_start = o.end
                while new_start < s.end and text[new_start] == " ":
                    new_start += 1
                s.start, s.address = new_start, None

    # Detector 4: license a capitalized phrase after each cue. A licensed
    # phrase that CONTAINS a known span upgrades it ("arrives at Kano
    # International Airport" absorbs the gazetteer's "Kano"); one that
    # overlaps a parsed span defers to the parser; otherwise it is only
    # admitted where the cue would otherwise have no target at all.
    for occ in occs:
        licensed = _license_span(text, occ.end, None)
        if licensed is None:
            continue
        contained = [i for i, s in enumerate(spans)
                     if licensed.start <= s.start and s.end <= licensed.end]
        overlaps_parsed = any(
            s.tier == 2 and s.start < licensed.end and licensed.start < s.end
            for s in spans
        )
        if overlaps_parsed:
            continue
        if contained:
            licensed.tier = max(spans[i].tier for i in contained)
            spans = [s for i, s in enumerate(spans) if i not in contained]
            spans.append(licensed)
        elif not any(
            _gap_tier(text, occ.end, s.start, pack) is not None for s in spans
        ):
            spans.append(licensed)
    spans = _dedup_spans(spans)

    bindings: dict[int, list[_Binding]] = {i: [] for i in range(len(spans))}
    consumed: set[int] = set()

    # Pair frames first ("between A and B") — they claim two spans at once.
    # The A slot prefers a licensable phrase directly after the cue over a
    # farther known span ("transfers between Tema and Kumasi": Tema may not
    # be in the gazetteer, but it is what "between" governs).
    for oi, occ in enumerate(occs):
        if occ.rule.kind != "pair":
            continue
        a_idx = _nearest_span(text, occ, spans, pack)
        lic_a = _license_span(text, occ.end, spans)
        if lic_a is not None and (
            a_idx is None or lic_a.start < spans[a_idx].start
        ):
            spans.append(lic_a)
            a_idx = len(spans) - 1
        if a_idx is None:
            continue
        a = spans[a_idx]
        join = _find_join(text, a.end, pack, occ.rule.join)
        if join is None:
            continue
        b_idx = None
        for i, s in enumerate(spans):
            if s.start >= join[1] and (b_idx is None or s.start < spans[b_idx].start):
                gap = text[join[1]:s.start]
                if len(gap) <= pack.max_gap and not _BOUNDARY_RE.search(gap):
                    b_idx = i
        if b_idx is None:
            licensed = _license_span(text, join[1], spans)
            if licensed is None:
                continue
            # Append without re-sorting: _license_span guarantees no overlap,
            # so existing binding indices stay valid and the new span simply
            # takes the next index. Output order is fixed by the final sort.
            spans.append(licensed)
            b_idx = len(spans) - 1
        tier_a = _gap_tier(text, occ.end, spans[a_idx].start, pack) or 1
        role_a, role_b = occ.rule.roles
        bindings.setdefault(a_idx, []).append(_Binding(
            role_a, occ.rule, text[occ.start:occ.end],
            (occ.start, occ.end), occ.phrase, tier_a,
        ))
        bindings.setdefault(b_idx, []).append(_Binding(
            role_b, occ.rule, text[join[0]:join[1]],
            (join[0], join[1]), text[join[0]:join[1]].lower(), 2,
        ))
        consumed.add(oi)

    # Single cues: each unconsumed occurrence binds its nearest valid span.
    for oi, occ in enumerate(occs):
        if oi in consumed or occ.rule.kind != "single":
            continue
        idx = _nearest_span(text, occ, spans, pack)
        if idx is None:
            continue
        if spans[idx].tier < occ.rule.min_span_tier:
            continue
        tier = _gap_tier(text, occ.end, spans[idx].start, pack)
        if tier is None:
            continue
        role = occ.rule.roles[0]
        if _NEGATION_RE.search(text[max(0, occ.start - 24):occ.start]):
            role = "unknown"  # the sentence cancels the role it names
        bindings.setdefault(idx, []).append(_Binding(
            role, occ.rule, text[occ.start:occ.end],
            (occ.start, occ.end), occ.phrase, tier,
        ))

    # Intrinsic anchors: the relation word lives inside the span.
    intrinsic = next((r for r in pack.rules if r.kind == "intrinsic"), None)
    if intrinsic is not None:
        for idx, s in enumerate(spans):
            span_text = text[s.start:s.end]
            low = span_text.lower()
            for prep in _ANCHOR_PREPOSITIONS:  # longest-first at module load
                p = prep.lower()
                if low.startswith(p + " "):
                    bindings.setdefault(idx, []).append(_Binding(
                        intrinsic.roles[0], intrinsic, span_text[:len(p)],
                        (s.start, s.start + len(p)), p, 2,
                    ))
                    break

    # Resolve per span: max priority wins; a role conflict at the top is an
    # abstention, never a guess.
    mentions: list[PlaceMention] = []
    for idx, s in enumerate(spans):
        cands = bindings.get(idx, [])
        mentions.append(_resolve(text, s, cands))
    mentions.sort(key=lambda m: m.span[0])
    return mentions


def _nearest_span(text: str, occ: _CueOcc, spans: list[_Span],
                  pack: RolePack) -> int | None:
    """Nearest span starting after the cue that the window admits."""
    best: int | None = None
    for i, s in enumerate(spans):
        if _gap_tier(text, occ.end, s.start, pack) is None:
            continue
        if best is None or s.start < spans[best].start:
            best = i
    return best


def _resolve(text: str, s: _Span, cands: list[_Binding]) -> PlaceMention:
    span_text = text[s.start:s.end]
    evidence: list[str] = [_SPAN_TIER_EVIDENCE[s.tier]]

    role: PlaceRole = "unknown"
    cue = cue_phrase = cue_rule = None
    cue_span = None
    cue_tier = 0
    if cands:
        top = max(b.rule.priority for b in cands)
        kept = [b for b in cands if b.rule.priority == top]
        roles = {b.role for b in kept}
        if len(roles) > 1:
            nearest = min(kept, key=lambda b: s.start - b.cue_span[1])
            cue, cue_span = nearest.cue_text, nearest.cue_span
            cue_phrase, cue_rule = nearest.cue_phrase, nearest.rule.id
            ids = "|".join(sorted({b.rule.id for b in kept}))
            evidence.append(f"cue_conflict:{ids}")
        else:
            best = max(kept, key=lambda b: (b.cue_tier, len(b.cue_phrase)))
            role = best.role  # type: ignore[assignment]
            cue, cue_span = best.cue_text, best.cue_span
            cue_phrase, cue_rule = best.cue_phrase, best.rule.id
            if role == "unknown":
                cue_tier = 0  # negated cue: named, reported, and abstained on
                evidence.append("cue:negated")
            else:
                cue_tier = best.cue_tier
                evidence.append(_CUE_TIER_EVIDENCE[cue_tier])
    else:
        evidence.append("cue:absent")

    confidence = _CONFIDENCE[(cue_tier, s.tier)]

    address = s.address
    if address is None:
        address = parse_address(span_text)
    if address is None:
        comps = AddressComponents()
        low = span_text.lower()
        if s.tier == 1 and any(low.startswith(p.lower() + " ")
                               for p in _ANCHOR_PREPOSITIONS):
            comps.anchor = span_text
        elif s.tier == 1:
            comps.city = span_text
        elif _GB_POSTCODE_RE.fullmatch(span_text.strip()):
            comps.postal_code = span_text.strip()
        code, conf, _trigger = infer_jurisdiction(span_text)
        if any(vars(comps).values()):
            address = Address(raw=span_text, span=(s.start, s.end),
                              components=comps, country_inferred=code,
                              country_confidence=conf, confidence=0.3)
        juris, juris_conf = code, conf
    else:
        juris = address.country_inferred or "XX"
        juris_conf = address.country_confidence

    return PlaceMention(
        role=role, text=span_text, span=(s.start, s.end),
        cue=cue, cue_span=cue_span, cue_rule=cue_rule, cue_phrase=cue_phrase,
        confidence=confidence, evidence=tuple(evidence),
        address=address, jurisdiction=juris, jurisdiction_confidence=juris_conf,
    )


# ---------------------------------------------------------------------------
# The gold set and the grader — the shareable half
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GoldPlace:
    role: str
    text: str
    span: tuple[int, int]
    cue: str | None
    cue_span: tuple[int, int] | None


@dataclass(frozen=True)
class GoldSentence:
    id: str
    text: str
    register: str
    jurisdiction: str
    places: tuple[GoldPlace, ...]
    note: str = ""


def load_gold(name: str = "place_roles_v1") -> list[GoldSentence]:
    """Load a labeled gold sentence set shipped in the wheel.

    Entries reference substrings, not offsets — the loader resolves each
    fragment to a span and raises when a fragment is absent or ambiguous,
    so the data file validates itself.
    """
    import yaml

    path = Path(__file__).resolve().parent / "_eval" / f"{name}.yaml"
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    sentences: list[GoldSentence] = []
    for raw in data.get("sentences", []):
        sid, text = raw["id"], raw["text"]
        places: list[GoldPlace] = []
        for p in raw.get("places") or []:
            span = _resolve_fragment(text, p["text"], sid, "place")
            cue = p.get("cue")
            cue_span = None
            if cue:
                cue_span = _resolve_cue_fragment(text, cue, span, sid)
            places.append(GoldPlace(
                role=p["role"], text=p["text"], span=span,
                cue=cue, cue_span=cue_span,
            ))
            if p["role"] not in _ROLES:
                raise RolePackError(
                    f"gold {sid}: unknown role {p['role']!r}"
                )
        sentences.append(GoldSentence(
            id=sid, text=text, register=raw.get("register", ""),
            jurisdiction=raw.get("jurisdiction", ""),
            places=tuple(places), note=raw.get("note", ""),
        ))
    return sentences


def _resolve_fragment(text: str, fragment: str, sid: str,
                      what: str) -> tuple[int, int]:
    count = text.count(fragment)
    if count == 0:
        raise RolePackError(f"gold {sid}: {what} fragment {fragment!r} "
                            "not found in sentence text")
    if count > 1:
        raise RolePackError(f"gold {sid}: {what} fragment {fragment!r} is "
                            "ambiguous (occurs more than once)")
    start = text.index(fragment)
    return (start, start + len(fragment))


def _resolve_cue_fragment(text: str, cue: str, span: tuple[int, int],
                          sid: str) -> tuple[int, int]:
    """Cues may legitimately repeat ("and"); take the occurrence nearest the
    place span, case-insensitively."""
    best: tuple[int, int] | None = None
    low, cue_low = text.lower(), cue.lower()
    at = low.find(cue_low)
    while at != -1:
        cand = (at, at + len(cue))
        if best is None or abs(span[0] - cand[1]) < abs(span[0] - best[1]):
            best = cand
        at = low.find(cue_low, at + 1)
    if best is None:
        raise RolePackError(f"gold {sid}: cue fragment {cue!r} not found")
    return best


@dataclass
class PlaceGrade:
    """Per-role scores + the refusal accounting, for any extractor's output.

    ``precision``/``recall``/``f1`` are ``None`` (never a fake 0.0) when the
    denominator is empty — no grade over zero items.
    """

    per_role: dict[str, dict[str, Any]]
    span_tp: int
    span_fp: int
    span_fn: int
    cue_correct: int
    cue_total: int
    abstentions: dict[str, int]
    pack: str | None = None

    @property
    def span_f1(self) -> float | None:
        return _f1(self.span_tp, self.span_fp, self.span_fn)

    @property
    def cue_accuracy(self) -> float | None:
        if not self.cue_total:
            return None
        return round(self.cue_correct / self.cue_total, 4)

    def summary(self) -> dict[str, Any]:
        return {
            "per_role": self.per_role,
            "span_f1": self.span_f1,
            "cue_accuracy": self.cue_accuracy,
            "abstentions": self.abstentions,
            "pack": self.pack,
        }


def _f1(tp: int, fp: int, fn: int) -> float | None:
    if tp + fp + fn == 0:
        return None
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    if not p or not r:
        return 0.0 if (fp or fn) else None
    return round(2 * p * r / (p + r), 4)


def _pred_fields(pred: Any) -> tuple[tuple[int, int], str, tuple[int, int] | None]:
    """(span, role, cue_span) from a PlaceMention or a plain mapping — plain
    dicts are accepted so a non-Python extractor's JSON grades against the
    same set."""
    if isinstance(pred, PlaceMention):
        return pred.span, pred.role, pred.cue_span
    span = pred.get("span") or (pred.get("start"), pred.get("end"))
    cue_span = pred.get("cue_span")
    if cue_span is None and pred.get("cue_start") is not None:
        cue_span = (pred["cue_start"], pred["cue_end"])
    return (int(span[0]), int(span[1])), str(pred.get("role", "unknown")), (
        (int(cue_span[0]), int(cue_span[1])) if cue_span else None
    )


def _jaccard(a: tuple[int, int], b: tuple[int, int]) -> float:
    inter = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    union = max(a[1], b[1]) - min(a[0], b[0])
    return inter / union if union else 0.0


def grade_places(
    gold: Sequence[GoldSentence],
    predictions: Mapping[str, Sequence[Any]],
    *,
    match: Literal["overlap", "exact"] = "overlap",
    pack: str | None = None,
) -> PlaceGrade:
    """Score any extractor's output against a gold set.

    ``predictions`` maps gold sentence id -> mentions (``PlaceMention``s or
    plain dicts with ``start``/``end``/``role``). Alignment is greedy
    one-to-one by span Jaccard (>0 for ``overlap``, ==1.0 for ``exact``).

    Refusal discipline (the point of the whole exercise): predicting
    ``unknown`` where gold committed counts as a false negative and
    ``missed_by_abstention`` — a non-answer, never a wrong answer. Predicting
    a committed role where gold is ``unknown`` counts as ``over_guess`` AND a
    false positive — that is the failure mode this feature exists to prevent.
    """
    per_role = {r: {"tp": 0, "fp": 0, "fn": 0} for r in _COMMITTED_ROLES}
    span_tp = span_fp = span_fn = 0
    cue_correct = cue_total = 0
    abst = {"correct_unknown": 0, "over_guess": 0, "missed_by_abstention": 0}

    for sent in gold:
        preds = [(_pred_fields(p)) for p in predictions.get(sent.id, ())]
        used: set[int] = set()
        pairs: list[tuple[GoldPlace, int, float]] = []
        for g in sent.places:
            best, best_j = None, 0.0
            for i, (span, _role, _cs) in enumerate(preds):
                if i in used:
                    continue
                j = _jaccard(g.span, span)
                ok = (j == 1.0) if match == "exact" else (j > 0.0)
                if ok and j > best_j:
                    best, best_j = i, j
            if best is not None:
                used.add(best)
                pairs.append((g, best, best_j))
            else:
                span_fn += 1
                if g.role in per_role:
                    per_role[g.role]["fn"] += 1
        for i, (_span, role, _cs) in enumerate(preds):
            if i not in used:
                span_fp += 1
                if role in per_role:
                    per_role[role]["fp"] += 1
                elif role == "unknown":
                    pass  # an abstained hallucinated span is only a span error

        for g, i, _j in pairs:
            span_tp += 1
            _span, role, cue_span = preds[i]
            if g.role == "unknown":
                if role == "unknown":
                    abst["correct_unknown"] += 1
                else:
                    abst["over_guess"] += 1
                    if role in per_role:
                        per_role[role]["fp"] += 1
                continue
            if role == "unknown":
                abst["missed_by_abstention"] += 1
                per_role[g.role]["fn"] += 1
                continue
            if role == g.role:
                per_role[role]["tp"] += 1
                if g.cue_span is not None:
                    cue_total += 1
                    if cue_span is not None and _jaccard(g.cue_span, cue_span) > 0:
                        cue_correct += 1
            else:
                per_role[g.role]["fn"] += 1
                if role in per_role:
                    per_role[role]["fp"] += 1

    out: dict[str, dict[str, Any]] = {}
    for role, c in per_role.items():
        tp, fp, fn = c["tp"], c["fp"], c["fn"]
        out[role] = {
            "tp": tp, "fp": fp, "fn": fn,
            "precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "recall": round(tp / (tp + fn), 4) if tp + fn else None,
            "f1": _f1(tp, fp, fn),
        }
    return PlaceGrade(
        per_role=out, span_tp=span_tp, span_fp=span_fp, span_fn=span_fn,
        cue_correct=cue_correct, cue_total=cue_total,
        abstentions=abst, pack=pack,
    )


__all__ = [
    "PlaceMention", "PlaceRole", "RolePack", "RolePackError",
    "GoldSentence", "GoldPlace", "PlaceGrade",
    "extract_places", "load_role_pack", "load_gold", "grade_places",
]
