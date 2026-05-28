"""Shared fixtures for arche SDK tests."""

from __future__ import annotations

import pytest


@pytest.fixture
def sample_identity_text() -> str:
    return (
        "Fatima Abdullahi called from +234 803 555 7890 about her NIN 12345678901. "
        "She is the same person as Fatoumata Abdoulaye from the Kaduna voter register "
        "and Fatimah Abdullah at the Lagos General Hospital."
    )


@pytest.fixture
def sample_fhir_patient() -> dict:
    return {
        "resourceType": "Patient",
        "id": "example-001",
        "name": [
            {
                "use": "official",
                "family": "Abdullahi",
                "given": ["Fatima"],
            }
        ],
        "identifier": [
            {
                "system": "urn:ng:nin",
                "value": "12345678901",
            }
        ],
        "telecom": [
            {
                "system": "phone",
                "value": "+234 803 555 7890",
                "use": "mobile",
            }
        ],
        "gender": "female",
        "birthDate": "1990-03-15",
        "address": [
            {
                "line": ["14 Awolowo Road"],
                "city": "Ikoyi",
                "state": "Lagos",
                "country": "NG",
            }
        ],
    }


@pytest.fixture
def sample_fhir_patients() -> list[dict]:
    return [
        {
            "resourceType": "Patient",
            "id": "opencrvs-001",
            "name": [{"use": "official", "family": "Abdullahi", "given": ["Fatima"]}],
            "identifier": [{"system": "urn:ng:nin", "value": "12345678901"}],
            "telecom": [{"system": "phone", "value": "+234 803 555 7890"}],
            "birthDate": "1990-03-15",
            "address": [{"city": "Lagos", "country": "NG"}],
        },
        {
            "resourceType": "Patient",
            "id": "mosip-002",
            "name": [{"use": "official", "family": "Abdoulaye", "given": ["Fatoumata"]}],
            "identifier": [{"system": "urn:ng:bvn", "value": "22100987654"}],
            "telecom": [{"system": "phone", "value": "+234 803 555 7890"}],
            "birthDate": "1990-03-15",
            "address": [{"city": "Lagos", "country": "NG"}],
        },
        {
            "resourceType": "Patient",
            "id": "dhis2-003",
            "name": [{"use": "official", "family": "Abdullah", "given": ["Fatimah"]}],
            "telecom": [{"system": "phone", "value": "+2348035557890"}],
            "address": [{"city": "Ikeja", "state": "Lagos", "country": "NG"}],
        },
    ]
