# Skill: `community-prep`

**Summary.** Prepare the four mandatory Phase 1 community-gating
artifacts before any mechanical edit submits to OSM: wiki page,
talk-us@ post, `_cincyimport` account, and changeset-tag templates.
**Mandatory; not optional**: failing community gating risks unilateral
revert by the DWG without notice, regardless of edit quality.

## What it does

Walks the maintainer through the four artifacts in dependency order:

1. **Private outreach to Minh Nguyễn** (`User:Mxn`): Cincinnati's
   de-facto organised-edits reviewer. A private "looks fine, post it"
   substantially de-risks the public posts.
2. **Create `_cincyimport`-suffix OSM account**: precedent from the
   Hamilton County Building Import. The suffix is what OSMCha + DWG
   reviewers recognize as an organised-edit account.
3. **Publish the OSM wiki page** at
   `wiki.openstreetmap.org/wiki/Automated_edits/<account-name>`. The
   URL becomes the value of every changeset's `description` tag.
4. **Post to talk-us@ + community.openstreetmap.org** with a 14-day
   comment window. Mandatory wait.

The drafts are paste-ready under `docs/community-prep/01-04*.md`. The
skill verifies each is current, customizes templates with the actual
account name + wiki URL, and reminds about the 14-day window.

## When to invoke

- "Community compliance" / "wiki page" / "talk-us" / "import account"
- "Before first submission" / "ready to submit?"
- "Phase 1 prep" / "gating artifacts"

## What it produces

- Customized drafts for the four artifacts (wiki page, talk-us@ post,
  Minh outreach email, account bio template).
- A status summary of which steps are done vs. pending.
- A "what's blocked" list cross-referenced with
  `osm preflight --zone <key>`.

## Related skills

- [`changeset-submit`](changeset-submit.md): runs *after* this skill;
  the seven changeset tags depend on the wiki URL set here.
- [`osmcha-monitor`](osmcha-monitor.md): sets up the post-submission
  watch that's required after community gating.

## See also

- [`SKILL.md`](../../.claude/skills/community-prep/SKILL.md)
- [`docs/explainers/osm-community-gating.md`](../explainers/osm-community-gating.md)
- [`docs/community-prep/`](../community-prep/): the actual paste-ready
  drafts (`01-wiki-page.md` through `04-pre-flight-checklist.md`).
- [OSM Automated Edits Code of Conduct](https://wiki.openstreetmap.org/wiki/Automated_Edits_code_of_conduct)
