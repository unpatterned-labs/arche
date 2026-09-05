# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Compare synthetic person text locally without persisting its values.

Run with:

    uv run --no-sync python examples/quick_text_resolution.py
"""

from __future__ import annotations

from arche import compare

TEXT_1 = (
    "Adesola Okonkwo, NIN 12345678901, address: 123 Maple Street, "
    "adesola@example.com"
)
TEXT_2 = (
    "Adesola Okonkwo, NIN 12345678901, adesola@gmail.com, "
    "address: 124 Maple Street"
)

receipt = compare(TEXT_1, TEXT_2, entity="person", jurisdiction="NG", backend="regex")
print(
    {
        "identity": receipt.identity,
        "action": receipt.action,
        "basis": receipt.basis,
        "explanation": receipt.explanation,
        "factor_names": sorted(receipt.factors),
    }
)
