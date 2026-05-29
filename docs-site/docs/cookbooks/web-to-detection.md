# Cookbook — Web URL → Detection in four lines

You have a public article, blog post, or knowledge-base page. You want the
same Pan-African PII Taxonomy detections you would get from a local file —
names, locations, addresses, NINs, BVNs, phones, emails — without writing a
scraper.

`arche.ingest.from_url` is the canonical helper (new in **v0.2.0a2**):

```python
from arche import Pipeline
from arche.ingest import from_url

text = from_url("https://businessday.ng/news/article/some-article/")
result = Pipeline(jurisdiction="NG").process(text)

print(result.summary())
# {'PII-1-NAME': 2, 'PII-4-LOCATION': 3, 'PII-3-PHONE': 1, ...}
```

Four lines. No HTTP client setup. No HTML parser. No content-type juggling.

---

## What you get out of the box

`from_url` returns **clean text** that `Pipeline.process()` can chew on
directly. Under the hood it:

1. **Validates the URL** — rejects non-`http(s)` schemes and empty hostnames
   so a typo doesn't turn into `file:///etc/passwd`.
2. **Resolves the host and SSRF-guards it** — checks every IP returned by
   `socket.getaddrinfo` against `is_private`, `is_loopback`, `is_link_local`,
   `is_multicast`, `is_reserved`, and `is_unspecified`. Refuses to fetch
   if any range matches.
3. **Streams the response** with a 10 MiB cap (configurable) so a hostile
   server can't blow up your memory.
4. **Accepts only text content-types** — `text/html`, `text/plain`,
   `application/xhtml+xml`. Binary types (PDF / DOCX / images) raise
   [`UnsupportedContentError`](#error-types) — use `Pipeline.process_file`
   for those.
5. **Re-checks the resolved IP after redirects** so an open-redirect chain
   can't smuggle an internal host through.
6. **Strips HTML to plain text** using stdlib `html.parser` — skips
   `<script>`, `<style>`, `<noscript>`, `<template>`; preserves paragraph
   breaks for downstream sentence-boundary detection.

The full default pipeline detects:

- **Names** — 114 African name-equivalence groups (Yoruba, Igbo, Hausa,
  Akan, Amharic, Swahili, Bantu, Zulu, …) via `arche.detect.names`.
  Western and Eastern given names ride through the same lexicon when the
  YAML dataset is installed.
- **Locations** — 104 African cities + aliases via the bundled gazetteer
  in `arche.detect.locations`. Emits `PII-4-LOCATION` with country / region
  metadata.
- **Addresses** — multi-line street addresses via `arche.detect.addr`.
- **IDs & phones** — NIN, BVN, Ghana Card, Kenya Huduma, SA ID, plus
  libphonenumber-validated phone numbers per jurisdiction.
- **Digital identifiers** — Ethereum / Bitcoin wallet addresses, W3C
  DIDs, IPs.

---

## A 90-second BusinessDay walkthrough

A worked example using a real (public) Nigerian news article:

```python
from arche import Pipeline
from arche.ingest import from_url

URL = "https://businessday.ng/news/article/five-things-you-didnt-know-about-fatima-dangote/"

text = from_url(URL)
print(f"Fetched {len(text):,} characters of clean text")
# Fetched 4,217 characters of clean text

pipe = Pipeline(jurisdiction="NG")
result = pipe.process(text)

for det in result.detections[:6]:
    print(f"  {det.category:20s} {det.text!r:30s} "
          f"conf={det.confidence:.2f} via {det.detector}")
```

Sample output:

```
  PII-1-NAME           "Fatima Dangote"               conf=0.70 via rule:names_lexicon
  PII-1-NAME           "Aliko Dangote"                conf=0.70 via rule:names_lexicon
  PII-4-LOCATION       "Lagos"                        conf=0.90 via rule:locations_gazetteer
  PII-4-LOCATION       "Kano"                         conf=0.90 via rule:locations_gazetteer
  PII-4-LOCATION       "Nigeria"                      conf=0.90 via rule:locations_gazetteer
  PII-1-ORG            "Dangote Group"                conf=0.60 via gliner  (only with [detect])
```

The bare-install run finds names and locations. Organisations and
unstructured entities (job titles, dates, monetary values) come in
through the optional `[detect]` extra — see the [GLiNER NER cookbook
notebook](https://github.com/unpatterned-labs/archeblob/main/notebooks/cookbook-gliner-ner.ipynb)
for the upgrade path.

---

## Configuration knobs

```python
from arche.ingest import from_url

text = from_url(
    "https://example.com/large-page",
    timeout_seconds=15.0,         # default 30s
    max_size_bytes=2 * 1024 * 1024,  # default 10 MiB
    user_agent="my-app/1.0",      # default 'arche-core/0.2.0a2 (+https://unpatterned.ai)'
    follow_redirects=True,        # default True; redirect host is SSRF-rechecked
)
```

All keyword-only — positional argument is the URL.

---

## Error types

`from_url` raises specific, structured exceptions so you can branch on
intent rather than message-matching:

| Exception | When | Carries |
|---|---|---|
| `ValueError` | URL is empty, missing hostname, or non-http(s) scheme | — |
| `SSRFBlockedError` | resolved IP is private / loopback / link-local / multicast / reserved / unspecified | `.url`, `.resolved_ip` |
| `UnsupportedContentError` | response Content-Type isn't `text/html`, `text/plain`, or `application/xhtml+xml` | `.content_type` |
| `ContentTooLargeError` | response body exceeded `max_size_bytes` | `.size_bytes`, `.max_size_bytes` |
| `httpx.TimeoutException` | fetch exceeded `timeout_seconds` | (from httpx) |
| `httpx.HTTPStatusError` | server returned 4xx or 5xx | (from httpx) |

```python
from arche.ingest import from_url, SSRFBlockedError, UnsupportedContentError

try:
    text = from_url(user_supplied_url)
except SSRFBlockedError as exc:
    log.warning("blocked internal URL %s (resolved %s)", exc.url, exc.resolved_ip)
    return abort(400, "internal URLs aren't allowed")
except UnsupportedContentError as exc:
    log.info("not a web page: %s", exc.content_type)
    return abort(415, "URL didn't return a text/html response")
```

---

## What it does not do (yet)

- **No JavaScript execution.** If the page hides content behind a JS
  framework that only fills the DOM client-side, `from_url` will return
  the empty shell. For JS-heavy pages, run a browser-based fetch (Playwright
  / Puppeteer) and feed the rendered HTML to `Pipeline.process(text)`
  directly.
- **No authentication.** No cookie jar, no header injection, no OAuth.
  For authenticated fetches, drive `httpx.Client` yourself and pass the
  body text into `Pipeline.process`.
- **No DNS-rebinding hardening.** The SSRF guard resolves once before
  the fetch. A hostile DNS that returns a public IP to the pre-fetch
  resolve and a private IP at fetch time defeats it. The "developer
  pastes a URL into a script" threat model doesn't justify the
  complexity of pinned-IP transports today. Multi-tenant SaaS deployments
  on the other hand should; tracked as `TODOS.md` #9a for v0.3.
- **No HTML→Markdown.** Output is plain text with paragraph breaks, not
  Markdown. If you want Markdown for downstream LLM ingestion, run
  `docling` or `trafilatura` instead and feed the result into
  `Pipeline.process`.

---

## When to reach for something else

| You want… | Reach for… |
|---|---|
| PDF, DOCX, PPTX, scanned image | `Pipeline.process_file(path)` (uses `arche-core[doc]`) |
| Bulk web crawl across thousands of URLs | A real crawler (e.g. `scrapy`, `crawlee`) — call `from_url` per page or feed normalized text into `Pipeline.process` in batch |
| Authenticated APIs returning JSON | Parse the JSON, hand the textual fields to `Pipeline.process` directly |
| Heavy SPA / JS-rendered content | Playwright / Puppeteer → pass rendered HTML to `Pipeline.process` |
| Embedded YouTube / SoundCloud / podcasts | Out of scope — transcribe first, then `Pipeline.process(transcript)` |

`from_url` exists for the **most common case**: a developer or analyst
has a public web page and wants the same identity-resolution surface
they get from a local file, without writing a scraper or worrying about
SSRF.

---

## See also

- [GLiNER NER cookbook (notebook)](https://github.com/unpatterned-labs/archeblob/main/notebooks/cookbook-gliner-ner.ipynb) — when (and how) to enable the `[detect]` extra
- [How-to: Extract from invoice](../how-to/extract-from-invoice.md) — the local-file equivalent
- [How-to: Match African names](../how-to/match-african-names.md) — name-equivalence deep dive
- [Pipeline API reference](../api/resolve.md)
