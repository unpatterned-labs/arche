"""Local Streamlit reviewer for Arche crosswalk adjudication packs."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import streamlit as st

OUTCOMES = ("same_entity", "different", "unresolved")
REVIEW_FIELDS = ("review_outcome", "reviewer", "reviewed_at", "reason")
DEFAULT_PACK = "data/review_packs/nigeria_facilities_2026-08-19/adjudication_pack.csv"


def _read_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    """Load the CSV and enforce the minimum review-pack shape."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fields = reader.fieldnames or []
    required = {"decision_id", "decision", "grid3_name", "hfr_name", *REVIEW_FIELDS}
    missing = required - set(fields)
    if missing:
        raise ValueError(f"review pack is missing columns: {', '.join(sorted(missing))}")
    if not rows:
        raise ValueError("review pack has no rows")
    return rows, fields


def _pack_signature(path: Path) -> str:
    """Return a local file signature used to reset stale session state."""
    stat = path.stat()
    return f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"


def _decision_digest(rows: list[dict[str, str]]) -> str:
    """Recompute the decision-ID manifest hash."""
    values = "\n".join(sorted(row["decision_id"] for row in rows))
    return hashlib.sha256(values.encode()).hexdigest()


def _read_manifest(path: Path) -> dict[str, Any] | None:
    """Load the optional sibling manifest without making it a requirement."""
    manifest_path = path.with_name("manifest.json")
    if not manifest_path.is_file():
        return None
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _reviewed(row: dict[str, str]) -> bool:
    """Return whether one row has a complete review outcome."""
    return bool((row.get("review_outcome") or "").strip())


def _visible_rows(
    rows: list[dict[str, str]], states: set[str], decisions: set[str], status: str
) -> list[dict[str, str]]:
    """Filter rows for the review list without mutating the source pack."""
    filtered = [
        row for row in rows
        if row.get("state", "") in states and row["decision"] in decisions
    ]
    if status == "Unreviewed":
        return [row for row in filtered if not _reviewed(row)]
    if status == "Reviewed":
        return [row for row in filtered if _reviewed(row)]
    return filtered


def _csv_bytes(rows: list[dict[str, str]], fields: list[str]) -> bytes:
    """Serialise a labelled copy for browser download."""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _now_utc() -> str:
    """Return a reviewer-friendly UTC timestamp."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _validate_review(outcome: str, reviewer: str, reviewed_at: str, reason: str) -> str | None:
    """Return a user-facing validation error, if one exists."""
    if outcome not in OUTCOMES:
        return "Choose an outcome before saving."
    if not reviewer.strip() or not reviewed_at.strip() or not reason.strip():
        return "Outcome, reviewer, UTC time, and reason are all required."
    try:
        parsed = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    except ValueError:
        return "Use an ISO 8601 UTC time, for example 2026-08-19T14:30:00Z."
    if parsed.tzinfo is None:
        return "The review time must include a UTC offset or Z."
    return None


def _load_pack(path: Path) -> tuple[list[dict[str, str]], list[str], dict[str, Any] | None]:
    """Load a new path into session state only when its local signature changes."""
    signature = _pack_signature(path)
    if st.session_state.get("pack_signature") != signature:
        rows, fields = _read_rows(path)
        st.session_state.pack_signature = signature
        st.session_state.rows = rows
        st.session_state.fields = fields
        st.session_state.manifest = _read_manifest(path)
    return st.session_state.rows, st.session_state.fields, st.session_state.manifest


def main() -> None:
    """Render the local review workflow."""
    st.set_page_config(page_title="Arche review log", page_icon="🔎", layout="wide")
    st.title("Arche review log")
    st.caption(
        "Inspect evidence, record an accountable outcome, then download a new labelled copy."
    )

    default_path = os.environ.get("REVIEW_PACK", DEFAULT_PACK)
    pack_text = st.sidebar.text_input("Review-pack CSV path", default_path)
    pack_path = Path(pack_text).expanduser()
    if not pack_path.is_file():
        st.error(f"Review pack not found: {pack_path}")
        st.stop()

    try:
        rows, fields, manifest = _load_pack(pack_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        st.error(f"Could not load review pack: {exc}")
        st.stop()

    digest = _decision_digest(rows)
    if manifest and manifest.get("decision_ids_sha256") != digest:
        st.error("The CSV decision IDs do not match its manifest. Do not review this file.")
        st.stop()

    reviewed = sum(_reviewed(row) for row in rows)
    decisions = Counter(row["decision"] for row in rows)
    outcomes = Counter(row["review_outcome"] for row in rows if _reviewed(row))
    metrics = st.columns(4)
    metrics[0].metric("Candidates", len(rows))
    metrics[1].metric("Reviewed", reviewed)
    metrics[2].metric("Match candidates", decisions.get("match", 0))
    metrics[3].metric("Review candidates", decisions.get("review", 0))
    st.caption(
        "Reviewed outcomes: " + ", ".join(
            f"{outcome}={outcomes.get(outcome, 0)}" for outcome in OUTCOMES
        )
    )

    all_states = sorted({row.get("state", "") for row in rows})
    states = set(st.sidebar.multiselect("States", all_states, default=all_states))
    decision_filter = set(st.sidebar.multiselect(
        "Matcher decision", ["match", "review"], default=["match", "review"]
    ))
    status = st.sidebar.radio("Review status", ["Unreviewed", "Reviewed", "All"])
    visible = _visible_rows(rows, states, decision_filter, status)
    st.subheader(f"Candidates in view: {len(visible)}")

    table_fields = [
        "state", "decision", "score", "distance_km", "grid3_name", "hfr_name",
        "review_outcome", "reviewer", "reviewed_at",
    ]
    st.dataframe(
        [{field: row.get(field, "") for field in table_fields} for row in visible],
        hide_index=True,
        use_container_width=True,
    )
    if not visible:
        st.info("No candidates match the current filters.")
        st.stop()

    by_id = {row["decision_id"]: row for row in visible}
    selected_id = st.selectbox(
        "Candidate to review",
        list(by_id),
        format_func=lambda value: (
            f"{by_id[value].get('state', '')} | {by_id[value]['decision']} | "
            f"{by_id[value]['grid3_name']} ↔ {by_id[value]['hfr_name']}"
        ),
    )
    selected = by_id[selected_id]
    left, right = st.columns(2)
    with left:
        st.markdown("#### GRID3 record")
        st.write(selected.get("grid3_name", ""))
        st.caption(selected.get("grid3_admin_path", ""))
        st.code(selected.get("grid3_id", ""), language=None)
    with right:
        st.markdown("#### HFR record")
        st.write(selected.get("hfr_name", ""))
        st.caption(selected.get("hfr_admin_path", ""))
        st.code(selected.get("hfr_id", ""), language=None)
    st.markdown("#### Matcher evidence")
    try:
        st.json(json.loads(selected.get("evidence", "{}")))
    except json.JSONDecodeError:
        st.code(selected.get("evidence", ""), language="json")
    st.caption(f"Decision ID: {selected['decision_id']}")

    current_outcome = selected.get("review_outcome", "")
    options = ["", *OUTCOMES]
    with st.form("review-form"):
        outcome = st.selectbox("Reviewer outcome", options, index=options.index(current_outcome))
        reviewer = st.text_input("Reviewer", value=selected.get("reviewer", ""))
        reviewed_at = st.text_input(
            "Reviewed at (UTC)", value=selected.get("reviewed_at") or _now_utc()
        )
        reason = st.text_area("Reason", value=selected.get("reason", ""))
        submit = st.form_submit_button("Apply outcome in this session")
    if submit:
        error = _validate_review(outcome, reviewer, reviewed_at, reason)
        if error:
            st.error(error)
        else:
            selected.update({
                "review_outcome": outcome,
                "reviewer": reviewer.strip(),
                "reviewed_at": reviewed_at.strip(),
                "reason": reason.strip(),
            })
            st.success("Outcome staged. Download the labelled CSV to preserve it.")

    st.download_button(
        "Download labelled adjudication pack",
        data=_csv_bytes(rows, fields),
        file_name="labelled_adjudication_pack.csv",
        mime="text/csv",
    )
    st.caption(
        "The app never overwrites the source CSV. Keep the source pack and manifest unchanged."
    )


if __name__ == "__main__":
    main()
