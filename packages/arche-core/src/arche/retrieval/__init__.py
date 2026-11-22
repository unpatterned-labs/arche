# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Retrieval: which records are worth comparing at all.

A blocker answers "which pairs should the comparators score?" A bad one loses a
true pair before any rule sees it, and nothing downstream can recover it. This
package holds the retrievers arche can put in front of
:func:`arche.resolve.reconcile`, each with the same contract:

* ``search(text, k)`` returns the ``k`` nearest gallery rows, best first;
* ``pins()`` names everything that can change which rows come back (the n-gram
  rule and vocabulary digest, or the model and its weights digest), so a
  decision made from a retrieved pair says which retriever proposed it.

Retrieval only *proposes*. A cosine never enters a score: the comparators and
the gate decide, exactly as for any other blocker.

:class:`CharNgramIndex`  character n-gram TF-IDF, pure Python and numpy. The
                         classical baseline any learned retriever must beat.
:class:`TextEncoder`     a Hugging Face encoder, mean-pooled and normalised,
                         its weights digested (``arche-core[detect2]`` brings
                         ``transformers``; nothing new to install).
:class:`EncoderIndex`    exact nearest neighbours over a :class:`TextEncoder`.
:class:`IndexedReference` any of the above over a record list, as an
                         :class:`arche.references.Reference` for
                         :func:`arche.references.link`.
:func:`record_text`      the text a record is retrieved by:
                         ``name | type | admin2 | admin1``.
"""

from __future__ import annotations

from arche.retrieval._encoder import EncoderIndex, TextEncoder, weights_digest
from arche.retrieval._reference import IndexedReference
from arche.retrieval._text import record_text
from arche.retrieval._tfidf import CharNgramIndex

__all__ = ["CharNgramIndex", "EncoderIndex", "IndexedReference", "TextEncoder",
           "record_text", "weights_digest"]
