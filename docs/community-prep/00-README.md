# Phase 1 community-prep artifacts

This directory holds the **drafts** the maintainer needs before submitting
the first changeset from the MetroNow audit pipeline. Per the OSM
[Automated Edits code of conduct](https://wiki.openstreetmap.org/wiki/Automated_Edits_code_of_conduct),
documentation and community discussion **must precede** any mechanical
edit, and Phase 1 of the remediation plan is explicitly gated on these
artifacts being published.

The pipeline itself is ready: Phases 2a–4c shipped CAGIS-verified
mechanical fixes with confidence ≥ 0.85, dry-run safety, polite-rate-limit
OAuth submission, the right `mechanical=yes` / `bot=yes` /
`cagis:attribution` tags, and BRouter route-impact measurement. The
only thing standing between "code is ready" and "first changeset
ships" is the four artifacts in this directory.

## What's here

| File | Where this gets pasted | Status |
|------|------------------------|--------|
| `01-wiki-page.md` | `wiki.openstreetmap.org/wiki/Automated_edits/<account-name>` | Draft, ready to paste |
| `02-talk-us-post.md` | Email to `talk-us@openstreetmap.org` AND a thread on `community.openstreetmap.org/c/local-chapters/united-states` | Draft, ready to paste |
| `03-minh-outreach.md` | Email or OSM message to [User:Mxn](https://wiki.openstreetmap.org/wiki/User:Mxn) (Minh Nguyễn) BEFORE the public post | Draft, ready to paste |
| `04-pre-flight-checklist.md` | The maintainer's own runbook before pressing `osm fix` | Procedural |

## The order matters

1. **Send the Minh outreach** (`03-minh-outreach.md`) and wait for response. He's the named local OSM contact in `RESEARCH-FINDINGS.md` and the Cincinnati community's de-facto reviewer for organised edits. Even a one-line "looks fine, post it" from him substantially de-risks the public posts.

2. **Create the OSM account** if not done already. Convention is `<your_username>_cincyimport` (precedent: the Hamilton County Building Import). Add a single bio line linking to the wiki page (which you'll create in step 3).

3. **Publish the wiki page** (`01-wiki-page.md`). The page URL becomes the value for the `description` tag on every changeset.

4. **Post to talk-us@ and community.openstreetmap.org** (`02-talk-us-post.md`). Wait the explicit two-week comment window before any production submission. Read every reply. Address concerns or pause the timeline if the community asks.

5. **Run the pre-flight checklist** (`04-pre-flight-checklist.md`) on the day of the first submission. Every item is a yes/no the maintainer can answer themselves; no assumptions left implicit.

6. **Submit the first 10-element batch.** Watch OSMCha for 72 hours.
   If reverted, halt and respond to feedback before retrying.

## What's NOT here

- **Email to Via Transportation and SORTA** asking about ViaMapping ingest cadence. This is mentioned in the plan as the most strategically valuable single contact. Worth a separate email, but not a Phase 1 blocker — the pipeline can ship even with the cadence question unanswered.
- **DWG import-role request.** The default rate limit is 1,000 edits/hr (ramping to 100,000 over a week per `RESEARCH-FINDINGS.md` item 14). Phase 1 ships a single 10-element batch; the DWG request is a Phase 5 (scale) prerequisite.

## Quick sanity check before you start

The pipeline's CAGIS-verified auto-submit pool, post-Phase-4a stage 3:

| Zone | Auto-submit fixes |
|------|------------------:|
| Blue Ash / Montgomery | 728 |
| Springdale / Sharonville | 637 |
| Northgate / Mt. Healthy | 299 |
| Forest Park / Pleasant Run | 379 |
| **Total** | **2,043** |

Don't ship all 2,043 at once. Phase 1 specifies the cleanest 10-element
`set_maxspeed_cagis` batch from Blue Ash. After 72 hours of OSMCha-clean
behaviour, scale gradually to ≤ 500-element batches per the community
norm. CGImap's hard limit is 10,000 elements per changeset; we deliberately
stay well below.
