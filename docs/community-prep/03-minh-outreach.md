<!--
Send the content between the ===== markers BEFORE posting publicly to
talk-us@. Minh Nguyễn (User:Mxn) is the Cincinnati community's
de-facto reviewer for organised edits per RESEARCH-FINDINGS.md;
even a one-line "looks fine, post it" substantially de-risks the
public threads.

Channels (use whichever you have prior contact through):
- OSM message: https://www.openstreetmap.org/message/new/Mxn
- Wiki talk: https://wiki.openstreetmap.org/wiki/User_talk:Mxn
- OSM-US Slack: @minh in #local-cincinnati or #imports
-->

# Outreach to Minh Nguyễn (User:Mxn)

**Subject (for OSM message or email):**
`Heads up — MetroNow OSM TIGER audit, public posting next week`

=====

Hi Minh,

Brief heads-up before I post publicly to talk-us@ and
community.openstreetmap.org about a mechanical-edit audit I'm preparing
for the four SORTA MetroNow on-demand microtransit zones in Hamilton
County. Wiki page draft and code are linked below — would value a
sanity check from you before I open the public comment window.

**Wiki page draft:**
<LINK_TO_DRAFT_WIKI_PAGE_OR_PASTEBIN>

**Code:** <https://github.com/AICincy/MetroNow>

**Account:** `<YOUR_ACCOUNT_NAME>` (following the local
`_cincyimport` convention from the Hamilton County Building Import).

The short version: tag-only edits to OSM ways inside MetroNow's
published service polygons, sourced from CAGIS Street Centerlines.
Three fix kinds — `set_maxspeed_cagis`, `set_oneway_cagis`,
`remove_oneway_cagis`. Auto-submit gated on confidence ≥ 0.85 against
a CAGIS conflation score. Anything below that threshold goes to a
per-zone MapRoulette challenge for human review, not auto-submitted.

The zone polygons come from SORTA's published web map — ArcGIS Online
item `ba2063d68a3e41bd86d486d372991d65` ("MetroNow!" by
`metro_mlinder`, public). I'm clipping every harvest to those polygons
intersected with Hamilton County, so nothing edits outside the actual
operational area.

Three things I'd value your input on:

1. **Is the `<YOUR_ACCOUNT_NAME>` naming OK** for the
   `_cincyimport` convention? Anything you want me to call out
   differently?
2. **Cincinnati corridor caveats** — anything you've hand-edited
   recently, or any street I should treat as a known disputed
   `oneway` arrangement? I'll exclude on request.
3. **Process omissions** — first time I'm running organised mechanical
   edits in this region. If I'm missing a step you typically expect
   from organised edits, I'd rather hear it from you privately than
   discover it on the public thread.

Plan is to post publicly on <PROPOSED_POST_DATE>, wait the standard
two-week comment window, then start with a single 10-element
`set_maxspeed_cagis` batch in Blue Ash and watch OSMCha for 72 hours
before proceeding. Total auto-submittable pool across all four zones
is ~2,043 fixes, mostly maxspeed.

Many thanks — and apologies for the unsolicited DM if you'd rather
just see this on talk-us@. I'll proceed regardless of whether I hear
back, but a one-liner at any time is welcome.

Best,
`<YOUR_ACCOUNT_NAME>` / <CONTACT_EMAIL>

=====
