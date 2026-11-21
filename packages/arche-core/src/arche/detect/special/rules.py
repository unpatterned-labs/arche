# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Special-category content: health, religion, race/ethnicity, sexual
orientation, political affiliation and trade-union membership.

Every statute pack governs these (GDPR / UK GDPR Art 9, POPIA s.26, NDPA s.30,
Kenya DPA s.2/s.44, Ghana DPA s.37), and the rules-only path emitted none of
them, so a discharge note came back with its diagnoses in the clear under a
statute citation. They are also the categories where getting it wrong in
either direction costs most: miss one and the worst data in the document leaks;
over-match and every clinical or HR document is shredded ("positive feedback",
"union of sets", "Christian Street", "the party arrived"). So the rules here
are **precision first**, and each detection says which rule fired
(``metadata["cue"]`` and ``metadata["rule"]``):

1. **Cue-anchored values** (``rule="cue"``). After a label that says what
   follows, the value up to the end of the clause, bounded in length:

   * health: ``Dx``, ``diagnosis:``/``diagnosis of``, ``diagnosed with``,
     ``PMH``, ``Hx``, ``h/o``, ``medical/family history (of)``, ``medication(s):``,
     ``meds:``, ``Rx:``, ``allergies:``, ``HIV status``, ``medical/chronic/
     underlying condition(s):`` (a bare ``condition:`` is a pass/fail
     condition, not a diagnosis), and,
     only in a sentence that is clinical (a word like patient, admitted, ward,
     hospital, Dx), ``presents with``, ``admitted (date) with/for``, ``suffers
     from``, ``treated for``, ``tested positive for``, ``known case of``,
     ``prescribed``. A bare ``history of`` is not a cue ("his history of
     fraud"); only ``medical/family/psychiatric history`` is. A list (``type 2 diabetes and
     depression``) becomes one detection per item; ``none``/``nil`` are dropped.
   * religion: ``religion:``, ``religious affiliation/belief:``, ``faith:``,
     ``denomination:``.
   * race: ``race:``, ``racial group:``, ``population group:``, but only when
     the value starts with a race/ethnicity word (so ``Race: 5k fun run`` is
     not a race); ``ethnicity:``, ``ethnic origin/group:``, ``tribe:`` take
     any short value.
   * sexual orientation: ``sexual orientation``, ``sexuality:``.
   * political: ``political affiliation/party/opinion/views:``, ``party
     membership:``.
   * trade union: ``trade union (membership):``, ``union membership:``.

   The label is never part of the span: ``Religion: Methodist`` masks to
   ``Religion: [RELIGION]``.

2. **Patterns** (``rule="pattern"``): a person subject and a lexicon value
   (``she is a devout Muslim``, ``he came out as gay``, ``converted to Islam``),
   party membership (``member of the Labour Party``, ``ANC councillor``) and
   union membership (``member of the National Union of Mineworkers``,
   ``COSATU shop steward``). A union needs a worker word (Workers, Teachers,
   Nurses, Mineworkers...) or a known union acronym, so ``European Union`` and
   ``union of sets`` never match.

3. **Standalone high-sensitivity terms** (``rule="standalone"``): HIV, AIDS,
   TB, tuberculosis, hepatitis B/C, schizophrenia, bipolar disorder, sickle
   cell disease, epilepsy, syphilis, antiretrovirals... only in a sentence
   that also refers to a person (patient, pt, Mr/Mrs, he/she, husband, ``34F``,
   ``82yo``). The short acronyms (TB, AIDS, STI, HBV) also need a clinical
   word in the sentence, and ``TB`` after a number (``2 TB``) is storage.
   A trailing status (``HIV positive``, ``HIV+``) is part of the span.

Nothing here is a classifier. A condition named without a cue ("attended with
Parkinson's tremor") is not found, and that is the documented trade.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from arche.workflow._primitive import Detection

HEALTH = "PII-6-HEALTH"
RELIGION = "PII-6-RELIGION"
RACE = "PII-6-RACE"
SEXUAL_ORIENTATION = "PII-6-SEXUAL_ORIENTATION"
POLITICAL = "PII-6-POLITICAL_AFFILIATION"
TRADE_UNION = "PII-6-TRADE_UNION"

# ── context gates ────────────────────────────────────────────────────────────

_PERSON = re.compile(
    r"(?i)\b(?:pt|patient|client|mr|mrs|ms|miss|mx|he|she|his|her|him|hers|husband|wife|"
    r"son|daughter|mother|father|brother|sister|child|baby|infant|boy|girl|man|woman|"
    r"employee|applicant|candidate|claimant|resident|inmate|deceased|nok|next of kin)\b"
    r"|\b\d{1,3}\s*(?:yo|y/o|yrs?|years?[- ]old)\b|\b\d{1,3}\s?[MF]\b"
)
_CLINICAL = re.compile(
    r"(?i)\b(?:pt|patient|admitted|admission|discharged?|diagnos\w*|dx|clinic(?:al)?|"
    r"hospital|ward|a&e|icu|opd|triage|referral|referred|gp|doctor|dr|nurse|physician|"
    r"consultant|symptoms?|medical|treatment|treated|medication|prescribed|tested|test|"
    r"results?|screening|presents?|presented|presenting|history|hx|pmh|positive|negative|"
    r"viral load|cd4|ARVs?)\b"
)

# ── health ───────────────────────────────────────────────────────────────────

_COLON = r"\s*[:=\-\u2013]\s*"
#: (cue name, regex, needs a clinical sentence, value mode)
_HEALTH_CUES: tuple[tuple[str, re.Pattern[str], bool, str], ...] = (
    ("dx", re.compile(r"\b(?:Dx|DX|dx)\b\.?\s*[:=\-\u2013]?\s*"), False, "list"),
    ("diagnosis", re.compile(r"(?i)\b(?:diagnos[ie]s|impression|assessment)" + _COLON
                             + r"|\bdiagnosis\s+of\s+"), False, "list"),
    ("diagnosed with", re.compile(r"(?i)\bdiagnosed\s+(?:with|as\s+having|as)\s+"),
     False, "list"),
    ("pmh", re.compile(r"\b(?:PMH|PMHx|Hx|h/o|H/O)\b\s*(?:of\b)?\s*[:=\-\u2013]?\s*"),
     False, "list"),
    ("medical history", re.compile(
        r"(?i)\b(?:past\s+medical|medical|family|psychiatric|surgical|clinical)\s+history"
        r"(?:\s+of\s+|" + _COLON + r")"), False, "list"),
    ("medication", re.compile(r"(?i)\b(?:medications?|meds|current\s+medicines?|drug\s+history)"
                              + _COLON + r"|\bRx\s*:\s*"), False, "meds"),
    ("allergies", re.compile(r"(?i)\ballerg(?:ies|y)" + _COLON + r"|\ballergic\s+to\s+"),
     False, "list"),
    ("hiv status", re.compile(r"(?i)\bHIV\s+status\s*(?:[:=\-\u2013]|is|was)?\s*"),
     False, "single"),
    ("condition", re.compile(r"(?i)(?<![\w/-])(?:medical|chronic|pre-?existing|underlying|"
                             r"health)\s+conditions?" + _COLON), False, "list"),
    ("presents with", re.compile(r"(?i)\bpresent(?:s|ed|ing)\s+with\s+"), True, "list"),
    ("admitted with", re.compile(
        r"(?i)\badmitted(?:\s+(?:on\s+)?[\d/.\-]{6,10})?\s+(?:with|for)\s+"), True, "list"),
    ("suffers from", re.compile(r"(?i)\bsuffer(?:s|ed|ing)?\s+from\s+"), True, "list"),
    ("treated for", re.compile(r"(?i)\b(?:treated|being\s+treated|on\s+treatment)\s+for\s+"),
     True, "list"),
    ("tested positive for", re.compile(r"(?i)\btested\s+positive\s+for\s+"), True, "list"),
    ("known case of", re.compile(r"(?i)\b(?:known\s+case\s+of|k/c/o|KCO)\s+"), True, "list"),
    ("prescribed", re.compile(r"(?i)\bprescribed\s+"), True, "meds"),
)

_HARD_STOP = re.compile(r"[;\n(|\[`\"\u201c\u201d\u2026]|\.(?=\s|$)|\s[-\u2013\u2014]\s")
_SOFT_STOP = re.compile(
    r"(?i)\s(?:in|on|since|for|at|by|from|to|who|which|that|but|was|were|is|are|has|had|"
    r"seen|referred|ruled\s+out|then|after|before|without|per|according|x\d|today|"
    r"yesterday|last|this|currently|now)\b"
)
_MEDS_STOP = re.compile(r"(?i)\s(?:who|which|but|was|were|is|are|seen|referred|today)\b")
_ITEM_SPLIT = re.compile(r",|\s+(?:and|or|plus|&)\s+")
_DETERMINER = re.compile(r"(?i)^(?:a|an|the|known|likely)\s+")
_EMPTY_VALUES = frozenset({
    "none", "nil", "n/a", "na", "no", "unknown", "nkda", "nkfa", "nad", "not known",
    "not applicable", "nothing", "-", "none known", "none reported",
})
_MAX_PHRASE = 120
_MAX_ITEM = 60

_STANDALONE = re.compile(
    r"(?<![\w-])(?:"
    r"(?P<acr>MDR-TB|XDR-TB|TB|AIDS|STIs?|STDs?|HBV|HCV)"
    r"|(?P<strong>HIV(?:/AIDS)?|PrEP|ARVs?"
    r"|(?i:tuberculosis|hepatitis\s+[BC]|schizophreni[ac]|schizoaffective\s+disorder"
    r"|bipolar(?:\s+affective)?\s+disorder|sickle[- ]cell(?:\s+(?:disease|anaemia|anemia|"
    r"trait|crisis))?|epilepsy|syphilis|gonorrh?oea|chlamydia|antiretrovirals?"
    r"|antiretroviral\s+(?:therapy|treatment)|dementia|alzheimer'?s(?:\s+disease)?"
    r"|multiple\s+sclerosis|cystic\s+fibrosis|ha?emophilia|leuka?emia|lymphoma|carcinoma"
    r"|psychosis|anorexia\s+nervosa|bulimia(?:\s+nervosa)?"
    r"|(?:opioid|alcohol|substance)\s+use\s+disorder))"
    r")(?P<status>(?:\s*[-\u2013]?\s*(?i:positive|negative|reactive|non-reactive|\+ve|-ve))"
    r"|\+)?(?![\w])"
)

# ── religion / race / orientation / political / union ───────────────────────

_RELIGION_WORDS = (
    r"Christian|Muslim|Moslem|Islamic|Catholic|Roman\s+Catholic|Protestant|Anglican|"
    r"Methodist|Baptist|Pentecostal|Presbyterian|Lutheran|Evangelical|Orthodox|"
    r"(?:Greek|Russian|Coptic|Ethiopian)\s+Orthodox|Jewish|Jew|Hindu|Buddhist|Sikh|Jain|"
    r"Atheist|Agnostic|Mormon|Jehovah'?s\s+Witness|Seventh[- ]day\s+Adventist|Adventist|"
    r"Rastafarian?|Quaker|Shia|Shi'?ite|Sunni|Ahmadi(?:yya)?|Bah[aá]'?[ií]|Zoroastrian|"
    r"Shinto|Taoist|Wiccan|Pagan|Zionist|Apostolic|Aladura|Cherubim\s+and\s+Seraphim|"
    r"Celestial|Born[- ]again"
)
_SUBJECT = (
    r"(?i:\b(?:I|he|she|they|patient|pt|client|applicant|employee|candidate|claimant|"
    r"resident|tenant|member|husband|wife)\s+(?:is|am|are|was|were|identifies\s+as|"
    r"describes\s+(?:himself|herself|themselves)\s+as|came\s+out\s+as)\s+)"
)
_INSTITUTION_NOUN = (
    r"(?!\s+(?i:school|church|mosque|temple|synagogue|charity|organi[sz]ation|hospital|"
    r"college|university|country|nation|name|community|group|radio|station|channel|"
    r"bookshop|bank|mission|missionary|holiday|festival|calendar|text|ministry|council))"
)
_RELIGION_PATTERN = re.compile(
    _SUBJECT + r"(?:an?\s+)?(?:(?i:practi[sc]ing|devout|observant|lapsed|converted|"
    r"committed|strict)\s+)?(?P<v>" + _RELIGION_WORDS + r")\b" + _INSTITUTION_NOUN
    + r"|\b(?i:converted|conversion)\s+to\s+(?P<v2>Islam|Christianity|Judaism|Hinduism|"
    r"Buddhism|Catholicism|Sikhism)\b"
)
_ORIENTATION_PATTERN = re.compile(
    _SUBJECT + r"(?:(?i:openly)\s+)?(?:an?\s+)?(?P<v>(?i:gay|lesbian|bisexual|homosexual|"
    r"heterosexual|queer|pansexual|asexual))\b"
)
_RACE_WORDS = re.compile(
    r"(?i)^(?:black|white|african|coloured|colored|indian|asian|caucasian|hispanic|latin[oax]|"
    r"arab|mixed|multiracial|biracial|native|indigenous|aboriginal|pacific|south\s+asian|"
    r"east\s+asian|chinese|middle\s+eastern|other|yoruba|igbo|ibo|hausa|fulani|ijaw|"
    r"kanuri|tiv|efik|ibibio|edo|zulu|xhosa|sotho|tswana|pedi|venda|tsonga|ndebele|swazi|"
    r"afrikaner|akan|ashanti|asante|ewe|ga|fante|dagomba|kikuyu|luo|luhya|kalenjin|kamba|"
    r"kisii|meru|somali|maasai|amhara|oromo|tigray|hutu|tutsi|shona|white\s+british|"
    r"black\s+british|roma|traveller|jewish)\b"
)
_VALUE_CUES: tuple[tuple[str, str, re.Pattern[str], bool], ...] = (
    # (category, cue name, regex, value must start with a race word)
    (RELIGION, "religion", re.compile(
        r"(?i)\b(?:religion|religious\s+(?:affiliation|beliefs?|denomination|preference)|"
        r"faith|denomination|belief\s+system)" + _COLON
        + r"|(?i:\breligion\s+(?:is|was)\s+)"), False),
    (RACE, "race", re.compile(
        r"(?i)\b(?:race|racial\s+(?:group|origin|classification|category)|"
        r"population\s+group)" + _COLON), True),
    (RACE, "ethnicity", re.compile(
        r"(?i)\b(?:ethnicity|ethnic\s+(?:origin|group|background|identity)|tribe|"
        r"tribal\s+affiliation)\s*(?:[:=\-\u2013]|is\b|was\b)\s*"), False),
    (SEXUAL_ORIENTATION, "sexual orientation", re.compile(
        r"(?i)\b(?:sexual\s+orientation|sexuality)\s*(?:[:=\-\u2013]|is\b|was\b)\s*"), False),
    (POLITICAL, "political affiliation", re.compile(
        r"(?i)\b(?:political\s+(?:affiliation|party|opinions?|views?|persuasion|leaning|"
        r"membership)|party\s+(?:membership|affiliation))\s*(?:[:=\-\u2013]|is\b|are\b|was\b)"
        r"\s*"), False),
    (TRADE_UNION, "trade union", re.compile(
        r"(?i)\b(?:trade\s+union(?:\s+(?:membership|member|affiliation))?|"
        r"union\s+(?:membership|affiliation))" + _COLON), False),
)
_SINGLE_STOP = re.compile(
    r"[.;,\n(|\[`\"\u201c\u201d\u2026]|\s[-\u2013\u2014]\s|\s(?i:and|but|who|since)\b"
)

_PARTY = (
    r"(?P<v>(?:[A-Z][\w'\u2019-]*\s+(?:of\s+|for\s+)?){1,5}Party(?:\s+of\s+[A-Z]\w+)?"
    r"|ANC|EFF|IFP|ActionSA|APC|PDP|NNPP|APGA|NDC|NPP|ODM|UDA|ZANU-PF|MDC|SNP|DUP|"
    r"UKIP|Reform\s+UK|Lib\s+Dems?|Liberal\s+Democrats|Tories|GOP)\b"
)
_PARTY_ROLE = (
    r"(?i:member|members|supporter|activist|card-carrying\s+member|candidate|councillor|"
    r"councilor|agent|chair(?:man|woman|person)?|official|ward\s+chair|organi[sz]er|"
    r"volunteer|delegate)"
)
_POLITICAL_PATTERN = re.compile(
    r"\b" + _PARTY_ROLE + r"\s+(?:of|for|with|in)\s+(?:the\s+)?" + _PARTY
    + r"|\b(?P<v2>ANC|EFF|IFP|APC|PDP|NDC|NPP|ODM|UDA|ZANU-PF|Labour|Conservative|"
    r"Republican|Democratic)\s+(?:party\s+)?(?i:member|supporter|activist|councillor|"
    r"councilor|candidate|ward\s+chair|official)\b"
)
_UNION_ACRONYMS = (
    r"COSATU|NUMSA|NUM|SADTU|NEHAWU|POPCRU|FEDUSA|SAFTU|DENOSA|NLC|TUC|NUT|NUJ|ASUU|"
    r"NANNM|NUPENG|PENGASSAN|NASU|UNISON|GMB|NASUWT|NEU|RMT|USDAW|SEIU|UAW|AFL-CIO|"
    r"Teamsters|KNUT|KUPPET|COTU|GNAT|TEWU|UNITE|Unite\s+the\s+Union|RCN|BMA"
)
_UNION_NAME = (
    r"(?P<v>(?:[A-Z][\w'\u2019&-]*\s+(?:of\s+|and\s+|&\s+|for\s+)?){1,7}Union"
    r"(?:\s+of\s+(?:[A-Z][\w'\u2019-]*\s*){1,5})?|" + _UNION_ACRONYMS + r")\b"
)
_WORKER_WORD = re.compile(
    r"(?i)\b(?:trade|workers?|teachers?|nurses?|midwives|labou?r|employees?|mineworkers|"
    r"metalworkers|transport|allied|staff|journalists|doctors|educators|police|seamen|"
    r"miners|railway|rail|maritime|public\s+service|municipal|academic|clerical|commercial|"
    r"petroleum|electricity|textile|teamsters|communication|postal\s+workers|firefighters)\b"
)
_UNION_ROLE = (
    r"(?i:member|members|shop\s+steward|steward|official|organi[sz]er|representative|rep|"
    r"branch\s+secretary|delegate|activist)"
)
_UNION_PATTERN = re.compile(
    r"\b(?:" + _UNION_ROLE + r"\s+(?:of|for|with|in)|(?i:joined|belongs\s+to))\s+(?:the\s+)?"
    + _UNION_NAME
    + r"|\b(?P<v2>" + _UNION_ACRONYMS + r")\s+(?i:member|shop\s+steward|steward|official|"
    r"organi[sz]er|representative|rep|delegate)\b"
)

_ABBREV = re.compile(r"(?i)\b(?:dr|mr|mrs|ms|mx|prof|st|no|vs|etc|e\.g|i\.e|approx|pt|ref)\.$")


@dataclass(frozen=True)
class _Cand:
    start: int
    end: int
    category: str
    cue: str
    rule: str
    confidence: float


def _sentences(text: str) -> Iterator[tuple[int, int]]:
    """``(start, end)`` of each sentence; abbreviations like ``Dr.`` do not end one."""
    start = 0
    for m in re.finditer(r"[.!?](?=\s)|\n", text):
        if m.group() != "\n" and _ABBREV.search(text[max(0, m.start() - 6):m.end()]):
            continue
        yield start, m.end()
        start = m.end()
    if start < len(text):
        yield start, len(text)


def _sentence_at(bounds: list[tuple[int, int]], pos: int) -> tuple[int, int]:
    for s, e in bounds:
        if s <= pos < e:
            return s, e
    return 0, 0


def _gate_text(text: str, sent: tuple[int, int], cut: tuple[int, int]) -> str:
    """The sentence with the cue (or term) itself blanked, so a cue never gates itself."""
    s, e = sent
    return text[s:cut[0]] + " " + text[cut[1]:e]


def _phrase_end(text: str, pos: int, limit: int, stops: re.Pattern[str]) -> int:
    window = text[pos:min(limit, pos + _MAX_PHRASE)]
    hard = _HARD_STOP.search(window)
    end = hard.start() if hard else len(window)
    soft = stops.search(window, 0, end)
    if soft:
        end = soft.start()
    if not hard and pos + len(window) < limit and end == len(window):
        cut = window.rfind(" ")
        end = cut if cut > 0 else end
    return pos + end


def _items(text: str, start: int, end: int) -> Iterator[tuple[int, int]]:
    """Split ``text[start:end]`` into list items, trimmed of space and determiners."""
    pos = start
    for piece in [*_ITEM_SPLIT.finditer(text, start, end), None]:
        stop = piece.start() if piece else end
        s, e = pos, stop
        while s < e and not text[s].isalnum():
            s += 1
        while e > s and not (text[e - 1].isalnum() or text[e - 1] in "+')"):
            e -= 1
        det = _DETERMINER.match(text, s, e)
        if det:
            s = det.end()
        if e - s > _MAX_ITEM:
            cut = text.rfind(" ", s, s + _MAX_ITEM)
            e = cut if cut > s else s + _MAX_ITEM
        value = text[s:e].strip()
        if value and any(c.isalpha() for c in value) and value.lower() not in _EMPTY_VALUES:
            yield s, e
        if piece is None:
            break
        pos = piece.end()


def _single(text: str, pos: int, limit: int) -> tuple[int, int] | None:
    window = text[pos:min(limit, pos + 50)]
    m = _SINGLE_STOP.search(window)
    end = m.start() if m else len(window)
    value = window[:end].rstrip()
    words = value.split()
    if len(words) > 4:
        value = " ".join(words[:4])
    if not value or not any(c.isalpha() for c in value) \
            or value.lower().strip(" .") in _EMPTY_VALUES:
        return None
    return pos, pos + len(value)


def _candidates(text: str) -> Iterator[_Cand]:
    bounds = list(_sentences(text))
    # 1. health cues
    for cue, pattern, gated, mode in _HEALTH_CUES:
        for m in pattern.finditer(text):
            sent = _sentence_at(bounds, m.start())
            if gated and not (_CLINICAL.search(_gate_text(text, sent, m.span()))
                              or _PERSON.search(_gate_text(text, sent, m.span()))
                              and cue != "admitted with"):
                continue
            if mode == "single":
                span = _single(text, m.end(), sent[1])
                if span:
                    yield _Cand(*span, HEALTH, cue, "cue", 0.85)
                continue
            stops = _MEDS_STOP if mode == "meds" else _SOFT_STOP
            end = _phrase_end(text, m.end(), sent[1], stops)
            for s, e in _items(text, m.end(), end):
                yield _Cand(s, e, HEALTH, cue, "cue", 0.85)
    # 2. other value cues
    for category, cue, pattern, needs_race_word in _VALUE_CUES:
        for m in pattern.finditer(text):
            sent = _sentence_at(bounds, m.start())
            span = _single(text, m.end(), sent[1])
            if span is None:
                continue
            if needs_race_word and not _RACE_WORDS.match(text[span[0]:span[1]]):
                continue
            yield _Cand(*span, category, cue, "cue", 0.85)
    # 3. patterns
    for category, cue, pattern in (
        (RELIGION, "religion pattern", _RELIGION_PATTERN),
        (SEXUAL_ORIENTATION, "orientation pattern", _ORIENTATION_PATTERN),
        (POLITICAL, "party membership", _POLITICAL_PATTERN),
        (TRADE_UNION, "union membership", _UNION_PATTERN),
    ):
        for m in pattern.finditer(text):
            group = "v" if m.group("v") else "v2"
            value = m.group(group)
            if category == TRADE_UNION and group == "v" and "Union" in value \
                    and not _WORKER_WORD.search(value):
                continue
            s, e = m.span(group)
            value = value.rstrip()
            yield _Cand(s, s + len(value), category, cue, "pattern", 0.8)
    # 4. standalone high-sensitivity health terms
    for m in _STANDALONE.finditer(text):
        sent = _sentence_at(bounds, m.start())
        ctx = _gate_text(text, sent, m.span())
        if not _PERSON.search(ctx):
            continue
        if m.group("acr"):
            if not _CLINICAL.search(ctx):
                continue
            if re.search(r"\d\s*$", text[max(0, m.start() - 4):m.start()]):
                continue
        yield _Cand(m.start(), m.end(), HEALTH, m.group(0).split()[0].rstrip("+"),
                    "standalone", 0.75)


def detect_special_categories(text: str) -> list[Detection]:
    """Special-category content in ``text``, by offset (see the module docstring).

    Overlaps resolve to the first-starting, then longest, candidate; a
    cue-anchored value therefore wins over a standalone term inside it.
    """
    cands = sorted(_candidates(text), key=lambda c: (c.start, -(c.end - c.start)))
    out: list[Detection] = []
    last_end = -1
    for c in cands:
        if c.start < last_end or c.end <= c.start:
            continue
        kind = c.category.rsplit("-", 1)[-1].lower()
        out.append(Detection(
            id=f"det:{kind}:{c.start}:{c.end}",
            category=c.category,
            text=text[c.start:c.end],
            start=c.start,
            end=c.end,
            confidence=c.confidence,
            detector=f"rule:special_{c.rule}",
            identity_class="inferred",
            metadata={"kind": kind, "cue": c.cue, "rule": c.rule},
        ))
        last_end = c.end
    return out


__all__ = [
    "HEALTH", "POLITICAL", "RACE", "RELIGION", "SEXUAL_ORIENTATION", "TRADE_UNION",
    "detect_special_categories",
]
