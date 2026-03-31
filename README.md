# Sprint Health Analyzer
AI-powered tool to analyze JIRA sprint data and identify blockers, risks, and team health indicators.
What It Does

## What it does
* Imports JIRA CSV exports or JIRA API
* Uses GPT-5 to analyze sprint velocity, story completion rates, blocker patterns
* Identifies risks: scope creep, technical debt, team capacity issues
* Generates actionable insights for TPMs and engineering managers

## Tech Stack
* Python 3.x
* OpenAI GPT-5 API
* Pandas (data processing)
* CSV import (works with JIRA, Azure DevOps, etc.)

## How to Use
* Export sprint data from JIRA (CSV format)
* Run: `python sprint_analyzer.py --input sprint_data.csv`
* View analysis output with AI-generated insights

## Sample Output
[Add screenshot here]

## Why I Built This
As a Principal TPM managing 300+ developers across 5 geographies at Oracle, I needed a faster way to identify sprint health issues. Manual analysis took 2-3 hours per sprint. This tool reduces that to 5 minutes.
