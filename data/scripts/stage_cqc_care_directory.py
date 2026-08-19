#!/usr/bin/env python
"""Download and scope a pinned Care Quality Commission location export.

The CQC directory contains regulated locations, not a universal physical-site
master. Select one exact CQC service type per run and preserve its location and
provider identifiers before any matching.

Example::

    uv run python data/scripts/stage_cqc_care_directory.py \
        --url https://www.cqc.org.uk/system/files/2026-08/19_August_2026_CQC_directory.csv \
        --service-type Hospital \
        --output C:\\tmp\\arche-cqc-hospitals-2026-08-19
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

SOURCE_PAGE = "https://www.cqc.org.uk/about-us/transparency/using-cqc-data"
LICENSE = "Open Government Licence v3.0"
USER_AGENT = "Arche data intake (https://github.com/unpatterned-labs/arche)"
HEADER = "Name"
OUTPUT_FIELDS = [
    "cqc_location_id",
    "cqc_provider_id",
    "name",
    "also_known_as",
    "address",
    "postcode",
    "phone",
    "website",
    "service_types",
    "specialisms_services",
    "provider_name",
    "local_authority",
    "region",
    "location_url",
    "latest_check_date",
]


def _sha256(path: Path) -> str:
    """Return the SHA-256 checksum for ``path``."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _header_index(path: Path) -> int:
    """Find CQC's header after its human-readable metadata preamble."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for index, row in enumerate(csv.reader(handle)):
            if row and row[0].strip() == HEADER:
                return index
    raise ValueError("Could not find the CQC directory header row")


def _source_date(path: Path) -> str:
    """Return CQC's source-date note when it is present in the preamble."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        for _ in range(_header_index(path)):
            row = next(reader, [])
            value = (row[0] if row else "").strip()
            if value.startswith("This data was produced on "):
                return value.removeprefix("This data was produced on ")
    return ""


def _rows(path: Path) -> list[dict[str, str]]:
    """Read the CQC records while skipping its metadata preamble."""
    header_index = _header_index(path)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for _ in range(header_index):
            next(handle)
        return list(csv.DictReader(handle))


def _has_service_type(row: dict[str, str], service_type: str) -> bool:
    """Return whether a pipe-delimited CQC service type exactly matches."""
    choices = (value.strip().casefold() for value in row["Service types"].split("|"))
    return service_type.casefold() in choices


def _normalise(row: dict[str, str]) -> dict[str, str]:
    """Map a CQC row to a stable, reviewable location record."""
    return {
        "cqc_location_id": row["CQC Location ID (for office use only)"].strip(),
        "cqc_provider_id": row["CQC Provider ID (for office use only)"].strip(),
        "name": row["Name"].strip(),
        "also_known_as": row["Also known as"].strip(),
        "address": row["Address"].strip(),
        "postcode": row["Postcode"].strip(),
        "phone": row["Phone number"].strip(),
        "website": row["Service's website (if available)"].strip(),
        "service_types": row["Service types"].strip(),
        "specialisms_services": row["Specialisms/services"].strip(),
        "provider_name": row["Provider name"].strip(),
        "local_authority": row["Local authority"].strip(),
        "region": row["Region"].strip(),
        "location_url": row["Location URL"].strip(),
        "latest_check_date": row["Date of latest check"].strip(),
    }


def _prepare_output(path: Path) -> None:
    """Create an empty output directory without replacing a prior snapshot."""
    if path.exists() and any(path.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {path}")
    path.mkdir(parents=True, exist_ok=True)


def _download(url: str, destination: Path) -> None:
    """Download a CQC export without silently following an unpinned source."""
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=120) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)


def main() -> None:
    """Create one pinned, service-specific CQC location lane."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Exact CQC CSV URL to pin")
    parser.add_argument(
        "--service-type", required=True, help="Exact CQC service type, for example Hospital"
    )
    parser.add_argument("--output", type=Path, required=True, help="New or empty directory")
    args = parser.parse_args()

    _prepare_output(args.output)
    raw_path = args.output / "cqc_care_directory.csv"
    _download(args.url, raw_path)
    source_rows = _rows(raw_path)
    selected = [_normalise(row) for row in source_rows if _has_service_type(row, args.service_type)]
    if not selected:
        raise ValueError(
            f"No CQC records have the exact service type {args.service_type!r}. "
            "Check the current CQC directory values."
        )
    if any(not row["cqc_location_id"] for row in selected):
        raise ValueError("CQC directory has selected records without a location ID")
    if len({row["cqc_location_id"] for row in selected}) != len(selected):
        raise ValueError("CQC directory has duplicate selected location IDs")

    records_path = args.output / "cqc_locations.csv"
    with records_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(selected)
    manifest = {
        "schema": "arche.cqc_location_lane.v1",
        "retrieved_at": datetime.now(UTC).isoformat(),
        "source": {
            "publisher": "Care Quality Commission",
            "source_page": SOURCE_PAGE,
            "download_url": args.url,
            "license": LICENSE,
            "reported_production_date": _source_date(raw_path),
            "raw_file": raw_path.name,
            "raw_sha256": _sha256(raw_path),
        },
        "entity_contract": (
            "A CQC-regulated location carrying the selected service type. It may be "
            "a management base, so it is not assumed to be a physical care site."
        ),
        "service_type": args.service_type,
        "source_records": len(source_rows),
        "selected_records": len(selected),
        "record_file": records_path.name,
        "record_sha256": _sha256(records_path),
        "matching_status": "staged only; no crosswalk or accuracy claim",
    }
    manifest_path = args.output / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"selected_records": len(selected), "manifest": str(manifest_path)}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (FileExistsError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
