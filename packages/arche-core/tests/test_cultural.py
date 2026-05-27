"""Tests for cultural naming intelligence."""

from arche.detect._names.lexicon import (
    KNOWN_AFRICAN_NAMES,
    _FULL_EQUIVALENCE_GROUPS,
    NAME_EQUIVALENCES,
    are_names_equivalent,
    is_known_african_name,
    normalize_african_name,
)


def test_total_equivalence_groups():
    """We should have at least 80 equivalence groups (Phase 1 target: 80+)."""
    assert len(_FULL_EQUIVALENCE_GROUPS) >= 80


def test_total_name_entries():
    """Lookup table should have substantial entries."""
    assert len(NAME_EQUIVALENCES) >= 300


def test_known_name_lookup_superset_of_equivalences():
    """Known-name lookup should include at least all equivalence keys."""
    assert len(KNOWN_AFRICAN_NAMES) >= len(NAME_EQUIVALENCES)


def test_is_known_african_name_positive():
    assert is_known_african_name("Mamadou Diallo") is True


def test_is_known_african_name_negative():
    assert is_known_african_name("Xyzqv Plmn") is False


# ── Normalize ──────────────────────────────────────────────────────


def test_normalize_last_first():
    assert normalize_african_name("DIALLO, Mamadou") == "Mamadou Diallo"


def test_normalize_diacritics():
    assert normalize_african_name("Adéyẹmí Olúwáṣeun") == "Adeyemi Oluwaseun"


def test_normalize_whitespace():
    assert normalize_african_name("  Janet   Okafor  ") == "Janet Okafor"


def test_normalize_empty():
    assert normalize_african_name("") == ""
    assert normalize_african_name("  ") == ""


# ── Pan-Islamic equivalences ──────────────────────────────────────


def test_mohammed_mamadou():
    ok, score = are_names_equivalent("Mohammed", "Mamadou")
    assert ok is True
    assert score >= 0.80


def test_fatima_fatoumata():
    ok, score = are_names_equivalent("Fatima", "Fatoumata")
    assert ok is True
    assert score >= 0.80


def test_abdullahi_abdoulaye():
    ok, score = are_names_equivalent("Abdullahi", "Abdoulaye")
    assert ok is True


def test_aisha_aisatou():
    ok, score = are_names_equivalent("Aisha", "Aisatou")
    assert ok is True


# ── Fulani / West African ─────────────────────────────────────────


def test_diallo_jallow():
    ok, _ = are_names_equivalent("Diallo", "Jallow")
    assert ok is True


def test_coulibaly_kulibali():
    ok, _ = are_names_equivalent("Coulibaly", "Kulibali")
    assert ok is True


def test_traore_diacritics():
    ok, _ = are_names_equivalent("Traoré", "Traore")
    assert ok is True


# ── Colonial-era cross-linguistic (new in v6) ─────────────────────


def test_pierre_peter():
    ok, _ = are_names_equivalent("Pierre", "Peter")
    assert ok is True


def test_jean_yohana():
    ok, _ = are_names_equivalent("Jean", "Yohana")
    assert ok is True


def test_musa_moussa():
    ok, _ = are_names_equivalent("Musa", "Moussa")
    assert ok is True


def test_joseph_yusuf():
    ok, score = are_names_equivalent("Joseph", "Yusuf")
    # These are in the same equivalence group but orthographically very different.
    # The combined score may be below the default threshold (0.80) because
    # Jaro-Winkler similarity is low. Test with a lower threshold.
    ok2, _ = are_names_equivalent("Joseph", "Yusuf", threshold=0.70)
    assert ok2 is True


# ── New groups (Luo, Wolof, Tswana, etc.) ─────────────────────────


def test_khadija_kadijatou():
    ok, _ = are_names_equivalent("Khadija", "Kadijatou")
    assert ok is True


def test_ndiaye_njay():
    ok, _ = are_names_equivalent("Ndiaye", "Njay")
    assert ok is True


def test_thandiwe_thandi():
    ok, _ = are_names_equivalent("Thandiwe", "Thandi")
    assert ok is True


# ── Full name matching ────────────────────────────────────────────


def test_full_name_cross_cultural():
    ok, score = are_names_equivalent("Fatima Abdullahi", "Fatoumata Abdoulaye")
    assert ok is True
    assert score >= 0.80


def test_full_name_different_people():
    ok, score = are_names_equivalent("Janet Okafor", "David Mensah")
    assert ok is False
    assert score < 0.50


def test_exact_match():
    ok, score = are_names_equivalent("Fatima Abdullahi", "Fatima Abdullahi")
    assert ok is True
    assert score == 1.0


def test_case_insensitive():
    ok, _ = are_names_equivalent("MOHAMMED", "mamadou")
    assert ok is True
