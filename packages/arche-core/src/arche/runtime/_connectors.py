# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The narrow boundary between permitted actions and evidence connectors."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from time import monotonic
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from ._models import EvidenceAction, Observation, ToolCapability


class EvidenceConnector(Protocol):
    """A read-only connector that turns one permitted action into an Observation."""

    capability: ToolCapability

    def observe(self, action: EvidenceAction) -> Observation:
        """Return an immutable Observation for the permitted action."""


@dataclass(frozen=True)
class ExternalEvidenceRequest:
    """One ephemeral request for an application-approved external evidence source."""

    path: str
    query: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.path.startswith("/") or self.path.startswith("//"):
            raise ValueError("external evidence request path must be an absolute relative path")
        if "?" in self.path or "#" in self.path or ".." in self.path:
            raise ValueError(
                "external evidence request path must not contain query, fragment, or traversal"
            )
        if isinstance(self.query, (str, bytes)) or not all(
            isinstance(item, tuple)
            and len(item) == 2
            and isinstance(item[0], str)
            and item[0]
            and isinstance(item[1], str)
            for item in self.query
        ):
            raise ValueError("external evidence request query must contain string key-value pairs")


@dataclass(frozen=True)
class HttpEvidenceResponse:
    """The minimal transport result retained by the HTTP evidence connector."""

    status_code: int
    body: bytes

    def __post_init__(self) -> None:
        if isinstance(self.status_code, bool) or not isinstance(self.status_code, int):
            raise ValueError("HTTP evidence response status_code must be an integer")
        if not isinstance(self.body, bytes):
            raise ValueError("HTTP evidence response body must be bytes")


@dataclass
class HttpEvidenceConnector:
    """Call one approved HTTPS source and return a provenance-only Observation."""

    capability: ToolCapability
    base_url: str
    request_for_action: Callable[[EvidenceAction], ExternalEvidenceRequest]
    estimated_cost: float
    max_requests: int
    window_seconds: float
    timeout_seconds: float = 10.0
    fetch: Callable[[str, float], HttpEvidenceResponse] = field(
        default=lambda url, timeout: _fetch(url, timeout)
    )
    clock: Callable[[], float] = monotonic
    recorded_at: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    _request_times: deque[float] = field(default_factory=deque, init=False, repr=False)

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("external evidence connector base_url must be an HTTPS origin or path")
        if not self.capability.read_only:
            raise ValueError("external evidence connector capability must be read-only")
        if self.estimated_cost < 0:
            raise ValueError("external evidence connector estimated_cost must be non-negative")
        if self.max_requests < 1 or self.window_seconds <= 0 or self.timeout_seconds <= 0:
            raise ValueError("external evidence connector limits must be positive")

    def observe(self, action: EvidenceAction) -> Observation:
        """Fetch approved evidence or record a terminal failure Observation."""
        if not self.capability.permits(action):
            raise ValueError("external evidence connector does not permit this action")
        if action.max_cost is None or self.estimated_cost > action.max_cost:
            return self._failure(action, "cost_limit")
        now = self.clock()
        self._discard_expired_requests(now)
        if len(self._request_times) >= self.max_requests:
            return self._failure(action, "rate_limit")
        try:
            request = self.request_for_action(action)
            url = self._url(request)
        except ValueError:
            return self._failure(action, "invalid_request")

        request_hash = _hash(url.encode())
        self._request_times.append(now)
        try:
            response = self.fetch(url, self.timeout_seconds)
        except (HTTPError, URLError, TimeoutError, OSError):
            return self._failure(action, "transport_error", request_hash=request_hash)
        response_hash = _hash(response.body)
        if not 200 <= response.status_code < 300:
            return self._failure(
                action,
                "http_error",
                request_hash=request_hash,
                response_status=response.status_code,
                response_hash=response_hash,
            )
        return Observation(
            observation_id=f"obs_{sha256(action.action_id.encode()).hexdigest()[:24]}",
            source_id=action.source_id,
            source_record_id=f"request:{request_hash[7:]}",
            recorded_at=self.recorded_at(),
            content_hash=response_hash,
            provenance={
                "connector": "http_evidence",
                "outcome": "success",
                "request_sha256": request_hash,
                "response_sha256": response_hash,
                "response_status": response.status_code,
                "estimated_cost": self.estimated_cost,
            },
        )

    def _discard_expired_requests(self, now: float) -> None:
        """Discard calls outside the connector's fixed rate window."""
        while self._request_times and now - self._request_times[0] >= self.window_seconds:
            self._request_times.popleft()

    def _url(self, request: ExternalEvidenceRequest) -> str:
        """Build a URL without allowing the request to change the configured origin."""
        base = urlsplit(self.base_url)
        path = f"{base.path.rstrip('/')}{request.path}"
        return urlunsplit((base.scheme, base.netloc, path, urlencode(request.query), ""))

    def _failure(
        self,
        action: EvidenceAction,
        reason: str,
        *,
        request_hash: str | None = None,
        response_status: int | None = None,
        response_hash: str | None = None,
    ) -> Observation:
        """Represent a connector failure without retaining request or response values."""
        content_hash = _hash(f"{reason}:{response_status}".encode())
        provenance: dict[str, object] = {
            "connector": "http_evidence",
            "outcome": "failure",
            "failure_reason": reason,
            "estimated_cost": self.estimated_cost,
        }
        if request_hash is not None:
            provenance["request_sha256"] = request_hash
        if response_status is not None:
            provenance["response_status"] = response_status
        if response_hash is not None:
            provenance["response_sha256"] = response_hash
        return Observation(
            observation_id=f"obs_{sha256((action.action_id + reason).encode()).hexdigest()[:24]}",
            source_id=action.source_id,
            source_record_id=f"failure:{action.action_id}",
            recorded_at=self.recorded_at(),
            content_hash=content_hash,
            provenance=provenance,
        )


def _fetch(url: str, timeout: float) -> HttpEvidenceResponse:
    """Perform one GET through the standard library without a new runtime dependency."""
    request = Request(url, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            return HttpEvidenceResponse(response.status, response.read())
    except HTTPError as error:
        return HttpEvidenceResponse(error.code, error.read())


def _hash(value: bytes) -> str:
    """Return the provenance hash format used by external observations."""
    return f"sha256:{sha256(value).hexdigest()}"
