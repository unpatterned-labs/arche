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

from arche.addr.parse import (
    Address,
    AddressComponents,
    infer_jurisdiction,
    parse_address,
    parse_addresses,
)

__all__ = [
    "Address",
    "AddressComponents",
    "infer_jurisdiction",
    "parse_address",
    "parse_addresses",
]
