# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""arche.ingest — input ingestion helpers.

Ships one public capability:

- :func:`from_url` (NEW in v0.2.0a2) — fetch a URL and return clean
  text suitable for ``Pipeline.process()``. SSRF-guarded so a
  developer pasting a URL can't accidentally hit internal services.

The v0.1 ``extract_text`` carryover used to be reachable here via a
lazy deprecation shim; that shim was removed. Import file-to-text
directly from its real home: :func:`arche.workflow._ingest.extract_text`.
"""

from __future__ import annotations

from arche.ingest.from_url import (
    ContentTooLargeError,
    SSRFBlockedError,
    UnsupportedContentError,
    from_url,
)

__all__ = [
    "from_url",
    "SSRFBlockedError",
    "UnsupportedContentError",
    "ContentTooLargeError",
]
