# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
# ruff: noqa: E501 — DSAR letter templates use long formatted legal text by design.

"""Per-jurisdiction Data Subject Access Request letter templates.

Stage 1 ships letter templates for the four launch statutes: NDPA-2023
(full), POPIA, Kenya DPA, Ghana DPA (functional but pending DPA
consultation, like the YAML scaffolds).

Templates are Python ``str.format``-style with named placeholders. The
DSARWorkflow renders them with the per-request context. Keeping them in
Python rather than separate files keeps Stage 1 simple — they move to
``.txt`` files alongside the YAML statute files in Stage 2 when the
NGO / civil society translation work begins.

The five request types per PRD §7.4 / GDPR-aligned vocabulary:

- ``access`` — right of access (most common)
- ``rectification`` — correct inaccurate or incomplete data
- ``erasure`` — right to be forgotten / deletion
- ``portability`` — receive data in machine-readable format
- ``objection`` — object to further processing

Each statute defines deadline defaults that the workflow respects.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StatuteRequestSpec:
    """Per-statute, per-request-type spec.

    ``citation`` is the section reference; ``verb_phrase`` is the
    legal language we use in the letter body; ``default_deadline_days``
    is what arche assumes when the caller doesn't override.
    """

    citation: str
    verb_phrase: str
    default_deadline_days: int


# ---------------------------------------------------------------------------
# Statute → request type → spec
# ---------------------------------------------------------------------------

REQUEST_SPECS: dict[str, dict[str, StatuteRequestSpec]] = {
    "NDPA-2023": {
        "access": StatuteRequestSpec(
            citation="NDPA-2023 s.34 (Right of Access)",
            verb_phrase="access to all personal data that you hold concerning me",
            default_deadline_days=30,
        ),
        "rectification": StatuteRequestSpec(
            citation="NDPA-2023 s.35 (Right to Rectification)",
            verb_phrase="rectification of inaccurate or incomplete personal data you hold concerning me",
            default_deadline_days=30,
        ),
        "erasure": StatuteRequestSpec(
            citation="NDPA-2023 s.36 (Right to Erasure)",
            verb_phrase="erasure of all personal data you hold concerning me, where the lawful basis no longer applies",
            default_deadline_days=30,
        ),
        "portability": StatuteRequestSpec(
            citation="NDPA-2023 s.38 (Right to Data Portability)",
            verb_phrase="transfer of my personal data in a structured, commonly used, and machine-readable format",
            default_deadline_days=30,
        ),
        "objection": StatuteRequestSpec(
            citation="NDPA-2023 s.37 (Right to Object)",
            verb_phrase="that you cease further processing of my personal data for the purposes I am objecting to",
            default_deadline_days=30,
        ),
    },
    "POPIA": {
        "access": StatuteRequestSpec(
            citation="POPIA s.23 (Access to personal information)",
            verb_phrase="access to all personal information you hold concerning me",
            default_deadline_days=30,  # POPIA Reg 4(2) - 30 days for response
        ),
        "rectification": StatuteRequestSpec(
            citation="POPIA s.24 (Correction of personal information)",
            verb_phrase="correction or deletion of personal information that is inaccurate, irrelevant, excessive, out of date, incomplete, misleading, or obtained unlawfully",
            default_deadline_days=30,
        ),
        "erasure": StatuteRequestSpec(
            citation="POPIA s.24 (Destruction or deletion of personal information)",
            verb_phrase="destruction or deletion of personal information that you are no longer authorised to retain",
            default_deadline_days=30,
        ),
        "portability": StatuteRequestSpec(
            citation="POPIA Conditions for Lawful Processing (Condition 8: Data subject participation)",
            verb_phrase="provision of my personal information in a usable, structured electronic format",
            default_deadline_days=30,
        ),
        "objection": StatuteRequestSpec(
            citation="POPIA s.11(3) (Objection to processing)",
            verb_phrase="that you cease further processing of my personal information",
            default_deadline_days=30,
        ),
    },
    "KENYA-DPA": {
        "access": StatuteRequestSpec(
            citation="Kenya DPA s.26(a) (Right of Access)",
            verb_phrase="access to my personal data held by you",
            default_deadline_days=30,
        ),
        "rectification": StatuteRequestSpec(
            citation="Kenya DPA s.26(d) (Right to Rectification)",
            verb_phrase="correction of false or misleading data concerning me",
            default_deadline_days=30,
        ),
        "erasure": StatuteRequestSpec(
            citation="Kenya DPA s.40 (Deletion of false or misleading data)",
            verb_phrase="deletion of false, misleading, or unlawfully obtained personal data concerning me",
            default_deadline_days=30,
        ),
        "portability": StatuteRequestSpec(
            citation="Kenya DPA s.26(b) (Right to Data Portability)",
            verb_phrase="my personal data in a structured, commonly used, and machine-readable format",
            default_deadline_days=30,
        ),
        "objection": StatuteRequestSpec(
            citation="Kenya DPA s.26(c) (Right to Object)",
            verb_phrase="that you cease processing of my personal data for direct marketing purposes",
            default_deadline_days=30,
        ),
    },
    "GHANA-DPA": {
        "access": StatuteRequestSpec(
            citation="Ghana DPA s.35 (Access to personal data)",
            verb_phrase="access to all personal data of mine that you process",
            default_deadline_days=21,  # Ghana DPA's shorter window
        ),
        "rectification": StatuteRequestSpec(
            citation="Ghana DPA s.36 (Correction of personal data)",
            verb_phrase="correction of personal data concerning me that is inaccurate, misleading, or out of date",
            default_deadline_days=21,
        ),
        "erasure": StatuteRequestSpec(
            citation="Ghana DPA s.37 (Deletion of personal data)",
            verb_phrase="deletion of personal data concerning me that is no longer necessary for the original purpose",
            default_deadline_days=21,
        ),
        "portability": StatuteRequestSpec(
            citation="Ghana DPA s.35 (Access to personal data)",
            verb_phrase="my personal data in an electronic format that I can re-use",
            default_deadline_days=21,
        ),
        "objection": StatuteRequestSpec(
            citation="Ghana DPA s.43 (Right to prevent processing for direct marketing)",
            verb_phrase="that you cease processing my personal data for direct marketing or unsolicited communication",
            default_deadline_days=21,
        ),
    },
}


# ---------------------------------------------------------------------------
# Letter template (jurisdiction-agnostic body, statute-aware citations)
# ---------------------------------------------------------------------------
# The template below is a *baseline* that all four statutes share. Each
# rendered letter substitutes statute-specific citation, verb phrase,
# deadline, and regulator. Future improvements include translations
# (Yoruba, Hausa, Swahili, Amharic) tracked in datasets/ as Stage 2 work.

DSAR_LETTER_TEMPLATE = """\
{date}

Data Protection Officer
{organization_name}
{organization_address}

Subject: Data Subject {request_type_title} Request under {statute_short}

Dear Data Protection Officer,

I, {requestor_name}, identified by {identifier_label} ({identifier_value}),
hereby exercise my right under {citation} to {verb_phrase}.

Identity verification details:
  Full name:     {requestor_name}
  {identifier_label}: {identifier_value}
{contact_block}

{purpose_block}

You are required to respond to this request within {deadline_days} days of
receipt, as provided by {statute_short}. Please confirm receipt within
{ack_days} working days and provide an estimated response date.

If you fail to respond within the statutory window, or if I am not
satisfied with your response, I reserve the right to lodge a complaint
with the {regulator}.

Yours faithfully,

{requestor_name}
{contact_line}

---
This letter was generated by arche-core v{arche_version} (NDPA / POPIA /
Kenya DPA / Ghana DPA compliant DSAR drafting workflow). The accompanying
signed envelope (arche+envelope/v1, Ed25519 over canonical JSON) provides
cryptographic provenance and tamper evidence.
"""


# ---------------------------------------------------------------------------
# Per-statute regulator metadata (for the complaint paragraph)
# ---------------------------------------------------------------------------

REGULATORS: dict[str, str] = {
    "NDPA-2023": "Nigeria Data Protection Commission (NDPC)",
    "POPIA": "Information Regulator (South Africa)",
    "KENYA-DPA": "Office of the Data Protection Commissioner (ODPC, Kenya)",
    "GHANA-DPA": "Data Protection Commission (Ghana)",
}


# ---------------------------------------------------------------------------
# Statute "short name" used in the subject line
# ---------------------------------------------------------------------------

STATUTE_SHORT_NAMES: dict[str, str] = {
    "NDPA-2023": "Nigeria Data Protection Act 2023 (NDPA-2023)",
    "POPIA": "Protection of Personal Information Act 2013 (POPIA)",
    "KENYA-DPA": "Kenya Data Protection Act 2019",
    "GHANA-DPA": "Ghana Data Protection Act 2012 (Act 843)",
}


def supported_statutes() -> list[str]:
    """Statute IDs with DSAR letter coverage."""
    return list(REQUEST_SPECS.keys())


def supported_request_types(statute_id: str) -> list[str]:
    """Request types available for a given statute."""
    return list(REQUEST_SPECS.get(statute_id, {}).keys())
