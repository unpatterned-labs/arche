# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Citizen-side Data Subject Access Request workflow.

Per Stage 1 PRD §7.4. A citizen exercising rights under NDPA-2023,
POPIA, Kenya DPA, or Ghana DPA invokes this workflow with their
identity and target organisations; arche generates a compliant draft
letter and a signed envelope that the citizen can dispatch manually.

**Stage 1 ships ``dispatch_mode="draft_only"`` only.** Fully autonomous
dispatch is deferred to Stage 4 with explicit consent mechanisms,
because incorrect legal letters dispatched at scale could cause real
harm (PRD §7.4, §15.3). The workflow generates a compliant draft
letter + a cryptographic envelope; the citizen reviews and dispatches.

Example::

    from arche.workflow.dsar import (
        DSARWorkflow, DSARRequestor, DSAROrganization,
    )
    from arche.sign import generate_keypair

    citizen_key = generate_keypair()
    wf = DSARWorkflow(
        jurisdiction="NG",
        statute="NDPA-2023",
        requestor=DSARRequestor(
            name="Adesola Okonkwo",
            identifier_label="NIN",
            identifier_value="12345678901",
            email="adesola@example.com",
        ),
        request_type="access",
        targets=[
            DSAROrganization(
                name="Sterling Bank",
                dpo_email="dpo@sterlingbank.ng",
            ),
        ],
    )
    result = wf.run(citizen_key)

    for draft in result.drafts:
        print(draft.letter_text)        # human-readable letter
        print(draft.signed_envelope)    # JWS for tamper-evidence

The signed envelope carries the same provenance any other
``SignWorkflow`` output does: issuer ``did:key``, jurisdiction, statute,
issued_at, purpose. The recipient organisation (or its automated
responder) can verify it offline with
:class:`arche.sign.VerifyExtractWorkflow`.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

from arche.sign import Keypair, SignWorkflow
from arche.workflow._dsar_templates import (
    DSAR_LETTER_TEMPLATE,
    REGULATORS,
    REQUEST_SPECS,
    STATUTE_SHORT_NAMES,
    supported_request_types,
    supported_statutes,
)


# ---------------------------------------------------------------------------
# Public input types
# ---------------------------------------------------------------------------

RequestType = Literal[
    "access", "rectification", "erasure", "portability", "objection"
]


@dataclass
class DSARRequestor:
    """The data subject making the request."""

    name: str
    identifier_label: str = "National ID"   # "NIN", "BVN", "Ghana Card", "SA ID", ...
    identifier_value: str = ""
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    # ``self_assertion`` is the only verified_via mode in Stage 1 per PRD
    # §15.3. Foundational ID gating + biometric verification land in
    # Stage 3 alongside the MOSIP integration.
    verified_via: Literal["self_assertion"] = "self_assertion"


@dataclass
class DSAROrganization:
    """A data controller / organisation receiving the DSAR."""

    name: str
    dpo_email: str | None = None
    dpo_address: str | None = None


# ---------------------------------------------------------------------------
# Output types
# ---------------------------------------------------------------------------

@dataclass
class DSARDraft:
    """One drafted letter + its signed envelope, addressed to one target."""

    target: DSAROrganization
    letter_text: str
    signed_envelope: str          # JWS compact form
    deadline: datetime
    citation: str
    statute_short: str


@dataclass
class DSARResult:
    """The output of ``DSARWorkflow.run``."""

    drafts: list[DSARDraft] = field(default_factory=list)
    dispatch_mode: str = "draft_only"
    sent_at: list[datetime | None] = field(default_factory=list)
    tracking: list[str | None] = field(default_factory=list)
    request_type: str = ""
    jurisdiction: str = ""
    statute: str = ""

    def __len__(self) -> int:
        return len(self.drafts)


# ---------------------------------------------------------------------------
# DSARWorkflow
# ---------------------------------------------------------------------------

class DSARWorkflow:
    """Generate jurisdiction-compliant DSAR draft letters with signed
    envelopes.

    Parameters
    ----------
    jurisdiction:
        ISO 3166-1 alpha-2 (``"NG"``, ``"ZA"``, ``"KE"``, ``"GH"``).
    statute:
        Statute identifier (``"NDPA-2023"``, ``"POPIA"``,
        ``"KENYA-DPA"``, ``"GHANA-DPA"``). Auto-inferred from
        ``jurisdiction`` when omitted.
    requestor:
        The data subject's identity claims.
    request_type:
        One of ``"access" | "rectification" | "erasure" | "portability"
        | "objection"``.
    targets:
        One or more data controllers receiving the request. The workflow
        drafts one letter per target.
    deadline_days:
        Override the statute's default response deadline.
    acknowledgement_days:
        Days within which an acknowledgement is expected (informational;
        defaults to 7).
    purpose_text:
        Optional free-form context describing the request's purpose.
    dispatch_mode:
        Stage 1 supports ``"draft_only"`` only. Other modes raise.
    """

    _STATUTE_FOR_JURISDICTION = {
        "NG": "NDPA-2023",
        "ZA": "POPIA",
        "KE": "KENYA-DPA",
        "GH": "GHANA-DPA",
    }

    def __init__(
        self,
        *,
        jurisdiction: str | None = None,
        statute: str | None = None,
        requestor: DSARRequestor,
        request_type: RequestType,
        targets: list[DSAROrganization],
        deadline_days: int | None = None,
        acknowledgement_days: int = 7,
        purpose_text: str | None = None,
        dispatch_mode: Literal["draft_only"] = "draft_only",
    ):
        if dispatch_mode != "draft_only":
            raise ValueError(
                "Stage 1 only supports dispatch_mode='draft_only'. "
                "Autonomous dispatch lands in Stage 4 with explicit "
                "consent mechanisms (PRD §15.3)."
            )

        self.jurisdiction = jurisdiction.upper() if jurisdiction else None
        self.statute = statute or (
            self._STATUTE_FOR_JURISDICTION.get(self.jurisdiction)
            if self.jurisdiction else None
        )
        if self.statute is None or self.statute not in supported_statutes():
            raise ValueError(
                f"Unsupported statute {self.statute!r}. "
                f"Supported: {supported_statutes()}"
            )
        if request_type not in supported_request_types(self.statute):
            raise ValueError(
                f"Unsupported request_type {request_type!r} for "
                f"{self.statute}. Supported: "
                f"{supported_request_types(self.statute)}"
            )
        if not targets:
            raise ValueError("At least one target organization is required.")

        self.requestor = requestor
        self.request_type = request_type
        self.targets = targets
        self.acknowledgement_days = acknowledgement_days
        self.purpose_text = purpose_text
        self.dispatch_mode = dispatch_mode

        # Resolve deadline (caller override > statute default)
        spec = REQUEST_SPECS[self.statute][self.request_type]
        self.deadline_days = deadline_days or spec.default_deadline_days
        self._spec = spec

    # -----------------------------------------------------------------------
    # Main entry point
    # -----------------------------------------------------------------------

    def run(self, signing_key: Keypair) -> DSARResult:
        """Generate drafts and sign each one with the citizen's key.

        Returns
        -------
        DSARResult
            One ``DSARDraft`` per target. ``sent_at`` and ``tracking``
            are populated with ``None`` in Stage 1 (draft_only).
        """
        signer = SignWorkflow(
            jurisdiction=self.jurisdiction,
            statute=self.statute,
        )

        now = datetime.now(timezone.utc)
        deadline = now + timedelta(days=self.deadline_days)

        drafts: list[DSARDraft] = []
        for target in self.targets:
            letter = self._render_letter(target=target, when=now)
            envelope = signer.sign(
                letter,
                signing_key,
                purpose=f"dsar_{self.request_type}",
                expires_at=deadline,
            )
            drafts.append(DSARDraft(
                target=target,
                letter_text=letter,
                signed_envelope=envelope,
                deadline=deadline,
                citation=self._spec.citation,
                statute_short=STATUTE_SHORT_NAMES[self.statute],
            ))

        return DSARResult(
            drafts=drafts,
            dispatch_mode=self.dispatch_mode,
            sent_at=[None] * len(drafts),
            tracking=[None] * len(drafts),
            request_type=self.request_type,
            jurisdiction=self.jurisdiction or "",
            statute=self.statute,
        )

    # -----------------------------------------------------------------------
    # Introspection (PRD FR-WF-8)
    # -----------------------------------------------------------------------

    def describe(self) -> dict:
        return {
            "kind": "DSARWorkflow",
            "jurisdiction": self.jurisdiction,
            "statute": self.statute,
            "request_type": self.request_type,
            "deadline_days": self.deadline_days,
            "target_count": len(self.targets),
            "dispatch_mode": self.dispatch_mode,
            "citation": self._spec.citation,
        }

    # -----------------------------------------------------------------------
    # Internal — letter rendering
    # -----------------------------------------------------------------------

    def _render_letter(self, *, target: DSAROrganization, when: datetime) -> str:
        contact_lines = []
        if self.requestor.email:
            contact_lines.append(f"  Email:         {self.requestor.email}")
        if self.requestor.phone:
            contact_lines.append(f"  Phone:         {self.requestor.phone}")
        if self.requestor.address:
            contact_lines.append(f"  Address:       {self.requestor.address}")
        contact_block = "\n".join(contact_lines) if contact_lines else ""
        contact_line = self.requestor.email or self.requestor.phone or ""

        purpose_block = ""
        if self.purpose_text:
            wrapped = textwrap.fill(self.purpose_text, width=72)
            purpose_block = f"Context / purpose of this request:\n\n{wrapped}\n"

        from arche._version import __version__ as arche_version

        return DSAR_LETTER_TEMPLATE.format(
            date=when.strftime("%Y-%m-%d"),
            organization_name=target.name,
            organization_address=target.dpo_address or "[Address on file]",
            request_type_title=self.request_type.title(),
            statute_short=STATUTE_SHORT_NAMES[self.statute],
            requestor_name=self.requestor.name,
            identifier_label=self.requestor.identifier_label,
            identifier_value=self.requestor.identifier_value,
            citation=self._spec.citation,
            verb_phrase=self._spec.verb_phrase,
            contact_block=contact_block,
            purpose_block=purpose_block,
            deadline_days=self.deadline_days,
            ack_days=self.acknowledgement_days,
            regulator=REGULATORS[self.statute],
            contact_line=contact_line,
            arche_version=arche_version,
        )


__all__ = [
    "DSARWorkflow",
    "DSARRequestor",
    "DSAROrganization",
    "DSARDraft",
    "DSARResult",
    "RequestType",
]
