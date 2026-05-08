<!--
Post the content between the ===== markers below to BOTH:

1. talk-us@openstreetmap.org (mailing list — subscribe first if you
   haven't: https://lists.openstreetmap.org/listinfo/talk-us)
2. community.openstreetmap.org/c/local-chapters/united-states (the
   "United States" category as a new topic)

Reuse the same body verbatim in both places so a reader on either
channel can follow the discussion. Cross-link the two threads in the
first reply on each side.
-->

# talk-us@ + community.openstreetmap.org post

**Subject / topic title:**
`MetroNow OSM TIGER audit — mechanical edits in Hamilton County, OH (2-week comment window)`

=====

Hi folks,

I'm preparing to run a mechanical-edit audit against OSM in Hamilton
County, Ohio, specifically inside the four [SORTA MetroNow](https://www.go-metro.com/riding-metro/metronow/)
on-demand microtransit service zones (Blue Ash / Montgomery,
Springdale / Sharonville, Northgate / Mt. Healthy, Forest Park /
Pleasant Run). This message is the
[Automated Edits code of conduct](https://wiki.openstreetmap.org/wiki/Automated_Edits_code_of_conduct)
notification — opening a two-week comment window before any production
submission.

**Wiki page documenting the edits:**
https://wiki.openstreetmap.org/wiki/Automated_edits/<YOUR_ACCOUNT_NAME>

**Account that will run the edits:** `<YOUR_ACCOUNT_NAME>` (following
the local `_cincyimport` convention from the
[Hamilton County Building Import](https://wiki.openstreetmap.org/wiki/Hamilton_County_Building_Import)).

**Source code, audit reports, and per-edit evidence:**
https://github.com/AICincy/MetroNow

## Why this audit

Via Transportation operates MetroNow for SORTA, and Via's product
documentation states unambiguously that ViaAlgo (the dispatch engine)
consumes OpenStreetMap through a custom layer called ViaMapping. So
defects in OSM in those four polygons silently degrade real
microtransit dispatch — refused turns, false `oneway=yes` on roads
that ViaAlgo then can't dispatch into both directions, missing
`maxspeed` driving incorrect ETAs, and the over-connected nodes the
2007–2008 TIGER/Line import left at grade separations. SORTA's own
"trip never arrived" complaint pipeline is a measurable downstream
proxy for this class of defect.

## What I'm proposing to edit

**Tag-only edits, no geometry changes.** Three fix kinds:

1. **`set_maxspeed_cagis`** — adds `maxspeed=<N> mph` when CAGIS
   publishes a speed limit and OSM has no `maxspeed` tag.
2. **`set_oneway_cagis`** — adds `oneway=yes`/`-1` when CAGIS
   `TRVL_DIR` indicates directionality and OSM disagrees.
3. **`remove_oneway_cagis`** — removes a false `oneway=yes` when
   CAGIS `TRVL_DIR=0` and OSM has it tagged as one-way.

A fix is auto-submitted only when **all** of these are true:

1. Way is inside the published MetroNow service polygon (traced from
   SORTA's [own web map](https://www.arcgis.com/home/item.html?id=ba2063d68a3e41bd86d486d372991d65),
   200 m buffered, county-clipped).
2. CAGIS has its own centerline within 30 m (directed Hausdorff,
   OSM→CAGIS).
3. Conflation confidence is ≥ 0.85 against the
   `0.5 × name + 0.3 × geometry + 0.2 × direction` formula.
4. (For oneway fixes) BRouter says the perturbation actually changes
   routing — `decision = real`, > 15% delta on the route cost.

Anything in 0.6 ≤ confidence < 0.85 goes through a human-review queue
and a per-zone MapRoulette challenge — NEVER auto-submitted.

## Approximate volume

| Zone | Auto-submit pool |
|------|-----------------:|
| Blue Ash / Montgomery | 728 |
| Springdale / Sharonville | 637 |
| Northgate / Mt. Healthy | 299 |
| Forest Park / Pleasant Run | 379 |
| **Total** | **2,043** |

(Most are `set_maxspeed_cagis`. The oneway fixes are a small fraction
— ~80 across all zones.)

I'm planning to ramp gradually: a 10-element first batch, then 50,
then 200, then ≤ 500 per the community norm — never approaching the
CGImap 10,000-element hard cap. No more than 1,000 elements per hour
total during the ramp.

## Changeset metadata

Every changeset will carry:

```
created_by   = MetroNow TIGER Audit Pipeline/0.1
source       = survey;CAGIS Open Data Hub
mechanical   = yes
bot          = yes
description  = <wiki page URL above>
cagis:attribution = Source: CAGIS Open Data Hub, Hamilton County, Ohio …
```

## What I'd like from this thread

1. **Sanity check.** Anything in the wiki page that isn't clear, or
   any fix kind you'd want me to drop or constrain further?
2. **Cincinnati local context.** The auditing pipeline is based on
   public CAGIS data + the published MetroNow service polygons — but
   the community here knows the streets. If a particular corridor
   has been hand-edited recently or has a contested
   `oneway` arrangement, please flag it so I can exclude it.
3. **Opt-outs.** Anyone who wants their work or a specific area
   excluded — please reply or DM, no questions asked.
4. **Process check.** First time I'm running organised mechanical
   edits in this region. If I've missed a step in the Automated Edits
   code of conduct, please let me know.

I'll wait at least two weeks from <START_DATE> before any production
submission, then start with a single 10-element `set_maxspeed_cagis`
batch in Blue Ash and watch OSMCha for 72 hours before proceeding.

Code, audit reports, and per-zone diagnostic baselines are in
<https://github.com/AICincy/MetroNow>; I'm happy to walk through any
piece in detail.

Thanks for reading,
`<YOUR_ACCOUNT_NAME>` / <CONTACT_EMAIL>

=====

<!--
Notes for the maintainer:

- Replace placeholders before sending: <YOUR_ACCOUNT_NAME> (4 places),
  <CONTACT_EMAIL> (1), <START_DATE> (1).
- After posting, edit the wiki page from `01-wiki-page.md` to fill in
  the discussion-history section with the actual archive URLs.
- Subscribe to talk-us@ at least 24 hours before posting so any
  immediate reply doesn't bounce because of pending-moderation.
- community.openstreetmap.org accepts the same content as a markdown
  topic; just paste verbatim.
- Suggested first-reply on each side once both are posted:
  "(cross-posted to community.openstreetmap.org/[link] —
   please reply on whichever channel you prefer)"
-->
