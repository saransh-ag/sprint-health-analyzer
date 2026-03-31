from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse, urlunparse

import requests


class JiraClientError(RuntimeError):
    pass


@dataclass
class JiraClient:
    base_url_or_domain: str
    email: str
    api_token: str
    timeout_seconds: int = 30

    def __post_init__(self) -> None:
        raw = self.base_url_or_domain.strip()
        if not (raw.startswith("http://") or raw.startswith("https://")):
            raw = f"https://{raw}"

        parsed = urlparse(raw)
        segments = [segment for segment in parsed.path.split("/") if segment]
        if not segments:
            normalized_path = ""
        elif len(segments) == 1:
            normalized_path = f"/{segments[0]}"
        else:
            # Users often paste project URLs (.../jira/projects/XYZ); keep only the context root.
            normalized_path = f"/{segments[0]}"

        self.base_url = urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                normalized_path.rstrip("/"),
                "",
                "",
                "",
            )
        ).rstrip("/")

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        response = requests.get(
            url,
            params=params,
            auth=(self.email, self.api_token),
            headers={"Accept": "application/json"},
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 400:
            content_type = response.headers.get("Content-Type", "")
            body_preview = response.text[:500]
            if response.status_code == 401 and "text/html" in content_type.lower():
                message = (
                    "Jira API authentication failed (401 HTML response). "
                    "This Jira instance appears to use SSO/web login for this endpoint, "
                    "so email + API token basic auth is likely not supported. "
                    "Use a Jira API-compatible host/token pair (for example Atlassian Cloud), "
                    "or an auth method supported by your Oracle Jira admins."
                )
            else:
                message = f"Jira API request failed: {response.status_code} {body_preview}"
            raise JiraClientError(message)
        return response.json()

    def get_boards(self, name_filter: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"maxResults": 100}
        if name_filter:
            params["name"] = name_filter
        data = self._get("/rest/agile/1.0/board", params=params)
        return data.get("values", [])

    def get_sprints(self, board_id: int, state: str = "active,future,closed") -> list[dict[str, Any]]:
        data = self._get(
            f"/rest/agile/1.0/board/{board_id}/sprint",
            params={"state": state, "maxResults": 100},
        )
        return data.get("values", [])

    def get_sprint(self, sprint_id: int) -> dict[str, Any]:
        return self._get(f"/rest/agile/1.0/sprint/{sprint_id}")

    def get_sprint_issues(self, sprint_id: int) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        start_at = 0
        page_size = 100

        while True:
            data = self._get(
                f"/rest/agile/1.0/sprint/{sprint_id}/issue",
                params={"maxResults": page_size, "startAt": start_at},
            )
            page_items = data.get("issues", [])
            issues.extend(page_items)
            if start_at + page_size >= data.get("total", 0):
                break
            start_at += page_size

        return issues
