# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Time expressions in text: what they say, and what date or time they mean.

``extract_times(text, anchor=...)`` finds each expression ("tomorrow by 4pm",
"two weeks from today", "Monday to Friday 8-5", "kesho saa mbili asubuhi") and
returns a :class:`TimeMention`: its words, its type, a TIMEX3-style value and,
when it can be worked out, the interval it covers (``start`` inclusive,
``end`` exclusive).

Three rules hold throughout:

* **No anchor, no date.** "Tomorrow" is resolved only against an anchor the
  caller gives (when the text was written). Without one it is returned as an
  offset (``offset={"days": 1}``), never as a guess about today.
* **Ambiguity is said, not hidden.** "by 6" (morning or evening), "3/12" (March
  or December), "next Friday" (this coming one or the one after) come back with
  ``ambiguous=True`` and every reading in ``alternatives``; ``start``/``end``
  hold the first, which is the more common reading.
* **The words decide.** Each mention carries the cue that set it (``cue``), so
  a reading can be checked against the text.

Swahili time is read as Swahili speakers read it: the day starts at sunrise,
so ``saa mbili asubuhi`` is 08:00, not 02:00, and ``saa nne usiku`` is 22:00.
Nigerian ``next tomorrow`` is the day after tomorrow. Yoruba and Hausa day
words are read with their tone marks, or without them when ``language`` says
the text is Yoruba (``yo``) or Hausa (``ha``): bare ``Ola`` is also a name.
"""

from arche.time._extract import TimeMention, extract_times

__all__ = ["TimeMention", "extract_times"]
