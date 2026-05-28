"""Wikidata ingestion for name evidence."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .constants import (
    DEFAULT_SOURCE_LICENSE,
    DEFAULT_USER_AGENT,
    DEFAULT_WIKIDATA_ENDPOINT,
    NAME_TYPE_TO_PROPERTY,
    WIKIDATA_LANGUAGE_TAGS,
)

NAME_TYPE_TO_ENTITY_ROOT = {
    "given": "Q202444",  # given name (covers first-name subclasses via P279*)
    "family": "Q101352",  # family name
}


def build_query(
    *,
    country_qid: str,
    name_type: str,
    limit: int,
    offset: int,
    language_tags: tuple[str, ...] = WIKIDATA_LANGUAGE_TAGS,
) -> str:
    """Build a country-scoped Wikidata SPARQL query for person names."""
    property_id = NAME_TYPE_TO_PROPERTY[name_type]
    lang_in = ", ".join(f'"{tag}"' for tag in language_tags)
    return f"""
SELECT DISTINCT
  ?nameEntity
  ?nameEntityLabel
  ?country
  ?countryLabel
  ?nativeLanguage
  ?nativeLanguageLabel
  ?alias
WHERE {{
  ?person wdt:P31 wd:Q5 ;
          wdt:P27 wd:{country_qid} ;
          wdt:{property_id} ?nameEntity .

  OPTIONAL {{ ?person wdt:P103 ?nativeLanguage . }}

  OPTIONAL {{
    ?nameEntity skos:altLabel ?alias .
    FILTER(LANG(?alias) IN ({lang_in}))
  }}

  SERVICE wikibase:label {{
    bd:serviceParam wikibase:language "[AUTO_LANGUAGE],en,fr,pt,ar" .
  }}
}}
LIMIT {limit}
OFFSET {offset}
""".strip()


def build_entity_query(
    *,
    country_qid: str,
    name_type: str,
    limit: int,
    offset: int,
    language_tags: tuple[str, ...] = WIKIDATA_LANGUAGE_TAGS,
) -> str:
    """Build a country-scoped query from name entities directly."""
    class_root_qid = NAME_TYPE_TO_ENTITY_ROOT[name_type]
    lang_in = ", ".join(f'"{tag}"' for tag in language_tags)
    return f"""
SELECT DISTINCT
  ?nameEntity
  ?nameEntityLabel
  ?country
  ?countryLabel
  ?nativeLanguage
  ?nativeLanguageLabel
  ?alias
WHERE {{
  ?nameEntity wdt:P31/wdt:P279* wd:{class_root_qid} .
  VALUES ?country {{ wd:{country_qid} }}

  {{
    ?nameEntity wdt:P17 ?country .
  }}
  UNION
  {{
    ?nameEntity wdt:P495 ?country .
  }}

  OPTIONAL {{ ?nameEntity wdt:P407 ?nativeLanguage . }}

  OPTIONAL {{
    ?nameEntity skos:altLabel ?alias .
    FILTER(LANG(?alias) IN ({lang_in}))
  }}

  SERVICE wikibase:label {{
    bd:serviceParam wikibase:language "[AUTO_LANGUAGE],en,fr,pt,ar" .
  }}
}}
LIMIT {limit}
OFFSET {offset}
""".strip()


def fetch_wikidata_rows(
    countries: dict[str, str],
    *,
    endpoint: str = DEFAULT_WIKIDATA_ENDPOINT,
    page_limit: int = 5000,
    max_pages: int = 6,
    retries: int = 4,
    pause_seconds: float = 0.25,
    include_direct_name_entities: bool = True,
    progress_callback: Callable[[str], None] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch raw name evidence rows from Wikidata for both name types."""
    rows: list[dict[str, Any]] = []
    query_hashes: list[str] = []
    total_requests = 0
    failed_requests = 0
    rows_by_mode: dict[str, int] = {"person": 0, "entity": 0}
    _emit(
        progress_callback,
        (
            "Starting Wikidata fetch: "
            f"countries={len(countries)}, page_limit={page_limit}, max_pages={max_pages}, "
            f"modes={'person+entity' if include_direct_name_entities else 'person'}"
        ),
    )

    for country_iso2, qid in countries.items():
        for name_type in ("given", "family"):
            query_modes = [("person", build_query)]
            if include_direct_name_entities:
                query_modes.append(("entity", build_entity_query))

            for mode_name, query_builder in query_modes:
                for page in range(max_pages):
                    offset = page * page_limit
                    query_label = (
                        f"country={country_iso2} type={name_type} mode={mode_name} "
                        f"page={page + 1}/{max_pages} offset={offset}"
                    )
                    _emit(progress_callback, f"Querying {query_label}")
                    query = query_builder(
                        country_qid=qid,
                        name_type=name_type,
                        limit=page_limit,
                        offset=offset,
                    )
                    query_hashes.append(hashlib.sha256(query.encode("utf-8")).hexdigest())
                    bindings = _run_query_with_retry(
                        endpoint=endpoint,
                        query=query,
                        retries=retries,
                        pause_seconds=pause_seconds,
                        progress_callback=progress_callback,
                        query_label=query_label,
                    )
                    total_requests += 1
                    if bindings is None:
                        failed_requests += 1
                        _emit(progress_callback, f"Failed query {query_label}")
                        break

                    extracted = _extract_rows(
                        bindings=bindings,
                        country_iso2=country_iso2,
                        name_type=name_type,
                    )
                    rows.extend(extracted)
                    rows_by_mode[mode_name] += len(extracted)
                    _emit(
                        progress_callback,
                        (
                            f"Fetched bindings={len(bindings)} extracted={len(extracted)} "
                            f"total_rows={len(rows)} for {query_label}"
                        ),
                    )
                    if len(bindings) < page_limit:
                        break

    metadata = {
        "endpoint": endpoint,
        "countries": sorted(countries.keys()),
        "name_types": ["given", "family"],
        "query_modes": ["person", "entity"] if include_direct_name_entities else ["person"],
        "page_limit": page_limit,
        "max_pages": max_pages,
        "total_requests": total_requests,
        "failed_requests": failed_requests,
        "rows_by_mode": rows_by_mode,
        "query_hashes": sorted(set(query_hashes)),
        "fetched_at": datetime.now(UTC).isoformat(),
    }
    _emit(
        progress_callback,
        (
            "Completed Wikidata fetch: "
            f"total_rows={len(rows)}, requests={total_requests}, failed={failed_requests}"
        ),
    )
    return rows, metadata


def _run_query_with_retry(
    *,
    endpoint: str,
    query: str,
    retries: int,
    pause_seconds: float,
    progress_callback: Callable[[str], None] | None = None,
    query_label: str = "",
) -> list[dict[str, dict[str, str]]] | None:
    params = urlencode({"query": query, "format": "json"})
    url = f"{endpoint}?{params}"
    wait = pause_seconds

    for attempt in range(retries + 1):
        try:
            req = Request(
                url=url,
                headers={
                    "Accept": "application/sparql-results+json",
                    "User-Agent": DEFAULT_USER_AGENT,
                },
            )
            with urlopen(req, timeout=90) as resp:  # noqa: S310 - fixed endpoint URL.
                payload = json.loads(resp.read().decode("utf-8"))
                return payload.get("results", {}).get("bindings", [])
        except Exception:
            if attempt >= retries:
                return None
            _emit(
                progress_callback,
                (
                    f"Retry {attempt + 1}/{retries} after error for "
                    f"{query_label or 'wikidata query'}"
                ),
            )
            time.sleep(wait)
            wait *= 2
    return None


def _extract_rows(
    *,
    bindings: list[dict[str, dict[str, str]]],
    country_iso2: str,
    name_type: str,
) -> list[dict[str, Any]]:
    now = datetime.now(UTC).isoformat()
    rows: list[dict[str, Any]] = []
    dedupe: set[tuple[str, str, str]] = set()

    for binding in bindings:
        source_id = _extract_qid(binding.get("nameEntity", {}).get("value", ""))
        label = binding.get("nameEntityLabel", {}).get("value", "").strip()
        alias = binding.get("alias", {}).get("value", "").strip()
        alias_lang = binding.get("alias", {}).get("xml:lang", "")

        for raw_name, lang_tag in ((label, "en"), (alias, alias_lang or "en")):
            if not raw_name:
                continue
            key = (source_id, raw_name.casefold(), lang_tag.casefold())
            if key in dedupe:
                continue
            dedupe.add(key)
            rows.append(
                {
                    "source": "wikidata",
                    "source_id": source_id or "unknown",
                    "source_license": DEFAULT_SOURCE_LICENSE,
                    "name_raw": raw_name,
                    "name_type": name_type,
                    "country_iso2": country_iso2,
                    "language_tag": lang_tag,
                    "evidence_count": 1,
                    "fetched_at": now,
                }
            )

    return rows


def _extract_qid(entity_url: str) -> str:
    if "/entity/" not in entity_url:
        return ""
    return entity_url.rsplit("/", 1)[-1]


def _emit(progress_callback: Callable[[str], None] | None, message: str) -> None:
    if progress_callback is not None:
        progress_callback(message)
