# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Nominatim (OpenStreetMap) as an evidence provider for place verification.

Nominatim is the right first adapter: free, no key, ODbL, and genuinely
independent of the government registries arche reconciles. It answers one
narrow question — *does an independent gazetteer put this named place where
you think it is?* — and returns the answer as :class:`ProviderEvidence`, never
as a merge decision.

What this is for. After a crosswalk merges two facility records, their claimed
coordinates are an average of two sources that may both be wrong. Asking an
independent gazetteer where the name actually resolves is a cheap check on the
merge. Disagreement routes to review; agreement is corroboration, not proof.

Usage policy, enforced rather than documented. The public Nominatim instance is
a donated service with a published policy: a genuine identifying ``User-Agent``,
no more than one request per second, and no bulk geocoding. This module
enforces the rate limit itself and refuses to run without a User-Agent, because
an adapter that gets the project banned is worse than no adapter. For anything
beyond spot verification, run your own instance and pass ``base_url``.

Egress. Sending a place name to a third-party service is a cross-border
transfer. Pass ``guard=`` to route the query through
:class:`arche.guard.EgressGuard` and let the statute pack decide whether it may
be sent at all — a facility name is usually fine, a patient's home address
usually is not.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from arche.adapters._evidence import ProviderEvidence, canonical_response_hash
from arche.resolve._matcher import haversine_km

__all__ = ["NOMINATIM_LICENCE", "NominatimError", "verify_place"]

#: OpenStreetMap data is ODbL and requires attribution. Not an open class for
#: pack-ingestion purposes: usable as evidence for one decision, never
#: retained into a pack, frequency table, or benchmark row.
NOMINATIM_LICENCE = "odbl-attribution"

_ENDPOINT = "https://nominatim.openstreetmap.org/search"
_MIN_INTERVAL_S = 1.0  # the published policy; not a tuning parameter

_rate_lock = threading.Lock()
_last_call = 0.0


class NominatimError(RuntimeError):
    """The provider could not be reached, or answered unusably."""


def _throttle(sleep: Callable[[float], None] = time.sleep) -> None:
    """Hold the caller to one request per second, process-wide."""
    global _last_call
    with _rate_lock:
        wait = _MIN_INTERVAL_S - (time.monotonic() - _last_call)
        if wait > 0:
            sleep(wait)
        _last_call = time.monotonic()


def _default_fetch(url: str, params: dict[str, str], headers: dict[str, str]) -> Any:
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover - httpx is a base dependency
        raise NominatimError("httpx is required for the Nominatim adapter") from exc

    try:
        response = httpx.get(url, params=params, headers=headers, timeout=15.0)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        raise NominatimError(f"Nominatim request failed: {exc}") from exc


def verify_place(
    name: str,
    lat: float | None = None,
    lon: float | None = None,
    *,
    retrieved_at: str,
    user_agent: str,
    country_codes: str | None = None,
    tolerance_km: float = 10.0,
    limit: int = 5,
    base_url: str = _ENDPOINT,
    fetch: Callable[[str, dict, dict], Any] | None = None,
    guard: Any | None = None,
) -> ProviderEvidence:
    """Ask an independent gazetteer whether ``name`` is where you think it is.

    Parameters
    ----------
    name:
        The place name to look up.
    lat, lon:
        The position being checked. Omit them to geocode without a claim — the
        verdict is then always ``inconclusive``, because there is nothing to
        corroborate or contradict.
    retrieved_at:
        ISO-8601 UTC timestamp, supplied by the caller. The adapter never reads
        the clock, so a recorded response replays identically in tests and in
        a re-verified attestation.
    user_agent:
        Required, and must identify you. Nominatim's policy asks for a real
        contact; sending a default would make every arche user look like one
        abusive client.
    tolerance_km:
        How far the gazetteer may disagree before the verdict is
        ``contradicts``. Defaults to the place pack's ``veto_km``.
    guard:
        Optional :class:`arche.guard.EgressGuard`. When supplied, the query is
        run through ``guard.guarded(name, provider="nominatim",
        crosses_border=True)`` before it leaves, and a name the statute pack
        forbids sending raises :class:`arche.guard.GuardDenied` rather than
        being transmitted.

    Returns
    -------
    ProviderEvidence
        ``corroborates`` when a candidate falls within ``tolerance_km``,
        ``contradicts`` when candidates were found but all lie beyond it, and
        ``inconclusive`` when nothing was found or no claim was supplied.

    Notes
    -----
    ``contradicts`` is not a claim that the merge is wrong. It means an
    independent source disagrees about the location, which is grounds for a
    human to look — the same posture the geographic veto takes.
    """
    if not user_agent or not user_agent.strip():
        raise ValueError(
            "user_agent is required: Nominatim's usage policy asks for a real "
            "identifying User-Agent with contact details. Passing a generic "
            "string on behalf of every arche user is how a shared service "
            "gets abused."
        )

    if guard is not None:
        # Sending a place name to a third party is egress. Let the statute
        # pack refuse before anything leaves the process.
        #
        # `crosses_border=True` is not a default we get to skip: the public
        # Nominatim instance is operated by the OSM Foundation in Europe, so
        # any query from a Nigerian or Kenyan deployment is a cross-border
        # transfer and the statute pack must be given the chance to say no.
        # Pass a guard built with the right `transfer_basis` if you have one.
        guard.guarded(name, provider="nominatim", crosses_border=True)

    params = {"q": name, "format": "jsonv2", "limit": str(limit)}
    if country_codes:
        params["countrycodes"] = country_codes
    headers = {"User-Agent": user_agent.strip(), "Accept": "application/json"}

    caller = fetch or _default_fetch
    if fetch is None:
        _throttle()
    payload = caller(base_url, params, headers)

    if not isinstance(payload, list):
        raise NominatimError(f"expected a JSON array, got {type(payload).__name__}")

    candidates: list[dict[str, Any]] = []
    for item in payload:
        try:
            candidates.append({
                "name": item.get("display_name", ""),
                "lat": float(item["lat"]),
                "lon": float(item["lon"]),
                "category": item.get("category", ""),
                "type": item.get("type", ""),
                "osm_id": item.get("osm_id"),
                "importance": item.get("importance"),
            })
        except (KeyError, TypeError, ValueError):
            # A malformed candidate is dropped, not fatal: partial evidence is
            # still evidence, and raising would discard the usable results.
            continue

    detail: dict[str, Any] = {
        "candidate_count": len(candidates),
        "tolerance_km": tolerance_km,
    }

    if lat is None or lon is None:
        verdict = "inconclusive"
        detail["reason"] = "no claimed position supplied"
    elif not candidates:
        verdict = "inconclusive"
        detail["reason"] = "gazetteer returned no candidates"
    else:
        distances = [haversine_km(float(lat), float(lon), c["lat"], c["lon"])
                     for c in candidates]
        nearest = min(distances)
        detail["nearest_km"] = round(nearest, 3)
        detail["nearest_index"] = distances.index(nearest)
        verdict = "corroborates" if nearest <= tolerance_km else "contradicts"

    return ProviderEvidence(
        provider="nominatim",
        query=name,
        verdict=verdict,
        retrieved_at=retrieved_at,
        licence=NOMINATIM_LICENCE,
        response_sha256=canonical_response_hash(payload),
        candidates=tuple(candidates),
        detail=detail,
    )
