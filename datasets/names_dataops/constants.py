"""Constants for the naming DataOps pipeline."""

from __future__ import annotations

from pathlib import Path

DATASETS_DIR = Path(__file__).resolve().parents[1]
NAME_EQUIVALENCES_DIR = DATASETS_DIR / "name_equivalences"
DATA_DIR = DATASETS_DIR / "data"
REVIEW_DIR = DATASETS_DIR / "review"
BUNDLE_DIR = REVIEW_DIR / "bundle"
SCHEMAS_DIR = DATASETS_DIR / "schemas"
CONTRIBUTIONS_DIR = DATASETS_DIR / "contributions"

RAW_EVIDENCE_PATH = REVIEW_DIR / "raw_name_evidence_v1.jsonl"
NORMALIZED_PATH = REVIEW_DIR / "normalized_names_v1.jsonl"
CANDIDATES_JSONL_PATH = REVIEW_DIR / "candidate_equivalences_v1.jsonl"
CANDIDATES_CSV_PATH = REVIEW_DIR / "candidate_equivalences_v1.csv"
REVIEW_CSV_PATH = BUNDLE_DIR / "review_candidates_v1.csv"
APPROVED_REGISTRY_PATH = REVIEW_DIR / "approved_registry_v1.jsonl"
RUN_METADATA_PATH = REVIEW_DIR / "run_metadata_v1.json"

ENRICHED_CSV_PATH = DATA_DIR / "african_naming_equivalences_enriched.csv"
ENRICHED_JSONL_PATH = DATA_DIR / "african_naming_equivalences_enriched.jsonl"
DATASET_STATS_PATH = DATA_DIR / "dataset_stats_v1.json"
LEXICON_CSV_PATH = DATA_DIR / "african_names_lexicon_v1.csv"
LEXICON_JSONL_PATH = DATA_DIR / "african_names_lexicon_v1.jsonl"
UNIQUE_NAMES_CSV_PATH = DATA_DIR / "african_names_unique_v1.csv"
UNIQUE_NAMES_JSONL_PATH = DATA_DIR / "african_names_unique_v1.jsonl"

DEFAULT_COUNTRY_SCOPE = "west_east_core16"
DEFAULT_WIKIDATA_ENDPOINT = "https://query.wikidata.org/sparql"
DEFAULT_SOURCE_LICENSE = "CC0-1.0 (Wikidata)"
DEFAULT_USER_AGENT = "arche-names-dataops/1.0 (https://github.com/Plehthore/arche)"

COUNTRY_SCOPE_CORE16: dict[str, str] = {
    "NG": "Q1033",  # Nigeria
    "GH": "Q117",  # Ghana
    "SN": "Q1041",  # Senegal
    "GM": "Q1005",  # Gambia
    "SL": "Q1044",  # Sierra Leone
    "LR": "Q1014",  # Liberia
    "GN": "Q1006",  # Guinea
    "ML": "Q912",  # Mali
    "NE": "Q1032",  # Niger
    "KE": "Q114",  # Kenya
    "UG": "Q1036",  # Uganda
    "TZ": "Q924",  # Tanzania
    "ET": "Q115",  # Ethiopia
    "SO": "Q1045",  # Somalia
    "ER": "Q986",  # Eritrea
    "RW": "Q1037",  # Rwanda
}

WIKIDATA_LANGUAGE_TAGS = ("en", "fr", "pt", "ar", "sw", "am", "ha", "yo", "ig", "so")

NAME_TYPE_TO_PROPERTY = {
    "given": "P735",
    "family": "P734",
}

WEST_AFRICA_ISO2 = {"NG", "GH", "SN", "GM", "SL", "LR", "GN", "ML", "NE"}
EAST_AFRICA_ISO2 = {"KE", "UG", "TZ", "ET", "SO", "ER", "RW"}
