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
SHARE_SCHEMA = "arche.review_pack.shared.v1"

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


# The formats a pack can arrive in, in the order a directory is searched.
# CSV first because it is what `review_pack` writes and what a reviewer can open
# in anything; the others because real pipelines do not end in CSV and the
# alternative to reading them is every caller writing their own parser.
PACK_SUFFIXES = (".csv", ".parquet", ".jsonl", ".ndjson", ".json")


def _as_text(value: Any) -> str:
    """One rule for turning a cell into what the rest of this module sees.

    Everything downstream — the content digest, the masking allowlist, the
    outcome vocabulary — is defined over strings, because a pack's first format
    was CSV and CSV has no other type. Parquet does have types, so reading one
    without normalising would give a pack whose digest disagreed with the digest
    of the identical CSV, and two files that are the same pack would fail each
    other's integrity check.

    So the typed formats are narrowed to the untyped one rather than the other
    way round. It loses the type, which is the correct loss here: a pack is a
    document to be read and adjudicated, not a frame to compute on.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        # Before the numeric branch: bool is an int in Python and `True` would
        # otherwise render as `1`.
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        # 1.0 from parquet and "1.0" from CSV have to agree, and repr already
        # gives "1.0" here. Spelled out because the alternative — int(value) —
        # is the tempting wrong answer and would give "1".
        return repr(value)
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, dict)):
        # Evidence arrives as a nested object in JSONL and as a JSON string in
        # CSV. Re-encode with the same separators `review_pack` uses so the two
        # produce the same bytes.
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    return str(value)


def _read_csv(path: Path) -> tuple[list[dict], list[str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(r) for r in reader]
        fields = list(reader.fieldnames or [])
    return rows, fields


def _read_parquet(path: Path) -> tuple[list[dict], list[str]]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise PackError(
            f"{path.name} is a parquet file and pyarrow is not installed. "
            "Install it with `pip install arche-core[parquet]`, or export the "
            "pack as CSV.") from exc
    table = pq.read_table(path)
    fields = list(table.column_names)
    rows = [{f: _as_text(record.get(f)) for f in fields}
            for record in table.to_pylist()]
    return rows, fields


def _read_jsonl(path: Path) -> tuple[list[dict], list[str]]:
    """One JSON object per line. Blank lines are skipped, not an error.

    A ragged file — objects that do not all carry the same keys — is read rather
    than refused, and the union of the keys becomes the field list in first-seen
    order. Refusing would be defensible, but a pack assembled by a pipeline that
    omits empty columns is common and there is nothing ambiguous about it.
    """
    rows: list[dict] = []
    fields: list[str] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise PackError(
                    f"{path.name} line {number} is not valid JSON: {exc}") from exc
            if not isinstance(record, dict):
                raise PackError(
                    f"{path.name} line {number} is a {type(record).__name__}, "
                    "and a pack row has to be an object")
            for key in record:
                if key not in seen:
                    seen.add(key)
                    fields.append(key)
            rows.append({k: _as_text(v) for k, v in record.items()})
    return [{f: r.get(f, "") for f in fields} for r in rows], fields


def _read_json(path: Path) -> tuple[list[dict], list[str]]:
    """A single JSON array of objects, or `{"rows": [...]}`."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PackError(f"{path.name} is not valid JSON: {exc}") from exc
    if isinstance(payload, dict):
        # Absent and empty are different. An object with no `rows` key is a
        # malformed pack, and reporting it as "has no rows" would send the
        # reader looking at the wrong thing.
        if "rows" not in payload:
            raise PackError(
                f"{path.name} does not hold a list of rows; a JSON pack is an "
                'array of objects, or an object with a "rows" array')
        payload = payload["rows"]
    if not isinstance(payload, list):
        raise PackError(
            f"{path.name} does not hold a list of rows; a JSON pack is an array "
            'of objects, or an object with a "rows" array')
    fields: list[str] = []
    seen: set[str] = set()
    for record in payload:
        if not isinstance(record, dict):
            raise PackError(f"{path.name} contains a non-object row")
        for key in record:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    rows = [{f: _as_text(r.get(f)) for f in fields} for r in payload]
    return rows, fields


_READERS = {".csv": _read_csv, ".parquet": _read_parquet,
            ".jsonl": _read_jsonl, ".ndjson": _read_jsonl, ".json": _read_json}


def _read_rows(path: Path) -> tuple[list[dict], list[str]]:
    """Dispatch on the extension, and say so plainly when there is no reader.

    Sniffing the content would be friendlier and is the wrong trade here: a pack
    is an artifact somebody will re-read months later, and a file whose format
    was guessed is a file whose reading cannot be reproduced.
    """
    reader = _READERS.get(path.suffix.lower())
    if reader is None:
        raise PackError(
            f"no reader for {path.suffix or 'a file with no extension'!r}; "
            f"a pack is one of {', '.join(PACK_SUFFIXES)}")
    return reader(path)

def read_records(path: str | Path) -> tuple[list[dict], list[str]]:
    """Read a table of records from any supported format.

    Returns ``(rows, fields)``. Every value is a string, for the reasons in
    :func:`_as_text`: the formats have to agree so the same data in two of them
    digests the same.

    This is :func:`read_pack` without the pack. `read_pack` additionally checks
    a manifest, looks for `decision_id`, and reports problems — all correct for
    an adjudication pack and noise for a plain list of people.

    It exists because the alternative was `arche.cli._load_records`, which is
    private, and which raises `SystemExit` on bad input. `SystemExit` is right
    for a command that a person typed and wrong for a library: it cannot be
    caught by anything reasonable and it terminates a server. Anything that
    imported it also froze it, since a patch release could rename it.
    """
    path = Path(path)
    if not path.exists():
        raise PackError(f"no file at {path}")
    return _read_rows(path)


def read_pack(path: str | Path) -> Pack:
    """Read a pack and check it against its manifest.

    Raises :class:`PackError` only when there is nothing to check: the file is
    missing, unreadable, or has no rows. Everything else comes back as a
    `Problem` on the returned pack, because "this pack is wrong" is an answer a
    caller wants to inspect rather than an exception to catch.
    """
    path = Path(path)
    if path.is_dir():
        directory = path
        found = [directory / f"pack{suffix}" for suffix in PACK_SUFFIXES
                 if (directory / f"pack{suffix}").exists()]
        if not found:
            # Fall back to any single supported file, so a directory holding
            # `decisions.parquet` works without renaming it.
            found = sorted(c for c in directory.iterdir()
                           if c.is_file() and c.suffix.lower() in _READERS)
        if not found:
            raise PackError(
                f"no pack in {directory}; expected one of "
                f"{', '.join('pack' + s for s in PACK_SUFFIXES)}")
        path = found[0]
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


# The schema reconcile hashes a crosswalk edge under (reconcile.py:975). Kept
# here as a constant rather than imported because `review` must not depend on
# `resolve`; `test_a_decision_id_recomputes_from_the_shared_artifact_alone`
# runs a real resolution through this function, so the two cannot drift
# silently.
_EDGE_SCHEMA = "arche.crosswalk_edge.v1"

# Everything a decision id is computed over, besides the pins. `candidate` is
# deliberately absent: reconcile includes it when retrieval produced one, and
# `review_pack` does not write it to the pack, so a pack cannot reproduce the
# id of such an edge. That is reported as unreproducible rather than as a
# mismatch, because the two mean different things.
_EDGE_NUMERIC = ("score", "distinctive_max")


def verify_decision_ids(pack: str | Path) -> dict[str, Any]:
    """Recompute every decision id in a pack from the pack and its pins.

    This is the check a second party runs. It needs the pack and nothing else:
    no source records, no access to whoever produced it, no network. A
    ``decision_id`` is a content hash over the edge and the pins, so if the
    recomputation agrees, the producer cannot have reached that decision from
    different evidence or under different software than it declares.

    What this does and does not establish. It establishes that **the stated
    evidence, under the stated pins, yields the stated verdict and address** --
    the producer cannot have swapped the evidence, moved a threshold, or edited
    a verdict after the fact. It does **not** establish that the evidence was
    computed correctly from the source records, because checking that requires
    the records. The claim is integrity of the judgement, not of its inputs.

    A masked pack whose evidence was redacted cannot be verified at all, and
    says so: the id was computed over what the evidence said before redaction.
    :func:`share_artifact` records this in ``decision_ids_verifiable``.
    """
    from arche.ids import content_hash

    read = read_pack(pack)
    manifest = read.manifest or {}
    pins = manifest.get("pins") or {}
    report: dict[str, Any] = {
        "pack": str(read.path),
        "rows": len(read.rows),
        "pins_present": bool(pins),
        "checked": 0,
        "matched": 0,
        "mismatched": [],
        "unreproducible": [],
        "problems": [],
    }

    if not pins:
        report["ok"] = False
        report["problems"].append(Problem(
            "no-pins",
            "this pack carries no pins, so no decision id in it can be "
            "recomputed. A decision id is a hash over the edge AND the pins. "
            "Ask the producer for a pack whose manifest includes them.").as_dict())
        return report

    if manifest.get("decision_ids_verifiable") is False:
        report["ok"] = False
        report["problems"].append(Problem(
            "evidence-redacted",
            manifest.get("decision_ids_verifiable_note")
            or "the manifest declares these decision ids unverifiable").as_dict())
        return report

    sides = _infer_sides(read.fields)
    if len(sides) != 2:
        report["ok"] = False
        report["problems"].append(Problem(
            "sides-unclear",
            f"expected two record sides in the columns, inferred {sides!r}; "
            "an edge needs exactly two ids").as_dict())
        return report

    id_cols = [c for c in (f"{s}_id" for s in sides) if c in read.fields]
    if len(id_cols) != 2:
        report["ok"] = False
        report["problems"].append(Problem(
            "id-columns-missing",
            f"could not find both id columns; looked for "
            f"{[f'{s}_id' for s in sides]!r}").as_dict())
        return report

    for index, row in enumerate(read.rows):
        stated = str(row.get("decision_id") or "")
        raw_evidence = row.get("evidence", "")
        if not stated:
            report["unreproducible"].append(
                {"row": index, "why": "the row states no decision id"})
            continue
        try:
            evidence = json.loads(raw_evidence) if raw_evidence not in ("", None) else {}
        except (TypeError, ValueError):
            report["unreproducible"].append(
                {"row": index, "decision_id": stated,
                 "why": "the evidence column is not readable as JSON"})
            continue

        edge: dict[str, Any] = {
            "a_id": row.get(id_cols[0]),
            "b_id": row.get(id_cols[1]),
            "decision": row.get("decision", ""),
            "evidence": evidence,
        }
        try:
            for name in _EDGE_NUMERIC:
                edge[name] = float(row[name])
        except (KeyError, TypeError, ValueError):
            report["unreproducible"].append(
                {"row": index, "decision_id": stated,
                 "why": f"{_EDGE_NUMERIC} must all be present and numeric"})
            continue

        recomputed = content_hash({"schema": _EDGE_SCHEMA, **edge, "pins": pins},
                                  prefix="xwd")
        report["checked"] += 1
        if recomputed == stated:
            report["matched"] += 1
        else:
            report["mismatched"].append(
                {"row": index, "stated": stated, "recomputed": recomputed})

    report["ok"] = (report["checked"] > 0
                    and not report["mismatched"]
                    and not report["unreproducible"])
    if report["mismatched"]:
        report["problems"].append(Problem(
            "decision-id-mismatch",
            f"{len(report['mismatched'])} decision id(s) do not match a "
            "recomputation. Either the pack was edited after it was written, "
            "or the edge carried a retrieval `candidate` block, which a pack "
            "does not preserve.").as_dict())
    if report["checked"] == 0 and not report["problems"]:
        report["problems"].append(Problem(
            "nothing-checkable",
            "no row in this pack could be recomputed", severity="warning",
        ).as_dict())
    return report


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


# What a reviewer's outcome means as a decision.
#
# The matcher proposes and a person disposes, but until now nothing wrote down
# what the disposal *was*. A pack carried `decision` from the matcher and
# `review_outcome` from the human in two columns that never met, so a row a
# reviewer had settled still read `review` everywhere it was displayed and the
# queue never got shorter. Somebody working a queue could mark forty rows and
# see no evidence that anything had happened.
#
# The vocabularies are deliberately different — `same_entity` is a claim about
# the world, `match` is a claim about what the system will do — so the mapping is
# stated here once rather than re-derived at each display site.
OUTCOME_DECISION = {
    "same_entity": "match",
    "different": "no_match",
    # Not an absence of an answer. A reviewer who looked and could not tell has
    # made a finding, and the finding is that this stays held.
    "unresolved": "review",
}


def effective_decision(row: dict, outcome: str | None = None) -> str:
    """The standing answer for one pair: the human's if there is one, else the
    matcher's.

    `outcome` overrides whatever the row carries, which is how a caller with
    fresher state than the file — the studio, reading its own store — asks the
    same question.
    """
    outcome = outcome if outcome is not None else row.get("review_outcome", "")
    if outcome:
        return OUTCOME_DECISION.get(outcome, row.get("decision", ""))
    return row.get("decision", "")


def effective_decisions(pack: str | Path, adjudication: dict | None = None,
                        ) -> dict[str, str]:
    """Every pair's standing answer, keyed by decision id."""
    read = pack if isinstance(pack, Pack) else read_pack(pack)
    marks = {e["decision_id"]: e.get("outcome", "")
             for e in (adjudication or {}).get("ledger", [])}
    return {row.get("decision_id", ""):
            effective_decision(row, marks.get(row.get("decision_id", "")))
            for row in read.rows}


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
    # `effective_decision` is added rather than `decision` being overwritten.
    # Both are worth keeping: what the matcher said is the thing being audited,
    # and destroying it to record the audit would be self-defeating. A consumer
    # who wants the standing answer reads one column instead of reimplementing
    # the mapping.
    fields = [*read.fields]
    if "effective_decision" not in fields:
        fields.insert(fields.index("decision") + 1 if "decision" in fields
                      else len(fields), "effective_decision")
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields,
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
            row = {**row, "effective_decision": effective_decision(row)}
            writer.writerow({f: row.get(f, "") for f in fields})
    return out_path


# Columns that are the matcher's machinery rather than anybody's data. Scores,
# levels and content-addressed ids describe a decision; they are not the record.
_DECISION_COLUMNS = ("decision_id", "decision", "score", "distinctive_max",
                     "distance_km", "evidence")

# Evidence values that are text rather than measurement. A score is not
# somebody's data and a reader needs it; a *string* inside the evidence is the
# data, and it travelled verbatim into every masked pack until 2026-10-05.
#
# `reconcile` writes `evidence["name_phrase"] = phrase` whenever the shared
# phrase is rarer than any shared token (reconcile.py:539). So the plaintext
# name appeared in the evidence precisely when the name was the decisive
# signal: the leak was correlated with how identifying the value was, which is
# the worst correlation such a leak can have. `a_name` and `b_name` showed
# `[NAME]` in the same row.
#
# The rule is by TYPE, not by key name, so a string-valued evidence key added
# later is masked without anyone remembering to come back here.
_EVIDENCE_TEXT_PLACEHOLDER = "[VALUE]"


def _mask_evidence_values(node: Any) -> Any:
    """Recurse a parsed evidence structure: numbers survive, text does not.

    Keyed on type rather than on key name, so a string-valued evidence key
    added later is masked without anyone remembering to come back here.

    The key is kept and only its value replaced, because *that a phrase drove
    this match* is information a reader of a masked pack legitimately needs,
    and it is not personal data. What the phrase said is.
    """
    if isinstance(node, dict):
        return {k: _mask_evidence_values(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_mask_evidence_values(v) for v in node]
    # bool is an int subclass; it is a measurement here, not text.
    if node is None or isinstance(node, (bool, int, float)):
        return node
    return _EVIDENCE_TEXT_PLACEHOLDER


def _mask_evidence_detail(cell: Any) -> tuple[Any, bool]:
    """Mask one ``evidence`` cell; say whether a value was actually replaced.

    The flag matters because ``decision_id`` is a hash over the evidence. If
    masking changed a value, the masked artifact addresses something the
    original decision did not, and re-deriving the id from it is impossible.
    The caller records that in the manifest rather than leaving a recipient to
    discover it by failing.

    Compared on the *parsed* structures, not the text: this function re-dumps
    with sorted keys, so comparing strings would report a redaction whenever
    the source happened to order its keys differently.

    A cell this function cannot parse is replaced wholesale rather than passed
    through: a value it cannot read is a value it cannot promise anything
    about, and the promise on this artifact is that nothing raw survives in it.
    """
    if cell in ("", None):
        return cell, False
    if not isinstance(cell, str):
        masked = _mask_evidence_values(cell)
        return masked, masked != cell
    try:
        parsed = json.loads(cell)
    except (TypeError, ValueError):
        return _EVIDENCE_TEXT_PLACEHOLDER, True
    # A cell holding a bare JSON scalar string ("\"Ada\"") parses to a str and
    # is text, which _mask_evidence_values handles correctly.
    masked = _mask_evidence_values(parsed)
    return json.dumps(masked, sort_keys=True), masked != parsed


def _mask_evidence(cell: Any) -> Any:
    """:func:`_mask_evidence_detail` when only the masked value is wanted."""
    return _mask_evidence_detail(cell)[0]


def share_artifact(pack: str | Path, out_dir: str | Path, *,
                   adjudication: dict | None = None,
                   include_reasons: bool = False,
                   id_columns: list[str] | None = None) -> dict:
    """Derive a masked pack that is safe to send somebody.

    A working pack is usually written with ``reveal=True``, because a masked one
    cannot be adjudicated: nobody can say whether two people are the same when
    both names are redacted. That makes the working pack a local document, and
    the studio's save path used to copy it verbatim, so a revealed pack stayed
    revealed the moment anybody shared the output.

    This produces the other artifact. Record values go through the same masking
    allowlist :func:`arche.report.review_pack` uses, so there is one
    implementation of what masked means rather than two that can disagree. The
    decision machinery survives, because a score is not somebody's data and a
    reader needs it to see what the matcher did.

    Three things make this a projection rather than a redaction pass:

    **It is computed from the source, not edited into it.** A masked file made by
    rewriting cells after a manifest was written has a manifest that describes
    something else. This writes a new artifact with its own ``content_sha256``
    and records the source digest beside it, so the two are linked and neither
    pretends to be the other.

    **Nothing raw survives anywhere in it.** Not in a sidecar, not in the
    manifest, not inside the evidence. A masked export that keeps the values
    somewhere is worse than none, because it invites the confidence a genuinely
    masked one would earn.

    **Reviewer reasons are dropped by default.** A reason is free text somebody
    typed and can contain anything, including the name the rest of the row just
    masked. Running a detector over it would miss things quietly, which is the
    failure mode that matters here. Pass ``include_reasons=True`` if you know
    what is in them.

    Sign the result rather than the source: the digest worth attesting is the one
    over the thing you are actually sending.

    **It carries the pins, so the thing you send can be checked.** A
    ``decision_id`` is a content hash over the edge *and* the pins, so a
    recipient without them holds every decision address and can recompute
    none. Until 2026-10-05 this manifest omitted them, which made the only
    artifact safe to share the only one that could not be verified. They are
    copied verbatim, because a hash does not survive editing, and they are
    screened for sensitive-looking values first, because ``extra_pins`` lets a
    caller put anything there and this file says "safe to share".

    **And it says whether verification is actually possible.**
    ``decision_ids_verifiable`` is false when masking changed an evidence value,
    because the id was computed over what the evidence said before redaction.
    Numeric evidence -- the common case -- is untouched and verifies; a row
    carrying a name phrase does not. A recipient should not have to discover
    that by failing, and the honest fix for the remaining case is to commit to a
    digest of each text-valued component rather than the value, which is a
    change to how ids are computed and is not done here.
    """
    from arche.render import render
    from arche.report import _SENSITIVE_ID

    read = read_pack(pack)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    sides = _infer_sides(read.fields)
    ids = list(id_columns or [f"{side}_id" for side in sides])
    present_ids = [c for c in ids if c in read.fields]

    # The same refusal `review_pack` makes in masked mode. A "masked" artifact
    # that prints national identifiers as join keys is a leak, not a projection.
    hot = sum(1 for r in read.rows for c in present_ids
              if _SENSITIVE_ID.match(str(r.get(c, "") or "")))
    if hot:
        raise PackError(
            f"{hot} row id(s) look like sensitive identifiers (9+ digit runs, "
            "the shape of a national ID). A masked pack still carries its ids, "
            "so this would leak them. Re-export the pack with a surrogate id "
            "column, or pass id_columns= naming the columns that are safe.")

    # Pins travel verbatim, so they get the same scrutiny the row ids get.
    # `reconcile` takes `extra_pins`, which means a caller can put anything in
    # here, and this file is stamped "safe to share". A pin is configuration --
    # digests, thresholds, an engine name -- and a 9+ digit run in one is not
    # configuration. Refuse rather than publish it under that stamp.
    pins = dict((read.manifest or {}).get("pins") or {})
    hot_pins = sorted(
        key for key, value in pins.items()
        if _SENSITIVE_ID.match(str(value or ""))
    )
    if hot_pins:
        raise PackError(
            f"pin(s) {hot_pins} hold a value shaped like a sensitive "
            "identifier (9+ digit runs, the shape of a national ID). Pins are "
            "published verbatim in the shared manifest so the decisions stay "
            "verifiable, so this would leak. Re-run the resolution without "
            "that value in extra_pins.")

    marks = {e["decision_id"]: e for e in (adjudication or {}).get("ledger", [])}
    keep_review = ["review_outcome", "reviewer"] + (
        ["reason"] if include_reasons else [])
    fields = [f for f in read.fields
              if f not in REVIEW_FIELDS or f in keep_review]

    rows: list[dict] = []
    evidence_redacted = False
    for row in read.rows:
        out: dict[str, Any] = {}
        for side in sides:
            prefix = f"{side}_"
            payload = {f[len(prefix):]: row.get(f, "")
                       for f in read.fields if f.startswith(prefix)}
            reveal = [c[len(prefix):] for c in present_ids
                      if c.startswith(prefix)]
            for key, value in render(payload, reveal=reveal or []).items():
                out[f"{prefix}{key}"] = value
        for column in read.fields:
            if column in _DECISION_COLUMNS:
                value = row.get(column, "")
                # `evidence` is the one decision column that can carry text.
                if column == "evidence":
                    value, redacted = _mask_evidence_detail(value)
                    evidence_redacted = evidence_redacted or redacted
                out[column] = value
        entry = marks.get(row.get("decision_id", ""))
        if entry:
            out["review_outcome"] = entry["outcome"]
            out["reviewer"] = entry["reviewer"]
            if include_reasons:
                out["reason"] = entry["reason"]
        else:
            for column in keep_review:
                out.setdefault(column, row.get(column, ""))
        rows.append({f: out.get(f, "") for f in fields})

    csv_path = out_dir / "pack.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    manifest = {
        "schema": SHARE_SCHEMA,
        "generated": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "disclosure": "masked (safe to share)",
        "rows": len(rows),
        "reasons_included": bool(include_reasons),
        # Its own digest, over what is actually in this file.
        "content_sha256": pack_content_digest(rows, fields),
        # And a pointer back, so the pair can be tied together without either
        # artifact carrying the other's contents.
        "source_pack": read.path.name,
        "source_pack_content_sha256": read.content_digest,
        # The pins, so the artifact you SEND can verify the decisions it
        # carries. `decision_id` is a content hash over the edge *and* the
        # pins, so without them a recipient holds every decision address and
        # cannot recompute one: the only artifact safe to share was the one
        # that could not be checked, which defeats the point of addressing a
        # decision at all. Verbatim, because a hash does not survive editing.
        "pins": pins,
        # And whether re-derivation is actually possible from this file, said
        # out loud rather than left to fail. Masking the evidence changes what
        # the id was computed over, so a redacted row addresses a decision this
        # file no longer describes. Numeric evidence is the common case and is
        # untouched; a row carrying a name phrase is not.
        "decision_ids_verifiable": bool(pins) and not evidence_redacted,
        "decision_ids_verifiable_note": (
            "recompute arche.ids.content_hash over the edge plus these pins"
            if pins and not evidence_redacted else
            "evidence was redacted in at least one row, so decision ids cannot "
            "be recomputed from this file; verify against the source pack"
            if pins else
            "the source pack carried no pins, so decision ids cannot be "
            "recomputed from this file"
        ),
    }
    if adjudication:
        manifest["adjudication_outcomes_sha256"] = adjudication.get(
            "outcomes_sha256", "")
        manifest["marked"] = len(marks)
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "HOW_TO_VERIFY.txt").write_text(
        _how_to_verify(manifest), encoding="utf-8")
    return manifest


def _how_to_verify(manifest: dict) -> str:
    """What a recipient needs, written for somebody who has never seen arche.

    It states the limit as plainly as the capability. A recipient who
    believes this file proves the evidence was computed correctly from the
    source records has been misled, and a verification note that oversells
    itself is worse than none.
    """
    verifiable = manifest.get("decision_ids_verifiable")
    lines = [
        "How to check the decisions in this folder",
        "=" * 41,
        "",
        "This folder holds linkage decisions with the record values masked.",
        "You do not need the source records to check them, and you do not",
        "need to trust whoever sent it.",
        "",
    ]
    if verifiable:
        lines += [
            "    pip install arche-core",
            "    arche review verify-decisions pack.csv",
            "",
            "It exits 0 if every decision id recomputes, 1 otherwise.",
            "",
            "WHAT THAT PROVES. Each decision carries an address that is a",
            "content hash over its evidence and over the pinned software,",
            "model and data versions in manifest.json. If the addresses",
            "recompute, the sender cannot have reached these verdicts from",
            "different evidence, under a different threshold, or with a",
            "different model than this manifest declares, and cannot have",
            "edited a verdict after the fact.",
            "",
            "WHAT IT DOES NOT PROVE. That the evidence was computed",
            "correctly from the source records. Checking that needs the",
            "records, which is exactly what this folder does not contain.",
            "This is integrity of the judgement, not of its inputs.",
        ]
    else:
        lines += [
            "THESE DECISION IDS CANNOT BE RECOMPUTED FROM THIS FOLDER.",
            "",
            f"Reason: {manifest.get('decision_ids_verifiable_note', 'unknown')}",
            "",
            "The decisions and their evidence are still readable, and the",
            "digests below still tie this file to the pack it came from.",
            "What you cannot do is independently confirm that these",
            "addresses belong to these decisions. Ask the sender for a",
            "pack whose manifest carries its pins.",
        ]
    lines += [
        "",
        f"this file          {manifest.get('content_sha256', '')}",
        f"derived from       {manifest.get('source_pack', '')}",
        f"  whose digest is  {manifest.get('source_pack_content_sha256', '')}",
        f"rows               {manifest.get('rows', 0)}",
        "",
    ]
    return "\n".join(lines)


def _infer_sides(fields: list[str]) -> list[str]:
    """The two column families, the way the studio infers them.

    Columns sharing a prefix before the first underscore, where the prefix is
    not one of the decision or review column names.
    """
    reserved = set(_DECISION_COLUMNS) | set(REVIEW_FIELDS)
    reserved_prefixes = {c.split("_", 1)[0] for c in reserved}
    groups: dict[str, int] = {}
    for column in fields:
        if column in reserved or "_" not in column:
            continue
        prefix = column.split("_", 1)[0]
        if prefix in reserved_prefixes:
            continue
        groups[prefix] = groups.get(prefix, 0) + 1
    return sorted((p for p, n in groups.items() if n >= 2),
                  key=lambda p: -groups[p])[:2]


__all__ = [
    "ADJUDICATION_SCHEMA",
    "OUTCOME_DECISION",
    "SHARE_SCHEMA",
    "Pack",
    "PackError",
    "Problem",
    "REVIEW_FIELDS",
    "REVIEW_OUTCOMES",
    "apply_outcomes",
    "PACK_SUFFIXES",
    "effective_decision",
    "effective_decisions",
    "read_pack",
    "read_records",
    "share_artifact",
    "validate_pack",
    "verify_adjudication",
    "verify_decision_ids",
    "write_reviewed_csv",
]
