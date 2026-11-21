# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""URLs (``PII-8-URL``), each flagged for whether it points at a person.

HIPAA Safe Harbor removes every URL (45 CFR §164.514(b)(2)(i)(N)). Under GDPR,
UK GDPR, POPIA and NDPA a URL is personal data only when it identifies someone:
``linkedin.com/in/folasade-adebayo`` does, ``https://www.gov.uk/tax`` does not.
This detector emits every URL and leaves the action to the statute pack, with
``metadata["has_name_or_id_path"]`` saying whether the URL carries a person:

* a path segment under a person-shaped parent (``/in/``, ``/users/``,
  ``/patients/``, ``/staff/``, ``/profile/``, ``/~name``, ``/@handle``), or
* the first path segment on a profile host (LinkedIn, GitHub, X/Twitter,
  Facebook, Instagram, TikTok, GitLab, Medium), or
* a query parameter naming a person or record (``name``, ``email``,
  ``patient_id``, ``mrn``, ``user_id``, ``dob``...).

``metadata["reason"]`` says which, and ``metadata["patient_path"]`` is True for
a ``/patient(s)/`` path. Matched: ``http(s)://`` and ``www.`` URLs, and bare
``host.tld/path`` (a path is required, so a company name like ``example.com``
in prose is not a URL detection, and an email's domain never is).
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl

from arche.workflow._primitive import Detection

_TLDS = (
    "com|org|net|io|co|me|info|biz|edu|gov|app|dev|ai|health|"
    "ng|za|ke|gh|ug|tz|rw|et|eg|ma|sn|ci|cm|zw|zm|bw|na|mw|"
    "uk|us|ca|au|nz|ie|de|fr|nl|be|es|it|pt|in"
)
_URL = re.compile(
    r"(?i)(?:\bhttps?://|\bwww\.)[^\s<>\"'`]+"
    r"|(?<![@\w.\-/])(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?:" + _TLDS + r")\b"
    r"/[^\s<>\"'`]*"
)
_TRAILING = ".,;:!?)]}'\""

_PERSON_PARENTS = frozenset({
    "in", "pub", "profile", "profiles", "user", "users", "u", "people", "person", "persons",
    "staff", "team", "member", "members", "patient", "patients", "client", "clients",
    "employee", "employees", "author", "authors", "student", "students", "customer",
    "customers", "account", "accounts", "contact", "contacts", "directory",
})
_PROFILE_HOSTS = re.compile(
    r"(?i)(?:^|\.)(?:linkedin\.com|github\.com|gitlab\.com|twitter\.com|x\.com|facebook\.com|"
    r"fb\.com|instagram\.com|tiktok\.com|medium\.com|threads\.net)$"
)
#: first path segments on a profile host that are site pages, not people
_SITE_PAGES = frozenset({
    "about", "login", "signup", "join", "search", "explore", "settings", "help", "jobs",
    "company", "school", "groups", "pages", "events", "home", "features", "pricing",
    "topics", "trending", "marketplace", "orgs", "sponsors", "policies", "legal", "privacy",
    "terms", "watch", "hashtag", "share", "intent", "i", "notifications", "messages",
})
_PERSON_QUERY_KEYS = re.compile(
    r"(?i)^(?:name|full_?name|first_?name|last_?name|surname|email|e-?mail|phone|dob|ssn|"
    r"mrn|patient(?:_?id)?|user(?:_?id|name)?|uid|member(?:_?id)?|customer(?:_?id)?|"
    r"client(?:_?id)?|account(?:_?id)?|nin|bvn)$"
)


def _split(url: str) -> tuple[str, list[str], str]:
    """``(host, path segments, query)`` of a URL with or without a scheme."""
    rest = re.sub(r"(?i)^https?://", "", url)
    rest = rest.split("#", 1)[0]
    rest, _, query = rest.partition("?")
    host, _, path = rest.partition("/")
    host = host.split("@")[-1].split(":")[0].lower()
    return host, [s for s in path.split("/") if s], query


def person_signal(url: str) -> str | None:
    """Why ``url`` points at a person, or ``None``."""
    host, segments, query = _split(url)
    for i, seg in enumerate(segments):
        if seg.startswith(("~", "@")) and len(seg) > 2:
            return "handle_segment"
        if seg.lower() in _PERSON_PARENTS and i + 1 < len(segments):
            return f"person_path:/{seg.lower()}/"
    if _PROFILE_HOSTS.search(host) and segments and segments[0].lower() not in _SITE_PAGES:
        return "profile_host"
    for key, value in parse_qsl(query, keep_blank_values=False):
        if value and _PERSON_QUERY_KEYS.match(key):
            return f"query:{key.lower()}"
    return None


def detect_urls(text: str) -> list[Detection]:
    """Every URL in ``text``: ``PII-8-URL`` when it names or identifies a person
    (``has_name_or_id_path``), ``PII-8-URL_OTHER`` otherwise.

    Two categories rather than one plus a flag, so each statute pack states
    its own choice: HIPAA Safe Harbor removes every URL; GDPR-style packs keep
    a URL that identifies no one (Art 4(1)) and would otherwise mask every link
    under their default.
    """
    out: list[Detection] = []
    for m in _URL.finditer(text):
        url = m.group(0).rstrip(_TRAILING)
        if url.count("(") < m.group(0).count(")") and url.endswith(")"):
            url = url[:-1]
        if len(url) < 6 or url.lower().rstrip("/") in ("http:", "https:", "www"):
            continue
        start, end = m.start(), m.start() + len(url)
        reason = person_signal(url)
        segments = _split(url)[1]
        out.append(Detection(
            id=f"det:url:{start}:{end}",
            category="PII-8-URL" if reason else "PII-8-URL_OTHER",
            text=url,
            start=start,
            end=end,
            confidence=0.95 if reason else 0.9,
            detector="rule:url",
            identity_class="inferred",
            metadata={
                "kind": "url",
                "has_name_or_id_path": reason is not None,
                "reason": reason,
                "patient_path": any(s.lower() in ("patient", "patients") for s in segments),
            },
        ))
    return out


__all__ = ["detect_urls", "person_signal"]
