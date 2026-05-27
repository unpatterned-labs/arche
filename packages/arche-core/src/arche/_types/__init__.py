# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Shared types for arche-core (PRD §10.2 consolidation target).

Currently houses :class:`SensitivityTier`, the StrEnum shared between
the detection layer (``arche.workflow._primitive.Detection``) and the
policy layer (``arche.policy.engine.Statute``). Placed here to avoid
circular imports — both layers import from ``arche._types``.

Full PRD §10.2 type consolidation (Detection, Address, PolicyOutcome,
AuditEvent, Result) lands in a future restructure.
"""

from __future__ import annotations

from enum import StrEnum


class SensitivityTier(StrEnum):
    """PII sensitivity tier (NIST 800-122-style classification).

    Mapped per-jurisdiction in statute YAMLs under
    ``arche/policy/statutes/*.yaml``. Different jurisdictions may tier
    the same category differently — by design. Address might be
    MODERATE under NDPA-2023 and HIGH under POPIA's biometric-proximity
    rules. The statute is the source of truth; this enum is the
    canonical wire format.

    Tier values match the lowercase strings used in YAML statute files,
    on the wire, and in audit log rows.

    -   HIGH       Foundational government IDs (NIN, SA ID, Ghana Card),
                   biometrics, financial account numbers, health records,
                   anything enabling identity theft or grave harm.
    -   MODERATE   Contact information (phone, email, address), employment
                   records, education records, less-sensitive government
                   IDs. The default for unmapped categories.
    -   LOW        Public information (business registration numbers),
                   aggregated or anonymized data.
    """

    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"


__all__ = ["SensitivityTier"]
