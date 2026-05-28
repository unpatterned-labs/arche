# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for arche.ingest.from_url.

Covers happy path + every SSRF-blocked range + content-type rejection
+ size limits + redirect SSRF re-check + the html.parser text
extractor.

httpx is mocked end-to-end via httpx.MockTransport — no live network
calls in CI. The SSRF resolver is monkey-patched per-test so we can
assert the guard fires on private IPs without DNS dependencies.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterator
from unittest.mock import patch

import httpx
import pytest
from arche.ingest import (
    ContentTooLargeError,
    SSRFBlockedError,
    UnsupportedContentError,
    from_url,
)
from arche.ingest.from_url import _strip_html

# ----------------------------------------------------------------------
# HTML extraction helper
# ----------------------------------------------------------------------


def test_strip_html_extracts_paragraph_text() -> None:
    html = "<html><body><p>Hello world</p><p>Second paragraph</p></body></html>"
    text = _strip_html(html)
    assert "Hello world" in text
    assert "Second paragraph" in text


def test_strip_html_skips_script_tag() -> None:
    html = """
    <html><body>
        <script>alert('evil')</script>
        <p>Real text</p>
    </body></html>
    """
    text = _strip_html(html)
    assert "Real text" in text
    assert "alert" not in text
    assert "evil" not in text


def test_strip_html_skips_style_tag() -> None:
    html = """
    <html><head><style>body { color: red; }</style></head>
    <body><p>Visible content</p></body></html>
    """
    text = _strip_html(html)
    assert "Visible content" in text
    assert "color: red" not in text


def test_strip_html_collapses_whitespace() -> None:
    html = "<p>Multiple    spaces    here</p>"
    assert "Multiple spaces here" in _strip_html(html)


def test_strip_html_preserves_paragraph_breaks() -> None:
    html = "<p>Paragraph one.</p><p>Paragraph two.</p>"
    text = _strip_html(html)
    lines = text.split("\n")
    assert any("Paragraph one" in line for line in lines)
    assert any("Paragraph two" in line for line in lines)


def test_strip_html_handles_nested_tags() -> None:
    html = "<div><p><strong>Bold</strong> and <em>italic</em>.</p></div>"
    text = _strip_html(html)
    assert "Bold" in text
    assert "italic" in text


# ----------------------------------------------------------------------
# URL validation
# ----------------------------------------------------------------------


def test_from_url_rejects_empty_string() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        from_url("")


def test_from_url_rejects_non_http_scheme() -> None:
    with pytest.raises(ValueError, match="not supported"):
        from_url("file:///etc/passwd")


def test_from_url_rejects_ftp_scheme() -> None:
    with pytest.raises(ValueError, match="not supported"):
        from_url("ftp://example.com/file")


def test_from_url_rejects_url_without_hostname() -> None:
    with pytest.raises(ValueError, match="hostname"):
        from_url("http://")


# ----------------------------------------------------------------------
# SSRF guard — each private/restricted range
# ----------------------------------------------------------------------


def _patch_dns(ip: str) -> Callable[[], None]:
    """Monkey-patch socket.getaddrinfo to resolve any host to `ip`."""
    return patch(
        "arche.ingest.from_url.socket.getaddrinfo",
        return_value=[(0, 0, 0, "", (ip, 0))],
    )


def test_from_url_blocks_rfc1918_192_168() -> None:
    with _patch_dns("192.168.1.1"), pytest.raises(SSRFBlockedError) as exc_info:
        from_url("http://attacker-internal.example/")
    assert exc_info.value.resolved_ip == "192.168.1.1"
    assert "private" in str(exc_info.value).lower()


def test_from_url_blocks_rfc1918_10() -> None:
    with _patch_dns("10.0.0.1"), pytest.raises(SSRFBlockedError):
        from_url("http://attacker-internal.example/")


def test_from_url_blocks_rfc1918_172_16() -> None:
    with _patch_dns("172.16.0.1"), pytest.raises(SSRFBlockedError):
        from_url("http://attacker-internal.example/")


def test_from_url_blocks_loopback_v4() -> None:
    with _patch_dns("127.0.0.1"), pytest.raises(SSRFBlockedError) as exc_info:
        from_url("http://localhost.example/")
    assert "loopback" in str(exc_info.value).lower()


def test_from_url_blocks_loopback_v6() -> None:
    with _patch_dns("::1"), pytest.raises(SSRFBlockedError):
        from_url("http://ipv6-localhost.example/")


def test_from_url_blocks_link_local() -> None:
    with _patch_dns("169.254.169.254"), pytest.raises(SSRFBlockedError) as exc_info:
        from_url("http://cloud-metadata.example/")
    assert "link-local" in str(exc_info.value).lower()


def test_from_url_blocks_unspecified() -> None:
    with _patch_dns("0.0.0.0"), pytest.raises(SSRFBlockedError) as exc_info:
        from_url("http://zero.example/")
    assert "unspecified" in str(exc_info.value).lower()


def test_from_url_blocks_multicast() -> None:
    with _patch_dns("224.0.0.1"), pytest.raises(SSRFBlockedError) as exc_info:
        from_url("http://mcast.example/")
    assert "multicast" in str(exc_info.value).lower()


def test_ssrf_blocked_error_carries_url_and_ip() -> None:
    """SSRFBlockedError exposes structured fields for caller logging."""
    with _patch_dns("10.0.0.1"):
        try:
            from_url("http://internal.example/path")
        except SSRFBlockedError as exc:
            assert exc.url == "http://internal.example/path"
            assert exc.resolved_ip == "10.0.0.1"


# ----------------------------------------------------------------------
# Happy path + content fetching (via httpx.MockTransport)
# ----------------------------------------------------------------------


def _public_dns():
    """Patch socket.getaddrinfo to return a public IP (8.8.8.8)."""
    return patch(
        "arche.ingest.from_url.socket.getaddrinfo",
        return_value=[(0, 0, 0, "", ("8.8.8.8", 0))],
    )


@contextlib.contextmanager
def _patched_httpx_client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> Iterator[None]:
    """Patch httpx.Client so calls inside from_url use a MockTransport.

    The trick: we capture the ORIGINAL __init__ before patching it, so
    the patched version calls into the unmodified original (not into
    itself, which would recurse infinitely).
    """
    original_init = httpx.Client.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *args, **kwargs)

    httpx.Client.__init__ = patched_init
    try:
        yield
    finally:
        httpx.Client.__init__ = original_init


def test_from_url_happy_path_html() -> None:
    """HTML response is stripped to plain text."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="<html><body><p>Customer Adesola at Lagos.</p></body></html>",
        )

    with _public_dns(), _patched_httpx_client(handler):
        text = from_url("http://example.com/article")
    assert "Customer Adesola at Lagos" in text


def test_from_url_happy_path_text_plain_passthrough() -> None:
    """text/plain is returned as-is, no HTML stripping."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            text="NIN 12345678901 in Lagos",
        )

    with _public_dns(), _patched_httpx_client(handler):
        text = from_url("http://example.com/plain.txt")
    assert text == "NIN 12345678901 in Lagos"


def test_from_url_rejects_image_content_type() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "image/png"},
            content=b"\x89PNG\r\n\x1a\n",
        )

    with (
        _public_dns(),
        _patched_httpx_client(handler),
        pytest.raises(UnsupportedContentError) as exc_info,
    ):
        from_url("http://example.com/img.png")
    assert exc_info.value.content_type.startswith("image/")


def test_from_url_rejects_pdf_content_type() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=b"%PDF-1.4",
        )

    with _public_dns(), _patched_httpx_client(handler), pytest.raises(UnsupportedContentError):
        from_url("http://example.com/doc.pdf")


def test_from_url_rejects_oversized_response() -> None:
    """Response body >max_size_bytes raises ContentTooLargeError."""
    big_payload = "x" * 5_000  # 5KB
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=big_payload,
        )

    with (
        _public_dns(),
        _patched_httpx_client(handler),
        pytest.raises(ContentTooLargeError) as exc_info,
    ):
        from_url("http://example.com/big.html", max_size_bytes=1024)
    assert exc_info.value.max_size_bytes == 1024
    assert exc_info.value.size_bytes > 1024


def test_from_url_raises_on_4xx() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            headers={"content-type": "text/html"},
            text="<html>Not found</html>",
        )

    with _public_dns(), _patched_httpx_client(handler), pytest.raises(httpx.HTTPStatusError):
        from_url("http://example.com/missing")


def test_from_url_raises_on_5xx() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            headers={"content-type": "text/html"},
            text="<html>Internal error</html>",
        )

    with _public_dns(), _patched_httpx_client(handler), pytest.raises(httpx.HTTPStatusError):
        from_url("http://example.com/broken")


def test_from_url_sends_user_agent() -> None:
    """Default User-Agent identifies arche to remote servers."""
    seen_ua: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_ua.append(request.headers.get("user-agent", ""))
        return httpx.Response(
            200, headers={"content-type": "text/html"}, text="<p>ok</p>",
        )

    with _public_dns(), _patched_httpx_client(handler):
        from_url("http://example.com/")
    assert any("arche-core" in ua for ua in seen_ua)


def test_from_url_custom_user_agent() -> None:
    seen_ua: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_ua.append(request.headers.get("user-agent", ""))
        return httpx.Response(
            200, headers={"content-type": "text/html"}, text="<p>ok</p>",
        )

    with _public_dns(), _patched_httpx_client(handler):
        from_url("http://example.com/", user_agent="custom-fetcher/1.0")
    assert "custom-fetcher/1.0" in seen_ua


# ----------------------------------------------------------------------
# Integration with Pipeline (end-to-end)
# ----------------------------------------------------------------------


def test_from_url_to_pipeline_end_to_end() -> None:
    """The documented 4-line pattern: from_url → Pipeline.process → detections."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=(
                "<html><body>"
                "<h1>Customer profile</h1>"
                "<p>Customer Fatima registered with NIN 12345678901 in Lagos.</p>"
                "<p>Phone +234 803 555 7890.</p>"
                "</body></html>"
            ),
        )

    from arche import Pipeline

    with _public_dns(), _patched_httpx_client(handler):
        text = from_url("http://example.com/profile")

    result = Pipeline(jurisdiction="NG").process(text)
    categories = {d.category for d in result.detections}
    assert "PII-2-NIN" in categories
    assert "PII-1-NAME" in categories
    assert "PII-4-LOCATION" in categories


# ----------------------------------------------------------------------
# Backward compatibility — extract_text shim has been removed
# ----------------------------------------------------------------------


def test_extract_text_shim_removed() -> None:
    """The v0.1 ``arche.ingest.extract_text`` deprecation shim is gone.

    ``extract_text`` now lives only at ``arche.workflow._ingest`` (and stays
    available top-level via ``from arche import extract_text``). Importing it
    from the old ``arche.ingest`` location raises ImportError."""
    with pytest.raises(ImportError):
        from arche.ingest import extract_text  # noqa: F401

    # The real home still works.
    from arche.workflow._ingest import extract_text as real_extract_text
    assert callable(real_extract_text)


def test_arche_ingest_import_does_not_warn() -> None:
    """Bare `import arche.ingest` does NOT emit a deprecation warning.

    Before this change, the old shim file emitted on every import,
    breaking the user-visible contract for the new from_url function.
    """
    import importlib
    import sys
    import warnings

    # Clear caches so this is a true re-import.
    for mod in list(sys.modules):
        if mod.startswith("arche.ingest"):
            del sys.modules[mod]

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        importlib.import_module("arche.ingest")
    deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert not deprecations, (
        f"Bare `import arche.ingest` emitted DeprecationWarning(s): "
        f"{[str(w.message) for w in deprecations]}"
    )


def test_arche_ingest_unknown_attr_raises_attribute_error() -> None:
    """Accessing a nonexistent attribute raises AttributeError, not a
    confusing fallback path."""
    import arche.ingest

    with pytest.raises(AttributeError, match="no attribute 'nonexistent_xyz'"):
        _ = arche.ingest.nonexistent_xyz
