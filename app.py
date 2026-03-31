from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path
from typing import Any

import streamlit as st
from dotenv import load_dotenv

from analysis import analyze_sprint
from jira_client import JiraClient, JiraClientError
from metrics import compute_sprint_health


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _normalize_status_category(status_name: str) -> str:
    done_names = {
        "done",
        "closed",
        "resolved",
        "complete",
        "completed",
        "ACCEPTED",
    }
    return "done" if status_name.strip().lower() in done_names else "indeterminate"


def _pick_story_points_key(row: dict[str, Any], preferred_field: str) -> str | None:
    candidates = [
        preferred_field,
        "Story Points",
        "Story point estimate",
        "story_points",
        "story points",
        "SP",
    ]
    for key in candidates:
        if key in row:
            return key
    return None


def _parse_labels(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    text = str(value).strip()
    if not text:
        return []
    if "," in text:
        return [x.strip() for x in text.split(",") if x.strip()]
    if ";" in text:
        return [x.strip() for x in text.split(";") if x.strip()]
    return [text]


def _named_items(value: Any) -> list[dict[str, str]]:
    return [{"name": x} for x in _parse_labels(value)]


def _pick_key(row: dict[str, Any], candidates: list[str]) -> str | None:
    for key in candidates:
        if key in row:
            return key
    return None


def _parse_time_to_seconds(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)

    text = str(value).strip().lower()
    if not text:
        return 0
    if text.isdigit():
        return int(text)

    # Supports strings like "2h 30m", "1d", "45m".
    total = 0
    for amount, unit in re.findall(r"(\d+(?:\.\d+)?)\s*([wdhm])", text):
        qty = float(amount)
        if unit == "w":
            total += int(qty * 5 * 8 * 3600)
        elif unit == "d":
            total += int(qty * 8 * 3600)
        elif unit == "h":
            total += int(qty * 3600)
        elif unit == "m":
            total += int(qty * 60)
    return total


def _json_issue_to_internal(issue: dict[str, Any], story_points_field: str) -> dict[str, Any]:
    fields = issue.get("fields")
    if isinstance(fields, dict):
        status = fields.get("status") or {}
        if isinstance(status, dict) and not (status.get("statusCategory") or {}).get("key"):
            status_name = str(status.get("name") or "")
            status["statusCategory"] = {"key": _normalize_status_category(status_name)}
            fields["status"] = status
        if not fields.get("timetracking"):
            fields["timetracking"] = {
                "originalEstimateSeconds": 0,
                "remainingEstimateSeconds": 0,
                "timeSpentSeconds": 0,
            }
        return issue

    status_name = str(issue.get("status") or issue.get("Status") or "")
    sp_key = _pick_story_points_key(issue, story_points_field)
    sp_value = issue.get(sp_key) if sp_key else None
    type_key = _pick_key(issue, ["issueType", "Issue Type", "issuetype"])
    priority_key = _pick_key(issue, ["priority", "Priority"])
    components_key = _pick_key(issue, ["components", "Components"])
    fix_versions_key = _pick_key(issue, ["fixVersions", "Fix Version/s", "Fix Versions"])
    orig_key = _pick_key(issue, ["original_estimate", "Original Estimate", "originalEstimateSeconds"])
    rem_key = _pick_key(issue, ["remaining_estimate", "Remaining Estimate", "remainingEstimateSeconds"])
    spent_key = _pick_key(issue, ["time_spent", "Time Spent", "timeSpentSeconds"])
    parent_key = _pick_key(issue, ["parent", "Parent"])

    return {
        "key": issue.get("key") or issue.get("Key"),
        "fields": {
            "summary": issue.get("summary") or issue.get("Summary") or "",
            "created": issue.get("created") or issue.get("Created"),
            "updated": issue.get("updated") or issue.get("Updated"),
            "resolutiondate": issue.get("resolutiondate") or issue.get("Resolution"),
            "labels": _parse_labels(issue.get("labels") or issue.get("Labels")),
            "components": _named_items(issue.get(components_key)) if components_key else [],
            "fixVersions": _named_items(issue.get(fix_versions_key)) if fix_versions_key else [],
            "issuetype": {"name": issue.get(type_key) if type_key else ""},
            "status": {
                "name": status_name,
                "statusCategory": {"key": _normalize_status_category(status_name)},
            },
            "priority": {"name": issue.get(priority_key) if priority_key else ""},
            "assignee": {"displayName": issue.get("assignee") or issue.get("Assignee")},
            "timetracking": {
                "originalEstimateSeconds": _parse_time_to_seconds(issue.get(orig_key)) if orig_key else 0,
                "remainingEstimateSeconds": _parse_time_to_seconds(issue.get(rem_key)) if rem_key else 0,
                "timeSpentSeconds": _parse_time_to_seconds(issue.get(spent_key)) if spent_key else 0,
            },
            "parent": {"key": issue.get(parent_key)} if parent_key and issue.get(parent_key) else None,
            story_points_field: sp_value,
        },
    }


def _csv_row_to_internal(row: dict[str, str], story_points_field: str) -> dict[str, Any]:
    status_name = row.get("Status", "")
    sp_key = _pick_story_points_key(row, story_points_field)
    sp_value = row.get(sp_key) if sp_key else None
    orig_key = _pick_key(row, ["Original Estimate", "original_estimate", "Original estimate"])
    rem_key = _pick_key(row, ["Remaining Estimate", "remaining_estimate", "Remaining estimate"])
    spent_key = _pick_key(row, ["Time Spent", "time_spent", "Time spent"])
    return {
        "key": row.get("Key") or row.get("Issue key"),
        "fields": {
            "summary": row.get("Summary", ""),
            "created": row.get("Created", ""),
            "updated": row.get("Updated", ""),
            "resolutiondate": row.get("Resolved", "") or row.get("Resolution date", ""),
            "labels": _parse_labels(row.get("Labels", "")),
            "components": _named_items(row.get("Component/s", "") or row.get("Components", "")),
            "fixVersions": _named_items(row.get("Fix Version/s", "") or row.get("Fix Versions", "")),
            "issuetype": {"name": row.get("Issue Type", "")},
            "status": {
                "name": status_name,
                "statusCategory": {"key": _normalize_status_category(row.get("Status Category", "") or status_name)},
            },
            "priority": {"name": row.get("Priority", "")},
            "assignee": {"displayName": row.get("Assignee", "Unassigned")},
            "timetracking": {
                "originalEstimateSeconds": _parse_time_to_seconds(row.get(orig_key, "")) if orig_key else 0,
                "remainingEstimateSeconds": _parse_time_to_seconds(row.get(rem_key, "")) if rem_key else 0,
                "timeSpentSeconds": _parse_time_to_seconds(row.get(spent_key, "")) if spent_key else 0,
            },
            "parent": {"key": row.get("Parent", "")} if row.get("Parent", "") else None,
            story_points_field: sp_value,
        },
    }


def load_uploaded_issues(uploaded_file: Any, story_points_field: str) -> list[dict[str, Any]]:
    filename = (uploaded_file.name or "").lower()
    raw = uploaded_file.getvalue()
    if filename.endswith(".json"):
        payload = json.loads(raw.decode("utf-8"))
        if isinstance(payload, dict):
            if isinstance(payload.get("issues"), list):
                source_issues = payload["issues"]
            elif isinstance(payload.get("values"), list):
                source_issues = payload["values"]
            else:
                raise ValueError("JSON must contain an 'issues' or 'values' array.")
        elif isinstance(payload, list):
            source_issues = payload
        else:
            raise ValueError("Unsupported JSON format.")
        return [_json_issue_to_internal(issue, story_points_field) for issue in source_issues if isinstance(issue, dict)]

    if filename.endswith(".csv"):
        text = raw.decode("utf-8-sig")
        rows = list(csv.DictReader(text.splitlines()))
        return [_csv_row_to_internal(row, story_points_field) for row in rows]

    raise ValueError("Unsupported file type. Upload a .csv or .json export.")


def main() -> None:
    env_path = Path(__file__).resolve().with_name(".env")
    load_dotenv(dotenv_path=env_path)
    st.set_page_config(page_title="Jira Sprint Health", layout="wide")
    st.title("Jira Sprint Health")
    st.caption("Monitor a sprint with a single health score and leading indicators.")

    with st.sidebar:
        st.header("Jira Connection")
        default_base_url = os.getenv("JIRA_BASE_URL", "") or os.getenv("JIRA_DOMAIN", "")
        default_email = os.getenv("JIRA_EMAIL", "")
        default_token = os.getenv("JIRA_API_TOKEN", "")
        default_sp_field = os.getenv("JIRA_STORY_POINTS_FIELD", "customfield_10016")
        default_board_id = os.getenv("JIRA_BOARD_ID", "")
        default_project_key = os.getenv("JIRA_PROJECT_KEY", "FMK")
        default_fix_version = os.getenv("JIRA_FIX_VERSION", "26.07")
        data_source = st.radio("Data Source", ["Live Jira API", "Upload Export"], index=0)
        project_key_filter = st.text_input("Project Key (optional filter)", value=default_project_key)
        fix_version_filter = st.text_input("Fix Version (optional filter)", value=default_fix_version)

        story_points_field = st.text_input("Story Points Field", value=default_sp_field)
        base_url = ""
        email = ""
        api_token = ""
        board_id_input = ""
        sprint_id_input = ""
        uploaded_file = None
        sprint_name = "Manual Sprint"
        sprint_start = None
        sprint_end = None

        if data_source == "Live Jira API":
            base_url = st.text_input(
                "Base URL or Domain",
                value=default_base_url,
                placeholder="https://jira.oraclecorp.com/jira or your-company.atlassian.net",
            )
            email = st.text_input("Email", value=default_email)
            api_token = st.text_input("API Token", value=default_token, type="password")
            board_id_input = st.text_input("Board ID", value=default_board_id, placeholder="e.g. 12")
            sprint_id_input = st.text_input(
                "Sprint ID (optional)", placeholder="If empty, active sprint will be used"
            )
        else:
            uploaded_file = st.file_uploader("Jira Export (.csv or .json)", type=["csv", "json"])
            sprint_name = st.text_input("Sprint Name", value="Manual Sprint")
            sprint_start = st.date_input("Sprint Start Date")
            sprint_end = st.date_input("Sprint End Date")

        load_btn = st.button("Run Sprint Analysis", type="primary")

    if not load_btn:
        st.info("Configure input and click `Run Sprint Analysis`.")
        return

    sprint_id = None
    if data_source == "Live Jira API" and sprint_id_input.strip():
        try:
            sprint_id = int(sprint_id_input)
        except ValueError:
            st.error("Sprint ID must be a number when provided.")
            return

    try:
        if data_source == "Live Jira API":
            if not base_url.strip() or not email.strip() or not api_token.strip() or not board_id_input.strip():
                st.error("Base URL/Domain, Email, API Token, and Board ID are required.")
                return

            try:
                board_id = int(board_id_input)
            except ValueError:
                st.error("Board ID must be a number.")
                return

            client = JiraClient(base_url_or_domain=base_url, email=email, api_token=api_token)
            if sprint_id is None:
                sprints = client.get_sprints(board_id, state="active")
                if not sprints:
                    st.error("No active sprint found. Set Sprint ID manually.")
                    return
                sprint = sprints[0]
                sprint_id = int(sprint["id"])
            else:
                sprint = client.get_sprint(sprint_id)

            issues = client.get_sprint_issues(sprint_id)
        else:
            if uploaded_file is None:
                st.error("Upload a Jira export file (.csv or .json).")
                return
            if sprint_end < sprint_start:
                st.error("Sprint End Date must be on or after Sprint Start Date.")
                return

            issues = load_uploaded_issues(uploaded_file, story_points_field)
            if not issues:
                st.error("No issues found in uploaded file.")
                return

            sprint = {
                "name": sprint_name.strip() or "Manual Sprint",
                "state": "active",
                "startDate": f"{sprint_start.isoformat()}T00:00:00+00:00",
                "endDate": f"{sprint_end.isoformat()}T23:59:59+00:00",
            }
            sprint_id = "manual"

        filtered_issues = []
        for issue in issues:
            fields = issue.get("fields", {}) or {}
            key = str(issue.get("key") or "")
            project_ok = True
            fix_ok = True

            if project_key_filter.strip():
                project_ok = key.upper().startswith(project_key_filter.strip().upper() + "-")
            if fix_version_filter.strip():
                fx = {str((x or {}).get("name") or "").strip().lower() for x in (fields.get("fixVersions") or [])}
                fix_ok = fix_version_filter.strip().lower() in fx

            if project_ok and fix_ok:
                filtered_issues.append(issue)

        if not filtered_issues:
            st.error("No issues matched the Project Key / Fix Version filters.")
            return

        issues = filtered_issues
        health = compute_sprint_health(sprint, issues, story_points_field)
        sprint_analysis = analyze_sprint(sprint, issues)
    except (JiraClientError, ValueError) as exc:
        st.error(str(exc))
        return

    st.subheader("Executive Summary")
    for line in sprint_analysis.executive_summary_lines:
        st.write(f"- {line}")
    for assumption in sprint_analysis.assumptions:
        st.info(f"Assumption: {assumption}")

    score_col, detail_col = st.columns([1, 2], gap="large")

    with score_col:
        st.metric("Health Score", f"{health.health_score:.0f}/100")
        st.progress(health.health_score / 100.0)
        st.write("")
        st.write(f"**Sprint:** {sprint.get('name', sprint_id)}")
        st.write(f"**State:** {sprint.get('state', 'n/a')}")
        st.write(f"**Issues:** {len(issues)}")

    with detail_col:
        c1, c2, c3 = st.columns(3)
        c1.metric("Completion", pct(health.completion_ratio))
        c2.metric("Scope Change", pct(health.scope_change_ratio))
        c3.metric("Carry Over Risk", pct(health.carry_over_ratio))

        c4, c5, c6 = st.columns(3)
        c4.metric("Blocker Ratio", pct(health.blocker_ratio))
        c5.metric("Pace vs Time", pct(health.pace_delta))
        c6.metric("Committed Done", f"{health.committed_done_count}/{health.committed_total_count}")

        st.divider()
        st.subheader("Volume")
        v1, v2, v3 = st.columns(3)
        v1.metric("Committed Work", f"{health.committed_total:.1f}")
        v2.metric("Completed Work", f"{health.completed_total:.1f}")
        v3.metric("Added After Start", f"{health.added_after_start_total:.1f}")

    st.divider()
    st.subheader("Assignment + Planned vs Remaining")
    team_col1, team_col2, team_col3 = st.columns(3)
    team_col1.metric("Team Planned (h)", f"{sprint_analysis.team_planned_seconds / 3600.0:.2f}")
    team_col2.metric("Team Remaining (h)", f"{sprint_analysis.team_remaining_seconds / 3600.0:.2f}")
    team_col3.metric("Team Spent (h)", f"{sprint_analysis.team_spent_seconds / 3600.0:.2f}")

    st.dataframe(sprint_analysis.per_assignee_rows, use_container_width=True, hide_index=True)
    st.write(f"**Unassigned issues ({len(sprint_analysis.unassigned_keys)}):** {', '.join(sprint_analysis.unassigned_keys[:20]) or 'none'}")
    st.write(f"**Unestimated issues ({len(sprint_analysis.unestimated_keys)}):** {', '.join(sprint_analysis.unestimated_keys[:20]) or 'none'}")

    st.divider()
    st.subheader("Agile Best-Practice Gaps (A-E)")
    for finding in sprint_analysis.findings:
        with st.expander(f"{finding.category}: {finding.issue}", expanded=False):
            st.write(f"**Why it matters:** {finding.why}")
            st.write(f"**Evidence:** {finding.evidence}")
            st.write(f"**Recommendation:** {finding.recommendation}")

    st.divider()
    st.subheader("Top 5 Actions For Next Sprint Planning")
    for idx, action in enumerate(sprint_analysis.top_actions, start=1):
        st.write(f"{idx}. {action}")

    with st.expander("Issue Details"):
        rows = []
        for issue in issues:
            fields = issue.get("fields", {})
            status = (fields.get("status") or {}).get("name", "")
            assignee = (fields.get("assignee") or {}).get("displayName", "Unassigned")
            sp = fields.get(story_points_field)
            tt = fields.get("timetracking") or {}
            rows.append(
                {
                    "key": issue.get("key"),
                    "summary": fields.get("summary", ""),
                    "issue_type": (fields.get("issuetype") or {}).get("name", ""),
                    "status": status,
                    "status_category": ((fields.get("status") or {}).get("statusCategory") or {}).get("key", ""),
                    "assignee": assignee,
                    "priority": (fields.get("priority") or {}).get("name", ""),
                    "created": fields.get("created", ""),
                    "updated": fields.get("updated", ""),
                    "resolutiondate": fields.get("resolutiondate", ""),
                    "story_points": sp,
                    "planned_h": round((tt.get("originalEstimateSeconds", 0) or 0) / 3600.0, 2),
                    "remaining_h": round((tt.get("remainingEstimateSeconds", 0) or 0) / 3600.0, 2),
                    "spent_h": round((tt.get("timeSpentSeconds", 0) or 0) / 3600.0, 2),
                    "components": ", ".join((x or {}).get("name", "") for x in (fields.get("components") or [])),
                    "fix_versions": ", ".join((x or {}).get("name", "") for x in (fields.get("fixVersions") or [])),
                    "labels": ", ".join(fields.get("labels", [])),
                    "parent": ((fields.get("parent") or {}).get("key", "")),
                }
            )
        st.dataframe(rows, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
