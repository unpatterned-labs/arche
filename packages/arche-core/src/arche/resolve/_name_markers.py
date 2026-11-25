"""Unit designators and country words in names — refute-only discriminators.

Two shapes produced confident false merges on the first UK and Nigeria runs
(18 November 2026), and in both countries the name similarity could not see the
token that carried the difference:

* **Unit designators.** ``Ark Data Centres (UK) Cody Park A103`` merged with
  ``... Cody Park A102``; ``Spring Park 1`` with ``Spring Park P4``. In Nigeria
  ``Geregu I power station`` matched ``Geregu Power Plant`` while ``Geregu II``
  went to review. One or two characters out of thirty is a rounding error in a
  string similarity and the whole identity of the unit.
* **Country words.** ``Birds Eye Ltd. UK (Invoicing Only)`` merged with
  ``Birds Eye Ireland Ltd. (Invoicing Only)``: two legal entities at one
  invoicing address, separated only by the country in the name.

Those two comparators return ``None`` unless BOTH names carry a marker. A name that
states no unit or no country is missing evidence, not a disagreement —
``Geregu Power Plant`` says nothing about which unit — so absence never
refutes. Declared with ``weight 0`` and ``refutes_below``, they can only demote
a ``match`` to ``review``; they never create agreement and never reach
``no_match``. That bounds the cost of a wrong refutation at one human glance.

A third, :func:`compare_group_words`, separates the companies of one group on a
register, and is the one that does read absence; see its docstring.

What is deliberately NOT a designator: number words (``One``, ``Two``), because
``One Stop Shop`` and ``East Anglia One`` are names, not units. So ``East Anglia
One North`` against ``East Anglia Offshore Wind`` is not settled here; it is a
different-company case for the legal-entity lane.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path

from arche.resolve._matcher import _normalise_text

# ── unit designators ─────────────────────────────────────────────────────────

_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8,
          "ix": 9, "x": 10, "xi": 11, "xii": 12, "xiii": 13, "xiv": 14, "xv": 15,
          "xvi": 16, "xvii": 17, "xviii": 18, "xix": 19, "xx": 20}
# A token carrying a digit, at most six characters: `2`, `p4`, `a103`, `lon01`,
# `2nd`. Longer digit runs are identifiers or phone numbers, not unit labels.
_CODE = re.compile(r"^(?=[a-z]*[0-9])[a-z0-9]{1,6}$")
_ORDINAL = re.compile(r"^([0-9]+)(st|nd|rd|th)$")
#: Compass words name a part of a place the way a unit number does:
#: `Sarkin Yamma Health Post` (west) and `Sarkin Kudu Health Post` (south) are
#: two facilities that a token table reads as one, because both words are
#: common. English, Hausa (arewa, kudu, gabas, yamma) and Yoruba (ariwa,
#: guusu). Added 20 Nov 2026 from the GRID3 coordless dedupe. Words that are
#: also ordinary in names elsewhere (Igbo `ugwu`, "hill") are left out.
_DIRECTIONS = {
    "north": "N", "northern": "N", "arewa": "N", "ariwa": "N",
    "south": "S", "southern": "S", "kudu": "S", "guusu": "S",
    "east": "E", "eastern": "E", "gabas": "E",
    "west": "W", "western": "W", "yamma": "W",
}


def name_designators(name: str) -> frozenset[str]:
    """The unit designators a name states, normalised; empty if none.

    Roman numerals become digits so ``Geregu II`` and ``Geregu 2`` agree;
    ordinals lose their suffix; leading zeros go (``LON01`` keeps its letters,
    so it stays ``lon01``). A bare ``I`` counts only after the first word, so
    ``I Love Food Ltd`` states no unit.
    """
    tokens = _normalise_text(str(name)).replace("-", " ").replace("/", " ").split()
    tokens = [t.strip(".,;:()[]") for t in tokens if t.strip(".,;:()[]")]
    # One label written with a space: `D 2` is `D2`, `6 A` is `6a`. Without
    # this `D 2 Staff Clinic` and `D2 Staff Clinic` stated different units.
    joined: list[str] = []
    for token in tokens:
        if joined and ((len(joined[-1]) == 1 and joined[-1].isalpha() and token.isdigit()
                        and len(token) <= 4)
                       or (joined[-1].isdigit() and len(token) == 1 and token.isalpha()
                           and token not in _ROMAN)):
            joined[-1] += token
        else:
            joined.append(token)
    tokens = joined
    out: set[str] = set()
    for position, token in enumerate(tokens):
        if not token:
            continue
        if token in _DIRECTIONS:
            out.add("dir:" + _DIRECTIONS[token])
            continue
        if token in _ROMAN and (token != "i" or position > 0):
            out.add(str(_ROMAN[token]))
            continue
        ordinal = _ORDINAL.match(token)
        if ordinal:
            out.add(str(int(ordinal.group(1))))
        elif _CODE.match(token):
            out.add(str(int(token)) if token.isdigit() else token)
    return frozenset(out)


def designator_markers_pin() -> str:
    """Content address of the designator vocabulary, so a receipt names it."""
    from arche.ids import content_hash

    body = {"roman": sorted(_ROMAN.items()), "directions": sorted(_DIRECTIONS.items()),
            "code": _CODE.pattern, "ordinal": _ORDINAL.pattern}
    return "designator_markers@" + content_hash(body, prefix="dm").split(":")[-1]


def compare_designators(name_a: str, name_b: str) -> float | None:
    """``1.0`` same units, ``0.0`` contradicting units, ``None`` otherwise.

    Contradiction needs each side to state a unit the other does not, after
    the shared ones are set aside -- the mutual rule `rival` uses. So
    ``Factory 1 & 2`` against ``Factory 2`` (a site and one of its parts) and
    ``LON01`` against ``LON01 (Building 1)`` are silent, while ``Building 1``
    against ``Building 2`` refutes.
    """
    a, b = name_designators(name_a), name_designators(name_b)
    if not a or not b:
        return None
    if a == b:
        return 1.0
    return 0.0 if (a - b) and (b - a) else None


# ── words that separate companies in one group ───────────────────────────────

#: Words a group uses to name its companies apart, each with its other spellings.
#: `Pondwell Limited`, `Pondwell Holdings Limited` and `Pondwell Services
#: Limited` are three companies, usually at one registered office. The words are
#: common, so a token table reads them as saying little; on a register they are
#: the whole difference. On CQC providers against Companies House (X17's dev
#: districts, 25 Nov 2026) pairs whose group words differ were 547 of the 872
#: wrong matches and 9 of the 8,534 right ones.
_GROUP_WORDS = {
    "holdings": ("holding", "hldgs"), "group": ("grp",), "trading": (),
    "services": ("service",), "properties": ("property",),
    "investments": ("investment",), "management": (),
    "developments": ("development",), "finance": ("financing",), "capital": (),
    "nominees": ("nominee",), "trustees": ("trustee",), "pension": ("pensions",),
    "enterprises": ("enterprise",), "international": ("intl",), "logistics": (),
    "estates": (), "assets": (), "ventures": (), "operations": (),
    "recruitment": (), "training": (), "consulting": ("consultancy",),
    "solutions": (), "partners": ("partnership",),
}
_GROUP = {w: k for k, forms in _GROUP_WORDS.items() for w in (k, *forms)}


def _trailing_letter(tokens: list[str]) -> str | None:
    """The letter that closes a name, its legal form aside: `Pondwell A Limited`."""
    while tokens and tokens[-1] in _LEGAL_TAIL:
        tokens = tokens[:-1]
    if len(tokens) > 1 and len(tokens[-1]) == 1 and tokens[-1].isalpha():
        return tokens[-1]
    return None


_LEGAL_TAIL = frozenset({"ltd", "limited", "plc", "llp", "lp", "inc", "llc", "corp",
                         "corporation", "company", "co", "cic", "cio", "gmbh"})


def compare_group_words(name_a: str, name_b: str) -> float | None:
    """``0.0`` when two names differ in a group word or a closing letter, else ``None``.

    Unlike the comparators above, one side is enough: the parent is usually the
    company that states no group word. That is only right between legal names,
    which is why the ``legal_entity`` pack carries it and ``organisation``, whose
    lists hold trading names, does not. Refuting only: it never returns 1.0.
    """
    a, b = (re.sub(r"[^a-z0-9]+", " ", _normalise_text(str(n)).replace("'", "")).split()
            for n in (name_a, name_b))
    if {_GROUP[t] for t in a if t in _GROUP} != {_GROUP[t] for t in b if t in _GROUP}:
        return 0.0
    letter_a, letter_b = _trailing_letter(a), _trailing_letter(b)
    return 0.0 if letter_a and letter_b and letter_a != letter_b else None


def group_words_pin() -> str:
    """Content address of the group words, so a receipt names them."""
    from arche.ids import content_hash

    body = {"group_words": sorted(_GROUP.items()), "legal_tail": sorted(_LEGAL_TAIL)}
    return "group_words@" + content_hash(body, prefix="gw").split(":")[-1]


# ── country words ────────────────────────────────────────────────────────────

_SNAPSHOT = Path(__file__).resolve().parents[1] / "_data" / "restcountries-v3.1-snapshot.json"

#: Abbreviations and demonyms the snapshot does not carry. Constituent nations
#: map to GB, so ``Scotland`` against ``UK`` agrees rather than refutes: the
#: safe direction when one side is a part of the other.
_EXTRA = {
    "uk": "GB", "u k": "GB", "gb": "GB", "great britain": "GB", "britain": "GB",
    "british": "GB", "england": "GB", "english": "GB", "scotland": "GB",
    "scottish": "GB", "wales": "GB", "welsh": "GB", "northern ireland": "GB",
    "usa": "US", "u s a": "US", "american": "US", "uae": "AE",
    "irish": "IE", "french": "FR", "german": "DE", "italian": "IT", "spanish": "ES",
    "dutch": "NL", "belgian": "BE", "swiss": "CH", "portuguese": "PT", "polish": "PL",
    "danish": "DK", "swedish": "SE", "norwegian": "NO", "finnish": "FI",
    "nigerian": "NG", "ghanaian": "GH", "kenyan": "KE", "south african": "ZA",
    "cameroonian": "CM", "beninese": "BJ", "canadian": "CA", "chinese": "CN",
    "indian": "IN", "pakistani": "PK", "japanese": "JP", "turkish": "TR",
    "thai": "TH", "vietnamese": "VN", "brazilian": "BR", "mexican": "MX",
}

#: Country names that are also ordinary words, brands or given names in the
#: names arche reads. Matching them would refute true pairs: `Iceland Foods`
#: (a UK supermarket), `Malta Guinness` (a Nigerian drink), `Jersey` knitwear,
#: `Jordan`, `Chad`, `Georgia` (people), `Turkey`, `China` (goods). Left out
#: entirely rather than guessed at.
_AMBIGUOUS = frozenset({
    "chad", "china", "georgia", "guinea", "iceland", "jersey", "guernsey", "jordan",
    "malta", "panama", "turkey", "cuba", "chile", "togo", "mali", "niger",
    "lebanon", "dominica", "peru", "oman", "jamaica", "christmas island",
    "india",  # `India` as a given name and in brand names; the demonym stays
})


@cache
def _country_lexicon() -> tuple[tuple[re.Pattern[str], str], ...]:
    entries: dict[str, str] = {}
    with open(_SNAPSHOT, encoding="utf-8") as fh:
        for country in json.load(fh):
            code = country.get("cca2")
            names = country.get("name") or {}
            for key in ("common", "official"):
                text = _normalise_text(str(names.get(key) or "")).replace(".", "")
                if text and text not in _AMBIGUOUS and code:
                    entries.setdefault(text, code)
    for text, code in _EXTRA.items():
        entries[_normalise_text(text)] = code
    # Longest first, so `south africa` is found before `africa`-like substrings
    # and `united kingdom` before anything shorter inside it.
    ordered = sorted(entries.items(), key=lambda kv: (-len(kv[0]), kv[0]))
    return tuple((re.compile(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])"), c)
                 for t, c in ordered)


def country_markers_pin() -> str:
    """Content address of the lexicon, so a receipt names the one it used."""
    from arche.ids import content_hash

    body = [(p.pattern, c) for p, c in _country_lexicon()]
    return "country_markers@" + content_hash(body, prefix="cm").split(":")[-1]


def name_countries(name: str) -> frozenset[str]:
    """ISO alpha-2 codes of the countries a name mentions; empty if none."""
    text = _normalise_text(str(name)).replace(".", " ")
    text = re.sub(r"\s+", " ", text)
    found: set[str] = set()
    for pattern, code in _country_lexicon():
        if pattern.search(text):
            found.add(code)
            text = pattern.sub(" ", text)
    return frozenset(found)


def compare_countries(name_a: str, name_b: str) -> float | None:
    """``0.0`` when both names name countries and none is shared.

    ``1.0`` when they name the same set; ``None`` when either names none, or
    when the sets overlap without being equal (``UK & Ireland`` against
    ``Ireland`` is a parent and a part, not a contradiction).
    """
    a, b = name_countries(name_a), name_countries(name_b)
    if not a or not b:
        return None
    if a == b:
        return 1.0
    return 0.0 if not (a & b) else None
