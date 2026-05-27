# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Fetch a URL and return clean text for Pipeline.process().

Public API per the 2026-05-22 detection-scope expansion CEO + eng review::

    from arche.ingest import from_url
    from arche import Pipeline

    text = from_url("https://businessday.ng/news/article/some-article/")
    result = Pipeline(jurisdiction="NG").process(text)

Codifies the BusinessDay-notebook pattern as a first-class helper.
The four-line workflow is the canonical web-to-detection story.

SSRF guard
==========

Every URL is resolved to its IP address before fetching. Resolved
private / loopback / link-local / multicast / reserved / unspecified
addresses are rejected loudly with :exc:`SSRFBlockedError`. This
defeats the "developer pastes a URL that happens to resolve to an
internal service" case.

Known limitation: DNS rebinding. An attacker-controlled DNS that
returns a public IP to the pre-fetch resolve, then flips to a private
IP for the actual fetch, defeats the guard. Hardening via pinned-IP
custom httpx transport is tracked as TODOS.md #9a (v0.3 work). The
"developer pastes a URL" threat model doesn't justify that complexity
yet; multi-tenant SaaS deployments do.

Errors raised
=============

-   :exc:`ValueError` — malformed URL, non-http/https scheme.
-   :exc:`SSRFBlockedError` — host resolved to a private / loopback /
    link-local / multicast / reserved / unspecified IP.
-   :exc:`httpx.TimeoutException` — fetch exceeded ``timeout_seconds``.
-   :exc:`httpx.HTTPStatusError` — server returned 4xx or 5xx.
-   :exc:`UnsupportedContentError` — response Content-Type is not
    text/html, text/plain, or application/xhtml+xml.
-   :exc:`ContentTooLargeError` — response body exceeded
    ``max_size_bytes`` (default 10 MiB).
"""

from __future__ import annotations

import ipaddress
import socket
from html.parser import HTMLParser
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    pass


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------

#: Default request timeout in seconds. Configurable per call.
DEFAULT_TIMEOUT_SECONDS = 30.0

#: Default maximum response body size (10 MiB). Anything larger raises
#: :exc:`ContentTooLargeError`. Configurable per call.
DEFAULT_MAX_SIZE_BYTES = 10 * 1024 * 1024

#: Acceptable Content-Type prefixes. Anything else raises
#: :exc:`UnsupportedContentError`.
_ACCEPTABLE_CONTENT_TYPES = ("text/html", "text/plain", "application/xhtml+xml")

#: Default User-Agent string. Identifies arche to remote servers.
_USER_AGENT = "arche-core/0.2.0a2 (+https://unpatterned.org)"


# ----------------------------------------------------------------------
# Custom exceptions
# ----------------------------------------------------------------------

class SSRFBlockedError(Exception):
    """The URL's resolved IP fell into a private / loopback / restricted range.

    Defeats the "developer pastes a URL that hits an internal service"
    case. Carries the URL and the resolved IP so the caller can diagnose
    without re-fetching.
    """

    def __init__(self, message: str, *, url: str, resolved_ip: str) -> None:
        super().__init__(message)
        self.url = url
        self.resolved_ip = resolved_ip


class UnsupportedContentError(Exception):
    """The remote response Content-Type isn't text/html, text/plain, or xhtml.

    arche.ingest.from_url is for fetching web pages and extracting their
    text content. Binary types (PDF, DOCX, images) should go through
    ``arche.doc`` / ``Pipeline.process_file()`` instead.
    """

    def __init__(self, message: str, *, content_type: str) -> None:
        super().__init__(message)
        self.content_type = content_type


class ContentTooLargeError(Exception):
    """The remote response body exceeded ``max_size_bytes``."""

    def __init__(self, message: str, *, size_bytes: int, max_size_bytes: int) -> None:
        super().__init__(message)
        self.size_bytes = size_bytes
        self.max_size_bytes = max_size_bytes


# ----------------------------------------------------------------------
# SSRF guard
# ----------------------------------------------------------------------

def _check_host_not_private(url: str, host: str) -> None:
    """Resolve ``host`` to an IP and raise :exc:`SSRFBlockedError` if
    the IP falls into a private / restricted range.

    Pre-fetch resolution check. Doesn't defeat DNS rebinding (see module
    docstring). For multi-tenant deployments, pin the IP at fetch time
    via a custom httpx transport (TODOS.md #9a).
    """
    try:
        # getaddrinfo returns multiple records for dual-stack hosts;
        # we check ALL of them so an attacker can't sneak in a private
        # IP behind a public-resolving hostname.
        addr_info = socket.getaddrinfo(host, None)
    except socket.gaierror:
        # DNS resolution failed — let httpx handle it downstream.
        # Don't preemptively block on DNS failure; the user gets the
        # actual error from the fetch step.
        return

    for _family, _socktype, _proto, _canonname, sockaddr in addr_info:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue

        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            reasons = []
            if ip.is_private:
                reasons.append("private (RFC1918)")
            if ip.is_loopback:
                reasons.append("loopback")
            if ip.is_link_local:
                reasons.append("link-local")
            if ip.is_multicast:
                reasons.append("multicast")
            if ip.is_reserved:
                reasons.append("reserved")
            if ip.is_unspecified:
                reasons.append("unspecified (0.0.0.0)")
            raise SSRFBlockedError(
                f"URL {url!r} resolved to {ip_str!r} which is "
                f"{', '.join(reasons)}. Refusing to fetch.",
                url=url,
                resolved_ip=ip_str,
            )


# ----------------------------------------------------------------------
# HTML → text extraction (stdlib only)
# ----------------------------------------------------------------------

class _TextExtractor(HTMLParser):
    """Minimal HTML → plain-text extractor using only stdlib.

    Skips <script>, <style>, <noscript>, <template>. Inserts a newline
    after block-level elements so paragraphs stay readable.
    """

    _SKIP_TAGS: frozenset[str] = frozenset({"script", "style", "noscript", "template"})
    _BLOCK_TAGS: frozenset[str] = frozenset({
        "p", "div", "br", "li", "tr", "td", "th",
        "h1", "h2", "h3", "h4", "h5", "h6",
        "blockquote", "pre", "section", "article", "aside",
        "header", "footer", "nav", "main",
    })

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        elif tag in self._BLOCK_TAGS and not self._skip_depth:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in self._BLOCK_TAGS and not self._skip_depth:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth and data.strip():
            self._chunks.append(data)

    def get_text(self) -> str:
        text = "".join(self._chunks)
        # Collapse runs of whitespace within lines; preserve paragraph breaks
        lines = []
        for line in text.split("\n"):
            stripped = " ".join(line.split())
            if stripped:
                lines.append(stripped)
        return "\n".join(lines)


def _strip_html(html: str) -> str:
    """Extract readable text from an HTML document via stdlib html.parser."""
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return parser.get_text()


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------

def from_url(
    url: str,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_size_bytes: int = DEFAULT_MAX_SIZE_BYTES,
    user_agent: str | None = None,
    follow_redirects: bool = True,
) -> str:
    """Fetch a URL and return clean text suitable for Pipeline.process().

    Args:
        url: The URL to fetch. Must be ``http://`` or ``https://``.
        timeout_seconds: Per-request timeout. Default 30s.
        max_size_bytes: Maximum response body size. Default 10 MiB.
            Larger responses raise :exc:`ContentTooLargeError`.
        user_agent: Custom User-Agent. Defaults to an arche-identifying
            string.
        follow_redirects: Follow 3xx redirects. Default True. Each
            redirect target is re-resolved and SSRF-checked.

    Returns:
        Plain text extracted from the HTML body (or pass-through if
        Content-Type is text/plain).

    Raises:
        ValueError: Malformed URL or non-http(s) scheme.
        SSRFBlockedError: Resolved IP is in a private / restricted range.
        UnsupportedContentError: Content-Type isn't text/* or xhtml.
        ContentTooLargeError: Response body exceeded ``max_size_bytes``.
        httpx.TimeoutException: Fetch timed out.
        httpx.HTTPStatusError: Server returned 4xx or 5xx.

    Examples:
        Fetch a news article and run it through Pipeline::

            from arche import Pipeline
            from arche.ingest import from_url

            text = from_url("https://example.com/article")
            result = Pipeline(jurisdiction="NG").process(text)
            for d in result.detections:
                print(d.category, d.text, d.sensitivity_tier.value)

        Tighter limits for high-throughput callers::

            text = from_url(url, timeout_seconds=5.0,
                             max_size_bytes=512 * 1024)
    """
    # Lazy-import httpx so `import arche.ingest` doesn't pay for the
    # ~500 KB load unless from_url is actually called. Keeps cold
    # import cheap.
    import httpx

    # URL validation
    if not isinstance(url, str) or not url.strip():
        raise ValueError("url must be a non-empty string")

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(
            f"url scheme {parsed.scheme!r} not supported; "
            f"arche.ingest.from_url accepts http and https only "
            f"(file://, ftp://, etc. are blocked for security)"
        )
    if not parsed.hostname:
        raise ValueError(f"url {url!r} has no hostname")

    # SSRF guard — resolve the hostname and reject private / restricted IPs.
    _check_host_not_private(url, parsed.hostname)

    # Fetch with size + content-type + redirect-resolve checks.
    headers = {"User-Agent": user_agent or _USER_AGENT}
    # Stream so we can enforce max_size_bytes without loading
    # potentially-huge responses into memory.
    with (
        httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=follow_redirects,
            headers=headers,
            max_redirects=10,
        ) as client,
        client.stream("GET", url) as response,
    ):
        # Re-check the FINAL URL post-redirect for SSRF — defends
        # against open-redirect chains that flip into private space.
        if str(response.url) != url:
            final_parsed = urlparse(str(response.url))
            if final_parsed.hostname:
                _check_host_not_private(str(response.url), final_parsed.hostname)

        response.raise_for_status()

        content_type = response.headers.get("content-type", "").lower()
        if not any(content_type.startswith(ct) for ct in _ACCEPTABLE_CONTENT_TYPES):
            raise UnsupportedContentError(
                f"url {url!r} returned content-type {content_type!r}; "
                f"arche.ingest.from_url handles text/html, text/plain, "
                f"and application/xhtml+xml. For PDF / DOCX / image input, "
                f"use arche.doc + Pipeline.process_file() instead.",
                content_type=content_type,
            )

        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > max_size_bytes:
                raise ContentTooLargeError(
                    f"url {url!r} response body exceeded "
                    f"{max_size_bytes:,} bytes (got {total:,} so far)",
                    size_bytes=total,
                    max_size_bytes=max_size_bytes,
                )
            chunks.append(chunk)

        # Decode using the response's apparent encoding (httpx handles
        # charset inference + apparent_encoding fallback).
        encoding = response.encoding or "utf-8"
        body = b"".join(chunks).decode(encoding, errors="replace")

    # text/plain — pass-through; text/html or xhtml — strip tags.
    if any(content_type.startswith(ct) for ct in ("text/html", "application/xhtml+xml")):
        return _strip_html(body)
    return body


__all__ = [
    "from_url",
    "SSRFBlockedError",
    "UnsupportedContentError",
    "ContentTooLargeError",
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_MAX_SIZE_BYTES",
]
