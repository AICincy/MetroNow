---
name: community-prep
description: Prepare all OSM community requirements before mechanical edits — wiki page, talk-us discussion, import account setup, changeset tag templates. This is mandatory and NOT optional.
when_to_use: "User mentions community compliance, wiki page, talk-us, import account, before first submission, or asks if ready to submit"
allowed-tools: Read Grep Glob Bash(python *) Bash(curl *)
---

# OSM Community Compliance Preparation

## Why this is mandatory

RESEARCH-FINDINGS Section 3 Item 8 and CLAUDE.md both state: mechanical edits require wiki documentation, `talk-us@` discussion, and `_cincyimport`-convention account. Failing to comply risks **unilateral revert by the DWG without notice**, regardless of edit quality.

## Checklist

### 1. Wiki documentation page
Create at: `wiki.openstreetmap.org/wiki/Automated_edits/<username>`

Must include:
- Description of the edit (TIGER defect correction in MetroNow zones)
- Scope (4 Hamilton County zones, specific defect classes)
- Data sources (Overpass, CAGIS, ODOT TIMS)
- Methodology (DaveHansenTiger filter, classification algorithm, gap detection)
- Expected edit volume and cadence
- Contact information
- Link to this GitHub project

### 2. Community discussion
Post on BOTH:
- `talk-us@openstreetmap.org` mailing list
- `community.openstreetmap.org` forum (US section)

Discussion should describe:
- What you plan to edit and why
- How MetroNow riders benefit
- The detection methodology
- How to opt out
- Timeline and expected volume

### 3. Dedicated import account
Follow the Cincinnati convention established by the CAGIS Building Import:
- Account name: `<username>_cincyimport` (e.g., `krassy513_cincyimport`)
- Wiki link in profile description
- User page explaining the account's purpose

### 4. Changeset tag template
Prepare the standard tags (see `/changeset-submit` for full list):
- `comment=` — descriptive per-changeset
- `source=` — data sources used
- `mechanical=yes`
- `created_by=MetroNow TIGER Audit Pipeline`
- `description=` — URL to wiki documentation page
- `bot=yes` if fully automated (not for reviewed edits)

### 5. Local community coordination
The Cincinnati OSM community is active:
- Minh Nguyen (User:Mxn) — experienced reviewer, provided initial project feedback
- Nate Wessel — CAGIS building import lead
- OSM US Slack — Cincinnati channel
- Notify them before the first batch

## Existing precedent

The CAGIS Building Import (2018-ongoing, ~358,167 buildings) followed this exact process:
- Formal proposal by Nate Wessel, Bogdan Petrea/Telenav, and Minh Nguyen
- Tasking-manager project 107 on tasks.openstreetmap.us
- `_cincyimport` account suffix convention
- Phase 1 complete (~295K buildings), Phase 2 ongoing (~62K manual conflation)

Follow the same pattern for credibility with the local community.

## Honor opt-outs

If any mapper or community member objects to the edits:
- Stop immediately
- Engage in discussion
- Be prepared for revert without notice
- Adjust approach based on feedback
