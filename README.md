# Sprint Health Analyzer
AI powered lightweight Streamlit app that analyzes sprint health and agile planning quality using Jira API or uploaded Jira exports.

- Health score (0-100)
- Completion ratio
- Scope change ratio (work added after sprint start)
- Carry-over risk
- Blocker ratio
- Pace vs elapsed sprint time
- Assignment and planned vs remaining workload
- Agile gap findings (estimation, scope quality, aging, workflow consistency, readiness)

## What it does
* Imports JIRA CSV exports or JIRA API
* Uses GPT-5 to analyze sprint velocity, story completion rates, blocker patterns
* Identifies risks: scope creep, technical debt, team capacity issues
* Generates actionable insights for TPMs and engineering managers

### 1) Data collection
Fetch **all issues in the sprint** (include subtasks if they are in the sprint) with at least these fields:
- key, summary
- issueType
- status (and status category)
- assignee (display name)
- priority
- created, updated, resolutiondate
- components, labels, fixVersions
- timetracking: original_estimate, remaining_estimate, time_spent
- parent (if subtask/story)

### 2) Assignment & time summary
Compute and output:
- **Team totals**
  - Planned time = sum(original_estimate)
  - Remaining time = sum(remaining_estimate)
  - (Optional) Time spent = sum(time_spent)
- **Per-assignee table** with:
  - Assignee, #issues
  - Planned (h), Remaining (h)
  - (Optional) list of issue keys
- Identify:
  - Unassigned issues
  - Unestimated issues (no original estimate and no remaining estimate)

### 3) Agile best-practice checks ( output findings + examples)
Evaluate the sprint for planning/process gaps. Provide:
- A bullet list of gaps, each with:
  - **What's the issue**
  - **Why it matters**
  - **Evidence** (counts + sample keys)
  - **Recommendation**

Runs these checks:

**A. Estimation hygiene**
- Count issues with missing original estimate.
- Count issues with missing remaining estimate.
- Count issues with both missing (unestimated).
- Flag Done issues where remaining_estimate > 0.

**B. Sprint scope quality / ticket quality**
- Find tickets with vague scope keywords in summary (e.g., `ad hoc`, `support`, `misc`, `bug fixes`, `investigate`, `TBD`).
- Identify oversized or "catch-all" tickets (high estimate + vague summary).
- Recommend splitting into smaller deliverable-based tickets.

**C. Stale work / aging**
- Count issues created long before sprint start (e.g., > 60/90 days old).
- Identify issues not updated recently but still in sprint.
- Recommend backlog refinement and re-validation of priority.

**D. Workflow consistency**
- Find issues with resolutiondate set but status category not Done.
- Find Done issues with no resolutiondate (if expected).
- Highlight inconsistent statuses (e.g., To Do with time_spent).

**E. Ready-ness / Definition of Ready indicators (heuristics)**
- Missing components/labels/fixVersion (if your org requires them).
- Missing assignee at sprint start (if known).
- High priority items still in To Do late in sprint (if sprint dates are provided).

### 4) Output format
Return:
1) Executive summary (5–10 lines)
2) Tables for assignment + planned vs remaining
3) Gap findings grouped by category (A–E)
4) "Top 5 actions for next sprint planning"

## Tech Stack
* Python 3.x
* OpenAI GPT-5 API
* Pandas (data processing)
* CSV import (works with JIRA, Azure DevOps, etc.)

## How to Use
### 1) Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2) Configure Jira credentials

Copy `.env.example` to `.env` and fill values:

```bash
copy .env.example .env
```

Required:
- `JIRA_BASE_URL` (example: `https://jira.company.com`
- `JIRA_EMAIL`
- `JIRA_API_TOKEN`
- `JIRA_BOARD_ID` (numeric board id)

Optional:
- `JIRA_STORY_POINTS_FIELD` (defaults to `customfield_10016`)
- `JIRA_DOMAIN` (backward compatible if you only have a domain value)
- `JIRA_PROJECT_KEY` (default filter in UI, example `ACME`)
- `JIRA_FIX_VERSION` (default filter in UI, example `3.04`)

### 3) Run

```bash
streamlit run app.py
```

Open the URL printed by Streamlit (usually `http://localhost:8501`).

## Sample Output
[Add screenshot here]

## Why I Built This
As a Principal TPM managing 300+ developers across 5 geographies at Oracle, I needed a faster way to identify sprint health issues. Manual analysis took 2-3 hours per sprint. This tool reduces that to 5 minutes.

## Notes

- If the Story Points field is unavailable, the app falls back to counting each issue as `1.0`.
- If no Sprint ID is provided, the app loads the active sprint from the board.
- You can use either a full URL (`https://jira.company.com`) or just a domain (`acme.atlassian.net`) in the app.
- Create a Jira API token here: <https://id.atlassian.com/manage-profile/security/api-tokens>
- If your Jira returns an HTML `401` page, the instance is likely behind SSO and does not accept email+token basic auth for REST API calls.
- Offline fallback: choose `Upload Export` in the sidebar, upload Jira `.csv`/`.json`, and provide sprint start/end dates.
- CSV/JSON upload supports these fields when present: key/summary/issue type/status/assignee/priority, created/updated/resolutiondate, components/labels/fixVersions, estimates/spent, parent.
