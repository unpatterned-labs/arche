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

"""African city gazetteer — offline geocoding for 100+ major African cities.

Provides a pre-loaded database of major African cities with coordinates,
approximate populations, alias lists, and H3 hexagonal cell IDs. Uses fuzzy
matching (via rapidfuzz) and spatial blocking (via H3) to resolve location
names against the database.

Coverage: capital + top 2-3 cities for 20+ countries across West, East,
Southern, Central, and North Africa.
"""

from __future__ import annotations

from dataclasses import dataclass, field

try:
    from rapidfuzz import fuzz
    from rapidfuzz import process as rf_process
except ImportError:
    fuzz = None  # type: ignore[assignment]
    rf_process = None  # type: ignore[assignment]

try:
    import h3
    _H3_AVAILABLE = True
except ImportError:
    _H3_AVAILABLE = False

# H3 resolution levels used for spatial blocking
H3_RES_COARSE = 4   # ~1,770 km² — regional proximity
H3_RES_MEDIUM = 5   # ~253 km² — city-level proximity
H3_RES_FINE = 7     # ~5.16 km² — neighborhood-level proximity


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class City:
    """An African city with geocoding data.

    Attributes
    ----------
    name:
        Primary English-language name.
    country:
        ISO 3166-1 alpha-2 country code.
    country_name:
        Human-readable country name.
    region:
        State, province, or administrative region.
    lat:
        Latitude (decimal degrees, WGS 84).
    lng:
        Longitude (decimal degrees, WGS 84).
    population:
        Approximate population (city proper, latest available estimate).
    aliases:
        Alternative names, spellings, abbreviations, and local-language
        names that should resolve to this city.
    h3_cell:
        H3 hexagonal cell index at medium resolution (level 5).
        Computed automatically from lat/lng.
    """

    name: str
    country: str
    country_name: str
    region: str
    lat: float
    lng: float
    population: int
    aliases: list[str] = field(default_factory=list)
    h3_cell: str = ""


# ---------------------------------------------------------------------------
# City database
# ---------------------------------------------------------------------------
# Data compiled from publicly available sources (UN, national statistics
# offices, OpenStreetMap, GeoNames).  Coordinates are city-centre
# approximations.  Populations are best-available recent estimates for
# the city proper (not metro area, unless noted).

AFRICAN_CITIES: list[City] = [
    # ══════════════════════════════════════════════════════════════════════
    # NIGERIA
    # ══════════════════════════════════════════════════════════════════════
    City("Abuja", "NG", "Nigeria", "Federal Capital Territory", 9.0579, 7.4951,
         3_600_000, ["FCT Abuja", "FCT", "Federal Capital"]),
    City("Lagos", "NG", "Nigeria", "Lagos State", 6.5244, 3.3792,
         16_000_000, ["Eko", "Lasgidi", "Lagos Island"]),
    City("Kano", "NG", "Nigeria", "Kano State", 12.0022, 8.5920,
         4_100_000, []),
    City("Ibadan", "NG", "Nigeria", "Oyo State", 7.3776, 3.9470,
         3_600_000, []),
    City("Port Harcourt", "NG", "Nigeria", "Rivers State", 4.8156, 7.0498,
         1_900_000, ["PH", "Pitakwa", "Port-Harcourt"]),
    City("Benin City", "NG", "Nigeria", "Edo State", 6.3350, 5.6270,
         1_500_000, ["Benin", "Edo"]),
    City("Kaduna", "NG", "Nigeria", "Kaduna State", 10.5105, 7.4165,
         1_600_000, []),
    City("Enugu", "NG", "Nigeria", "Enugu State", 6.4584, 7.5464,
         900_000, ["Coal City"]),

    # ══════════════════════════════════════════════════════════════════════
    # KENYA
    # ══════════════════════════════════════════════════════════════════════
    City("Nairobi", "KE", "Kenya", "Nairobi County", -1.2921, 36.8219,
         4_400_000, ["Nai", "NBO", "Green City in the Sun"]),
    City("Mombasa", "KE", "Kenya", "Mombasa County", -4.0435, 39.6682,
         1_200_000, ["Mvita"]),
    City("Kisumu", "KE", "Kenya", "Kisumu County", -0.1022, 34.7617,
         600_000, []),
    City("Nakuru", "KE", "Kenya", "Nakuru County", -0.3031, 36.0800,
         500_000, []),

    # ══════════════════════════════════════════════════════════════════════
    # SOUTH AFRICA
    # ══════════════════════════════════════════════════════════════════════
    City("Johannesburg", "ZA", "South Africa", "Gauteng", -26.2041, 28.0473,
         5_800_000, ["Joburg", "Jozi", "JHB", "Egoli"]),
    City("Cape Town", "ZA", "South Africa", "Western Cape", -33.9249, 18.4241,
         4_600_000, ["Kaapstad", "CPT", "Mother City"]),
    City("Durban", "ZA", "South Africa", "KwaZulu-Natal", -29.8587, 31.0218,
         3_100_000, ["eThekwini", "DUR"]),
    City("Pretoria", "ZA", "South Africa", "Gauteng", -25.7479, 28.2293,
         2_500_000, ["Tshwane", "Jacaranda City", "PTA"]),
    City("Soweto", "ZA", "South Africa", "Gauteng", -26.2227, 27.8540,
         1_300_000, ["South Western Townships"]),

    # ══════════════════════════════════════════════════════════════════════
    # GHANA
    # ══════════════════════════════════════════════════════════════════════
    City("Accra", "GH", "Ghana", "Greater Accra", 5.6037, -0.1870,
         2_500_000, ["ACC"]),
    City("Kumasi", "GH", "Ghana", "Ashanti Region", 6.6885, -1.6244,
         3_300_000, ["Garden City", "Asu"]),
    City("Tamale", "GH", "Ghana", "Northern Region", 9.4008, -0.8393,
         500_000, []),
    City("Sekondi-Takoradi", "GH", "Ghana", "Western Region", 4.9340, -1.7137,
         600_000, ["Takoradi", "Sekondi"]),

    # ══════════════════════════════════════════════════════════════════════
    # TANZANIA
    # ══════════════════════════════════════════════════════════════════════
    City("Dar es Salaam", "TZ", "Tanzania", "Dar es Salaam Region", -6.7924, 39.2083,
         5_400_000, ["Dar", "DSM", "Bongo"]),
    City("Dodoma", "TZ", "Tanzania", "Dodoma Region", -6.1630, 35.7516,
         450_000, []),
    City("Mwanza", "TZ", "Tanzania", "Mwanza Region", -2.5164, 32.9175,
         700_000, []),
    City("Arusha", "TZ", "Tanzania", "Arusha Region", -3.3869, 36.6830,
         600_000, []),

    # ══════════════════════════════════════════════════════════════════════
    # UGANDA
    # ══════════════════════════════════════════════════════════════════════
    City("Kampala", "UG", "Uganda", "Central Region", 0.3476, 32.5825,
         1_700_000, ["KLA"]),
    City("Gulu", "UG", "Uganda", "Northern Region", 2.7746, 32.2990,
         200_000, []),
    City("Mbarara", "UG", "Uganda", "Western Region", -0.6117, 30.6545,
         200_000, []),

    # ══════════════════════════════════════════════════════════════════════
    # RWANDA
    # ══════════════════════════════════════════════════════════════════════
    City("Kigali", "RW", "Rwanda", "Kigali City", -1.9403, 29.8739,
         1_200_000, ["KGL"]),
    City("Butare", "RW", "Rwanda", "Southern Province", -2.5967, 29.7394,
         100_000, ["Huye"]),
    City("Gisenyi", "RW", "Rwanda", "Western Province", -1.7027, 29.2563,
         100_000, ["Rubavu"]),

    # ══════════════════════════════════════════════════════════════════════
    # ETHIOPIA
    # ══════════════════════════════════════════════════════════════════════
    City("Addis Ababa", "ET", "Ethiopia", "Addis Ababa", 9.0192, 38.7525,
         5_000_000, ["Addis", "Finfinne", "ADD"]),
    City("Dire Dawa", "ET", "Ethiopia", "Dire Dawa", 9.5931, 41.8661,
         500_000, []),
    City("Adama", "ET", "Ethiopia", "Oromia", 8.5400, 39.2700,
         400_000, ["Nazret", "Nazareth"]),
    City("Hawassa", "ET", "Ethiopia", "Sidama", 7.0621, 38.4763,
         400_000, ["Awasa", "Awassa"]),

    # ══════════════════════════════════════════════════════════════════════
    # EGYPT
    # ══════════════════════════════════════════════════════════════════════
    City("Cairo", "EG", "Egypt", "Cairo Governorate", 30.0444, 31.2357,
         10_000_000, ["Al-Qahira", "al-Qāhirah", "CAI"]),
    City("Alexandria", "EG", "Egypt", "Alexandria Governorate", 31.2001, 29.9187,
         5_200_000, ["Al-Iskandariyya", "Alex"]),
    City("Giza", "EG", "Egypt", "Giza Governorate", 30.0131, 31.2089,
         4_200_000, ["Al Jizah", "El Giza"]),
    City("Shubra El Kheima", "EG", "Egypt", "Qalyubia", 30.1286, 31.2422,
         1_200_000, ["Shubra"]),

    # ══════════════════════════════════════════════════════════════════════
    # MOROCCO
    # ══════════════════════════════════════════════════════════════════════
    City("Casablanca", "MA", "Morocco", "Casablanca-Settat", 33.5731, -7.5898,
         3_700_000, ["Casa", "Dar el Beida", "CMN"]),
    City("Rabat", "MA", "Morocco", "Rabat-Sale-Kenitra", 34.0209, -6.8416,
         580_000, []),
    City("Marrakech", "MA", "Morocco", "Marrakech-Safi", 31.6295, -7.9811,
         1_000_000, ["Marrakesh", "RAK"]),
    City("Fes", "MA", "Morocco", "Fes-Meknes", 34.0331, -5.0003,
         1_200_000, ["Fez", "Fas"]),

    # ══════════════════════════════════════════════════════════════════════
    # COTE D'IVOIRE
    # ══════════════════════════════════════════════════════════════════════
    City("Abidjan", "CI", "Cote d'Ivoire", "Abidjan", 5.3600, -4.0083,
         5_600_000, ["Babi", "ABJ"]),
    City("Yamoussoukro", "CI", "Cote d'Ivoire", "Yamoussoukro", 6.8276, -5.2893,
         300_000, []),
    City("Bouake", "CI", "Cote d'Ivoire", "Vallee du Bandama", 7.6939, -5.0309,
         800_000, ["Bouaké"]),

    # ══════════════════════════════════════════════════════════════════════
    # SENEGAL
    # ══════════════════════════════════════════════════════════════════════
    City("Dakar", "SN", "Senegal", "Dakar Region", 14.7167, -17.4677,
         1_200_000, ["DSS"]),
    City("Thies", "SN", "Senegal", "Thies Region", 14.7910, -16.9260,
         400_000, ["Thiès"]),
    City("Saint-Louis", "SN", "Senegal", "Saint-Louis Region", 16.0179, -16.4897,
         250_000, ["Ndar"]),

    # ══════════════════════════════════════════════════════════════════════
    # CAMEROON
    # ══════════════════════════════════════════════════════════════════════
    City("Yaounde", "CM", "Cameroon", "Centre Region", 3.8480, 11.5021,
         4_100_000, ["Yaoundé", "YAO"]),
    City("Douala", "CM", "Cameroon", "Littoral Region", 4.0511, 9.7679,
         3_600_000, ["DLA"]),
    City("Bamenda", "CM", "Cameroon", "Northwest Region", 5.9597, 10.1458,
         500_000, []),

    # ══════════════════════════════════════════════════════════════════════
    # DR CONGO
    # ══════════════════════════════════════════════════════════════════════
    City("Kinshasa", "CD", "DR Congo", "Kinshasa Province", -4.4419, 15.2663,
         17_000_000, ["Kin", "FIH", "Leopoldville"]),
    City("Lubumbashi", "CD", "DR Congo", "Haut-Katanga", -11.6876, 27.5026,
         2_000_000, ["L'shi"]),
    City("Mbuji-Mayi", "CD", "DR Congo", "Kasai-Oriental", -6.1360, 23.5897,
         2_000_000, []),
    City("Kisangani", "CD", "DR Congo", "Tshopo", 0.5153, 25.1950,
         1_200_000, ["Boyoma"]),

    # ══════════════════════════════════════════════════════════════════════
    # ANGOLA
    # ══════════════════════════════════════════════════════════════════════
    City("Luanda", "AO", "Angola", "Luanda Province", -8.8399, 13.2894,
         8_300_000, ["LAD"]),
    City("Huambo", "AO", "Angola", "Huambo Province", -12.7761, 15.7392,
         700_000, ["Nova Lisboa"]),
    City("Lobito", "AO", "Angola", "Benguela Province", -12.3646, 13.5366,
         400_000, []),

    # ══════════════════════════════════════════════════════════════════════
    # MOZAMBIQUE
    # ══════════════════════════════════════════════════════════════════════
    City("Maputo", "MZ", "Mozambique", "Maputo City", -25.9692, 32.5732,
         1_100_000, ["MPM", "Lourenço Marques"]),
    City("Beira", "MZ", "Mozambique", "Sofala Province", -19.8436, 34.8389,
         600_000, []),
    City("Nampula", "MZ", "Mozambique", "Nampula Province", -15.1165, 39.2666,
         700_000, []),

    # ══════════════════════════════════════════════════════════════════════
    # ZIMBABWE
    # ══════════════════════════════════════════════════════════════════════
    City("Harare", "ZW", "Zimbabwe", "Harare Province", -17.8252, 31.0335,
         1_500_000, ["Salisbury", "HRE"]),
    City("Bulawayo", "ZW", "Zimbabwe", "Bulawayo Province", -20.1325, 28.6266,
         700_000, ["BUQ"]),
    City("Mutare", "ZW", "Zimbabwe", "Manicaland", -18.9707, 32.6709,
         300_000, ["Umtali"]),

    # ══════════════════════════════════════════════════════════════════════
    # ZAMBIA
    # ══════════════════════════════════════════════════════════════════════
    City("Lusaka", "ZM", "Zambia", "Lusaka Province", -15.3875, 28.3228,
         2_500_000, ["LUN"]),
    City("Kitwe", "ZM", "Zambia", "Copperbelt Province", -12.8025, 28.2130,
         600_000, []),
    City("Ndola", "ZM", "Zambia", "Copperbelt Province", -12.9586, 28.6366,
         500_000, []),

    # ══════════════════════════════════════════════════════════════════════
    # BOTSWANA
    # ══════════════════════════════════════════════════════════════════════
    City("Gaborone", "BW", "Botswana", "South-East District", -24.6282, 25.9231,
         250_000, ["Gabs", "GBE"]),
    City("Francistown", "BW", "Botswana", "North-East District", -21.1667, 27.5000,
         100_000, []),

    # ══════════════════════════════════════════════════════════════════════
    # NAMIBIA
    # ══════════════════════════════════════════════════════════════════════
    City("Windhoek", "NA", "Namibia", "Khomas Region", -22.5609, 17.0658,
         430_000, ["WDH"]),
    City("Walvis Bay", "NA", "Namibia", "Erongo Region", -22.9576, 14.5053,
         85_000, ["Walvisbaai"]),

    # ══════════════════════════════════════════════════════════════════════
    # ADDITIONAL WEST AFRICAN CITIES
    # ══════════════════════════════════════════════════════════════════════
    City("Bamako", "ML", "Mali", "Bamako District", 12.6392, -8.0029,
         2_700_000, ["BKO"]),
    City("Ouagadougou", "BF", "Burkina Faso", "Centre Region", 12.3714, -1.5197,
         2_800_000, ["Ouaga", "OUA"]),
    City("Niamey", "NE", "Niger", "Niamey", 13.5127, 2.1128,
         1_300_000, ["NIM"]),
    City("Conakry", "GN", "Guinea", "Conakry", 9.6412, -13.5784,
         2_000_000, ["CKY"]),
    City("Lome", "TG", "Togo", "Maritime Region", 6.1725, 1.2314,
         1_900_000, ["Lomé", "LFW"]),
    City("Cotonou", "BJ", "Benin", "Littoral Department", 6.3703, 2.3912,
         700_000, ["COO"]),
    City("Freetown", "SL", "Sierra Leone", "Western Area", 8.4844, -13.2344,
         1_100_000, ["FNA"]),
    City("Monrovia", "LR", "Liberia", "Montserrado County", 6.3004, -10.7969,
         1_000_000, ["ROB"]),
    City("Banjul", "GM", "Gambia", "Banjul", 13.4549, -16.5790,
         35_000, ["Bathurst", "BJL"]),
    City("Bissau", "GW", "Guinea-Bissau", "Bissau", 11.8636, -15.5977,
         500_000, ["OXB"]),
    City("Nouakchott", "MR", "Mauritania", "Nouakchott", 18.0735, -15.9582,
         1_100_000, ["NKC"]),
    City("Praia", "CV", "Cape Verde", "Santiago", 14.9330, -23.5133,
         160_000, ["RAI"]),

    # ══════════════════════════════════════════════════════════════════════
    # ADDITIONAL EAST AFRICAN CITIES
    # ══════════════════════════════════════════════════════════════════════
    City("Mogadishu", "SO", "Somalia", "Banaadir", 2.0469, 45.3182,
         2_400_000, ["Muqdisho", "Xamar", "MGQ"]),
    City("Hargeisa", "SO", "Somalia", "Woqooyi Galbeed", 9.5600, 44.0650,
         1_200_000, ["Hargeysa"]),
    City("Djibouti", "DJ", "Djibouti", "Djibouti", 11.5880, 43.1456,
         600_000, ["JIB"]),
    City("Asmara", "ER", "Eritrea", "Maekel", 15.3229, 38.9251,
         900_000, ["Asmera", "ASM"]),
    City("Juba", "SS", "South Sudan", "Central Equatoria", 4.8594, 31.5713,
         500_000, ["JUB"]),
    City("Antananarivo", "MG", "Madagascar", "Analamanga", -18.8792, 47.5079,
         1_400_000, ["Tana", "TNR"]),

    # ══════════════════════════════════════════════════════════════════════
    # ADDITIONAL CENTRAL AFRICAN CITIES
    # ══════════════════════════════════════════════════════════════════════
    City("Brazzaville", "CG", "Republic of Congo", "Brazzaville", -4.2634, 15.2429,
         2_400_000, ["BZV"]),
    City("Libreville", "GA", "Gabon", "Estuaire", 0.4162, 9.4673,
         800_000, ["LBV"]),
    City("Bangui", "CF", "Central African Republic", "Bangui", 4.3947, 18.5582,
         900_000, ["BGF"]),
    City("Ndjamena", "TD", "Chad", "Ndjamena", 12.1348, 15.0557,
         1_400_000, ["N'Djamena", "NDJ", "Fort-Lamy"]),
    City("Malabo", "GQ", "Equatorial Guinea", "Bioko Norte", 3.7504, 8.7371,
         300_000, ["SSG"]),

    # ══════════════════════════════════════════════════════════════════════
    # ADDITIONAL NORTH AFRICAN CITIES
    # ══════════════════════════════════════════════════════════════════════
    City("Algiers", "DZ", "Algeria", "Algiers Province", 36.7538, 3.0588,
         3_900_000, ["Alger", "El Djazair", "ALG"]),
    City("Oran", "DZ", "Algeria", "Oran Province", 35.6976, -0.6337,
         900_000, ["Wahran"]),
    City("Tunis", "TN", "Tunisia", "Tunis Governorate", 36.8065, 10.1815,
         700_000, ["TUN"]),
    City("Tripoli", "LY", "Libya", "Tripoli District", 32.9022, 13.1664,
         1_200_000, ["Tarabulus", "TIP"]),
    City("Benghazi", "LY", "Libya", "Benghazi District", 32.1194, 20.0868,
         700_000, ["Banghazi", "BEN"]),
    City("Khartoum", "SD", "Sudan", "Khartoum State", 15.5007, 32.5599,
         6_000_000, ["Al-Khurtum", "KRT"]),
    City("Omdurman", "SD", "Sudan", "Khartoum State", 15.6361, 32.4777,
         2_800_000, ["Umm Durman"]),
]


# ---------------------------------------------------------------------------
# Build lookup indices and compute H3 cells
# ---------------------------------------------------------------------------

# Compute H3 cells for all cities
if _H3_AVAILABLE:
    for _city in AFRICAN_CITIES:
        if _city.lat != 0.0 and _city.lng != 0.0 and not _city.h3_cell:
            _city.h3_cell = h3.latlng_to_cell(_city.lat, _city.lng, H3_RES_MEDIUM)

# Map of normalised name → City for O(1) exact lookups
_NAME_INDEX: dict[str, City] = {}
for _city in AFRICAN_CITIES:
    _NAME_INDEX[_city.name.lower()] = _city
    for _alias in _city.aliases:
        _alias_key = _alias.lower()
        if _alias_key not in _NAME_INDEX:
            _NAME_INDEX[_alias_key] = _city

# Map of H3 cell → list of cities (for spatial queries)
_H3_INDEX: dict[str, list[City]] = {}
for _city in AFRICAN_CITIES:
    if _city.h3_cell:
        _H3_INDEX.setdefault(_city.h3_cell, []).append(_city)

# All searchable names for fuzzy matching
_ALL_NAMES: list[str] = list(_NAME_INDEX.keys())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def geocode_african_location(
    name: str,
    *,
    score_cutoff: int = 70,
) -> City | None:
    """Fuzzy-match a location name against the African city gazetteer.

    Uses exact lookup first (O(1)), then falls back to rapidfuzz
    token-set-ratio fuzzy matching.

    Parameters
    ----------
    name:
        Location name to resolve (e.g. ``"Joburg"``, ``"Dar"``, ``"Nai"``).
    score_cutoff:
        Minimum fuzzy match score (0-100) required to return a result.
        Default is 70.

    Returns
    -------
    City | None
        The best matching city, or ``None`` if no match exceeds the cutoff.

    Examples
    --------
    >>> geocode_african_location("Joburg")
    City(name='Johannesburg', country='ZA', ...)
    >>> geocode_african_location("Dar")
    City(name='Dar es Salaam', country='TZ', ...)
    >>> geocode_african_location("Nowhere")
    None
    """
    if not name or not name.strip():
        return None

    query = name.strip().lower()

    # 1) Exact match
    if query in _NAME_INDEX:
        return _NAME_INDEX[query]

    # 2) Fuzzy match via rapidfuzz
    if rf_process is None or fuzz is None:
        # Without rapidfuzz, try simple substring match
        for key, city in _NAME_INDEX.items():
            if query in key or key in query:
                return city
        return None

    result = rf_process.extractOne(
        query,
        _ALL_NAMES,
        scorer=fuzz.token_set_ratio,
        score_cutoff=score_cutoff,
    )
    if result is None:
        return None

    matched_name, score, _idx = result
    return _NAME_INDEX.get(matched_name)


def latlng_to_h3(lat: float, lng: float, resolution: int = H3_RES_MEDIUM) -> str:
    """Convert lat/lng to an H3 cell index.

    Parameters
    ----------
    lat, lng:
        Coordinates in decimal degrees (WGS 84).
    resolution:
        H3 resolution level (0-15). Default is 5 (~253 km²).

    Returns
    -------
    str
        H3 cell index, or empty string if h3 is not available.
    """
    if not _H3_AVAILABLE:
        return ""
    return h3.latlng_to_cell(lat, lng, resolution)


def are_locations_nearby(
    lat1: float, lng1: float,
    lat2: float, lng2: float,
    resolution: int = H3_RES_MEDIUM,
) -> bool:
    """Check if two locations are in the same or adjacent H3 cells.

    At resolution 5 (~253 km²), "nearby" means within roughly 15-20 km.

    Parameters
    ----------
    lat1, lng1:
        First location coordinates.
    lat2, lng2:
        Second location coordinates.
    resolution:
        H3 resolution level.

    Returns
    -------
    bool
        True if the locations are in the same or adjacent H3 cells.
    """
    if not _H3_AVAILABLE:
        return False
    cell1 = h3.latlng_to_cell(lat1, lng1, resolution)
    cell2 = h3.latlng_to_cell(lat2, lng2, resolution)
    if cell1 == cell2:
        return True
    # Check if adjacent (k-ring of 1)
    neighbors = h3.grid_disk(cell1, 1)
    return cell2 in neighbors


def cities_near(lat: float, lng: float, resolution: int = H3_RES_COARSE) -> list[City]:
    """Find gazetteer cities near a given coordinate using H3 spatial indexing.

    Parameters
    ----------
    lat, lng:
        Query coordinates.
    resolution:
        H3 resolution level for proximity search. Coarser = wider search.

    Returns
    -------
    list[City]
        Cities in the same or adjacent H3 cells at the given resolution.
    """
    if not _H3_AVAILABLE:
        return []

    center = h3.latlng_to_cell(lat, lng, resolution)
    ring = h3.grid_disk(center, 1)

    # We need to compare at the same resolution
    results: list[City] = []
    for city in AFRICAN_CITIES:
        if city.lat == 0.0 and city.lng == 0.0:
            continue
        city_cell = h3.latlng_to_cell(city.lat, city.lng, resolution)
        if city_cell in ring:
            results.append(city)

    return results
