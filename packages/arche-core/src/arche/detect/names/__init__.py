# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""African name detection from the shipped lexicon.

Public surface::

    from arche.detect.names import detect_names, person_spans

    detect_names("Met Adesola Okonkwo and Fatima Abdullahi today.")
    # -> one PII-1-NAME Detection per name token:
    #    Adesola, Okonkwo, Fatima, Abdullahi

    person_spans("Met Adesola Okonkwo and Fatima Abdullahi today.")
    # -> [(4, 19, "Adesola Okonkwo"), (24, 40, "Fatima Abdullahi")]

Two sources of names, both offline:

* the **equivalence groups** (114 groups, ~440 spellings: *Diallo* /
  *Jallow* / *Diaw*), matched case-insensitively as before;
* the **name lexicon** that ships in the wheel — 13,342 given and family
  names derived from Wikidata / ParaNames (CC-BY-4.0, see
  ``arche/_data/README.md``) — matched token by token, and only when the
  token is capitalised in the text. *Grace*, *Hope*, *Peace* and *Victor* are
  names in this lexicon and ordinary words in English prose; the capital is
  what separates the two, imperfectly, at confidence 0.7.

Before the lexicon shipped, ``pip install arche-core`` detected 118 names and
"Adesola Okonkwo" was not among them. The 13k lexicon existed only as a file
in the source repository that the installed package could not see.

:func:`detect_names` keeps its per-token contract, which is what the PII
pipeline redacts. :func:`person_spans` is for the extractors: it merges
adjacent name tokens (allowing an initial between them) into one span and
requires at least two, so a record gets ``name="Adesola E. Okonkwo"`` rather
than ``name="Adesola"``, and a lone capitalised *May* is not a person.

The lexicon loads on the first call, not at import; ``import arche.detect.names``
stays within the cold-import budget.
"""

from __future__ import annotations

import re
from threading import Lock

from arche.detect._base import _compile_lexicon, _lexicon_detect
from arche.workflow._primitive import Detection

_PATTERN: re.Pattern[str] | None = None
_KNOWN: frozenset[str] | None = None
_LOCK = Lock()

#: Two-character "names" like *Ba* collide with function words in Hausa,
#: Swahili and Pidgin too often to be useful without context.
_MIN_LEXICON_TERM_LEN = 3

#: English words that are also, somewhere, a name. A capital letter is the
#: only context a lexicon match has, and every one of these is capitalised at
#: the start of a sentence, in a date, or as a title. Excluding them costs the
#: rare person actually called *Will* or *June*; keeping them costs a name
#: token on every "The", "Monday" and "Dr". Virtue names -- *Grace*, *Peace*,
#: *Patience*, *Mercy*, *Faith*, *Hope*, *Joy* -- are deliberately NOT here:
#: they are among the commonest given names in Nigeria and Ghana, and a
#: detector calibrated for that region cannot afford to drop them.
_STOP: frozenset[str] = frozenset({
    # function and frequent words (*Will* and *May* are weak, not stopped:
    # see _WEAK)
    "the", "and", "for", "from", "with", "this", "that", "these", "those", "then",
    "there", "their", "they", "them", "when", "where", "which", "while", "what",
    "who", "whom", "why", "how", "all", "any", "some", "one", "two", "our", "your",
    "his", "her", "its", "was", "were", "are", "have", "has", "had", "would",
    "can", "could", "might", "must", "shall", "should", "not", "yes", "new",
    "old", "day", "week", "month", "year", "time", "first", "last", "next", "more",
    "most", "many", "much", "very", "also", "just", "only", "over", "under", "into",
    "upon", "about", "after", "before", "between", "during", "since", "until",
    "again", "here", "now", "today", "please", "thank", "thanks", "dear", "hello",
    "general", "central", "north", "south", "east", "west", "saint", "san",
    # months, weekdays
    "january", "february", "march", "april", "june", "july", "august", "september",
    "october", "november", "december", "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
    # titles
    "dr", "mr", "mrs", "ms", "miss", "prof", "sir", "madam", "rev", "hon", "chief",
    "alhaji", "alhaja", "engr", "barr", "mnr", "mev", "mej", "pt", "mx", "dame", "pastor",
    # form and email boilerplate that the lexicon also holds as surnames.
    # Measured on 300 English texts: "Given" (given name:), "Best" (best
    # regards), "Holder" (account holder) and "Law" were the four most
    # frequent name false positives, 30 of 91 between them. Real surnames all,
    # and in running English prose a word first.
    "given", "best", "holder", "law", "say", "family", "person", "immediate",
    # sentence-initial verbs and courtesy words the census holds as surnames
    # ("See https://...", "Note: ...", "Call me"): never a name on their own
    "see", "note", "call", "send", "ask", "check", "visit", "meet", "contact",
    "attach", "attached", "find", "read", "let", "tell", "keep", "hold", "sign",
    "kindly", "regards", "cheers", "sincerely", "attention", "attn", "subject",
})

#: Document, form and kinship words the lexicons hold as surnames (*Tax*,
#: *Bill*, *Husband*, *Order*). Never a name on their own, and they break a run:
#: in "TAX INVOICE", "Husband Babatunde", "Customer Chukwuemeka Obi" the word
#: is a label beside the name, not part of it.
_DOCUMENT_WORDS: frozenset[str] = frozenset({
    "invoice", "tax", "total", "subtotal", "order", "amount", "balance", "receipt",
    "ref", "reference", "client", "customer", "patient", "applicant", "account",
    "acct", "bank", "card", "vat", "date", "item", "ship", "payment", "due", "paid",
    "number", "phone", "cell", "mobile", "email", "address", "name", "surname",
    "kin", "husband", "wife", "son", "daughter", "mother", "father", "brother",
    "sister", "uncle", "aunt", "aunty", "auntie", "cousin", "nephew", "niece",
    "grandmother", "grandfather", "child", "baby", "partner", "spouse", "guardian",
    "nurse", "doctor", "referee", "referral", "discharge", "staff", "company",
    "product", "model", "part", "tracking", "server", "portal", "profile", "visit",
    "skills", "experience", "matric", "religion", "race", "plot", "phase", "block",
    "flat", "unit", "suite", "apt", "from", "to", "dear", "regards", "kind",
})

#: Words that, written *after* capitalised words, make those words a place or
#: an organisation: "St James's Hospital", "Mass General", "Rose Hill station",
#: "Ahmadu Bello Way", "Ogun State". The run before one is not a name.
_PLACE_SUFFIX: frozenset[str] = frozenset({
    "hospital", "clinic", "street", "st", "road", "rd", "avenue", "ave", "lane",
    "close", "crescent", "drive", "way", "place", "court", "square", "station",
    "state", "general", "university", "college", "school", "church", "mosque",
    "cathedral", "chapel", "park", "bridge", "centre", "center", "house", "island",
    "river", "valley", "county", "city", "town", "district", "province", "region",
    "airport", "market", "mall", "plaza", "group", "ltd", "limited", "inc", "corp",
    "llc", "plc", "foundation", "trust", "medical", "health", "memorial",
    "institute", "academy", "library", "museum", "hotel", "estate", "gardens",
    "terrace", "boulevard", "highway", "barracks", "infirmary", "surgery",
    "pharmacy", "stadium", "ward", "campus", "village", "parish", "municipality",
})

#: Words that, written *before* capitalised words, make them a place: "St
#: James", "Port Harcourt", "Mount Kenya", "Lake Victoria", "Fort Worth".
_PLACE_PREFIX: frozenset[str] = frozenset({
    "st", "saint", "mount", "mt", "fort", "port", "lake", "cape", "santa",
})

_HARD: frozenset[str] = _STOP | _DOCUMENT_WORDS | _PLACE_SUFFIX | _PLACE_PREFIX

#: Surnames and given names that are also everyday English words or places.
#: A weak token is a name only beside another name token (*Will Bishop*,
#: *Rose Hill said*), after a title or a cue; alone it is left in clear
#: (*Bill to:*, *Boston, MA*, *State of origin: Ogun*). Virtue names stay
#: strong on purpose (see :data:`_STOP`).
_WEAK: frozenset[str] = frozenset({
    # English words in the census top 3,000 and the lexicons
    "will", "may", "bill", "rose", "mass", "grant", "park", "white", "young",
    "green", "hall", "ward", "wood", "price", "long", "bell", "west", "black",
    "mills", "lane", "fields", "little", "banks", "day", "chambers", "powers", "page",
    "love", "sharp", "cross", "moss", "gross", "roman", "farmer", "short", "wall",
    "bridges", "gates", "shields", "rich", "golden", "marks", "english", "strong",
    "sellers", "weeks", "small", "case", "bean", "cherry", "good", "branch", "key",
    "lake", "cash", "head", "hatch", "smart", "quick", "fish", "field", "blue",
    "swift", "sun", "drew", "self", "post", "heard", "link", "hand", "block", "land",
    "hurt", "major", "deal", "root", "urban", "story", "brand", "keys", "gold",
    "pack", "fair", "hooks", "read", "light", "ring", "rider", "means", "mock",
    "driver", "call", "power", "merchant", "cloud", "laws", "harms", "mark",
    "chance", "early", "high", "pool", "hook", "carrier", "shell", "scales",
    "blank", "burden", "main", "stock", "grey", "gray", "pan", "still", "rust",
    "low", "stack", "king", "hill", "brown", "wells", "rice", "stone",
    "bush", "frank", "noble", "best", "lord", "bishop", "dean",
    "rivers", "waters", "glass", "hart", "fox", "wolf", "lamb", "bird",
    "nation", "north", "south", "east", "london", "england", "street", "house",
    "court", "summer", "winter", "spring", "august", "sky",
    "star", "pearl", "ruby", "amber", "dawn", "art", "rock", "stern",
    "ball", "bond", "booker", "reader", "dealer", "joiner",
    # places that the lexicons hold as names
    "boston", "ogun", "lagos", "kano", "abuja", "oyo", "benin", "kaduna", "ondo",
    "delta", "plateau", "niger", "durban", "pretoria", "soweto", "chicago",
    "houston", "dallas", "austin", "denver", "phoenix", "miami", "atlanta",
    "orlando", "memphis", "nashville", "detroit", "cleveland", "jackson",
    "madison", "lincoln", "washington", "columbus", "florence", "georgia",
    "virginia", "carolina", "dakota", "kansas", "texas", "nevada", "montana",
    "indiana", "kent", "essex", "york", "cardiff", "bristol", "leeds", "kingston",
    "victoria", "charlotte", "eugene", "troy", "salem", "paris",
})

#: Name particles: written lower case between the parts of one name.
_PARTICLES: frozenset[str] = frozenset({
    "van", "der", "den", "de", "du", "da", "das", "dos", "di", "del", "della", "von",
    "ter", "ten", "le", "la", "bin", "binti", "ibn", "bint", "al", "el", "ben", "abu",
    "mac", "ka", "wa",
})

#: Lower-case cue words. After one, lower-case words the lexicon knows are a
#: name ("pt tom hargreaves", "customer ngozi okafor-eze", "dear ade").
_CUE = re.compile(
    r"\b(?:pt|patient|customer|client|applicant|dear|mr|mrs|ms|dr|mnr|mev|"
    r"name(?:\s+is)?|next\s+of\s+kin|nok|contact)\b\s*[:.]?[ \t]+",
    re.IGNORECASE,
)

#: A chat handle at the start of a line: "sipho: ok", "[10:42] annelie: hey".
_HANDLE = re.compile(r"(?m)^[ \t]*(?:\[[^\]\n]*\][ \t]*)?([^\W\d_][\w'’\-]*):")

_LOWER_FUNCTION: frozenset[str] = frozenset({
    "is", "was", "has", "had", "and", "or", "the", "a", "an", "of", "in", "on", "at",
    "with", "for", "to", "from", "by", "said", "says", "again", "here",
})


#: A word made of letters, allowing an internal apostrophe or hyphen
#: (*N'Diaye*, *Abd al-Rahman*).
_TOKEN = re.compile(r"[^\W\d_]+(?:['’\-][^\W\d_]+)*")
#: An initial: one capital letter with an optional full stop.
_INITIAL = re.compile(r"^[A-Z]\.?$")


def _build_pattern() -> re.Pattern[str]:
    """The equivalence-group pattern: every spelling in every group, longest first."""
    from arche.detect._names.lexicon import _load_all_groups

    terms = [
        variant
        for group in _load_all_groups()
        for variant in group
        if len(variant) >= _MIN_LEXICON_TERM_LEN
    ]
    return _compile_lexicon(terms, case_insensitive=True)


def _get_pattern() -> re.Pattern[str]:
    global _PATTERN
    if _PATTERN is None:
        with _LOCK:
            if _PATTERN is None:
                _PATTERN = _build_pattern()
    return _PATTERN


def _known() -> frozenset[str]:
    """Normalised name tokens: equivalence groups, shipped lexicon, common names.

    Hard stop words and particles are removed; *weak* tokens (:data:`_WEAK`)
    stay in, and :func:`_name_runs` decides when they count.
    """
    global _KNOWN
    if _KNOWN is None:
        with _LOCK:
            if _KNOWN is None:
                from arche.detect._names.lexicon import (
                    KNOWN_AFRICAN_NAMES,
                    load_common_names,
                )

                _KNOWN = frozenset(
                    token for token in KNOWN_AFRICAN_NAMES | load_common_names()
                    if len(token) >= _MIN_LEXICON_TERM_LEN
                    and token not in _HARD and token not in _PARTICLES
                )
    return _KNOWN


def _normalise(token: str) -> str:
    from arche.detect._names.lexicon import _strip_diacritics

    return _strip_diacritics(token).lower()


def _name_tokens(text: str) -> list[tuple[int, int, str]]:
    """Name tokens of ``text`` after context rules, in offset order.

    See :func:`_name_runs`; this flattens its runs to tokens.
    """
    return [tok for run in _name_runs(text) for tok in run[2]]


def person_spans(text: str) -> list[tuple[int, int, str]]:
    """Runs of two or more adjacent name tokens, each as one ``(start, end, text)``.

    Adjacent means separated only by whitespace, optionally with an initial
    (``E.``) or a particle (``van der``) in between. A single known token on
    its own is not returned: one capitalised word that happens to be in a name
    lexicon is not evidence of a person, and the extractors that call this
    build records from it.
    """
    spans: list[tuple[int, int, str]] = []
    for start, end, tokens, _ in _name_runs(text):
        words = [t for t in tokens if len(t[2]) > 1 and _normalise(t[2]) not in _PARTICLES]
        if len(words) >= 2:
            spans.append((start, end, text[start:end]))
    return spans


#: A courtesy or honorific title, then one to three capitalised words: those
#: words are a name whether or not the lexicon knows them ("Mrs Ada Okwuosa",
#: "Chief Bamidele Adeyemi-Lawal"). Without it a surname the lexicon lacks
#: stayed in clear beside a masked first name.
_TITLED = re.compile(
    r"\b(?:Mr|Mrs|Ms|Miss|Mx|Dr|Prof|Sir|Madam|Dame|Rev|Hon|Chief|Alhaji|Alhaja|Engr|Barr"
    r"|Pastor|Mnr|Mev|Mej)\.?[ \t]+"
    r"((?:[A-Z][^\W\d_]+(?:['’\-][^\W\d_]+)*)"
    r"(?:[ \t]+(?:[A-Z]\.?[ \t]+)?[A-Z][^\W\d_]+(?:['’\-][^\W\d_]+)*){0,2})"
)


def _titled_tokens(text: str) -> list[tuple[int, int, str]]:
    out = []
    for m in _TITLED.finditer(text):
        for t in _TOKEN.finditer(m.group(1)):
            token = t.group(0)
            if len(token) >= 2 and token[0].isupper() and _normalise(token) not in _STOP:
                out.append((m.start(1) + t.start(), m.start(1) + t.end(), token))
    return out


def _key(token: str) -> str:
    """Lookup form: normalised, possessive dropped (*James's* -> *james*)."""
    norm = _normalise(token)
    for suffix in ("'s", "’s"):
        if norm.endswith(suffix):
            return norm[: -len(suffix)]
    return norm


def _status(token: str, known: frozenset[str]) -> str | None:
    """``strong``, ``weak`` or ``None`` for one token, hyphen parts included.

    A hyphenated token is a name when any part of three or more letters is
    (*MARY-JANE*, *Al-Amin*, *okafor-eze*); the whole token is the name then.
    """
    key = _key(token)
    if key in _HARD:
        return None
    parts = [key] + ([p for p in re.split(r"['’\-]", key) if len(p) >= 3] if "-" in key
                     else [])
    best = None
    for part in parts:
        if part in _HARD or part not in known:
            continue
        if part in _WEAK:
            best = best or "weak"
        else:
            return "strong"
    return best


_JOIN = re.compile(r"[ \t]{1,3}|\.[ \t]{1,3}")


def _name_runs(text: str) -> list[tuple[int, int, list[tuple[int, int, str]], str]]:
    """Name runs: ``(start, end, tokens, detector)``.

    A run is a stretch of capitalised tokens (one style: Title case or ALL
    CAPS), initials and particles joined by spaces. It is a name when it holds
    a strong lexicon token, two known tokens (weak ones included), or follows
    a title. The whole run is then the name, so *Pieter van der Merwe* and
    *MARY-JANE FOTHERINGHAM-SMYTHE* mask whole. Unknown Title-case words
    before the first known token are not taken (*Yesterday Adesola*); after
    the last one at most two are. A run followed by *Hospital*, *Street*,
    *State*, *General*... or preceded by *St*, *Port*, *Mount*... is a place.
    """
    known = _known()
    words = list(_TOKEN.finditer(text))
    titled = {(s, e) for s, e, _ in _titled_tokens(text)}
    runs: list[tuple[int, int, list[tuple[int, int, str]], str]] = []
    i = 0
    n = len(words)

    def style(tok: str) -> str:
        if len(tok) == 1:
            return "initial"
        return "upper" if tok.isupper() else "title"

    def eligible(k: int) -> bool:
        tok = words[k].group(0)
        if not tok[0].isupper() or _key(tok) in _HARD:
            return False
        # glued to a digit: a code ("SAA-C03", "B12"), not a name
        if text[words[k].end():words[k].end() + 1].isdigit():
            return False
        if len(tok) == 1:
            return True
        # mixed-case or lowercase tails ("McDonald", "O'Neill") are fine
        return True

    while i < n:
        w = words[i]
        tok = w.group(0)
        if not eligible(i) or len(tok) == 1:
            i += 1
            continue
        run_style = style(tok)
        members = [i]
        j = i + 1
        while j < n:
            gap = text[words[j - 1].end():words[j].start()]
            nxt = words[j].group(0)
            if not _JOIN.fullmatch(gap):
                break
            if gap.startswith(".") and len(words[j - 1].group(0)) != 1 \
                    and _key(words[j - 1].group(0)) not in _STOP:
                break
            if nxt.lower() in _PARTICLES and nxt.islower():
                members.append(j)
                j += 1
                continue
            if not eligible(j):
                break
            st = style(nxt)
            if st != "initial" and st != run_style:
                break
            members.append(j)
            j += 1
        # trim particles and initials hanging off the end
        while members and (words[members[-1]].group(0).islower()
                           or len(words[members[-1]].group(0)) == 1):
            members.pop()
        after = j if j < n else None
        before = i - 1 if i > 0 else None
        i = j
        if not members:
            continue
        first, last = words[members[0]], words[members[-1]]
        if after is not None and _key(words[after].group(0)) in _PLACE_SUFFIX and \
                _JOIN.fullmatch(text[last.end():words[after].start()]):
            continue
        if before is not None and _key(words[before].group(0)) in _PLACE_PREFIX and \
                _JOIN.fullmatch(text[words[before].end():first.start()]):
            continue
        status = [_status(words[k].group(0), known) for k in members]
        is_titled = any((words[k].start(), words[k].end()) in titled for k in members)
        strong = [k for k, s in zip(members, status, strict=True) if s == "strong"]
        named = [k for k, s in zip(members, status, strict=True) if s]
        if run_style == "upper":
            # ALL-CAPS acronyms ("AWS", "NHS") are not names on their own
            strong = [k for k in strong if len(words[k].group(0)) >= 4]
        if not (strong or len(named) >= 2 or is_titled):
            continue
        # a lone possessive surname is usually an eponym ("Parkinson's tremor")
        if len(members) == 1 and not is_titled and _key(tok) != _normalise(tok) \
                and words[members[0]].group(0)[-2:] in ("'s", "’s"):
            continue
        anchors = [k for k, s in zip(members, status, strict=True)
                   if s or (words[k].start(), words[k].end()) in titled]
        lo = members.index(anchors[0])
        hi = members.index(anchors[-1])
        # take particles (+ the capitalised word before them) on the left
        while lo >= 2 and words[members[lo - 1]].group(0).islower():
            lo -= 1
            while lo >= 1 and words[members[lo - 1]].group(0).islower():
                lo -= 1
            if lo >= 1:
                lo -= 1
        # one unknown word before the first known one, when the run follows a
        # field label or list comma ("NOMVULA KHUMALO", ", Nomvula Khumalo"),
        # not at a sentence start ("Yesterday Adesola", "Reach Amina")
        if lo == 1 and (run_style == "upper"
                        or re.search(r"[,;:|(][ \t]*$", text[:first.start()])):
            lo = 0
        # initials directly before the first anchor are part of the name
        while lo >= 1 and len(words[members[lo - 1]].group(0)) == 1:
            lo -= 1
        extra = 0
        while hi + 1 < len(members) and extra < 2:
            nxt = words[members[hi + 1]].group(0)
            if not (nxt.islower() or len(nxt) == 1):
                extra += 1
            hi += 1
        while words[members[hi]].group(0).islower():
            hi -= 1
        chosen = members[lo:hi + 1]
        toks = [(words[k].start(), words[k].end(), words[k].group(0)) for k in chosen]
        detector = "rule:names_title" if is_titled and not strong else "rule:names_lexicon"
        runs.append((toks[0][0], toks[-1][1], toks, detector))
    runs.extend(_lowercase_runs(text, known))
    runs.sort(key=lambda r: r[0])
    return runs


def _lowercase_runs(
    text: str, known: frozenset[str],
) -> list[tuple[int, int, list[tuple[int, int, str]], str]]:
    """Lower-case names, only after a cue word or as a chat handle."""
    runs = []
    starts = [m.end() for m in _CUE.finditer(text)]
    starts += [m.start(1) for m in _HANDLE.finditer(text)]
    for pos in sorted(set(starts)):
        toks = []
        for m in _TOKEN.finditer(text, pos):
            if toks and not re.fullmatch(r"[ \t]{1,3}", text[toks[-1][1]:m.start()]):
                break
            if not toks and m.start() != pos:
                break
            tok = m.group(0)
            if not tok.islower() or len(toks) == 3 or _key(tok) in _LOWER_FUNCTION:
                break
            if _status(tok, known) is None:
                # an unknown word after a known one ends the name only when
                # punctuation or the text end follows ("tom hargreaves (")
                tail = text[m.end():].lstrip(" \t")[:1]
                if not toks or tail.isalnum():
                    break
                toks.append((m.start(), m.end(), tok))
                break
            toks.append((m.start(), m.end(), tok))
        if toks:
            runs.append((toks[0][0], toks[-1][1], toks, "rule:names_cue"))
    return runs


def detect_names(text: str, *, confidence: float = 0.7) -> list[Detection]:
    """Find names in ``text``: one ``PII-1-NAME`` detection per name token.

    Every token of a name run (see :func:`_name_runs`) is reported, particles
    and initials included, so a redaction leaves no fragment; ``metadata
    ["span"]`` carries the whole run. Equivalence-group spellings also match
    case-insensitively, as before, unless the token is a place in context.
    """
    detections: list[Detection] = []
    taken: list[tuple[int, int]] = []
    for run_start, run_end, toks, detector in _name_runs(text):
        if any(s < run_end and run_start < e for s, e in taken):
            toks = [t for t in toks if not any(s < t[1] and t[0] < e for s, e in taken)]
        for start, end, token in toks:
            detections.append(Detection(
                id=f"det:name:{start}:{end}",
                category="PII-1-NAME",
                text=token,
                start=start,
                end=end,
                confidence=max(confidence, 0.8) if detector == "rule:names_title"
                else confidence,
                detector=detector,
                identity_class="inferred",
                metadata={"span": [run_start, run_end]},
            ))
            taken.append((start, end))
    blocked = _context_blocked(text)
    for d in _lexicon_detect(
        text,
        _get_pattern(),
        category="PII-1-NAME",
        detector_name="rule:names_lexicon",
        identity_class="inferred",
        confidence=confidence,
    ):
        if any(s < d.end and d.start < e for s, e in taken):
            continue
        if any(s <= d.start and d.end <= e for s, e in blocked):
            continue
        if _key(d.text) in _HARD or _key(d.text) in _WEAK:
            continue
        detections.append(d)
        taken.append((d.start, d.end))
    detections.sort(key=lambda d: d.start)
    return detections


def _context_blocked(text: str) -> list[tuple[int, int]]:
    """Capitalised stretches that are places or organisations by context."""
    out = []
    words = list(_TOKEN.finditer(text))
    for k, w in enumerate(words):
        key = _key(w.group(0))
        if key in _PLACE_SUFFIX and k > 0:
            j = k - 1
            while j >= 0 and words[j].group(0)[0].isupper() and _JOIN.fullmatch(
                    text[words[j].end():words[j + 1].start()]):
                j -= 1
            if j + 1 < k:
                out.append((words[j + 1].start(), words[k - 1].end()))
        if key in _PLACE_PREFIX and k + 1 < len(words) and _JOIN.fullmatch(
                text[w.end():words[k + 1].start()]):
            out.append((words[k + 1].start(), words[k + 1].end()))
    return out


__all__ = ["detect_names", "person_spans"]
