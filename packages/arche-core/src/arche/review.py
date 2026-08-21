# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Read, check and adjudicate a review pack, without a tool to do it in.

`arche.report.review_pack` writes a pack. Until this module there was nothing in
the library that could read one back, so a caller who exported their own data had
a CSV, a manifest, and no supported way to work them. The only consumer was a
local web tool you got by cloning the repository, which is a strange thing to
require of somebody who installed a library.

The deliberate choice here is that arche supplies the **artifact protocol** and
not the reviewing. Read a pack, check it is the pack the matcher produced, apply
a file of outcomes somebody arrived at however they liked, and get back an
immutable adjudication that can be signed and re-checked. The human part happens
in a spreadsheet, a notebook, an internal queue, or a web tool, and none of those
need to be arche's problem.

What that buys, concretely: an auditor months later can take the pack, the
adjudication and this module, and verify that the decisions are the ones the
matcher produced and that each one was marked the way the record says. No
database, no server, no trusting the tool the reviewing happened in.

The outcomes file
-----------------
CSV or JSONL, one row per decision, with at least::

    decision_id,outcome,reviewer
    xwd:sha256:ab12...,same_entity,dee
    xwd:sha256:cd34...,different,dee

`reason` and `reviewed_at` are optional and carried through. `outcome` must be
one of :data:`arche.report.REVIEW_OUTCOMES`. Extra columns are ignored rather
than rejected, because a reviewer's own spreadsheet will have some.

A pack exported with `reveal=True` and then filled in directly is also an
outcomes file: the four `REVIEW_FIELDS` columns are exactly this schema.
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from arche.report import (
    PACK_SCHEMA,
    REVIEW_FIELDS,
    REVIEW_OUTCOMES,
    pack_content_digest,
)

ADJUDICATION_SCHEMA = "arche.adjudication.v1"

# Columns an outcomes file must carry. `review_outcome` is accepted as an alias
# for `outcome` so a filled-in pack works as an outcomes file unchanged.
_OUTCOME_ALIASES = {"review_outcome": "outcome", "reviewed_at": "reviewed_at"}


class PackError(ValueError):
    """A pack could not be read at all. Distinct from a pack that reads and is wrong."""


@dataclass(frozen=True)
class Problem:
    """One thing wrong with a pack or an outcomes file.

    `code` is stable and meant to be matched on; `detail` is for a person.
    Severity is either ``"error"`` (the artifact cannot be trusted) or
    ``"warning"`` (readable, but something is missing that usually should not be).
    """

    code: str
    detail: str
    severity: str = "error"

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail, "severity": self.severity}


@dataclass(frozen=True)
class Pack:
    """A review pack on disk, read and checked."""

    path: Path
    rows: list[dict]
    fields: list[str]
    manifest: dict | None
    content_digest: str
    problems: list[Problem] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(p.severity == "error" for p in self.problems)

    @property
    def decision_ids(self) -> list[str]:
        return [r.get("decision_id", "") for r in self.rows]


def _read_rows(path: Path) -> tuple[list[dict], list[str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(r) for r in reader]
        fields = list(reader.fieldnames or [])
    return rows, fields


def read_pack(path: str | Path) -> Pack:
    """Read a pack and check it against its manifest.

    Raises :class:`PackError` only when there is nothing to check: the file is
    missing, unreadable, or has no rows. Everything else comes back as a
    `Problem` on the returned pack, because "this pack is wrong" is an answer a
    caller wants to inspect rather than an exception to catch.
    """
    path = Path(path)
    if path.is_dir():
        path = path / "pack.csv"
    if not path.exists():
        raise PackError(f"no pack at {path}")
    try:
        rows, fields = _read_rows(path)
    except (OSError, UnicodeDecodeError) as exc:
        raise PackError(f"cannot read {path}: {exc}") from exc
    if not rows:
        raise PackError(f"{path} has no rows")

    manifest_path = path.parent / "manifest.json"
    manifest: dict | None = None
    problems: list[Problem] = []
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(Problem("manifest-unreadable",
                                    f"manifest.json is not valid JSON: {exc}"))
    else:
        problems.append(Problem(
            "manifest-missing",
            f"no manifest.json beside {path.name}; the pack cannot be checked "
            "against what the matcher said it wrote",
            severity="warning"))

    digest = pack_content_digest(rows, fields)
    problems.extend(_check(rows, fields, manifest, digest))
    return Pack(path=path, rows=rows, fields=fields, manifest=manifest,
                content_digest=digest, problems=problems)


def _check(rows: list[dict], fields: list[str], manifest: dict | None,
           digest: str) -> list[Problem]:
    problems: list[Problem] = []

    if "decision_id" not in fields:
        problems.append(Problem(
            "no-decision-id",
            "the pack has no `decision_id` column, so no outcome can be tied "
            "to a decision"))
        return problems

    ids = [r.get("decision_id", "") for r in rows]
    blank = sum(1 for i in ids if not i)
    if blank:
        problems.append(Problem("blank-decision-id",
                                f"{blank} row(s) have an empty `decision_id`"))
    seen: dict[str, int] = {}
    for i in ids:
        if i:
            seen[i] = seen.get(i, 0) + 1
    duplicated = {k: v for k, v in seen.items() if v > 1}
    if duplicated:
        # The old manifest digest sorted the ids before hashing, so a duplicated
        # id was invisible to it. An outcome applied to a duplicated id is
        # ambiguous by construction.
        problems.append(Problem(
            "duplicate-decision-id",
            f"{len(duplicated)} decision id(s) appear more than once, so an "
            f"outcome for them is ambiguous: "
            f"{', '.join(sorted(duplicated)[:3])}"))

    if manifest is None:
        return problems

    if manifest.get("schema") != PACK_SCHEMA:
        problems.append(Problem(
            "schema-unexpected",
            f"manifest says schema {manifest.get('schema')!r}, expected "
            f"{PACK_SCHEMA!r}", severity="warning"))

    claimed_rows = manifest.get("rows")
    if isinstance(claimed_rows, int) and claimed_rows != len(rows):
        problems.append(Problem(
            "row-count-mismatch",
            f"manifest says {claimed_rows} rows, the CSV has {len(rows)}"))

    claimed = manifest.get("content_sha256")
    if not claimed:
        problems.append(Problem(
            "no-content-digest",
            "manifest carries no `content_sha256`, so the pack's contents "
            "cannot be checked; it was written before that field existed",
            severity="warning"))
    elif claimed != digest:
        problems.append(Problem(
            "content-digest-mismatch",
            "the pack does not match its manifest: a value was changed, a row "
            f"added, or a row dropped. manifest {claimed[:16]}..., "
            f"recomputed {digest[:16]}..."))
    return problems


def validate_pack(path: str | Path) -> dict:
    """Check a pack and return a machine-readable report. Never raises.

    Shaped for a CLI and for a pipeline step: `ok` is the thing to branch on,
    `problems` is the thing to print.
    """
    try:
        pack = read_pack(path)
    except PackError as exc:
        return {"ok": False, "path": str(path), "rows": 0,
                "problems": [Problem("unreadable", str(exc)).as_dict()]}
    return {
        "ok": pack.ok,
        "path": str(pack.path),
        "rows": len(pack.rows),
        "content_sha256": pack.content_digest,
        "manifest": bool(pack.manifest),
        "problems": [p.as_dict() for p in pack.problems],
    }


def _read_outcomes(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".jsonl", ".ndjson"):
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    if path.suffix.lower() == ".json":
        loaded = json.loads(text)
        return loaded if isinstance(loaded, list) else [loaded]
    return list(csv.DictReader(text.splitlines()))


def _normalise(entry: dict) -> dict:
    out = dict(entry)
    for alias, canonical in _OUTCOME_ALIASES.items():
        if alias in out and canonical not in out:
            out[canonical] = out.pop(alias)
    return out


def apply_outcomes(pack: str | Path, outcomes: str | Path, *,
                   require_clean_pack: bool = True) -> dict:
    """Bind a file of outcomes to a pack and return an immutable adjudication.

    Every outcome is checked against the pack before anything is produced: the
    decision id has to exist, the outcome has to be in the vocabulary, and a
    reviewer has to be named. An unattributed adjudication cannot be audited,
    which is the same rule the studio enforces at its save button and the reason
    it is enforced here too rather than only there.

    The returned artifact carries the source pack's `content_sha256`, so it is
    bound to the pack it was made against and not merely to a filename. Pass it
    to :func:`verify_adjudication` to re-check both halves later.

    ``require_clean_pack`` is on by default: adjudicating a pack that does not
    match its manifest produces an artifact that asserts something about a
    document nobody can identify. Turn it off only if you know why.
    """
    read = read_pack(pack)
    if require_clean_pack and not read.ok:
        raise PackError(
            "the pack has errors, so an adjudication built on it would attest "
            "to a document that cannot be identified: "
            + "; ".join(p.detail for p in read.problems if p.severity == "error")
            + ". Pass require_clean_pack=False to override."
        )

    entries = [_normalise(e) for e in _read_outcomes(Path(outcomes))]
    known = set(read.decision_ids)
    ledger: list[dict] = []
    problems: list[Problem] = []
    seen: set[str] = set()

    for n, entry in enumerate(entries, 1):
        did = str(entry.get("decision_id", "")).strip()
        outcome = str(entry.get("outcome", "")).strip()
        reviewer = str(entry.get("reviewer", "")).strip()
        if not did:
            problems.append(Problem("outcome-no-decision-id",
                                    f"row {n} has no decision_id"))
            continue
        if not outcome:
            continue           # an unmarked row is not an error, just not a mark
        if did not in known:
            problems.append(Problem(
                "outcome-unknown-decision",
                f"row {n}: decision id {did[:24]}... is not in this pack"))
            continue
        if did in seen:
            problems.append(Problem(
                "outcome-duplicated",
                f"row {n}: decision id {did[:24]}... is marked more than once"))
            continue
        if outcome not in REVIEW_OUTCOMES:
            problems.append(Problem(
                "outcome-not-in-vocabulary",
                f"row {n}: outcome {outcome!r} is not one of "
                f"{list(REVIEW_OUTCOMES)}"))
            continue
        if not reviewer:
            problems.append(Problem(
                "outcome-no-reviewer",
                f"row {n}: no reviewer named; an unattributed adjudication "
                "cannot be audited"))
            continue
        seen.add(did)
        ledger.append({
            "decision_id": did,
            "outcome": outcome,
            "reviewer": reviewer,
            "reason": str(entry.get("reason", "") or ""),
            "reviewed_at": str(entry.get("reviewed_at", "") or ""),
        })

    if problems:
        raise PackError(
            "the outcomes file does not fit this pack: "
            + "; ".join(p.detail for p in problems[:5])
            + (f" (and {len(problems) - 5} more)" if len(problems) > 5 else "")
        )

    ledger.sort(key=lambda r: r["decision_id"])
    counts: dict[str, int] = {}
    for entry in ledger:
        counts[entry["outcome"]] = counts.get(entry["outcome"], 0) + 1

    return {
        "schema": ADJUDICATION_SCHEMA,
        "generated": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        # Bound to the pack's CONTENT, not its name. Two packs with the same
        # filename and different rows are different documents.
        "source_pack": read.path.name,
        "source_pack_content_sha256": read.content_digest,
        "pack_rows": len(read.rows),
        "marked": len(ledger),
        "unmarked": len(read.rows) - len(ledger),
        "outcomes": dict(sorted(counts.items())),
        # The binding. Recompute from `ledger` to check it.
        "outcomes_sha256": _ledger_digest(ledger),
        "ledger": ledger,
    }


def _ledger_digest(ledger: list[dict]) -> str:
    canonical = json.dumps(ledger, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_adjudication(adjudication: str | Path | dict,
                        pack: str | Path | None = None) -> dict:
    """Re-check an adjudication: its own binding, and the pack it claims.

    Two questions, answered separately because they fail separately. Does the
    ledger still hash to what the artifact claims, which catches a swapped or
    edited ledger. And is the pack in front of me the pack this was made
    against, which catches an adjudication being read next to the wrong file.

    A signature over the artifact proves neither of these on its own: it proves
    the artifact has not changed since it was signed. This is the part that says
    the artifact was true when it was made.
    """
    if isinstance(adjudication, (str, Path)):
        adjudication = json.loads(Path(adjudication).read_text(encoding="utf-8"))

    ledger = adjudication.get("ledger") or []
    recomputed = _ledger_digest(ledger)
    claimed = adjudication.get("outcomes_sha256", "")
    report: dict[str, Any] = {
        "ok": recomputed == claimed,
        "outcomes_match": recomputed == claimed,
        "recomputed_outcomes_sha256": recomputed,
        "claimed_outcomes_sha256": claimed,
        "marked": len(ledger),
        "problems": [],
    }
    if recomputed != claimed:
        report["problems"].append(Problem(
            "ledger-digest-mismatch",
            "the ledger does not hash to the digest this artifact claims; it "
            "has been edited or swapped").as_dict())

    if pack is None:
        report["pack_checked"] = False
        return report

    report["pack_checked"] = True
    try:
        read = read_pack(pack)
    except PackError as exc:
        report["ok"] = False
        report["problems"].append(Problem("pack-unreadable", str(exc)).as_dict())
        return report

    claimed_pack = adjudication.get("source_pack_content_sha256", "")
    report["pack_matches"] = read.content_digest == claimed_pack
    if not report["pack_matches"]:
        report["ok"] = False
        report["problems"].append(Problem(
            "pack-mismatch",
            "this adjudication was made against a different pack: it claims "
            f"{claimed_pack[:16]}..., the pack here is "
            f"{read.content_digest[:16]}...").as_dict())

    unknown = [e["decision_id"] for e in ledger
               if e["decision_id"] not in set(read.decision_ids)]
    if unknown:
        report["ok"] = False
        report["problems"].append(Problem(
            "ledger-decision-not-in-pack",
            f"{len(unknown)} adjudicated decision(s) are not in this pack"
        ).as_dict())
    return report


def write_reviewed_csv(pack: str | Path, adjudication: dict,
                       out_path: str | Path) -> Path:
    """The pack with its four review columns filled in from an adjudication.

    For handing to somebody who wants a spreadsheet rather than a JSON artifact.
    The original pack is never written to, which is the same rule the studio
    follows: the matcher's output and the adjudication of it are two documents.
    """
    read = read_pack(pack)
    by_id = {e["decision_id"]: e for e in adjudication.get("ledger", [])}
    out_path = Path(out_path)
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=read.fields,
                                extrasaction="ignore")
        writer.writeheader()
        for row in read.rows:
            entry = by_id.get(row.get("decision_id", ""))
            if entry:
                row = {**row,
                       "review_outcome": entry["outcome"],
                       "reviewer": entry["reviewer"],
                       "reason": entry["reason"],
                       "reviewed_at": entry["reviewed_at"]}
            writer.writerow({f: row.get(f, "") for f in read.fields})
    return out_path


__all__ = [
    "ADJUDICATION_SCHEMA",
    "Pack",
    "PackError",
    "Problem",
    "REVIEW_FIELDS",
    "REVIEW_OUTCOMES",
    "apply_outcomes",
    "read_pack",
    "validate_pack",
    "verify_adjudication",
    "write_reviewed_csv",
]
