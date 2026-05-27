# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

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

"""Country jurisdiction packs — the unit of value in identity intelligence.

Each pack bundles ID validators, phone formats, naming conventions,
address norms, and compliance metadata for one country.

Usage:
    from arche.jurisdictions import nigeria
    profile = nigeria.get_profile()
    result = nigeria.validate_nin("12345678901")
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import JurisdictionProfileModel

# Registry of loaded packs (lazy)
_registry: dict[str, JurisdictionProfileModel] = {}


def get_profile(country_code: str) -> JurisdictionProfileModel:
    """Load and return the jurisdiction profile for a country code.

    Parameters
    ----------
    country_code:
        ISO 3166-1 alpha-2 (e.g. ``"NG"``, ``"GH"``, ``"KE"``).

    Raises
    ------
    ValueError
        If no pack exists for the given country.
    """
    code = country_code.upper()
    if code in _registry:
        return _registry[code]

    if code == "NG":
        from . import nigeria
        profile = nigeria.get_profile()
    elif code == "GH":
        from . import ghana
        profile = ghana.get_profile()
    elif code == "KE":
        from . import kenya
        profile = kenya.get_profile()
    elif code == "ZA":
        from . import south_africa
        profile = south_africa.get_profile()
    else:
        raise ValueError(
            f"No jurisdiction pack for '{code}'. "
            f"Available: {', '.join(available_jurisdictions())}."
        )

    _registry[code] = profile
    return profile


def available_jurisdictions() -> list[str]:
    """Return country codes with available packs."""
    return ["NG", "GH", "KE", "ZA"]
