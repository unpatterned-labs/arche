# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Character n-gram TF-IDF: the baseline a learned retriever has to beat.

Character n-grams survive what word tokens do not: a dropped letter
(``Kalahaddi``/``Kalahadi``), a joined or split word (``Yan Amar``/``Yanamar``),
an apostrophe. No model, no training, deterministic, and fast enough to be the
default. Pure Python and numpy; no scikit-learn.
"""

from __future__ import annotations

import hashlib
import heapq
import math
import unicodedata
from collections import Counter
from collections.abc import Sequence
from typing import Any


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return " ".join("".join(ch if ch.isalnum() else " " for ch in text).split())


def char_ngrams(text: str, n: int = 3) -> Counter[str]:
    """Counted n-grams of each word, padded so word edges count (``#ka``)."""
    grams: Counter[str] = Counter()
    for word in _fold(text).split():
        padded = f"#{word}#"
        if len(padded) <= n:
            grams[padded] += 1
            continue
        for i in range(len(padded) - n + 1):
            grams[padded[i:i + n]] += 1
    return grams


class CharNgramIndex:
    """Sublinear TF-IDF over character n-grams, cosine-ranked.

    ``search`` touches only the gallery rows that share an n-gram with the
    query (an inverted index), so it scales with overlap, not gallery size.
    """

    def __init__(self, texts: Sequence[str], *, n: int = 3) -> None:
        self.n = n
        self._size = len(texts)
        docs = [char_ngrams(t, n) for t in texts]
        df: Counter[str] = Counter()
        for d in docs:
            df.update(d.keys())
        self._idf = {g: math.log((1 + self._size) / (1 + c)) + 1.0 for g, c in df.items()}
        self._postings: dict[str, list[tuple[int, float]]] = {}
        for row, d in enumerate(docs):
            vec = self._weights(d)
            for g, w in vec.items():
                self._postings.setdefault(g, []).append((row, w))
        digest = hashlib.sha256()
        for g in sorted(self._idf):
            digest.update(f"{g}\t{df[g]}\n".encode())
        self._vocab_digest = "sha256:" + digest.hexdigest()

    def _weights(self, grams: Counter[str]) -> dict[str, float]:
        vec = {g: (1.0 + math.log(c)) * self._idf.get(g, 0.0) for g, c in grams.items()}
        norm = math.sqrt(sum(w * w for w in vec.values()))
        return {g: w / norm for g, w in vec.items() if w} if norm else {}

    def __len__(self) -> int:
        return self._size

    def search(self, text: str, k: int = 10) -> list[tuple[int, float]]:
        """The ``k`` best rows as ``(row, cosine)``, best first; ties by row."""
        scores: dict[int, float] = {}
        for g, w in self._weights(char_ngrams(text, self.n)).items():
            for row, v in self._postings.get(g, ()):
                scores[row] = scores.get(row, 0.0) + w * v
        best = heapq.nsmallest(k, scores.items(), key=lambda kv: (-kv[1], kv[0]))
        return [(row, round(score, 6)) for row, score in best]

    def pins(self) -> dict[str, Any]:
        return {"retriever": "tfidf-char", "n": self.n, "rows": self._size,
                "vocabulary": self._vocab_digest}
