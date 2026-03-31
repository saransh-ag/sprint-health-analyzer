from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def parse_jira_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None

    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        pass

    formats = [
        "%d/%b/%y %I:%M %p",  # 11/Mar/26 12:07 PM
        "%d/%b/%Y %I:%M %p",
        "%Y-%m-%d %H:%M:%S",
        "%d-%b-%Y %H:%M",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    raise ValueError(f"Unsupported date format: {value}")


def to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass
class SprintHealth:
    health_score: float
    completion_ratio: float
    scope_change_ratio: float
    carry_over_ratio: float
    blocker_ratio: float
    pace_delta: float
    committed_total: float
    completed_total: float
    added_after_start_total: float
    committed_done_count: int
    committed_total_count: int
    blockers_count: int
    carry_over_count: int
    now: datetime


def compute_sprint_health(
    sprint: dict[str, Any], issues: list[dict[str, Any]], story_points_field: str
) -> SprintHealth:
    start = parse_jira_datetime(sprint.get("startDate"))
    end = parse_jira_datetime(sprint.get("endDate"))
    now = datetime.now(timezone.utc)
    if not start or not end:
        raise ValueError("Sprint does not include startDate/endDate.")
    cutoff = min(now, end)

    committed_total = 0.0
    completed_total = 0.0
    added_after_start_total = 0.0

    committed_total_count = 0
    committed_done_count = 0
    blockers_count = 0
    carry_over_count = 0

    for issue in issues:
        fields = issue.get("fields", {})
        created = parse_jira_datetime(fields.get("created"))
        resolution_date = parse_jira_datetime(fields.get("resolutiondate"))
        status = fields.get("status", {}) or {}
        status_category = (status.get("statusCategory") or {}).get("key")
        done_now = status_category == "done"

        # For historical sprints, evaluate completion as of sprint end instead of current status.
        if resolution_date is not None:
            done = resolution_date <= cutoff
        else:
            done = done_now

        labels = [str(x).lower() for x in fields.get("labels", [])]
        is_blocked = "blocked" in labels or "blocker" in labels
        if is_blocked and not done:
            blockers_count += 1

        points = to_float(fields.get(story_points_field))
        if points <= 0:
            points = 1.0

        committed = bool(created and created <= start)
        if committed:
            committed_total += points
            committed_total_count += 1
            if done:
                completed_total += points
                committed_done_count += 1
            else:
                carry_over_count += 1
        else:
            added_after_start_total += points

    completion_ratio = (completed_total / committed_total) if committed_total else 0.0
    scope_change_ratio = (
        added_after_start_total / committed_total if committed_total else 0.0
    )
    carry_over_ratio = (
        (committed_total_count - committed_done_count) / committed_total_count
        if committed_total_count
        else 0.0
    )
    blocker_ratio = blockers_count / len(issues) if issues else 0.0

    elapsed_ratio = min(max((cutoff - start).total_seconds() / (end - start).total_seconds(), 0.0), 1.0)
    pace_delta = completion_ratio - elapsed_ratio

    health = 100.0
    health -= max(0.0, (1.0 - completion_ratio)) * 45.0
    health -= min(scope_change_ratio, 1.0) * 20.0
    health -= carry_over_ratio * 20.0
    health -= blocker_ratio * 10.0
    health += min(max(pace_delta, -1.0), 1.0) * 5.0
    health = min(max(health, 0.0), 100.0)

    return SprintHealth(
        health_score=health,
        completion_ratio=completion_ratio,
        scope_change_ratio=scope_change_ratio,
        carry_over_ratio=carry_over_ratio,
        blocker_ratio=blocker_ratio,
        pace_delta=pace_delta,
        committed_total=committed_total,
        completed_total=completed_total,
        added_after_start_total=added_after_start_total,
        committed_done_count=committed_done_count,
        committed_total_count=committed_total_count,
        blockers_count=blockers_count,
        carry_over_count=carry_over_count,
        now=now,
    )
