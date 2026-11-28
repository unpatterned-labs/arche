# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Rules for :func:`arche.time.extract_times`. See the package docstring."""

from __future__ import annotations

import calendar
import datetime as _dt
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

_D = _dt.timedelta
DAY, MIN = _D(days=1), _D(minutes=1)

# ── words ────────────────────────────────────────────────────────────────────

_NUM_WORDS = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "ninety": 90,
    "couple of": 2,
    "a couple of": 2,
    "few": 3,
    "a few": 3,
}
_NUM = (
    r"(?:\d{1,3}|"
    + "|".join(sorted((re.escape(w) for w in _NUM_WORDS), key=len, reverse=True))
    + r")"
)
_UNIT = (
    r"(?P<unit>(?:business|working|work|bank)[\s-]?days?|workdays?|clear\s+days?"
    r"|min(?:ute)?s?|mins|hours?|hrs?|days?|nights?|weeks?|wks?|fortnights?|months?|mths?"
    r"|years?|yrs?)"
)
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_WD_FORMS = {w: i for i, w in enumerate(_WEEKDAYS)}
_WD_FORMS.update(
    {
        "mon": 0,
        "tue": 1,
        "tues": 1,
        "wed": 2,
        "weds": 2,
        "thu": 3,
        "thur": 3,
        "thurs": 3,
        "fri": 4,
        "sat": 5,
        "sun": 6,
    }
)
_SW_WEEKDAYS = {
    "jumatatu": 0,
    "jumanne": 1,
    "jumatano": 2,
    "alhamisi": 3,
    "ijumaa": 4,
    "jumamosi": 5,
    "jumapili": 6,
}
_WD = r"(?P<wd>" + "|".join(sorted(_WD_FORMS, key=len, reverse=True)) + r")\.?"
_MONTHS: dict[str, int] = {}
for _i, _name in enumerate(calendar.month_name):
    if _i:
        _MONTHS[_name.lower()] = _i
        _MONTHS[_name[:3].lower()] = _i
_MONTHS["sept"] = 9
_MON = r"(?P<mon>" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?"
# Month names that are also names or verbs: they need a day, a year or a preposition.
_MONTH_WORDS = {
    "may",
    "march",
    "june",
    "april",
    "august",
    "jan",
    "mar",
    "jun",
    "aug",
    "sept",
    "sep",
}

# Day words, by language. Plain Yoruba and Hausa forms need ``language``.
_DAY_WORDS = {
    "today": 0,
    "tonight": 0,
    "tonite": 0,
    "this night": 0,
    "tomorrow": 1,
    "tomorow": 1,
    "tmrw": 1,
    "tmr": 1,
    "tmw": 1,
    "2moro": 1,
    "2morrow": 1,
    "2mrw": 1,
    "tomoro": 1,
    "yesterday": -1,
    "yday": -1,
    "ystday": -1,
    "day after tomorrow": 2,
    "the day after tomorrow": 2,
    "next tomorrow": 2,
    "next tomorow": 2,
    "day before yesterday": -2,
    "the day before yesterday": -2,
    "leo": 0,
    "kesho": 1,
    "jana": -1,
    "kesho kutwa": 2,
    "keshokutwa": 2,
    "juzi": -2,
    "òní": 0,
    "ọ̀la": 1,
    "ọla": 1,
    "òla": 1,
    "àná": -1,
    "ọ̀túnla": 2,
    "otunla": 2,
}
_DAY_WORDS_PLAIN = {
    "yo": {"oni": 0, "ola": 1, "ana": -1},
    "ha": {"yau": 0, "gobe": 1, "jiya": -1, "jibi": 2, "shekaranjiya": -2},
}
_DAY_NIGHT = {"tonight", "tonite", "this night"}

_PARTS = {  # part of day -> (start hour, end hour); end may pass midnight
    "morning": (6, 12),
    "mrng": (6, 12),
    "afternoon": (12, 17),
    "evening": (17, 21),
    "night": (21, 30),
    "tonight": (21, 30),
    "midday": (12, 13),
    "noon": (12, 13),
    "asubuhi": (6, 12),
    "mchana": (12, 17),
    "jioni": (17, 21),
    "usiku": (21, 30),
}

# Swahili hours run from sunrise: saa moja is 7.
_SW_HOURS = {
    "moja": 1,
    "mbili": 2,
    "tatu": 3,
    "nne": 4,
    "tano": 5,
    "sita": 6,
    "saba": 7,
    "nane": 8,
    "tisa": 9,
    "kumi": 10,
    "kumi na moja": 11,
    "kumi na mbili": 12,
}

# Words after a bare number that make it a quantity or an address, not a time.
_NOT_TIME_AFTER = re.compile(
    r"^\s*(?:[A-Z][a-z]\w*\s+(?:[A-Z]|[Rr]oad|[Ss]treet|[Aa]venue|[Ll]ane|[Cc]lose|[Ww]ay|[Dd]rive|[Cc]rescent)"
    r"|[A-Z][a-z]*\s+(?:[Rr]oad|[Ss]treet|[Aa]venue|[Ll]ane|[Cc]lose)"
    r"|(?i:kg|g|km|m|%|percent|people|persons|items?|pieces?|pcs|boxes|bags|cartons|"
    r"crates|tons?|tonnes?|units?|naira|cedis|shillings|rand|dollars|pounds|ksh|ngn|by\b|x\b|of\b|"
    r"rooms?|flats?|floors?|street|road|avenue|lane|close)\b)"
)

# ── the mention ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TimeMention:
    """One time expression and what it means.

    ``type`` is ``date``, ``time``, ``datetime``, ``duration``, ``set`` or
    ``range``. ``start``/``end`` (ISO, end exclusive) are set when the
    expression names an interval and the anchor allows it; a date is written
    ``YYYY-MM-DD``, anything finer ``YYYY-MM-DDTHH:MM``. ``value`` is
    TIMEX3-style (``2026-03-15``, ``2026-03-15T16:00``, ``P3D``, ``XXXX-12-25``,
    ``2026-W12``, ``XXXX-WXX-2``). ``offset`` records a relative expression
    ("in 3 days": ``{"days": 3}``) and what it counts from (``relative_to``:
    ``anchor`` or ``previous``, the time before it in the text).
    """

    text: str
    span: tuple[int, int]
    type: str
    value: str | None = None
    start: str | None = None
    end: str | None = None
    mod: str | None = None
    ambiguous: bool = False
    alternatives: tuple[tuple[str, str], ...] = ()
    offset: dict[str, int] | None = None
    relative_to: str | None = None
    cue: str | None = None
    confidence: float = 0.9
    language: str = "en"

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "span": list(self.span),
            "type": self.type,
            "value": self.value,
            "start": self.start,
            "end": self.end,
            "mod": self.mod,
            "ambiguous": self.ambiguous,
            "alternatives": [list(a) for a in self.alternatives],
            "offset": self.offset,
            "relative_to": self.relative_to,
            "cue": self.cue,
            "confidence": self.confidence,
            "language": self.language,
        }


@dataclass
class _Atom:
    """A matched piece before it is joined to its neighbours."""

    start: int
    end: int
    kind: str  # day, clock, part, period, duration, set
    lo: _dt.datetime | None = None
    hi: _dt.datetime | None = None
    grain: str = "day"  # day, minute, week, month, quarter, year
    value: str | None = None
    alts: list[tuple[_dt.datetime, _dt.datetime]] = field(default_factory=list)
    offset: dict[str, int] | None = None
    rel: str | None = None
    cue: str | None = None
    conf: float = 0.9
    lang: str = "en"
    hour: int | None = None  # clock: 0-23, or 1-12 when am/pm is open
    minute: int = 0
    open_ampm: bool = False
    part: tuple[int, int] | None = None
    mod: str | None = None


# ── helpers ──────────────────────────────────────────────────────────────────


def _num(word: str) -> int:
    w = word.casefold().strip()
    return int(w) if w.isdigit() else _NUM_WORDS[w]


def _midnight(d: _dt.date) -> _dt.datetime:
    return _dt.datetime(d.year, d.month, d.day)


def _add_months(d: _dt.date, n: int) -> _dt.date:
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return _dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _month_span(y: int, m: int) -> tuple[_dt.datetime, _dt.datetime]:
    lo = _dt.datetime(y, m, 1)
    return lo, _midnight(_add_months(lo.date(), 1))


def _iso(t: _dt.datetime, grain: str) -> str:
    return t.strftime("%Y-%m-%d") if grain != "minute" else t.strftime("%Y-%m-%dT%H:%M")


def _day_value(lo: _dt.datetime) -> str:
    return lo.strftime("%Y-%m-%d")


def _past_tense(text: str, start: int) -> bool:
    """Whether the clause before ``start`` reads as the past."""
    clause = re.split(r"[.;!?\n]", text[:start])[-1].casefold()
    return bool(
        re.search(
            r"\b(?:was|were|did|had|went|came|sent|arrived|left|happened|ago|last|"
            r"since|delivered|received|paid|called|visited|saw|met|\w+ed)\b",
            clause,
        )
    )


def _ws(text: str, i: int, j: int) -> str:
    return text[i:j]


# ── atoms ────────────────────────────────────────────────────────────────────

_B, _E = r"(?<![\w/.:-])", r"(?![\w/-]|[.:]\d)"

_RE_DAYWORD = re.compile(
    _B
    + r"(?P<w>"
    + "|".join(sorted((re.escape(w) for w in _DAY_WORDS), key=len, reverse=True))
    + r")"
    + r"(?![\w])",
    re.IGNORECASE,
)
_RE_WEEKDAY = re.compile(
    _B
    + r"(?:(?P<q>this|next|last|coming|the\s+coming|on|by|this\s+coming|past|the\s+following)\s+)?"
    r"(?:(?P<wk>next|last|this)\s+week\s+)?" + _WD + r"(?:\s+(?P<wk2>next|last|this)\s+week)?"
    r"(?![\w])",
    re.IGNORECASE,
)
_RE_WEEK_ON = re.compile(_B + r"a\s+week\s+(?:on\s+|from\s+)?" + _WD + r"(?![\w])", re.IGNORECASE)
_RE_SW_WEEKDAY = re.compile(
    _B + r"(?P<wd>" + "|".join(_SW_WEEKDAYS) + r")(?:\s+(?P<q>ijayo|iliyopita|hii))?(?![\w])",
    re.IGNORECASE,
)
#: Events a period is counted from when the text gives no date for them: "30 days after invoice".
_EVENTS = (
    r"shipping|shipment|dispatch|despatch|delivery|receipt|invoice|invoicing|order|ordering"
    r"|purchase|payment|signing|signature|approval|booking|registration|notice|notification"
    r"|collection|pickup|pick-up|submission|confirmation|completion|filing|application"
)
_RE_OFFSET = re.compile(
    _B
    + r"(?:(?P<in>in|within|after)\s+(?:the\s+next\s+)?)?(?P<n>"
    + _NUM
    + r")(?:\s*(?:-|–|to)\s*(?P<n2>\d{1,3}))?\s+"
    + _UNIT
    + r"(?:\s+(?P<dir>from\s+(?:now|today|tomorrow|yesterday|the\s+(?:day|date)\b)"
    + r"|(?:after|from|following|of)\s+(?:the\s+|your\s+|our\s+|its\s+)?(?P<event>"
    + _EVENTS
    + r")\b"
    + r"|ago|time|later|after|before|earlier"
    r"|from\s+" + _WD + r"))?(?![\w])",
    re.IGNORECASE,
)
_RE_SW_OFFSET = re.compile(
    _B + r"(?:(?P<pre>baada\s+ya)\s+)?(?P<unit>siku|wiki|miezi|mwezi|miaka|mwaka|saa)\s+(?P<n>\w+)"
    r"(?:\s+(?P<post>zilizopita|iliyopita|zijazo|ijayo|ujao|zilizobaki))?(?![\w])",
    re.IGNORECASE,
)
_SW_NUMS = {
    "moja": 1,
    "mbili": 2,
    "tatu": 3,
    "nne": 4,
    "tano": 5,
    "sita": 6,
    "saba": 7,
    "nane": 8,
    "tisa": 9,
    "kumi": 10,
}
_RE_CHAIN = re.compile(
    _B
    + r"(?:the\s+)?(?P<w>(?:next|following|previous|same)\s+"
    + r"(?P<u>day|morning|evening|night|week|month)"
    r"|day\s+(?P<d>before|after))(?![\w])",
    re.IGNORECASE,
)
_RE_PERIOD = re.compile(
    _B
    + r"(?:(?P<edge>end|start|beginning|middle|mid|early|late"
    + r"|the\s+end|the\s+start|the\s+beginning)"
    r"(?:\s+of)?\s+(?:the\s+)?)?(?P<q>this|next|last|coming|current|the\s+coming|the\s+following)\s+"
    r"(?P<p>week|weekend|month|year|quarter)(?![\w])"
    r"|"
    + _B
    + r"(?P<edge2>end|start|beginning|middle)\s+of\s+(?:the\s+)?(?P<p2>week|month|year|day)(?![\w])"
    r"|" + _B + r"(?P<we>(?:the|this)\s+weekend)(?![\w])"
    r"|" + _B + r"(?P<qn>Q[1-4])(?:\s+(?P<qy>\d{4}))?(?![\w])"
    r"|"
    + _B
    + r"(?P<sw>wiki|mwezi|mwaka)\s+(?P<swq>ijayo|ujao|iliyopita|uliopita|huu|hii)(?![\w])",
    re.IGNORECASE,
)
_RE_ABS = [  # full dates
    ("iso", re.compile(_B + r"(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})(?![\w/-]|[.:]\d)")),
    (
        "num",
        re.compile(_B + r"(?P<a>\d{1,2})(?P<s>[/.-])(?P<b>\d{1,2})(?P=s)(?P<y>\d{4}|\d{2})" + _E),
    ),
    (
        "dmy",
        re.compile(
            r"(?i)(?<![\w.-])(?P<d>\d{1,2})(?:st|nd|rd|th)?(?:\s+of)?[\s-]+"
            + _MON
            + r"(?:[\s,-]+(?P<y>\d{4}))?(?![\w/-]|[.:]\d)"
        ),
    ),
    (
        "mdy",
        re.compile(
            r"(?i)(?<![\w.-])" + _MON + r"\s+(?P<d>\d{1,2})(?:st|nd|rd|th)?(?![\w])"
            r"(?:,?\s+(?P<y>\d{4}))?(?![\w/-]|[.:]\d)"
        ),
    ),
    (
        "my",
        re.compile(
            r"(?i)(?<![\w.-])(?:(?P<pre>in|by|since|until|till|from|next|last|this|early|late|mid|end\s+of)\s+)?"
            + _MON
            + r"(?:\s+(?P<y>\d{4}))?(?![\w])"
        ),
    ),
    (
        "ord",
        re.compile(
            r"(?i)(?<![\w.-])(?:the\s+)?(?P<d>\d{1,2})(?:st|nd|rd|th)(?!\s*(?:floor|time|edition|place|anniversary|birthday|grade|class|year|street))(?![\w])"
        ),
    ),
    ("short", re.compile(_B + r"(?P<a>\d{1,2})/(?P<b>\d{1,2})(?![\w/.-]|:\d)")),
]
_RE_CLOCK = re.compile(
    _B + r"(?:(?P<h>\d{1,2})(?:[:.](?P<mi>\d{2}))?\s*(?P<ap>a\.?\s?m\.?|p\.?\s?m\.?|am|pm)(?![\w])"
    r"|(?P<h24>[01]?\d|2[0-3]):(?P<m24>[0-5]\d)(?:\s*(?:hrs?|h)\b)?"
    r"|(?P<hhmm>[01]\d|2[0-3])(?P<mm>[0-5]\d)\s*(?:hrs|hours|h)(?![\w])"
    r"|(?P<half>half\s+past|quarter\s+past|quarter\s+to|(?P<mins>\d{1,2}|ten|twenty|five|twenty[\s-]five)\s+(?:minutes\s+)?(?P<pt>past|to))\s+(?P<hw>\d{1,2}|"
    + "|".join(
        w for w, n in _NUM_WORDS.items() if 1 <= n <= 12 and " " not in w and w not in ("a", "an")
    )
    + r")"
    r"|(?P<oc>\d{1,2}|"
    + "|".join(
        w for w, n in _NUM_WORDS.items() if 1 <= n <= 12 and " " not in w and w not in ("a", "an")
    )
    + r")\s*o'?\s?clock"
    r"|(?P<named>noon|midday|midnight|mid-day)"
    r")(?![\w])",
    re.IGNORECASE,
)
_RE_BARE = re.compile(  # "by 6", "around 7", "at 4:30" -- a time only after a time cue
    r"(?i)(?<![\w])(?P<cue>at|by|around|about|before|after|till|until|from|latest|between|and|to)\s+"
    r"(?P<h>\d{1,2})(?:[:.](?P<mi>[0-5]\d))?(?![\w:.,/-]|[.,]\d)"
)
_RE_PART = re.compile(
    _B + r"(?:(?P<q>this|tomorrow|yesterday|in\s+the|early|late|on\s+\w+)\s+)?"
    r"(?P<p>morning|mrng|afternoon|evening|night|asubuhi|mchana|jioni|usiku)(?![\w])",
    re.IGNORECASE,
)
_RE_SW_CLOCK = re.compile(
    r"(?i)(?<![\w])saa\s+(?P<h>\d{1,2}|kumi\s+na\s+(?:moja|mbili)|moja|mbili|tatu|nne|tano|sita|saba|nane|tisa|kumi)"
    r"(?:\s+(?P<frac>na\s+nusu|na\s+robo|kasorobo|kasoro\s+robo))?"
    r"(?:\s+(?:za\s+|ya\s+)?(?P<p>asubuhi|mchana|jioni|usiku|alfajiri))?(?![\w])"
)
_RE_DURATION = re.compile(
    r"(?i)(?<![\w])(?P<cue>for|lasting|lasts|takes|took|over|about)\s+(?:(?:about|around|roughly|the\s+next)\s+)?"
    r"(?P<n>" + _NUM + r")\s+" + _UNIT + r"(?![\w])"
    r"|(?<![\w])(?P<n2>\d{1,3}|"
    + "|".join(w for w in _NUM_WORDS if " " not in w and w not in ("a", "an", "few"))
    + r")[\s-](?P<unit2>day|week|month|hour|minute|year|night)(?:s)?[\s-]?long(?![\w])"
)
_RE_SET = re.compile(
    r"(?i)(?<![\w])(?:(?P<every>every|each)\s+(?:other\s+)?(?:"
    + _WD
    + r"|(?P<u>day|morning|evening|night|week|month|year|weekday|weekend))"
    r"|(?P<adv>daily|weekly|monthly|yearly|annually|fortnightly|nightly)"
    r"|(?P<k>once|twice|three\s+times|\d+\s+times)\s+(?:a|per|every)\s+(?P<ku>day|week|month|year))(?![\w])"
)

_RE_HHRANGE = re.compile(
    r"(?i)(?<![\w:/.-])(?P<h1>\d{1,2})(?::(?P<m1>[0-5]\d))?\s*(?P<ap1>am|pm)?\s*(?:-|–|to)\s*"
    r"(?P<h2>\d{1,2})(?::(?P<m2>[0-5]\d))?\s*(?P<ap2>am|pm|a\.m\.|p\.m\.)?(?![\w:/-])"
)
_HOURS_BEFORE = re.compile(
    r"(?i)(?:\b(?:"
    + "|".join(sorted(_WD_FORMS, key=len, reverse=True))
    + r")\.?|\b(?:open|opens|hours|from|"
    r"between|time|times|working|daily|weekdays|today|tomorrow|tonight|morning|evening)\b)[\s,:]*$"
)


def _atoms_hhrange(m: re.Match, c: _Ctx) -> list[_Atom]:
    h1, h2 = int(m["h1"]), int(m["h2"])
    if not (0 <= h1 <= 23 and 0 <= h2 <= 23):
        return []
    if not (
        m["ap1"] or m["ap2"] or _HOURS_BEFORE.search(c.text[max(0, m.start() - 30) : m.start()])
    ):
        return []
    out = []
    for h, mi, ap, s, e in (
        (
            h1,
            m["m1"],
            m["ap1"],
            m.start("h1"),
            m.end("ap1") if m["ap1"] else m.end("m1") if m["m1"] else m.end("h1"),
        ),
        (h2, m["m2"], m["ap2"], m.start("h2"), m.end()),
    ):
        a = _Atom(s, e, "clock", grain="minute", cue="hours", conf=0.75)
        a.pair = True  # type: ignore[attr-defined]
        a.hour, a.minute = h, int(mi or 0)
        if ap:
            if not 1 <= h <= 12:
                return []
            a.hour = h % 12 + (12 if ap.casefold().startswith("p") else 0)
        else:
            a.open_ampm = 1 <= h <= 12
        out.append(a)
    return out


_CUE_BEFORE = re.compile(
    r"(?i)(?:\b(?P<c>by|before|after|until|till|til|up\s+to|no\s+later\s+than|not\s+later\s+than|latest(?:\s+by)?|"
    r"from|since|around|about|approximately|approx\.?|circa|starting|beginning|not\s+before|on\s+or\s+before)\s*,?\s*)$"
)
_MOD = {
    "by": "ON_OR_BEFORE",
    "until": "ON_OR_BEFORE",
    "till": "ON_OR_BEFORE",
    "til": "ON_OR_BEFORE",
    "up to": "ON_OR_BEFORE",
    "no later than": "ON_OR_BEFORE",
    "not later than": "ON_OR_BEFORE",
    "latest": "ON_OR_BEFORE",
    "latest by": "ON_OR_BEFORE",
    "on or before": "ON_OR_BEFORE",
    "before": "BEFORE",
    "after": "AFTER",
    "not before": "ON_OR_AFTER",
    "from": "START",
    "since": "START",
    "starting": "START",
    "beginning": "START",
    "around": "APPROX",
    "about": "APPROX",
    "approximately": "APPROX",
    "approx": "APPROX",
    "approx.": "APPROX",
    "circa": "APPROX",
}


class _Ctx:
    weekend: tuple[int, ...] = (5, 6)
    holidays: frozenset = frozenset()

    def __init__(self, text: str, anchor: _dt.datetime | None, mdy: bool, language: str | None):
        self.text, self.anchor, self.mdy, self.language = (
            text,
            anchor,
            mdy,
            (language or "").casefold(),
        )

    @property
    def today(self) -> _dt.date | None:
        return self.anchor.date() if self.anchor else None


def _atom_dayword(m: re.Match, c: _Ctx) -> _Atom:
    w = re.sub(r"\s+", " ", m["w"].casefold())
    n = _DAY_WORDS.get(w, _DAY_WORDS_PLAIN.get(c.language, {}).get(w, 0))
    lang = (
        "sw"
        if w in ("leo", "kesho", "jana", "kesho kutwa", "keshokutwa", "juzi")
        else (
            "yo"
            if w in ("òní", "ọ̀la", "ọla", "òla", "àná", "ọ̀túnla", "otunla", "oni", "ola", "ana")
            else "ha"
            if w in ("yau", "gobe", "jiya", "jibi", "shekaranjiya")
            else "pcm"
            if w.startswith("next tom") or w == "this night"
            else "en"
        )
    )
    a = _Atom(m.start("w"), m.end("w"), "day", offset={"days": n}, rel="anchor", cue=w, lang=lang)
    if c.today:
        a.lo = _midnight(c.today + _D(days=n))
        a.hi = a.lo + DAY
        a.value = _day_value(a.lo)
    if w in _DAY_NIGHT:
        a.part = (21, 30)
    return a


def _next_weekday(today: _dt.date, wd: int, *, include_today: bool) -> _dt.date:
    ahead = (wd - today.weekday()) % 7
    if ahead == 0 and not include_today:
        ahead = 7
    return today + _D(days=ahead)


def _atom_weekday(
    m: re.Match, c: _Ctx, wd: int, q: str, week: str | None, lang: str = "en"
) -> _Atom:
    a = _Atom(m.start(), m.end(), "day", cue=(q + " " if q else "") + m["wd"].casefold(), lang=lang)
    if (
        m["wd"].casefold() in ("sun", "sat", "wed", "mon")
        and not q
        and not week
        and m["wd"] == m["wd"].lower()
    ):
        a.conf = 0.5
    a.value = f"XXXX-WXX-{wd + 1}"
    if not c.today:
        return a
    t = c.today
    monday = t - _D(days=t.weekday())
    readings: list[_dt.date] = []
    if week:
        shift = {"next": 7, "last": -7, "this": 0}[week]
        readings = [monday + _D(days=shift + wd)]
    elif q in ("next", "the following"):
        coming = _next_weekday(t, wd, include_today=False)
        following_week = monday + _D(days=7 + wd)
        readings = [following_week] if coming == following_week else [coming, following_week]
        if len(readings) == 2:
            # Both readings are common; the one inside next calendar week first.
            readings = [following_week, coming]
    elif q in ("last", "past"):
        recent = t - _D(days=((t.weekday() - wd) % 7) or 7)
        prev_week = monday - _D(days=7) + _D(days=wd)
        readings = [recent] if recent == prev_week else [prev_week, recent]
    elif q in ("this",):
        readings = (
            [monday + _D(days=wd)]
            if wd >= t.weekday()
            else [_next_weekday(t, wd, include_today=True)]
        )
    elif q in ("coming", "the coming", "this coming"):
        readings = [_next_weekday(t, wd, include_today=False)]
    else:  # bare or "on Friday": the coming one, or the last one when the clause is past
        if _past_tense(c.text, m.start()):
            readings = [t - _D(days=((t.weekday() - wd) % 7) or 7)]
        else:
            readings = [_next_weekday(t, wd, include_today=True)]
        a.conf = min(a.conf, 0.8)
    a.lo = _midnight(readings[0])
    a.hi = a.lo + DAY
    a.value = _day_value(a.lo)
    if len(readings) > 1:
        a.alts = [(_midnight(r), _midnight(r) + DAY) for r in readings]
        a.conf = 0.6
    return a


def _atom_offset(m: re.Match, c: _Ctx) -> _Atom | None:
    n, unit = _num(m["n"]), m["unit"].casefold().rstrip("s")
    unit = {
        "min": "minute",
        "minute": "minute",
        "hour": "hour",
        "hr": "hour",
        "day": "day",
        "night": "day",
        "week": "week",
        "wk": "week",
        "fortnight": "fortnight",
        "month": "month",
        "mth": "month",
        "year": "year",
        "yr": "year",
    }.get(unit, unit)
    if re.match(r"(?:business|working|work|bank|clear)[\s-]*day|workday", unit):
        unit = "business_day"
    d = (m["dir"] or "").casefold()
    lead = (m["in"] or "").casefold()
    if not d and not lead:
        return None  # a bare quantity ("3 days") is a duration, read elsewhere
    sign = -1 if d.startswith(("ago", "before", "earlier")) else 1
    base_days = 0
    rel = "anchor"
    if d.startswith("from tomorrow"):
        base_days = 1
    elif d.startswith("from yesterday"):
        base_days = -1
    elif d in ("later", "after", "before", "earlier") or d.startswith("from the"):
        rel = "previous"
    if m["event"]:
        rel = "event:" + re.sub(r"\s+", " ", m["event"].casefold())
    wd = m["wd"]
    a = _Atom(m.start(), m.end(), "day", cue=(lead + " " if lead else "") + (d or ""), rel=rel)
    if lead == "within":
        a.mod = "ON_OR_BEFORE"
    days = {"day": 1, "week": 7, "fortnight": 14}.get(unit)
    a.offset = {unit + "s": sign * n} if unit != "fortnight" else {"days": sign * 14 * n}
    if m["n2"]:
        a.offset_to = sign * int(m["n2"]) * (14 if unit == "fortnight" else 1)  # type: ignore[attr-defined]
        if a.offset_to * sign < n:  # type: ignore[attr-defined]
            return None
    if unit in ("hour", "minute"):
        a.grain = "minute"
    if c.anchor is None:
        return a
    if rel != "anchor":
        return a  # counted from another date in the text, or from an event with no date
    base = c.anchor
    if wd:
        base = _midnight(
            _next_weekday(c.today, _WD_FORMS[wd.casefold().rstrip(".")], include_today=False)
        )
    base = base + _D(days=base_days)
    _shift(a, base, unit, sign * n, days, c)
    _range_to(a, base, unit, days, c)
    return a


def _range_to(a: _Atom, base: _dt.datetime, unit: str, days: int | None, c: _Ctx) -> None:
    """ "3-5 business days": from the first count to the end of the last."""
    to = getattr(a, "offset_to", None)
    if to is None or a.lo is None:
        return
    lo, value = a.lo, a.value
    if a.offset:
        a.offset = {**a.offset, next(iter(a.offset)) + "_to": to}
    _shift(a, base, unit, to, days, c)
    a.lo, a.value = lo, f"{value}/{a.value}"
    a.is_range = True  # type: ignore[attr-defined]


def _business_days(d: _dt.date, n: int, c: _Ctx | None) -> _dt.date:
    """``n`` working days after ``d`` (before, when negative), skipping the weekend and holidays."""
    weekend = c.weekend if c else (5, 6)
    holidays = c.holidays if c else frozenset()
    step, left = (1 if n >= 0 else -1), abs(n)
    while left:
        d += _D(days=step)
        if d.weekday() not in weekend and d not in holidays:
            left -= 1
    return d


def _shift(
    a: _Atom, base: _dt.datetime, unit: str, n: int, days: int | None, c: _Ctx | None = None
) -> None:
    if unit in ("business_day", "business_days"):
        a.lo = _midnight(_business_days(base.date(), n, c))
        a.hi = a.lo + DAY
        a.value = _day_value(a.lo)
        return
    if unit in ("hour", "minute"):
        t = base + (_D(hours=n) if unit == "hour" else _D(minutes=n))
        t = t.replace(second=0, microsecond=0)
        a.lo, a.hi, a.grain = t, t + MIN, "minute"
        a.value = t.strftime("%Y-%m-%dT%H:%M")
        return
    if unit in ("month", "year"):
        dd = _add_months(base.date(), n if unit == "month" else 12 * n)
    else:
        dd = base.date() + _D(days=n * (days or 1))
    a.lo = _midnight(dd)
    a.hi = a.lo + DAY
    a.value = _day_value(a.lo)


def _atom_sw_offset(m: re.Match, c: _Ctx) -> _Atom | None:
    word = m["n"].casefold()
    if word not in _SW_NUMS and not word.isdigit():
        return None
    if not (m["pre"] or m["post"]):
        return None
    n = int(word) if word.isdigit() else _SW_NUMS[word]
    unit = {
        "siku": "day",
        "wiki": "week",
        "mwezi": "month",
        "miezi": "month",
        "mwaka": "year",
        "miaka": "year",
        "saa": "hour",
    }[m["unit"].casefold()]
    sign = -1 if (m["post"] or "").casefold() in ("zilizopita", "iliyopita") else 1
    a = _Atom(
        m.start(),
        m.end(),
        "day",
        cue=m.group(0).casefold(),
        rel="anchor",
        lang="sw",
        offset={unit + "s": sign * n},
    )
    if c.anchor:
        _shift(a, c.anchor, unit, sign * n, {"day": 1, "week": 7}.get(unit))
    return a


def _atom_chain(m: re.Match, c: _Ctx) -> _Atom:
    w = m["w"].casefold()
    if m["d"]:
        off = {"days": -1 if m["d"].casefold() == "before" else 1}
    else:
        q, u = w.split()[0], m["u"].casefold()
        step = {"next": 1, "following": 1, "previous": -1, "same": 0}[q]
        off = (
            {"weeks": step} if u == "week" else {"months": step} if u == "month" else {"days": step}
        )
    a = _Atom(m.start(), m.end(), "day", cue=w, rel="previous", offset=off)
    if m["u"] and m["u"].casefold() in ("morning", "evening", "night"):
        a.part = _PARTS[m["u"].casefold()]
    return a


def _atom_period(m: re.Match, c: _Ctx) -> _Atom | None:
    a = _Atom(m.start(), m.end(), "period", cue=m.group(0).casefold())
    t = c.today
    edge = (m["edge"] or m["edge2"] or "").casefold().replace("the ", "")
    if m["qn"]:
        qn = int(m["qn"][1])
        y = int(m["qy"]) if m["qy"] else (t.year if t else None)
        a.grain, a.value = "quarter", (f"{y}-Q{qn}" if y else f"XXXX-Q{qn}")
        if y:
            a.lo, a.hi = (
                _dt.datetime(y, 3 * qn - 2, 1),
                _midnight(_add_months(_dt.date(y, 3 * qn - 2, 1), 3)),
            )
        return a
    if m["sw"]:
        p = {"wiki": "week", "mwezi": "month", "mwaka": "year"}[m["sw"].casefold()]
        q = {
            "ijayo": "next",
            "ujao": "next",
            "iliyopita": "last",
            "uliopita": "last",
            "huu": "this",
            "hii": "this",
        }[m["swq"].casefold()]
        a.lang = "sw"
    elif m["we"]:
        p, q = "weekend", "this"
    elif m["p2"]:
        p, q = m["p2"].casefold(), "this"
    else:
        p = m["p"].casefold()
        q = {
            "current": "this",
            "coming": "next",
            "the coming": "next",
            "the following": "next",
        }.get(m["q"].casefold(), m["q"].casefold())
    if not t:
        a.value = {
            "week": "XXXX-WXX",
            "weekend": "XXXX-WXX-WE",
            "month": "XXXX-XX",
            "year": "XXXX",
            "quarter": "XXXX-QX",
            "day": "XXXX-XX-XX",
        }[p]
        return a
    step = {"this": 0, "next": 1, "last": -1}[q]
    if p in ("week", "weekend"):
        monday = t - _D(days=t.weekday()) + _D(days=7 * step)
        lo, hi = _midnight(monday), _midnight(monday + _D(days=7))
        iso = monday.isocalendar()
        a.value = f"{iso[0]}-W{iso[1]:02d}"
        if p == "weekend":
            lo, hi = _midnight(monday + _D(days=5)), _midnight(monday + _D(days=7))
            a.value += "-WE"
        a.grain = "week"
    elif p == "month":
        first = _add_months(t.replace(day=1), step)
        lo, hi = _month_span(first.year, first.month)
        a.value, a.grain = first.strftime("%Y-%m"), "month"
    elif p == "year":
        lo, hi = _dt.datetime(t.year + step, 1, 1), _dt.datetime(t.year + step + 1, 1, 1)
        a.value, a.grain = str(t.year + step), "year"
    elif p == "quarter":
        qn = (t.month - 1) // 3 + 1 + step
        y = t.year + (qn - 1) // 4
        qn = (qn - 1) % 4 + 1
        lo, hi = (
            _dt.datetime(y, 3 * qn - 2, 1),
            _midnight(_add_months(_dt.date(y, 3 * qn - 2, 1), 3)),
        )
        a.value, a.grain = f"{y}-Q{qn}", "quarter"
    else:  # end of the day
        lo, hi = _midnight(t), _midnight(t) + DAY
        a.value = _day_value(lo)
    a.lo, a.hi = lo, hi
    if edge in ("end",):
        a.mod = "END"
    elif edge in ("start", "beginning", "early"):
        a.mod = "START"
    elif edge in ("middle", "mid"):
        a.mod = "MID"
    elif edge == "late":
        a.mod = "END"
    return a


def _atom_abs(kind: str, m: re.Match, c: _Ctx) -> _Atom | None:
    g = m.groupdict()
    t = c.today
    a = _Atom(m.start(), m.end(), "day", cue=kind, conf=0.9)
    if kind in ("iso",):
        y, mo, d = int(g["y"]), int(g["m"]), int(g["d"])
        return _fix(a, y, mo, d)
    if kind == "num":
        x, b, yr = int(g["a"]), int(g["b"]), g["y"]
        y = int(yr) if len(yr) == 4 else 2000 + int(yr) if int(yr) < 70 else 1900 + int(yr)
        dmy, mdy = _valid(y, b, x), _valid(y, x, b)
        order = (
            [("mdy", x, b), ("dmy", b, x)]
            if c.mdy and g["s"] != "."
            else [("dmy", b, x), ("mdy", x, b)]
        )
        ok = [(y, mo, d) for _, mo, d in order if _valid(y, mo, d)]
        if not ok:
            return None
        _fix(a, *ok[0])
        if dmy and mdy and x != b:
            a.alts = [(_dt.datetime(*r), _dt.datetime(*r) + DAY) for r in ok]
            a.conf = 0.6
        return a
    if (
        kind == "short"
    ):  # 3/12, no year: day/month by jurisdiction, always two readings when both are real
        x, b = int(g["a"]), int(g["b"])
        before = c.text[max(0, m.start() - 12) : m.start()].casefold()
        if not re.search(r"\b(?:on|by|from|until|till|due|date|dated|before|after)\s*$", before):
            return None
        y = t.year if t else 2000
        order = [(x, b), (b, x)] if c.mdy else [(b, x), (x, b)]
        ok = [(mo, d) for mo, d in order if _valid(y, mo, d)]
        if not ok:
            return None
        if not t:
            a.value = f"XXXX-{ok[0][0]:02d}-{ok[0][1]:02d}"
            a.ambiguous_note = True  # type: ignore[attr-defined]
            return a
        readings = [_future(c, m.start(), mo, d) for mo, d in ok]
        _fix(a, *readings[0])
        if len(ok) == 2 and ok[0] != ok[1]:
            a.alts = [(_dt.datetime(*r), _dt.datetime(*r) + DAY) for r in readings]
            a.conf = 0.6
        return a
    mon = (g.get("mon") or "").casefold().rstrip(".")
    if kind in ("dmy", "mdy"):
        mo, d = _MONTHS[mon], int(g["d"])
        if g.get("y"):
            return _fix(a, int(g["y"]), mo, d)
        if not t:
            a.value = f"XXXX-{mo:02d}-{d:02d}"
            return a if _valid(2000, mo, d) else None
        return _fix(a, *_future(c, m.start(), mo, d))
    if kind == "my":
        mo = _MONTHS[mon]
        pre = (g.get("pre") or "").casefold()
        if mon in _MONTH_WORDS and not g.get("y") and not pre:
            return None
        if mon in _MONTH_WORDS and m.group(0)[m.start("mon") - m.start()].islower():
            return None
        a.grain, a.kind = "month", "period"
        if g.get("y"):
            y = int(g["y"])
        elif t:
            if pre == "next":
                y = t.year + (1 if mo <= t.month else 0)
            elif pre == "last":
                y = t.year - (1 if mo >= t.month else 0)
            else:
                y = t.year if (mo >= t.month or _past_tense(c.text, m.start())) else t.year + 1
        else:
            a.value = f"XXXX-{mo:02d}"
            return a
        a.lo, a.hi = _month_span(y, mo)
        a.value = f"{y}-{mo:02d}"
        if pre in ("early",):
            a.mod = "START"
        elif pre in ("late", "end of"):
            a.mod = "END"
        elif pre == "mid":
            a.mod = "MID"
        a.start = (
            m.start("mon") if pre in ("in", "by", "since", "until", "till", "from") else m.start()
        )
        return a
    if kind == "ord":
        d = int(g["d"])
        if not 1 <= d <= 31:
            return None
        before = c.text[max(0, m.start() - 14) : m.start()].casefold()
        if not re.search(
            r"\b(?:on|by|from|until|till|to|before|after|the|due|of)\s*$", before
        ) and not m.group(0).casefold().startswith("the"):
            return None
        if not t:
            a.value = f"XXXX-XX-{d:02d}"
            return a
        past = _past_tense(c.text, m.start())
        cand = t.replace(day=1)
        for k in (0, -1, -2) if past else (0, 1, 2):
            mm = _add_months(cand, k)
            if d <= calendar.monthrange(mm.year, mm.month)[1] and (
                (mm.replace(day=d) >= t) != past or mm.replace(day=d) == t
            ):
                return _fix(a, mm.year, mm.month, d)
        return None
    return None


def _valid(y: int, mo: int, d: int) -> bool:
    return 1 <= mo <= 12 and 1 <= d <= calendar.monthrange(y, mo)[1]


def _future(c: _Ctx, at: int, mo: int, d: int) -> tuple[int, int, int]:
    """A day and month with no year: this year's, or the next one when it has passed (the last
    one, when the clause is in the past)."""
    t = c.today
    y = t.year
    if mo == 2 and d == 29:
        while not calendar.isleap(y):
            y += 1
    target = _dt.date(y, mo, d)
    if _past_tense(c.text, at):
        if target > t:
            y -= 1
    elif target < t:
        y += 1
    if not _valid(y, mo, d):
        y += 1 if not _past_tense(c.text, at) else -1
    return y, mo, d


def _fix(a: _Atom, y: int, mo: int, d: int) -> _Atom | None:
    if not _valid(y, mo, d):
        return None
    a.lo = _dt.datetime(y, mo, d)
    a.hi = a.lo + DAY
    a.value = _day_value(a.lo)
    return a


def _atom_clock(m: re.Match, c: _Ctx) -> _Atom | None:
    a = _Atom(m.start(), m.end(), "clock", grain="minute", cue=m.group(0).casefold())
    if m["h"] is not None:
        h, mi = int(m["h"]), int(m["mi"] or 0)
        if not 1 <= h <= 12 or mi > 59:
            return None
        pm = m["ap"].casefold().startswith("p")
        a.hour, a.minute = (h % 12) + (12 if pm else 0), mi
    elif m["h24"] is not None:
        a.hour, a.minute = int(m["h24"]), int(m["m24"])
        if (
            0 < a.hour < 12
            and not m.group(0).casefold().rstrip().endswith(("h", "hrs", "hr"))
            and not m["h24"].startswith("0")
        ):
            a.open_ampm = True
    elif m["hhmm"] is not None:
        a.hour, a.minute = int(m["hhmm"]), int(m["mm"])
    elif m["half"] is not None:
        hw = m["hw"].casefold()
        h = int(hw) if hw.isdigit() else _NUM_WORDS[hw]
        if not 1 <= h <= 12:
            return None
        ph = m["half"].casefold()
        if ph.startswith("half"):
            a.hour, a.minute = h, 30
        elif ph.startswith("quarter past"):
            a.hour, a.minute = h, 15
        elif ph.startswith("quarter to"):
            a.hour, a.minute = (h - 1) or 12, 45
        else:
            mins = m["mins"].casefold().replace("-", " ")
            n = (
                int(mins)
                if mins.isdigit()
                else {"five": 5, "ten": 10, "twenty": 20, "twenty five": 25}[mins]
            )
            if m["pt"].casefold() == "past":
                a.hour, a.minute = h, n
            else:
                a.hour, a.minute = (h - 1) or 12, 60 - n
        a.open_ampm = True
    elif m["oc"] is not None:
        w = m["oc"].casefold()
        h = int(w) if w.isdigit() else _NUM_WORDS[w]
        if not 1 <= h <= 12:
            return None
        a.hour, a.open_ampm = h, True
    else:
        n = m["named"].casefold()
        a.hour = 0 if n == "midnight" else 12
    return a


def _atom_bare(m: re.Match, c: _Ctx) -> _Atom | None:
    h, mi = int(m["h"]), int(m["mi"] or 0)
    if h > 23 or re.search(r"\d\s*$", c.text[: m.start()]):
        return None
    after = c.text[m.end() : m.end() + 14]
    if _NOT_TIME_AFTER.match(after) and not re.match(
        r"(?i)\s*(?:am|pm|a\.m|p\.m|o'?clock|hrs?)\b", after
    ):
        return None
    if m["cue"].casefold() in ("and", "to") and not re.search(
        r"(?i)\b(?:between|from)\b[^.;]{0,25}$", c.text[: m.start()]
    ):
        return None
    a = _Atom(m.start("h"), m.end(), "clock", grain="minute", cue=m["cue"].casefold(), conf=0.7)
    a.hour, a.minute = h, mi
    a.open_ampm = 1 <= h <= 12 and not (m["mi"] and h == 0)
    return a


def _atom_part(m: re.Match, c: _Ctx) -> _Atom:
    p = m["p"].casefold()
    q = (m["q"] or "").casefold()
    a = _Atom(
        m.start(),
        m.end(),
        "part",
        grain="minute",
        part=_PARTS[p],
        cue=m.group(0).casefold(),
        lang="sw" if p in ("asubuhi", "mchana", "jioni", "usiku") else "en",
    )
    if q in ("tomorrow", "yesterday"):
        a.offset = {"days": 1 if q == "tomorrow" else -1}
    if q in ("by",):
        a.mod = "ON_OR_BEFORE"
    if q.startswith("on "):
        return _Atom(m.start("p"), m.end(), "part", grain="minute", part=_PARTS[p], cue=p)
    return a


def _atom_sw_clock(m: re.Match, c: _Ctx) -> _Atom | None:
    w = re.sub(r"\s+", " ", m["h"].casefold())
    h = int(w) if w.isdigit() else _SW_HOURS.get(w)
    if not h or not 1 <= h <= 12:
        return None
    h12 = (h + 6 - 1) % 12 + 1  # saa moja -> 7, saa sita -> 12, saa saba -> 1
    frac = (m["frac"] or "").casefold()
    mi = 30 if "nusu" in frac else 15 if frac == "na robo" else 0
    if "kasoro" in frac:
        h12, mi = (h12 - 1) or 12, 45
    part = (m["p"] or "").casefold()
    a = _Atom(m.start(), m.end(), "clock", grain="minute", cue=m.group(0).casefold(), lang="sw")
    if part in ("asubuhi", "alfajiri"):
        a.hour = h12 % 12 if h12 != 12 or part == "alfajiri" else 12
        if part == "asubuhi" and h12 == 12:
            a.hour = 12
    elif part in ("mchana", "jioni"):
        a.hour = h12 % 12 + 12 if h12 != 12 else 12
    elif part == "usiku":
        a.hour = h12 % 12 + 12 if h12 >= 7 and h12 != 12 else h12 % 12
    else:
        a.hour, a.open_ampm = h12, True
    a.minute = mi
    return a


def _atom_duration(m: re.Match, c: _Ctx) -> _Atom | None:
    n = _num(m["n"] or m["n2"])
    u = (m["unit"] or m["unit2"]).casefold().rstrip("s")
    if re.match(r"(?:business|working|work|bank|clear)[\s-]*day|workday", u):
        u = "business day"
    code = {
        "business day": "BD",  # not TIMEX3: it has no working day; P5BD is five working days
        "min": "TM",
        "minute": "TM",
        "mins": "TM",
        "hour": "TH",
        "hr": "TH",
        "day": "D",
        "night": "D",
        "week": "W",
        "wk": "W",
        "fortnight": "W",
        "month": "M",
        "mth": "M",
        "year": "Y",
        "yr": "Y",
    }[u]
    if u == "fortnight":
        n *= 2
    start = m.start("n") if m["n"] else m.start()
    v = ("PT" + str(n) + code[1]) if code.startswith("T") else ("P" + str(n) + code)
    return _Atom(
        start,
        m.end(),
        "duration",
        value=v if code != "BD" else f"P{n}BD",
        cue=(m["cue"] or "long").casefold(),
        conf=0.85,
    )


def _atom_set(m: re.Match, c: _Ctx) -> _Atom:
    g = {k: (v or "").casefold() for k, v in m.groupdict().items()}
    if g["wd"]:
        v = f"XXXX-WXX-{_WD_FORMS[g['wd'].rstrip('.')] + 1}"
    elif g["u"]:
        v = {
            "day": "P1D",
            "morning": "TMO",
            "evening": "TEV",
            "night": "TNI",
            "week": "P1W",
            "month": "P1M",
            "year": "P1Y",
            "weekday": "XXXX-WXX-WD",
            "weekend": "XXXX-WXX-WE",
        }[g["u"]]
    elif g["adv"]:
        v = {
            "daily": "P1D",
            "nightly": "P1D",
            "weekly": "P1W",
            "fortnightly": "P2W",
            "monthly": "P1M",
            "yearly": "P1Y",
            "annually": "P1Y",
        }[g["adv"]]
    else:
        v = {"day": "P1D", "week": "P1W", "month": "P1M", "year": "P1Y"}[g["ku"]]
    return _Atom(m.start(), m.end(), "set", value=v, cue=m.group(0).casefold(), conf=0.85)


# ── joining ──────────────────────────────────────────────────────────────────

_JOIN_DT = re.compile(
    r"(?i)^\s*(?:,\s*)?(?:at|by|around|about|from|on|@|-|,|before|after|in\s+the|this|from\s+about)?\s*(?:,\s*)?$"
)
_JOIN_RANGE = re.compile(r"(?i)^\s*(?:to|till|til|until|-|–|—|through|thru|and)\s*$")


def _place_time(a: _Atom, day: _dt.date | None, c: _Ctx) -> None:
    """Give a clock or part of day its date and interval."""
    if a.kind == "clock":
        if day is None:
            a.value = f"T{a.hour:02d}:{a.minute:02d}"
            return
        base = _midnight(day)
        readings = [base + _D(hours=a.hour, minutes=a.minute)]
        if a.open_ampm and a.hour < 12:
            readings.append(base + _D(hours=a.hour + 12, minutes=a.minute))
        lo = readings[0]
        a.lo, a.hi = lo, lo + MIN
        a.value = lo.strftime("%Y-%m-%dT%H:%M")
        if len(readings) > 1:
            a.alts = [(r, r + MIN) for r in readings]
    elif a.kind == "part":
        s, e = a.part or (0, 24)
        if day is None:
            a.value = {(6, 12): "TMO", (12, 17): "TAF", (17, 21): "TEV", (21, 30): "TNI"}.get(
                (s, e), "T12:00"
            )
            return
        a.lo = _midnight(day) + _D(hours=s)
        a.hi = _midnight(day) + _D(hours=e)
        a.value = day.isoformat() + {
            (6, 12): "TMO",
            (12, 17): "TAF",
            (17, 21): "TEV",
            (21, 30): "TNI",
        }.get((s, e), "")


def _resolve_part(clock: _Atom, part: tuple[int, int] | None) -> None:
    """An open am/pm settles by the part of day: "this evening around 7" is 19:00."""
    if part is None or not clock.open_ampm or clock.hour is None:
        return
    s, e = part
    for h in (clock.hour, clock.hour + 12):
        if s <= h < e or s <= h + 24 < e:
            clock.hour, clock.open_ampm = h % 24, False
            return


def _mentions(text: str, c: _Ctx) -> list[_Atom]:
    atoms: list[_Atom] = []

    def take(rx: re.Pattern, fn) -> None:
        for m in rx.finditer(text):
            a = fn(m)
            if a is not None:
                atoms.append(a)

    take(_RE_SET, lambda m: _atom_set(m, c))
    take(_RE_DURATION, lambda m: _atom_duration(m, c))
    take(_RE_PERIOD, lambda m: _atom_period(m, c))
    take(_RE_OFFSET, lambda m: _atom_offset(m, c))
    take(_RE_SW_OFFSET, lambda m: _atom_sw_offset(m, c))
    take(_RE_WEEK_ON, lambda m: _week_on(m, c))
    take(_RE_CHAIN, lambda m: _atom_chain(m, c))
    for kind, rx in _RE_ABS:
        take(rx, lambda m, k=kind: _atom_abs(k, m, c))
    take(
        _RE_WEEKDAY,
        lambda m: _atom_weekday(
            m,
            c,
            _WD_FORMS[m["wd"].casefold().rstrip(".")],
            re.sub(r"\s+", " ", (m["q"] or "").casefold()),
            (m["wk"] or m["wk2"] or "").casefold() or None,
        ),
    )
    take(_RE_SW_WEEKDAY, lambda m: _sw_weekday(m, c))
    take(_RE_SW_CLOCK, lambda m: _atom_sw_clock(m, c))
    take(_RE_CLOCK, lambda m: _atom_clock(m, c))
    for m in _RE_HHRANGE.finditer(text):
        atoms.extend(_atoms_hhrange(m, c))
    take(_RE_BARE, lambda m: _atom_bare(m, c))
    take(_RE_PART, lambda m: _atom_part(m, c))
    take(_RE_DAYWORD, lambda m: _atom_dayword(m, c))
    if c.language in _DAY_WORDS_PLAIN:
        rx = re.compile(
            r"(?i)(?<![\w])(?P<w>" + "|".join(_DAY_WORDS_PLAIN[c.language]) + r")(?![\w])"
        )
        take(rx, lambda m: _atom_dayword(m, c))
    # longest first, earliest first; drop anything inside a kept atom
    atoms.sort(key=lambda a: (-(a.end - a.start), a.start))
    kept: list[_Atom] = []
    for a in atoms:
        if a.conf < 0.55 and a.kind == "day" and not a.cue:
            continue
        if any(a.start < k.end and k.start < a.end for k in kept):
            continue
        kept.append(a)
    kept.sort(key=lambda a: a.start)
    return kept


def _week_on(m: re.Match, c: _Ctx) -> _Atom:
    wd = _WD_FORMS[m["wd"].casefold().rstrip(".")]
    a = _Atom(
        m.start(), m.end(), "day", cue="a week " + m["wd"].casefold(), value=f"XXXX-WXX-{wd + 1}"
    )
    if c.today:
        a.lo = _midnight(_next_weekday(c.today, wd, include_today=False) + _D(days=7))
        a.hi, a.value = a.lo + DAY, _day_value(a.lo)
    return a


def _sw_weekday(m: re.Match, c: _Ctx) -> _Atom:
    wd = _SW_WEEKDAYS[m["wd"].casefold()]
    q = {"ijayo": "next", "iliyopita": "last", "hii": "this", "": ""}[(m["q"] or "").casefold()]
    fake = re.match(r"(?P<wd>\w+)", m["wd"])
    a = _atom_weekday(m, c, wd, q, None, lang="sw")
    del fake
    return a


def _finish(text: str, atoms: list[_Atom], c: _Ctx) -> list[TimeMention]:
    # 1. day + clock/part (either order), part + clock
    merged: list[list[_Atom]] = []
    for a in atoms:
        if merged:
            prev = merged[-1]
            gap = text[prev[-1].end : a.start]
            kinds = {x.kind for x in prev}
            fits = (
                a.kind in ("clock", "part")
                and kinds & {"day", "clock", "part"}
                and not (kinds & {"clock"} and a.kind == "clock")
            ) or (a.kind == "day" and kinds <= {"clock", "part"})
            if getattr(a, "pair", False) or getattr(prev[-1], "pair", False):
                fits = False
            if fits and _JOIN_DT.match(gap) and len(gap) <= 12:
                prev.append(a)
                continue
        merged.append([a])
    out: list[_Atom] = []
    last_day: _dt.datetime | None = None
    following: dict[int, _dt.datetime] = {}
    for k, group in enumerate(merged):
        x = group[0]
        if (
            x.rel == "previous"
            and re.search(r"(?:before|after)$", x.cue or "")
            or (x.rel or "").startswith("event:")
        ) and k + 1 < len(merged):
            nxt = merged[k + 1][0]
            between = text[x.end : nxt.start]
            if (
                nxt.lo is not None
                and nxt.rel is None
                and len(between) <= 40
                and not re.search(r"[.;!?\n]", between)
            ):
                following[k] = _midnight(nxt.lo.date())
    for k, group in enumerate(merged):
        day = next((x for x in group if x.kind == "day"), None)
        clock = next((x for x in group if x.kind == "clock"), None)
        part = next((x for x in group if x.kind == "part"), None)
        lead = group[0]
        # chained: resolve against the previous date in the text
        for x in group:
            if (x.rel or "").startswith("event:") and x.offset is not None and k in following:
                x.rel = (
                    "previous"  # "30 days after invoice dated 3 November": the date that follows
                )
            if x.rel == "previous" and x.offset is not None:
                base = following.get(k) or last_day or (_midnight(c.today) if c.today else None)
                if base is not None:
                    unit, n = next(iter(x.offset.items()))
                    _shift(
                        x, base, unit.rstrip("s"), n, {"day": 1, "week": 7}.get(unit.rstrip("s")), c
                    )
                    _range_to(
                        x, base, unit.rstrip("s"), {"day": 1, "week": 7}.get(unit.rstrip("s")), c
                    )
                    x.lo = (
                        x.lo.replace(hour=0, minute=0) if unit not in ("hours", "minutes") else x.lo
                    )
                    if unit not in ("hours", "minutes") and not getattr(x, "is_range", False):
                        x.hi = x.lo + DAY
                        x.value = _day_value(x.lo)
                x.rel = (
                    "following"
                    if k in following
                    else "previous"
                    if last_day is not None
                    else "anchor"
                )
        if part is not None and part.offset and c.today:
            when = _midnight(c.today + _D(days=part.offset["days"]))
            if day is None:
                day = _Atom(part.start, part.start, "day", lo=when, hi=when + DAY)
        if day is not None and day.part and part is None:
            part = _Atom(day.start, day.start, "part", part=day.part)
        on_date = (
            day.lo.date()
            if day is not None and day.lo is not None
            else (c.today if c.today else None)
        )
        if clock is not None:
            _resolve_part(clock, part.part if part else None)
            _place_time(clock, on_date, c)
            result = clock
            if day is not None:
                result.offset, result.rel = day.offset, day.rel
                if day.alts and clock.lo is not None:
                    result.alts = [
                        (
                            lo + _D(hours=clock.hour, minutes=clock.minute),
                            lo + _D(hours=clock.hour, minutes=clock.minute) + MIN,
                        )
                        for lo, _ in day.alts
                    ]
        elif part is not None and (day is not None or c.today):
            _place_time(part, on_date, c)
            result = part
            if day is not None:
                result.offset, result.rel = day.offset, day.rel
        elif part is not None:
            _place_time(part, None, c)
            result = part
        else:
            result = group[0]
        gaps = [text[x.end : y.start] for x, y in zip(group, group[1:], strict=False)]
        result.start, result.end = group[0].start, group[-1].end
        result.cue = " ".join(x.cue for x in group if x.cue) or result.cue
        result.mod = next((x.mod for x in group if x.mod), None)
        for gap in gaps:
            inner = re.search(r"(?i)\b(by|before|after|around|about|until|till|from)\s*$", gap)
            if inner and result.mod is None:
                result.mod = _MOD.get(inner[1].casefold())
        result.lang = next((x.lang for x in group if x.lang != "en"), "en")
        result.conf = min(x.conf for x in group)
        result.kind_out = (
            "datetime"
            if clock is not None and (day is not None or part is not None and part.offset)
            else "time"
            if clock is not None or part is not None
            else "duration"
            if lead.kind == "duration"
            else "set"
            if lead.kind == "set"
            else "date"
        )
        if any(getattr(x, "is_range", False) for x in group):
            result.kind_out = "range"
        if result.lo is not None and result.kind_out == "date":
            last_day = result.lo
        elif result.lo is not None:
            last_day = _midnight(result.lo.date())
        out.append(result)
    # 2. ranges: X to Y of one kind
    joined: list[_Atom] = []
    for a in out:
        if joined:
            p = joined[-1]
            gap = text[p.end : a.start]
            if (
                _JOIN_RANGE.match(gap)
                and p.kind_out == a.kind_out
                and p.kind_out in ("date", "time", "datetime")
                and not (
                    gap.strip().casefold() == "and"
                    and not re.search(r"(?i)\bbetween\s*$", text[: p.start])
                )
            ):
                if (
                    p.kind == "clock"
                    and a.kind == "clock"
                    and p.open_ampm
                    and not a.open_ampm
                    and a.hour is not None
                ):
                    # "between 2 and 4pm": the first takes the second's half of the day
                    if (
                        a.hour >= 12
                        and p.hour is not None
                        and p.hour < 12
                        and p.hour + 12 <= a.hour
                    ):
                        p.hour += 12
                        p.open_ampm = False
                        if p.lo is not None:
                            p.lo += _D(hours=12)
                            p.hi = p.lo + MIN
                            p.value = p.lo.strftime("%Y-%m-%dT%H:%M")
                            p.alts = []
                elif (
                    p.kind == "clock"
                    and a.kind == "clock"
                    and p.open_ampm
                    and a.open_ampm
                    and p.hour
                    and a.hour
                    and a.hour < p.hour
                ):
                    # "8-5": a working day, 08:00 to 17:00
                    a.hour += 12
                    a.open_ampm = p.open_ampm = False
                    if a.lo is not None:
                        a.lo += _D(hours=12)
                        a.hi = a.lo + MIN
                        a.value = a.lo.strftime("%Y-%m-%dT%H:%M")
                    p.alts, a.alts = [], []
                if (
                    p.kind == "day"
                    and a.kind == "day"
                    and p.lo is not None
                    and a.lo is not None
                    and a.lo < p.lo
                    and re.match(r"(?:\w+\s)?(?:" + "|".join(_WD_FORMS) + r")", a.cue or "")
                ):
                    a.lo, a.hi = (
                        a.lo + _D(days=7),
                        a.hi + _D(days=7),
                    )  # "Friday to Monday" runs forward
                    a.value = _day_value(a.lo)
                # a span of clock times ends at the second time; of days, after the last day
                rng = _Atom(
                    p.start,
                    a.end,
                    p.kind,
                    lo=p.lo,
                    hi=a.lo if a.kind == "clock" else a.hi,
                    cue="range",
                )
                rng.kind_out = "range"
                rng.value = f"{p.value}/{a.value}" if p.value and a.value else None
                rng.alts = []
                rng.conf = min(p.conf, a.conf)
                rng.lang = p.lang if p.lang != "en" else a.lang
                lead_gap = text[max(0, p.start - 9) : p.start].casefold()
                rng.start = (
                    p.start - (len(lead_gap) - lead_gap.rfind("between"))
                    if "between" in lead_gap
                    else p.start
                )
                rng.start = (
                    p.start - (len(lead_gap) - lead_gap.rfind("from"))
                    if "from" in lead_gap
                    else rng.start
                )
                joined[-1] = rng
                continue
        joined.append(a)
    # 3. a cue before it: by, before, after, from, around
    final: list[TimeMention] = []
    for a in joined:
        m = _CUE_BEFORE.search(text[max(0, a.start - 22) : a.start])
        mod = a.mod
        if m and a.kind_out != "range" and a.kind_out not in ("duration", "set"):
            cue = re.sub(r"\s+", " ", m["c"].casefold()).rstrip(".")
            mod = mod or _MOD.get(cue)
            if a.cue == cue:
                a.conf = max(a.conf, 0.7)
        if a.kind == "clock" and a.cue in ("between", "from") and a.kind_out != "range":
            mod = None
        alts = tuple(
            (
                _iso(lo, "minute" if a.kind_out in ("time", "datetime") else "day"),
                _iso(hi, "minute" if a.kind_out in ("time", "datetime") else "day"),
            )
            for lo, hi in a.alts
        )
        grain = (
            "minute"
            if a.kind_out in ("time", "datetime")
            or (a.kind_out == "range" and a.kind in ("clock", "part"))
            else "day"
        )
        if a.grain == "minute" and a.kind_out == "date":
            grain = "minute"
        final.append(
            TimeMention(
                text=text[a.start : a.end],
                span=(a.start, a.end),
                type=a.kind_out,
                value=a.value,
                start=_iso(a.lo, grain) if a.lo else None,
                end=_iso(a.hi, grain) if a.hi else None,
                mod=mod,
                ambiguous=len(alts) > 1,
                alternatives=alts if len(alts) > 1 else (),
                offset=a.offset,
                relative_to=a.rel,
                cue=a.cue,
                confidence=round(a.conf, 2),
                language=a.lang,
            )
        )
    return final


def extract_times(
    text: str,
    *,
    anchor: _dt.datetime | _dt.date | str | None = None,
    jurisdiction: str | None = None,
    language: str | None = None,
    weekend: tuple[int, ...] = (5, 6),
    holidays: Iterable[_dt.date | str] = (),
) -> list[TimeMention]:
    """Every time expression in ``text``, in order, resolved against ``anchor`` when given.

    ``anchor`` is when the text was written (a ``datetime``, ``date`` or ISO
    string). ``jurisdiction`` sets numeric date order: ``US`` reads 3/12 as
    March 12, everywhere else December 3, and both are returned when both are
    real days. ``language`` (``yo``, ``ha``) admits Yoruba and Hausa day words
    written without tone marks.

    Business and working days ("5 business days from today", "3-5 working
    days") skip ``weekend`` (weekday numbers, Monday 0; Saturday and Sunday by
    default) and the dates in ``holidays``. arche ships no holiday calendar:
    pass the one that applies, or the count is weekends only. A period counted
    from an event the text gives no date for ("30 days after invoice") keeps its
    offset and ``relative_to="event:invoice"``, and no date.

    Only the first 20,000 characters of ``text`` are read, so the time a call
    takes stays bounded. Split longer text and call once per part.
    """
    if isinstance(anchor, str):
        anchor = _dt.datetime.fromisoformat(anchor)
    elif isinstance(anchor, _dt.date) and not isinstance(anchor, _dt.datetime):
        anchor = _midnight(anchor)
    c = _Ctx(text[:20000], anchor, (jurisdiction or "").upper() == "US", language)
    c.weekend = tuple(weekend)
    c.holidays = frozenset(_dt.date.fromisoformat(h) if isinstance(h, str) else h for h in holidays)
    return _finish(c.text, _mentions(c.text, c), c)
