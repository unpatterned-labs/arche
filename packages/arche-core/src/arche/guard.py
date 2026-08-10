# Copyright 2026 unpatterned.org
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Egress guard — a fail-closed boundary for agent / MCP tool calls.

The guard wraps a statute-aware :class:`~arche.workflow._primitive.Pipeline` so
that nothing crosses the boundary a policy did not permit. It is the "Project
Arcturus" pattern: personal data is replaced by deterministic **strong hashed
IDs** before any model call, a cross-border transfer without a declared basis is
refused, and a disallowed provider is refused.

Fail-closed, four teeth (all default to *deny*):

1. **Deny on absence** — no statute configured means no policy means no
   permission. A bare ``Pipeline()`` returns text unchanged; the guard refuses.
2. **Deny on undeclared cross-border** — a transfer out of region without a
   basis in the statute's ``cross_border_transfer.permitted_basis`` is refused,
   with the statute cited.
3. **Deny on disallowed provider** — a provider not in the allow-list is refused.
4. **Deny on exception** — any error becomes a refusal, never a fallthrough that
   emits the original text.

The projection guarantees that **no raw detection value appears in any output
field** — dropped categories are removed, everything else is replaced by a
strong keyed token (:mod:`arche._tokens`), never the 32-bit masking token.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from arche._tokens import token as _strong_token

# Same ordering the statute engine uses, imported rather than restated so the
# guard and the policy layer can never disagree about which action is stricter.
from arche.policy.engine import _ACTION_SEVERITY

if TYPE_CHECKING:
    from arche.workflow._primitive import Detection, Pipeline


class GuardDenied(Exception):
    """Raised when the egress guard refuses to emit a projection.

    Carries a human-readable ``reason`` and, where a statute drove the refusal,
    the ``citation`` for it.
    """

    def __init__(self, reason: str, citation: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.citation = citation


@dataclass
class GuardedField:
    """One detected field, with the raw value removed."""

    category: str
    action: str
    token: str | None  # strong hashed ID; None when the field was dropped
    citation: str | None
    tier: str
    #: Every category absorbed into this region when detections overlapped.
    #: A single field can stand for several detections — an address that
    #: contains a location and a name is replaced once — and this keeps the
    #: collapsed categories auditable instead of silently dropping them.
    covers: tuple[str, ...] = ()


@dataclass
class GuardedProjection:
    """What the guard lets leave: redacted text + per-field metadata, no raw PII."""

    redacted_text: str
    fields: list[GuardedField] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def _label(category: str) -> str:
    parts = category.split("-")
    return parts[-1] if parts else "PII"


def _id_type_for(category: str) -> str:
    """Map a PII category to a canonicaliser so identical values tokenise alike."""
    c = category.upper()
    if "PHONE" in c:
        return "phone"
    if "EMAIL" in c:
        return "email"
    if "NAME" in c:
        return "name"
    if c.startswith("PII-2") or c.startswith("PII-5"):
        return "id"
    return "text"


class EgressGuard:
    """A fail-closed projection boundary over a statute-aware Pipeline."""

    def __init__(
        self,
        pipeline: Pipeline,
        *,
        key: str | bytes,
        allowed_providers: list[str] | set[str] | None = None,
        transfer_basis: str | None = None,
        fail_closed: bool = True,
    ) -> None:
        if not key:
            raise ValueError(
                "EgressGuard requires a non-empty key for hashed IDs (fail-closed)."
            )
        self._pipeline = pipeline
        self._key = key
        self._allowed_providers = (
            set(allowed_providers) if allowed_providers is not None else None
        )
        self._transfer_basis = transfer_basis
        self._fail_closed = fail_closed

    def guarded(
        self,
        text: str,
        *,
        provider: str | None = None,
        crosses_border: bool = False,
    ) -> GuardedProjection:
        """Run the pipeline and return a projection safe to send onward.

        Raises :class:`GuardDenied` when any of the four teeth fire. The caller
        (e.g. an MCP tool handler) declares ``provider`` and whether the call
        ``crosses_border``; region auto-detection is a follow-up (C2-T3).
        """
        try:
            statute = self._pipeline._ensure_statute()
            # Tooth 1: deny on absence of policy.
            if statute is None:
                raise GuardDenied(
                    "no statute configured on the pipeline — no policy means no "
                    "permission to emit",
                )
            # Tooth 3: provider allow-list.
            if self._allowed_providers is not None and provider not in self._allowed_providers:
                raise GuardDenied(
                    f"provider {provider!r} is not in the allow-list "
                    f"{sorted(self._allowed_providers)}",
                )
            # Tooth 2: cross-border transfer basis.
            if crosses_border:
                permitted = set(
                    statute.cross_border_transfer.get("permitted_basis", [])
                )
                if not self._transfer_basis or self._transfer_basis not in permitted:
                    raise GuardDenied(
                        "cross-border transfer without a permitted basis "
                        f"(declared={self._transfer_basis!r}, "
                        f"permitted={sorted(permitted)})",
                        citation=f"{statute.statute_id} cross-border transfer rules",
                    )

            result = self._pipeline.process(text)
            redacted, fields = self._project(text, result.detections, statute)
            return GuardedProjection(
                redacted_text=redacted,
                fields=fields,
                metadata={
                    "statute_id": statute.statute_id,
                    "provider": provider,
                    "crosses_border": crosses_border,
                    "transfer_basis": self._transfer_basis if crosses_border else None,
                },
            )
        except GuardDenied:
            raise
        except Exception as exc:  # noqa: BLE001 — intentional: deny on any error
            # Tooth 4: never let an error become a raw-text fallthrough.
            if self._fail_closed:
                raise GuardDenied(f"guard error (fail-closed): {exc}") from exc
            raise

    def _project(
        self, text: str, detections: list[Detection], statute: Any
    ) -> tuple[str, list[GuardedField]]:
        """Replace every detected region with a strong hashed ID (or remove it).

        Overlapping detections are grouped into **disjoint regions** and each
        region is replaced exactly once. This is the same resolution
        ``policy.engine`` applies, and it is here for the same reason.

        The previous implementation sorted by ``(start, end)`` descending and
        skipped any span whose ``end`` ran past the last span it consumed. Its
        docstring claimed the outer span won. It did not: descending order
        reaches the *inner* span first, so the container was the one skipped,
        and its unconsumed prefix crossed the boundary in clear. The shipped
        Nigerian detector set produces exactly that shape on an ordinary
        address, where ``PII-4-ADDRESS`` contains ``PII-4-LOCATION``::

            in   Janet Okafor lives at 12 Awolowo Road, Ikoyi, Lagos.
            out  Janet [NAME:…] lives at 12 Awolowo Road, Ikoyi, [LOCATION:…].

        The address survived, and ``PII-4-ADDRESS`` was absent from the output
        fields entirely, so nothing downstream could tell. Severity inverted
        too: ADDRESS generalises where LOCATION is retained, so the span that
        was dropped was the more restricted one.

        Two decisions per region, and they are deliberately different. The
        **action** comes from the most restrictive member, because that is the
        safety property. The **label** comes from the widest member, because an
        address containing a name is still an address, and rendering it
        ``[NAME:…]`` would misdescribe what left even though it would be
        equally safe. Every category the region absorbed is reported on
        ``GuardedField.covers`` so a collapsed region is still auditable.
        """
        resolved: list[tuple[int, int, str, str, str | None, str]] = []
        for det in detections:
            action, ref, _ = statute.action_for(det.category)
            resolved.append((
                det.start,
                det.end,
                det.category,
                action,
                ref or det.regulatory_citation,
                # Authoritative from the statute, not from prior enrichment.
                statute.tier_for(det.category).value,
            ))

        groups: list[dict] = []
        # Sorted by start, then widest first, so a container is seen before
        # whatever it contains.
        for item in sorted(resolved, key=lambda r: (r[0], -r[1])):
            start, end = item[0], item[1]
            if groups and start < groups[-1]["end"]:
                g = groups[-1]
                g["end"] = max(g["end"], end)
                g["members"].append(item)
            else:
                groups.append({"start": start, "end": end, "members": [item]})

        fields: list[GuardedField] = []
        for g in groups:
            widest = max(g["members"], key=lambda r: (r[1] - r[0]))
            action = max(
                g["members"], key=lambda r: _ACTION_SEVERITY.get(r[3], 0)
            )[3]
            category = widest[2]
            if action == "drop":
                tok = None
                g["replacement"] = ""
            else:
                # The token stands in for the WHOLE region, so it is derived
                # from the region's text — not from any single detection's
                # `.text`, which would only cover part of what left.
                tok = _strong_token(
                    text[g["start"]:g["end"]], _id_type_for(category), self._key
                )
                g["replacement"] = f"[{_label(category)}:{tok[:16]}]"
            fields.append(
                GuardedField(
                    category=category,
                    action=action,
                    token=tok,
                    citation=widest[4],
                    tier=widest[5],
                    covers=tuple(sorted({m[2] for m in g["members"]})),
                )
            )

        out = text
        for g in sorted(groups, key=lambda g: -g["start"]):
            out = out[: g["start"]] + g["replacement"] + out[g["end"] :]
        return out, fields
