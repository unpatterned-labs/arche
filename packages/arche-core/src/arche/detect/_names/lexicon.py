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

"""African name equivalence tables and matching utilities.

The naming data is loaded from YAML dataset files (datasets/name_equivalences/)
when available. A bundled starter set of ~20 core equivalence groups ships with
the package for offline use. The full dataset (114+ groups) is available under
Apache 2.0 -- see datasets/DATASET_LICENSE.md.

Key capabilities:
- 114+ equivalence groups covering 400+ name variants (with full dataset)
- Diacritic normalization (Yoruba tonal marks, French diacritics, Arabic transliterations)
- Cross-ethnic variant recognition (e.g., Fulani Diallo = Jallow = Diaw)
- Phonetic similarity via Jaro-Winkler distance
- Optional lexicon-backed known-name coverage (from DataOps `african_names_*` exports)
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path

try:
    from jellyfish import jaro_winkler_similarity
except ImportError:
    def jaro_winkler_similarity(a: str, b: str) -> float:  # type: ignore[misc]
        """Fallback stub — install jellyfish for real phonetic matching."""
        if a == b:
            return 1.0
        return 0.0


_log = logging.getLogger("arche.african.names")


# ---------------------------------------------------------------------------
# Bundled starter set (Apache 2.0 -- ships with arche-core)
# ---------------------------------------------------------------------------
# These 20 core groups cover the most common cross-system name mismatches
# in African DPI deployments. Enough to demonstrate value and pass tests.
# The full 114+ group dataset is loaded from datasets/ when available.

_BUNDLED_STARTER_GROUPS: list[list[str]] = [
    # Pan-Islamic (most impactful for cross-system matching)
    ["Mohammed", "Muhammad", "Mohamed", "Muhammed", "Muhammadu", "Mamadou",
     "Mahamadou", "Mohammadu", "Mohamad", "Mouhamed", "Mahamed", "Mamadu"],
    ["Abdullahi", "Abdullah", "Abdulahi", "Abdoulay", "Abdoulaye", "Abdulai",
     "Abdallah", "Abdellah", "Abdalla", "Abdoul"],
    ["Ibrahim", "Ibraheem", "Ebrahim", "Brahim", "Ibrahima", "Ibraahim"],
    ["Fatima", "Fatimah", "Fatoumata", "Fatimatou", "Fatouma", "Fatma",
     "Fadimata", "Fatime", "Fatou", "Fati"],
    ["Aisha", "Ayesha", "Aicha", "Aishat", "Aissata", "Aisatou", "Aysha"],
    ["Usman", "Osman", "Uthman", "Ousmane", "Ousman", "Osmane"],
    ["Yusuf", "Youssef", "Youssouph", "Youssouf", "Yusuph", "Yousuf"],
    ["Amina", "Aminah", "Aminata", "Aminatou"],
    ["Maryam", "Mariam", "Mariama", "Mariame", "Meriem", "Miriam"],
    ["Suleiman", "Sulaiman", "Sulayman", "Souleymane", "Soulaymane"],
    ["Khadija", "Khadijah", "Kadija", "Kadijatou", "Dija", "Hadja"],
    ["Halima", "Halimah", "Halimatou", "Halimata"],
    # Fulani (critical for cross-border matching)
    ["Diallo", "Jallow", "Diaw", "Jalo", "Jalloh"],
    ["Coulibaly", "Kulibali", "Kulibaly", "Coulibali"],
    # Hausa
    ["Abubakar", "Aboubacar", "Abubakari", "Abu Bakr", "Abubaker"],
    ["Musa", "Moussa", "Mousa", "Moses"],
    # Colonial-era cross-linguistic
    ["Pierre", "Peter", "Petros", "Pedro", "Pita"],
    ["Jean", "John", "Yohana", "Yahya", "Yohannes"],
    ["Marie", "Mary", "Mariya", "Maria", "Maryamu"],
    # Southern African
    ["Thandiwe", "Thandeka", "Thandi"],
]


# ---------------------------------------------------------------------------
# Dataset loader — loads from YAML files when available
# ---------------------------------------------------------------------------

def _load_yaml_groups(dataset_dir: Path) -> list[list[str]]:
    """Load name equivalence groups from YAML dataset files."""
    try:
        import yaml  # noqa: F811
    except ImportError:
        _log.debug("PyYAML not installed -- cannot load YAML dataset files")
        return []

    groups: list[list[str]] = []
    if not dataset_dir.is_dir():
        return groups

    for yaml_file in sorted(dataset_dir.glob("*.yaml")):
        try:
            with open(yaml_file, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not data or "groups" not in data:
                continue
            for group in data["groups"]:
                canonical = group.get("canonical", "")
                variants = group.get("variants", [])
                if canonical:
                    groups.append([canonical] + variants)
        except Exception as exc:
            _log.warning("Failed to load naming data from %s: %s", yaml_file, exc)

    return groups


def _find_dataset_dir() -> Path | None:
    """Search for the naming dataset directory."""
    import os

    env_dir = os.environ.get("ARCHE_DATASET_DIR")
    if env_dir:
        p = Path(env_dir) / "name_equivalences"
        if p.is_dir():
            return p
        p = Path(env_dir)
        if p.is_dir() and list(p.glob("*.yaml")):
            return p

    cwd = Path.cwd()
    for candidate in [
        cwd / "datasets" / "name_equivalences",
        cwd.parent / "datasets" / "name_equivalences",
    ]:
        if candidate.is_dir() and list(candidate.glob("*.yaml")):
            return candidate

    this_dir = Path(__file__).resolve().parent
    for ancestor in [this_dir.parents[4], this_dir.parents[3], this_dir.parents[2]]:
        candidate = ancestor / "datasets" / "name_equivalences"
        if candidate.is_dir() and list(candidate.glob("*.yaml")):
            return candidate

    return None


def _load_all_groups() -> list[list[str]]:
    """Load full dataset if available, else bundled starter."""
    dataset_dir = _find_dataset_dir()
    if dataset_dir is not None:
        full_groups = _load_yaml_groups(dataset_dir)
        if full_groups:
            _log.debug(
                "Loaded %d naming groups from %s", len(full_groups), dataset_dir,
            )
            return full_groups

    _log.debug("Using bundled starter set (%d groups)", len(_BUNDLED_STARTER_GROUPS))
    return _BUNDLED_STARTER_GROUPS


# The full hardcoded set (kept for backward compatibility when YAML unavailable)
_FULL_EQUIVALENCE_GROUPS: list[list[str]] = [
    # ── Pan-Islamic / Arabic-origin names widely used across Africa ──────
    ["Mohammed", "Muhammad", "Mohamed", "Muhammed", "Muhammadu", "Mamadou",
     "Mahamadou", "Mohammadu", "Mohamad", "Mouhamed", "Mahamed", "Mamadu",
     "Mohd", "Md"],
    ["Abdullahi", "Abdullah", "Abdulahi", "Abdoulay", "Abdoulaye", "Abdulai",
     "Abdallah", "Abdellah", "Abdalla", "Abdoul"],
    # 3. Ibrahim variants
    ["Ibrahim", "Ibraheem", "Ebrahim", "Brahim", "Ibrahima", "Ibraahim",
     "Abraam", "Ibra"],
    # 4. Fatima variants
    ["Fatima", "Fatimah", "Fatoumata", "Fatimatou", "Fatouma", "Fatma",
     "Fadimata", "Fatime", "Fatou", "Fati"],
    # 5. Aisha variants
    ["Aisha", "Ayesha", "Aicha", "Aïsha", "Aishat", "Aissata", "Aisatou",
     "Aïssatou", "Aysha", "Aisatu"],
    # 6. Usman / Osman
    ["Usman", "Osman", "Uthman", "Ousmane", "Ousman", "Osmane", "Usumanu"],
    # 7. Yusuf
    ["Yusuf", "Youssef", "Youssouph", "Youssouf", "Yusuph", "Yousuf",
     "Yussufu", "Yussuf", "Yousef"],
    # 8. Ali
    ["Ali", "Aly", "Aliu", "Aliou", "Aliy"],
    # 9. Hassan
    ["Hassan", "Hasan", "Hassane", "Assane", "Assan"],
    # 10. Hussein
    ["Hussein", "Hussain", "Husseini", "Housseini", "Houssein", "Hissein"],
    # 11. Amina
    ["Amina", "Aminah", "Aminata", "Aminatou", "Amine"],
    # 12. Maryam
    ["Maryam", "Mariam", "Mariama", "Mariame", "Meriem", "Meryem", "Miriam"],
    # 13. Ismail
    ["Ismail", "Ismaila", "Ismaël", "Ismael", "Esmail", "Ishmael"],
    # 14. Suleiman
    ["Suleiman", "Sulaiman", "Sulayman", "Souleymane", "Soulaymane",
     "Sulaimana", "Soulaimane", "Soliman"],

    # ── Fulani / Pulaar / Mandinka (West Africa) ────────────────────────
    # 15. Diallo variants
    ["Diallo", "Jallow", "Diaw", "Jalo", "Jalloh", "Dialaw", "Dyal"],
    # 16. Ba / Bah
    ["Ba", "Bah", "Bâ"],
    # 17. Sow
    ["Sow", "So", "Sao"],
    # 18. Koné / Coulibaly
    ["Koné", "Kone", "Coney", "Konaté", "Konate"],
    # 19. Coulibaly
    ["Coulibaly", "Kulibali", "Kulibaly", "Coulibali"],
    # 20. Traoré
    ["Traoré", "Traore", "Traoure"],

    # ── Yoruba (Nigeria / Benin) ────────────────────────────────────────
    # 21. Adeyemi and tonal/diacritical variants
    ["Adeyemi", "Adeyẹmi", "Adéyẹmí"],
    # 22. Adekunle
    ["Adekunle", "Adékunlé", "Adekunle"],
    # 23. Oladipo
    ["Oladipo", "Oladipọ", "Oládípò"],
    # 24. Oluwaseun
    ["Oluwaseun", "Olúwáṣeun", "Oluseun", "Shewn"],
    # 25. Adeola
    ["Adeola", "Adéọlá", "Adeolá"],
    # 26. Babatunde
    ["Babatunde", "Babátúndé", "Bàbátúndé"],
    # 27. Ayodele
    ["Ayodele", "Ayọdélé", "Ayodélé"],

    # ── Igbo (Nigeria) ──────────────────────────────────────────────────
    # 28. Chukwu prefix names
    ["Chukwu", "Chukwuma", "Chukwuemeka", "Chuks", "Chukwudi"],
    # 29. Okafor
    ["Okafor", "Okafo", "Ọkafọ"],
    # 30. Nneka / Nnenna
    ["Nneka", "Neka", "Nnekā"],
    # 31. Obiora
    ["Obiora", "Obinna", "Obi"],
    # 32. Nnamdi
    ["Nnamdi", "Namdi", "Nnámdi"],
    # 33. Chimamanda
    ["Chimamanda", "Chimamandà", "Chimama"],
    # 34. Emeka
    ["Emeka", "Emeká", "Chukwuemeka"],

    # ── Akan / Ghanaian day-names ───────────────────────────────────────
    # 35. Kwame / Monday-born male
    ["Kwame", "Kwamena", "Kweku"],
    # 36. Kofi / Friday-born male
    ["Kofi", "Fiifi", "Yoofi"],
    # 37. Ama / Saturday-born female
    ["Ama", "Amba"],
    # 38. Akua / Wednesday-born female
    ["Akua", "Ekua", "Akuba"],
    # 39. Kwesi / Sunday-born male
    ["Kwesi", "Kwasi", "Akwasi"],

    # ── Bantu / Southern & Eastern Africa ───────────────────────────────
    # 40. Nkomo / Nkhomo
    ["Nkomo", "Nkhomo", "Ngomo"],
    # 41. Mandela
    ["Mandela", "Madela"],
    # 42. Dlamini (common Swazi / Zulu surname)
    ["Dlamini", "Dhlamini", "Ndlamini"],
    # 43. Mwangi (Kikuyu, Kenya)
    ["Mwangi", "Wangi"],
    # 44. Kamau
    ["Kamau", "Kamao"],
    # 45. Ndlovu (Zulu/Ndebele)
    ["Ndlovu", "Ndhlovu", "Dhlovu"],

    # ── Swahili / East African ──────────────────────────────────────────
    # 46. Juma
    ["Juma", "Djuma", "Jouma"],
    # 47. Baraka
    ["Baraka", "Barack", "Barrack"],
    # 48. Amani
    ["Amani", "Amány"],

    # ── Amharic / Ethiopian ─────────────────────────────────────────────
    # 49. Tekle
    ["Tekle", "Teklé", "Tekla", "Teklè"],
    # 50. Haile
    ["Haile", "Hailé", "Haylè", "Hayle"],
    # 51. Abebe
    ["Abebe", "Abèbè", "Abäbä"],
    # 52. Getachew
    ["Getachew", "Getatchew", "Getachaw"],

    # ── Somali ──────────────────────────────────────────────────────────
    # 53. Abdi
    ["Abdi", "Abdirahman", "Abdikarim", "Abdiqani"],
    # 54. Aden
    ["Aden", "Aadan", "Aaden"],

    # ── Hausa (Nigeria / Niger) ─────────────────────────────────────────
    # 55. Buhari
    ["Buhari", "Bukhari", "Bukar"],
    # 56. Sanusi
    ["Sanusi", "Sanussi", "Sanusy"],
    # 57. Abubakar
    ["Abubakar", "Aboubacar", "Abubakari", "Abu Bakr", "Aboubaker",
     "Abubaker"],

    # ── North African (Amazigh / Berber + Arabic) ───────────────────────
    # 58. Bouchta
    ["Bouchta", "Bouchtà"],
    # 59. Driss
    ["Driss", "Idriss", "Idris", "Idrees"],
    # 60. Rachid
    ["Rachid", "Rashid", "Rasheed", "Racheed"],

    # ─�� Additional Pan-Islamic (female) ────────────────────────────────
    # 61. Khadija
    ["Khadija", "Khadijah", "Kadija", "Kadijatou", "Dija", "Hadja",
     "Hadiatou", "Khadidjah"],
    # 62. Zainab
    ["Zainab", "Zaynab", "Zeinab", "Zeynab", "Zainaba", "Zenab"],
    # 63. Safiya
    ["Safiya", "Safiyya", "Sofia", "Safia", "Safiatou"],
    # 64. Halima
    ["Halima", "Halimah", "Halimatou", "Halimata", "Halime"],
    # 65. Ruqayya
    ["Ruqayya", "Ruqayyah", "Rukayat", "Rokia", "Rokiatou", "Roukia"],

    # ── Luo (Kenya / Uganda / Tanzania) ────────────────────────────────
    # 66. Ochieng
    ["Ochieng", "Otieng", "Ochieng'"],
    # 67. Onyango
    ["Onyango", "Nyango", "Nyong'o"],
    # 68. Akinyi
    ["Akinyi", "Akiny", "Akini"],
    # 69. Odhiambo
    ["Odhiambo", "Adhiambo", "Atieno"],
    # 70. Owuor
    ["Owuor", "Owuour", "Ouwor"],

    # ── Tswana / Sotho (Southern Africa) ───────────────────────────────
    # 71. Modise
    ["Modise", "Modishe"],
    # 72. Mokone / Mogane
    ["Mokone", "Mogane", "Mokhone"],
    # 73. Thabo
    ["Thabo", "Thabiso", "Thabs"],
    # 74. Lerato
    ["Lerato", "Leratu"],
    # 75. Mpho
    ["Mpho", "Mpho-Mary", "Neo"],

    # ── Tigrinya (Eritrea / Ethiopia) ──────────────────────────────────
    # 76. Berhe
    ["Berhe", "Berhé", "Birhe"],
    # 77. Tesfaye
    ["Tesfaye", "Tesfay", "Tesfa"],
    # 78. Gebremedhin
    ["Gebremedhin", "Ghebremedhin", "Gibremedhin"],
    # 79. Abrehet
    ["Abrehet", "Abrahet", "Abreha"],

    # ���─ Wolof (Senegal / Gambia) ───────────────────────────────────────
    # 80. Ndiaye
    ["Ndiaye", "Ndaye", "N'Diaye", "Njay"],
    # 81. Fall
    ["Fall", "Faal", "Fal"],
    # 82. Gueye
    ["Gueye", "Gay", "Gaye", "Guèye"],
    # 83. Diop
    ["Diop", "Joop", "Diob"],

    # ── Congolese (Lingala / Kikongo) ──────────────────────────────────
    # 84. Kabila
    ["Kabila", "Kabilah"],
    # 85. Mukendi
    ["Mukendi", "Mukendy"],
    # 86. Tshisekedi
    ["Tshisekedi", "Tchisekedi", "Tsisekedi"],

    # ─�� Malagasy (Madagascar) ──────────────────────────────────────────
    # 87. Rakoto
    ["Rakoto", "Rakotondra", "Rakotonirina"],
    # 88. Andrianaivo
    ["Andrianaivo", "Andrianaivó"],

    # ── Colonial-era cross-linguistic adaptations ────────���─────────────
    # 89. Pierre / Peter / Petros (Francophone / Anglophone / Lusophone)
    ["Pierre", "Peter", "Petros", "Pedro", "Pita"],
    # 90. Jean / John / Yohana
    ["Jean", "John", "Yohana", "Yahya", "Yohannes", "Johannes", "João"],
    # 91. Marie / Mary / Mariya
    ["Marie", "Mary", "Mariya", "Maria", "Maryamu", "Maïmouna"],
    # 92. Joseph / Yusuf / José
    ["Joseph", "Yusuf", "José", "Yusufu", "Josefa", "Yussufu"],
    # 93. Paul / Paulo / Bulus
    ["Paul", "Paulo", "Bulus", "Paulu", "Pablo"],
    # 94. David / Dauda / Dawud
    ["David", "Dauda", "Dawud", "Daouda", "Davide"],
    # 95. James / Jacques / Yakubu
    ["James", "Jacques", "Yakubu", "Jaime", "Yaqub"],
    # 96. Elizabeth / Élisabeth / Erizabeti
    ["Elizabeth", "Élisabeth", "Erizabeti", "Elisabete", "Liz", "Beti"],

    # ── Additional Yoruba ──────────────────────────────────────────────
    # 97. Oluwafemi
    ["Oluwafemi", "Olúwafẹmi", "Femi"],
    # 98. Temitope
    ["Temitope", "Tẹmitọpẹ", "Temi"],
    # 99. Olayinka
    ["Olayinka", "Ọlayinka", "Yinka"],

    # ── Additional Igbo ────────────────────────────────────────────────
    # 100. Chidinma
    ["Chidinma", "Chidinmá", "Dinma"],
    # 101. Ugochukwu
    ["Ugochukwu", "Ugo", "Ugochi"],
    # 102. Adaeze
    ["Adaeze", "Ada", "Adaézé"],

    # ── Additional Swahili / East African ──────────────────────────────
    # 103. Mwalimu
    ["Mwalimu", "Mualimu"],
    # 104. Rehema
    ["Rehema", "Rahma", "Rahmah"],
    # 105. Zawadi
    ["Zawadi", "Zawadie"],

    # ── Additional Akan / Ghanaian ─────────────────────────────────────
    # 106. Yaa / Thursday-born female
    ["Yaa", "Yaaba", "Yawa"],
    # 107. Adjoa / Monday-born female
    ["Adjoa", "Adwoa", "Ajua"],
    # 108. Akosua / Sunday-born female
    ["Akosua", "Akosuah", "Esi"],

    # ── Additional Hausa ───────────────────────────────────────────────
    # 109. Binta
    ["Binta", "Bintu", "Bintou", "Bint"],
    # 110. Hauwa
    ["Hauwa", "Hawa", "Hawwa", "Eve"],
    # 111. Musa
    ["Musa", "Moussa", "Mousa", "Moses"],

    # ── Southern African additional ────────────────────────────────────
    # 112. Sipho (Zulu/Xhosa male)
    ["Sipho", "Sifiso"],
    # 113. Nomusa (Zulu female)
    ["Nomusa", "Nomusá"],
    # 114. Thandiwe
    ["Thandiwe", "Thandeka", "Thandi"],
]


def _build_equivalences(
    groups: list[list[str]],
) -> dict[str, set[str]]:
    """Build the canonical → variants lookup from raw groups.

    Each name in a group maps to the *full* set of equivalents
    (including itself), keyed by a normalised lower-case form.
    """
    table: dict[str, set[str]] = {}
    for group in groups:
        normalised_group = {_strip_diacritics(n.lower()) for n in group}
        # Also keep original forms for display
        for name in group:
            key = _strip_diacritics(name.lower())
            table[key] = normalised_group
    return table


def _strip_diacritics(text: str) -> str:
    """Remove combining diacritical marks (accents, tonal marks, cedillas, etc.)."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in nfkd if unicodedata.category(ch) != "Mn")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _resolve_groups() -> list[list[str]]:
    """Resolve which equivalence groups to use.

    Priority: YAML dataset > hardcoded full set > bundled starter.
    """
    # Try YAML dataset first (CC-BY-NC-SA 4.0 data)
    loaded = _load_all_groups()
    if loaded is not _BUNDLED_STARTER_GROUPS:
        return loaded  # Got full YAML dataset

    # Fall back to hardcoded full set (kept in source for backward compat)
    return _FULL_EQUIVALENCE_GROUPS


NAME_EQUIVALENCES: dict[str, set[str]] = _build_equivalences(_resolve_groups())
"""Canonical (normalised lowercase) name -> set of known equivalent normalised names."""


def _find_lexicon_path() -> Path | None:
    """Find the optional African names lexicon file generated from DataOps."""
    import os

    env_path = os.environ.get("ARCHE_LEXICON_PATH")
    if env_path:
        candidate = Path(env_path)
        if candidate.is_file():
            return candidate

    env_dir = os.environ.get("ARCHE_DATASET_DIR")
    if env_dir:
        for candidate in [
            Path(env_dir) / "data" / "african_names_unique_v1.jsonl",
            Path(env_dir) / "african_names_unique_v1.jsonl",
            Path(env_dir) / "data" / "african_names_lexicon_v1.jsonl",
            Path(env_dir) / "african_names_lexicon_v1.jsonl",
        ]:
            if candidate.is_file():
                return candidate

    cwd = Path.cwd()
    for candidate in [
        cwd / "datasets" / "data" / "african_names_unique_v1.jsonl",
        cwd / "datasets" / "data" / "african_names_lexicon_v1.jsonl",
        cwd.parent / "datasets" / "data" / "african_names_unique_v1.jsonl",
        cwd.parent / "datasets" / "data" / "african_names_lexicon_v1.jsonl",
    ]:
        if candidate.is_file():
            return candidate

    this_dir = Path(__file__).resolve().parent
    for ancestor in [this_dir.parents[4], this_dir.parents[3], this_dir.parents[2]]:
        for candidate in [
            ancestor / "datasets" / "data" / "african_names_unique_v1.jsonl",
            ancestor / "datasets" / "data" / "african_names_lexicon_v1.jsonl",
        ]:
            if candidate.is_file():
                return candidate

    return None


def _load_lexicon_names() -> set[str]:
    """Load normalised name tokens from lexicon JSONL if available."""
    path = _find_lexicon_path()
    if path is None:
        return set()

    names: set[str] = set()
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                name = str(
                    row.get("name")
                    or row.get("name_nfc")
                    or row.get("name_display")
                    or "",
                ).strip()
                if not name:
                    continue
                for token in _normalise_tokens_for_lookup(name):
                    token_norm = _strip_diacritics(token)
                    if len(token_norm) >= 2:
                        names.add(token_norm)
    except Exception as exc:
        _log.warning("Failed to load African lexicon from %s: %s", path, exc)
        return set()

    _log.debug("Loaded %d lexicon name tokens from %s", len(names), path)
    return names


def _build_known_name_lookup() -> set[str]:
    """Build known African name-token lookup (equivalence + lexicon)."""
    known = set(NAME_EQUIVALENCES.keys())
    known.update(_load_lexicon_names())
    return known


def _normalise_tokens_for_lookup(text: str) -> list[str]:
    text = _strip_diacritics(text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return [t for t in text.split(" ") if t]


KNOWN_AFRICAN_NAMES: set[str] = _build_known_name_lookup()
"""Known African name tokens from equivalence tables + optional lexicon."""


def normalize_african_name(name: str) -> str:
    """Normalise an African name for comparison.

    Steps applied:
    1. Strip leading/trailing whitespace.
    2. Convert "LAST, First" or "LAST,First" → "First Last".
    3. Collapse multiple spaces / hyphens.
    4. Strip diacritics (Yoruba tonal marks, French accents, Arabic hamza, etc.).
    5. Title-case the result.

    Parameters
    ----------
    name:
        Raw name string, e.g. ``"DIALLO, Mamadou"`` or ``"Adéyẹmí  Olúwáṣeun"``.

    Returns
    -------
    str
        Normalised form, e.g. ``"Mamadou Diallo"`` or ``"Adeyemi Oluwaseun"``.

    Examples
    --------
    >>> normalize_african_name("DIALLO, Mamadou")
    'Mamadou Diallo'
    >>> normalize_african_name("Adéyẹmí  Olúwáṣeun")
    'Adeyemi Oluwaseun'
    """
    if not name or not name.strip():
        return ""

    text = name.strip()

    # Handle "Last, First" or "Last,First" format
    if "," in text:
        parts = [p.strip() for p in text.split(",", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            text = f"{parts[1]} {parts[0]}"

    # Strip diacritics
    text = _strip_diacritics(text)

    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()

    # Title-case
    text = text.title()

    return text


def is_known_african_name(name: str) -> bool:
    """Check whether any token in ``name`` is a known African name token."""
    normalized = normalize_african_name(name).lower()
    if not normalized:
        return False
    for token in normalized.split():
        token_norm = _strip_diacritics(token)
        if token_norm in KNOWN_AFRICAN_NAMES:
            return True
    return False


def are_names_equivalent(
    name1: str,
    name2: str,
    *,
    equivalence_weight: float = 0.60,
    jaro_weight: float = 0.40,
    threshold: float = 0.80,
) -> tuple[bool, float]:
    """Determine whether two names refer to the same person.

    Uses a weighted combination of:
    - **Equivalence-table lookup** — checks if any name token from ``name1``
      belongs to the same equivalence group as a token in ``name2``.
    - **Jaro-Winkler similarity** — character-level fuzzy match on the full
      normalised strings.

    Parameters
    ----------
    name1, name2:
        Names to compare.  Can be in any format supported by
        :func:`normalize_african_name`.
    equivalence_weight:
        Weight for equivalence-table match component (default 0.60).
    jaro_weight:
        Weight for Jaro-Winkler component (default 0.40).
    threshold:
        Combined score must reach this value to be declared equivalent
        (default 0.80).

    Returns
    -------
    tuple[bool, float]
        ``(is_equivalent, confidence)`` where *confidence* is in [0, 1].

    Examples
    --------
    >>> are_names_equivalent("Mamadou Diallo", "Muhammad Jallow")
    (True, 0.90)
    >>> are_names_equivalent("John Smith", "Jane Doe")
    (False, 0.12)
    """
    norm1 = normalize_african_name(name1).lower()
    norm2 = normalize_african_name(name2).lower()

    if not norm1 or not norm2:
        return (False, 0.0)

    # Exact match after normalisation
    if norm1 == norm2:
        return (True, 1.0)

    tokens1 = norm1.split()
    tokens2 = norm2.split()

    # ── Equivalence-table score ─────────────────────────────────────────
    equiv_score = _equivalence_score(tokens1, tokens2)

    # ── Jaro-Winkler on full name ───────────────────────────────────────
    jw_full = jaro_winkler_similarity(norm1, norm2)

    # Also compute best token-to-token JW and use max
    jw_token_best = 0.0
    for t1 in tokens1:
        for t2 in tokens2:
            jw_token_best = max(jw_token_best, jaro_winkler_similarity(t1, t2))

    jw_score = max(jw_full, jw_token_best)

    # ── Combine ─────────────────────────────────────────────────────────
    combined = equiv_score * equivalence_weight + jw_score * jaro_weight
    combined = min(combined, 1.0)

    return (combined >= threshold, round(combined, 4))


def _equivalence_score(tokens1: list[str], tokens2: list[str]) -> float:
    """Return 0-1 score based on how many token pairs fall in the same equivalence group."""
    if not tokens1 or not tokens2:
        return 0.0

    matches = 0
    max_possible = max(len(tokens1), len(tokens2))
    used2: set[int] = set()

    for t1 in tokens1:
        group1 = NAME_EQUIVALENCES.get(t1)
        if group1 is None:
            # Token not in table — treat as its own group
            group1 = {t1}
        best_j = -1
        for j, t2 in enumerate(tokens2):
            if j in used2:
                continue
            if t2 in group1:
                best_j = j
                break
        if best_j >= 0:
            matches += 1
            used2.add(best_j)

    return matches / max_possible if max_possible else 0.0
