from __future__ import annotations

from datetime import datetime

import pytest

from datasets.names_dataops.io_utils import validate_rows
from datasets.names_dataops.schemas import CuratedContributionCSVV1, RawNameEvidenceV1


def test_raw_schema_validates() -> None:
    rows = [
        {
            "source": "wikidata",
            "source_id": "Q123",
            "source_license": "CC0",
            "name_raw": "Amina",
            "name_type": "given",
            "country_iso2": "ng",
            "language_tag": "en",
            "evidence_count": 2,
            "fetched_at": datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
        },
    ]
    validated = validate_rows(RawNameEvidenceV1, rows)
    assert validated[0]["country_iso2"] == "NG"


def test_curated_csv_requires_license() -> None:
    rows = [
        {
            "source": "manual_csv",
            "source_id": "x1",
            "name_raw": "Amina",
            "name_type": "given",
            "country_iso2": "NG",
            "language_tag": "en",
            "evidence_count": 1,
            "fetched_at": "2026-01-01T00:00:00+00:00",
        },
    ]
    with pytest.raises(ValueError):
        validate_rows(CuratedContributionCSVV1, rows)


def test_curated_csv_rejects_invalid_name_type() -> None:
    rows = [
        {
            "source": "manual_csv",
            "source_id": "x1",
            "source_license": "CC-BY-4.0",
            "name_raw": "Amina",
            "name_type": "nickname",
            "country_iso2": "NG",
            "language_tag": "en",
            "evidence_count": 1,
            "fetched_at": "2026-01-01T00:00:00+00:00",
        },
    ]
    with pytest.raises(ValueError):
        validate_rows(CuratedContributionCSVV1, rows)
