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
    # function and frequent words
    "the", "and", "for", "from", "with", "this", "that", "these", "those", "then",
    "there", "their", "they", "them", "when", "where", "which", "while", "what",
    "who", "whom", "why", "how", "all", "any", "some", "one", "two", "our", "your",
    "his", "her", "its", "was", "were", "are", "have", "has", "had", "will", "would",
    "can", "could", "may", "might", "must", "shall", "should", "not", "yes", "new",
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
    "alhaji", "engr", "barr",
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
    """Normalised name tokens: equivalence groups plus the shipped lexicon."""
    global _KNOWN
    if _KNOWN is None:
        with _LOCK:
            if _KNOWN is None:
                from arche.detect._names.lexicon import KNOWN_AFRICAN_NAMES

                _KNOWN = frozenset(
                    token for token in KNOWN_AFRICAN_NAMES
                    if len(token) >= _MIN_LEXICON_TERM_LEN and token not in _STOP
                )
    return _KNOWN


def _normalise(token: str) -> str:
    from arche.detect._names.lexicon import _strip_diacritics

    return _strip_diacritics(token).lower()


def _name_tokens(text: str) -> list[tuple[int, int, str]]:
    """Capitalised tokens of ``text`` that the lexicon knows, in offset order."""
    known = _known()
    out: list[tuple[int, int, str]] = []
    for match in _TOKEN.finditer(text):
        token = match.group(0)
        if not token[0].isupper() or len(token) < _MIN_LEXICON_TERM_LEN:
            continue
        if _normalise(token) in known:
            out.append((match.start(), match.end(), token))
    return out


def person_spans(text: str) -> list[tuple[int, int, str]]:
    """Runs of two or more adjacent name tokens, each as one ``(start, end, text)``.

    Adjacent means separated only by whitespace, optionally with an initial
    (``E.``) in between. A single known token on its own is not returned:
    one capitalised word that happens to be in a name lexicon is not evidence
    of a person, and the extractors that call this build records from it.
    """
    tokens = _name_tokens(text)
    spans: list[tuple[int, int, str]] = []
    i = 0
    while i < len(tokens):
        start, end, _ = tokens[i]
        count = 1
        j = i + 1
        while j < len(tokens):
            gap = text[end:tokens[j][0]]
            if gap.strip() == "" and gap:
                end = tokens[j][1]
                count += 1
                j += 1
                continue
            # allow exactly one initial between two name tokens
            between = gap.strip()
            if _INITIAL.match(between) and gap[:1].isspace() and gap[-1:].isspace():
                end = tokens[j][1]
                count += 1
                j += 1
                continue
            break
        if count >= 2:
            spans.append((start, end, text[start:end]))
        i = j
    return spans


def detect_names(text: str, *, confidence: float = 0.7) -> list[Detection]:
    """Find African names in ``text``: one ``PII-1-NAME`` detection per name token.

    Equivalence-group spellings match case-insensitively; lexicon names match
    only when capitalised in the text. Overlaps are resolved in favour of the
    group match, which is the older and better-curated source.
    """
    detections = _lexicon_detect(
        text,
        _get_pattern(),
        category="PII-1-NAME",
        detector_name="rule:names_lexicon",
        identity_class="inferred",
        confidence=confidence,
    )
    taken = [(d.start, d.end) for d in detections]
    for start, end, token in _name_tokens(text):
        if any(s < end and start < e for s, e in taken):
            continue
        detections.append(Detection(
            id=f"det:name:{start}:{end}",
            category="PII-1-NAME",
            text=token,
            start=start,
            end=end,
            confidence=confidence,
            detector="rule:names_lexicon",
            identity_class="inferred",
            metadata={},
        ))
    detections.sort(key=lambda d: d.start)
    return detections


__all__ = ["detect_names", "person_spans"]
