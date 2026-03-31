from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from metrics import parse_jira_datetime


VAGUE_SCOPE_KEYWORDS = ("ad hoc", "support", "misc", "bug fixes", "investigate", "tbd")
DONE_STATUS_CANDIDATES = {"done", "closed", "resolved", "complete", "completed"}
HIGH_PRIORITY_CANDIDATES = {"highest", "high", "p0", "p1", "critical", "blocker"}


@dataclass
class GapFinding:
    category: str
    issue: str
    why: str
    evidence: str
    recommendation: str


@dataclass
class SprintAnalysis:
    team_planned_seconds: int
    team_remaining_seconds: int
    team_spent_seconds: int
    per_assignee_rows: list[dict[str, Any]]
    unassigned_keys: list[str]
    unestimated_keys: list[str]
    findings: list[GapFinding]
    executive_summary_lines: list[str]
    top_actions: list[str]
    assumptions: list[str]


def _to_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip()
    if not text:
        return default
    try:
        return int(float(text))
    except ValueError:
        return default


def _hours(seconds: int) -> float:
    return round(seconds / 3600.0, 2)


def _sample_keys(keys: list[str], limit: int = 5) -> str:
    if not keys:
        return "none"
    return ", ".join(keys[:limit])


def _is_done(status_category_key: str, status_name: str) -> bool:
    if status_category_key.strip().lower() == "done":
        return True
    return status_name.strip().lower() in DONE_STATUS_CANDIDATES


def analyze_sprint(
    sprint: dict[str, Any],
    issues: list[dict[str, Any]],
    reference_now: datetime | None = None,
) -> SprintAnalysis:
    now = reference_now or datetime.now(timezone.utc)
    start = parse_jira_datetime(sprint.get("startDate"))
    end = parse_jira_datetime(sprint.get("endDate"))
    has_sprint_dates = bool(start and end)
    if not has_sprint_dates:
        start = now
        end = now

    assignee_rollup: dict[str, dict[str, Any]] = {}
    unassigned_keys: list[str] = []
    unestimated_keys: list[str] = []

    missing_original: list[str] = []
    missing_remaining: list[str] = []
    both_missing: list[str] = []
    done_with_remaining: list[str] = []
    vague_scope: list[str] = []
    oversized_catch_all: list[str] = []
    created_old_60: list[str] = []
    created_old_90: list[str] = []
    stale_updates: list[str] = []
    resolved_not_done: list[str] = []
    done_without_resolution: list[str] = []
    todo_with_spent: list[str] = []
    missing_meta: list[str] = []
    missing_fix_version: list[str] = []
    missing_assignee_at_start: list[str] = []
    high_priority_todo_late: list[str] = []

    team_planned = 0
    team_remaining = 0
    team_spent = 0

    sprint_progress = 0.0
    if has_sprint_dates and end > start:
        sprint_progress = min(max((now - start).total_seconds() / (end - start).total_seconds(), 0.0), 1.0)

    for issue in issues:
        key = str(issue.get("key") or "")
        fields = issue.get("fields", {}) or {}
        summary = str(fields.get("summary") or "")
        status = fields.get("status", {}) or {}
        status_name = str(status.get("name") or "")
        status_category_key = str((status.get("statusCategory") or {}).get("key") or "")
        assignee_obj = fields.get("assignee") or {}
        assignee = str(assignee_obj.get("displayName") or "Unassigned")
        priority = str((fields.get("priority") or {}).get("name") or "")
        labels = fields.get("labels") or []
        components = fields.get("components") or []
        fix_versions = fields.get("fixVersions") or []
        created = parse_jira_datetime(fields.get("created"))
        updated = parse_jira_datetime(fields.get("updated"))
        resolution_date = parse_jira_datetime(fields.get("resolutiondate"))

        tt = fields.get("timetracking") or {}
        original_seconds = _to_int(tt.get("originalEstimateSeconds"))
        remaining_seconds = _to_int(tt.get("remainingEstimateSeconds"))
        spent_seconds = _to_int(tt.get("timeSpentSeconds"))

        team_planned += original_seconds
        team_remaining += remaining_seconds
        team_spent += spent_seconds

        if assignee not in assignee_rollup:
            assignee_rollup[assignee] = {
                "Assignee": assignee,
                "#issues": 0,
                "Planned (h)": 0.0,
                "Remaining (h)": 0.0,
                "Time spent (h)": 0.0,
                "Issue keys": [],
            }
        row = assignee_rollup[assignee]
        row["#issues"] += 1
        row["Planned (h)"] = round(row["Planned (h)"] + (original_seconds / 3600.0), 2)
        row["Remaining (h)"] = round(row["Remaining (h)"] + (remaining_seconds / 3600.0), 2)
        row["Time spent (h)"] = round(row["Time spent (h)"] + (spent_seconds / 3600.0), 2)
        if key:
            row["Issue keys"].append(key)

        if assignee == "Unassigned":
            unassigned_keys.append(key)

        if original_seconds <= 0:
            missing_original.append(key)
        if remaining_seconds <= 0:
            missing_remaining.append(key)
        if original_seconds <= 0 and remaining_seconds <= 0:
            both_missing.append(key)
            unestimated_keys.append(key)

        if _is_done(status_category_key, status_name) and remaining_seconds > 0:
            done_with_remaining.append(key)

        summary_lc = summary.lower()
        has_vague = any(word in summary_lc for word in VAGUE_SCOPE_KEYWORDS)
        if has_vague:
            vague_scope.append(key)
        if has_vague and original_seconds >= 16 * 3600:
            oversized_catch_all.append(key)

        if created and has_sprint_dates:
            age_days = (start - created).days
            if age_days > 60:
                created_old_60.append(key)
            if age_days > 90:
                created_old_90.append(key)

        if updated:
            stale_days = (now - updated).days
            if stale_days >= 14 and not _is_done(status_category_key, status_name):
                stale_updates.append(key)

        if resolution_date and not _is_done(status_category_key, status_name):
            resolved_not_done.append(key)
        if _is_done(status_category_key, status_name) and not resolution_date:
            done_without_resolution.append(key)

        if status_name.strip().lower() in {"to do", "open", "selected for development"} and spent_seconds > 0:
            todo_with_spent.append(key)

        if not labels or not components:
            missing_meta.append(key)
        if not fix_versions:
            missing_fix_version.append(key)
        if assignee == "Unassigned" and has_sprint_dates and created and created <= start:
            missing_assignee_at_start.append(key)

        if (
            priority.strip().lower() in HIGH_PRIORITY_CANDIDATES
            and status_name.strip().lower() in {"to do", "open", "selected for development"}
            and sprint_progress >= 0.7
        ):
            high_priority_todo_late.append(key)

    per_assignee = sorted(assignee_rollup.values(), key=lambda x: (-x["Remaining (h)"], x["Assignee"]))
    for row in per_assignee:
        row["Issue keys"] = ", ".join(row["Issue keys"][:10])

    findings: list[GapFinding] = []

    findings.append(
        GapFinding(
            category="A. Estimation hygiene",
            issue="Estimation coverage gaps",
            why="Missing estimates weaken sprint capacity and burn tracking.",
            evidence=(
                f"Missing original: {len(missing_original)} ({_sample_keys(missing_original)}); "
                f"Missing remaining: {len(missing_remaining)} ({_sample_keys(missing_remaining)}); "
                f"Both missing: {len(both_missing)} ({_sample_keys(both_missing)})."
            ),
            recommendation="Require original + remaining estimate at sprint entry; enforce via board filter/workflow validator.",
        )
    )
    findings.append(
        GapFinding(
            category="B. Estimation hygiene",
            issue="Done issues still carry remaining estimate",
            why="Residual remaining time on Done tickets distorts completion and forecasting.",
            evidence=f"Count: {len(done_with_remaining)} ({_sample_keys(done_with_remaining)}).",
            recommendation="Auto-zero remaining estimate on transition to Done or add transition screen validation.",
        )
    )
    findings.append(
        GapFinding(
            category="C. Sprint scope quality / ticket quality",
            issue="Vague/catch-all scope detected",
            why="Ambiguous scope hides risk and prevents objective acceptance criteria.",
            evidence=(
                f"Vague summary matches: {len(vague_scope)} ({_sample_keys(vague_scope)}); "
                f"Oversized catch-all (>=16h): {len(oversized_catch_all)} ({_sample_keys(oversized_catch_all)})."
            ),
            recommendation="Split into outcome-based tickets with clear acceptance criteria and bounded estimates.",
        )
    )
    findings.append(
        GapFinding(
            category="D. Stale work / aging",
            issue="Aging and stale in-sprint work",
            why="Old or untouched tickets in sprint often indicate planning debt and hidden carry-over.",
            evidence=(
                f"Created >60d before sprint start: {len(created_old_60)} ({_sample_keys(created_old_60)}); "
                f"Created >90d: {len(created_old_90)} ({_sample_keys(created_old_90)}); "
                f"Not updated in 14+ days and not Done: {len(stale_updates)} ({_sample_keys(stale_updates)})."
            ),
            recommendation="Run refinement before sprint start; remove/re-scope stale items and revalidate priority.",
        )
    )
    findings.append(
        GapFinding(
            category="E. Workflow consistency",
            issue="Status/resolution/time inconsistencies",
            why="Workflow inconsistencies reduce reporting trust and automation accuracy.",
            evidence=(
                f"Resolution date set but not Done: {len(resolved_not_done)} ({_sample_keys(resolved_not_done)}); "
                f"Done without resolution date: {len(done_without_resolution)} ({_sample_keys(done_without_resolution)}); "
                f"To Do/Open with time spent: {len(todo_with_spent)} ({_sample_keys(todo_with_spent)})."
            ),
            recommendation="Harden workflow transitions and post-functions to keep status, resolution, and worklog aligned.",
        )
    )
    findings.append(
        GapFinding(
            category="F. Ready-ness / DoR indicators",
            issue="Readiness metadata and ownership gaps",
            why="Missing metadata/ownership reduces traceability and slows execution during sprint.",
            evidence=(
                f"Missing labels/components: {len(missing_meta)} ({_sample_keys(missing_meta)}); "
                f"Missing fixVersion: {len(missing_fix_version)} ({_sample_keys(missing_fix_version)}); "
                f"Unassigned at sprint start: {len(missing_assignee_at_start)} ({_sample_keys(missing_assignee_at_start)}); "
                f"High-priority still To Do late sprint: {len(high_priority_todo_late)} ({_sample_keys(high_priority_todo_late)})."
            ),
            recommendation="Enforce DoR checklist (assignee, metadata, fixVersion, estimate) before sprint commitment.",
        )
    )

    summary_lines = [
        f"Sprint analyzed: {sprint.get('name', 'n/a')} with {len(issues)} issues.",
        f"Team planned: {_hours(team_planned):.2f}h, remaining: {_hours(team_remaining):.2f}h, spent: {_hours(team_spent):.2f}h.",
        f"Unassigned issues: {len(unassigned_keys)}. Unestimated issues: {len(unestimated_keys)}.",
        f"Estimation hygiene gaps found on original/remaining estimates and Done-with-remaining checks.",
        f"Scope quality flags found for vague and catch-all tickets.",
        f"Workflow consistency checks surfaced status-resolution-time mismatches.",
        f"Readiness indicators show metadata/ownership improvement opportunities.",
    ]

    top_actions = [
        "Set sprint-entry policy: no ticket enters sprint without assignee + original + remaining estimate.",
        "Split vague or oversized tickets into 1-2 day deliverables with measurable acceptance criteria.",
        "Add workflow validators/post-functions for resolution date and remaining estimate on Done transition.",
        "Run a weekly stale-item sweep for tickets not updated in 14+ days.",
        "Enforce DoR metadata (components, labels, fixVersion) in backlog refinement before sprint planning.",
    ]

    assumptions: list[str] = []
    if not has_sprint_dates:
        assumptions.append(
            "Sprint start/end dates were unavailable; current date was used as reference for aging-related checks."
        )

    return SprintAnalysis(
        team_planned_seconds=team_planned,
        team_remaining_seconds=team_remaining,
        team_spent_seconds=team_spent,
        per_assignee_rows=per_assignee,
        unassigned_keys=unassigned_keys,
        unestimated_keys=unestimated_keys,
        findings=findings,
        executive_summary_lines=summary_lines,
        top_actions=top_actions,
        assumptions=assumptions,
    )
