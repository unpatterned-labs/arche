# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Address layer — parse African addresses and infer jurisdiction.

Per Stage 1 PRD §5. Hybrid rule-based and statistical parser for African
addresses including informal landmark-anchored formats ("behind the Total
filling station, Madina Junction"). Emits structured Address records with
GERS IDs and Placekeys where matchable (Stage 2).

Jurisdiction inference is one of arche's load-bearing capabilities: parsed
address signal flows downstream to `arche.policy` to select the applicable
data protection statute (NDPA, POPIA, Kenya DPA, Ghana DPA).

Public API::

    from arche.addr import parse_address, parse_addresses, Address

    addr = parse_address("7B Allen Avenue, Ikeja, Lagos, Nigeria")
    addr.components.city       # "Lagos"
    addr.country_inferred      # "NG"
    addr.country_confidence    # 0.95

Stage 1 MVP focuses on Nigerian and South African patterns; Kenya and
Ghana addresses parse best-effort via the shared gazetteer.
"""

from arche.addr import request
from arche.addr.document_roles import (
    DOCUMENT_ROLES,
    DocumentAddressMention,
    DocumentAddressRole,
    DocumentRolePack,
    extract_document_address_roles,
    grade_document_addresses,
    load_document_gold,
    load_document_role_pack,
)
from arche.addr.parse import (
    Address,
    AddressComponents,
    extract_anchor,
    infer_jurisdiction,
    normalise_gb_postcode,
    normalize_landmark,
    parse_address,
    parse_addresses,
)
from arche.addr.roles import (
    GoldSentence,
    PlaceGrade,
    PlaceMention,
    PlaceRole,
    RolePack,
    extract_places,
    grade_places,
    load_gold,
    load_role_pack,
)

__all__ = [
    "DOCUMENT_ROLES",
    "Address",
    "AddressComponents",
    "DocumentAddressMention",
    "DocumentAddressRole",
    "DocumentRolePack",
    "GoldSentence",
    "PlaceGrade",
    "PlaceMention",
    "PlaceRole",
    "RolePack",
    "extract_anchor",
    "extract_document_address_roles",
    "extract_places",
    "request",
    "grade_document_addresses",
    "grade_places",
    "infer_jurisdiction",
    "load_document_gold",
    "load_document_role_pack",
    "load_gold",
    "load_role_pack",
    "normalise_gb_postcode",
    "normalize_landmark",
    "parse_address",
    "parse_addresses",
]
