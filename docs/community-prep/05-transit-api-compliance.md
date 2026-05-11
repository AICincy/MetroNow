# Transit App API — compliance & runbook

This file records the obligations the maintainer accepted when
requesting a Transit App developer API key. The client at
`src/osm/transit.py` is engineered to honour these obligations
defensively; the **publication / launch** decisions still require
human action.

## Where the key lives

The Transit API key is **NEVER** in this repository. It lives at:

```
~/.config/osm/transit_api.json
```

with permissions `0600`. File shape:

```json
{"api_key": "transit_publicapi_v3_..."}
```

The client (`src/osm/transit.py:_load_api_key`) reads it on demand. If
the file is missing or malformed, the client returns `None` for every
endpoint call — the main scan/fix path is never blocked.

## Quota limits (after the 2026-05-11 civic/accessibility uplift)

| Limit | Value | Where enforced |
|-------|-------|----------------|
| Calls per month | 5,000 | `transit.py:_quota_exhausted()` (refuses at 80 % = 4,000) |
| Calls per minute | 5 | `transit.py:_rate_limit_pace()` (token bucket) |

The default public tier is 1,500 calls/month; Transit's CBO
(David Block-Schachter) granted this project the 5,000-call
civic/accessibility uplift requested in the ToS-compliance email
(see "Quota uplift" below). The 80 % monthly cap leaves headroom for
the rest of the month and absorbs the unavoidable error-response
counts. Increase only if Transit grants a further uplift.

## Terms of service obligations (verbatim from Transit's email)

1. **Don't share access to the key with any third party.** The
   key file is `0600` and never logged. The client never includes
   the key in error messages or stack traces. The repo's `.gitignore`
   already covers `.env` files.

2. **Provide Transit at least 10 business days notice before making
   public any tool or service relying on the API.** Email
   `apis@transitapp.com` BEFORE publishing anything that uses the
   client — the OSM wiki page, the talk-us@ post, the
   community.openstreetmap.org topic, any blog post, any conference
   talk. Provide information about the integration and accept
   reasonably-requested modifications.

3. **Visibly display the "Powered by Transit" logo in the main
   interface of your tool or service.** The client exposes the
   attribution string as `transit.POWERED_BY_TRANSIT_ATTRIBUTION`.
   Wire it into any UI panel that renders Transit data — the
   Investigations panel and Fix panel are the current candidates.
   Logo asset: <https://transitapp.com/partners/apis> (download the
   official "Powered by Transit" lockup; do not redraw).

4. **Share any press release, marketing material, or other public
   communication mentioning Transit (or the API, or any Transit
   trademark) with `apis@transitapp.com` for approval BEFORE
   publication.** This includes the OSM wiki page if it cites
   Transit; it includes any social-media announcement of the project
   that names Transit; it includes the changelog entry that lands
   when the Transit cross-check first ships.

## Engineering safeguards (already implemented)

- `~/.config/osm/transit_api.json` (0600) — never committed, never logged
- Token-bucket pacer at `RATE_LIMIT_PER_MINUTE` (5/min)
- Monthly quota counter at `~/.config/osm/transit_api_usage.json`,
  reset on month rollover; client refuses at 80 % consumed
- Per-endpoint TTL cache at `~/.config/osm/transit_cache/` —
  cache hits do not count against quota
- Fail-open: any quota or network error logs and returns `None`
- `User-Agent: MetroNow-OSM-Audit/0.1 (github.com/AICincy/MetroNow)`
  on every request — required for traceability per Transit's request

## Pre-launch checklist (run when the integration is ready to ship)

- [ ] Email `apis@transitapp.com` ≥ 10 business days before any
      public mention of the integration. Include: wiki page draft,
      project description, expected call volume.
- [ ] Embed "Powered by Transit" logo in the Atlas Investigations
      panel + Fix panel + any other Transit-data-rendering surface.
- [ ] Verify `transit.status()` reports `has_key=True`,
      `quota_exhausted=False`, `cache_dir_exists=True` before any
      live demo.
- [ ] Confirm the OSM wiki page cites Transit only as a data source
      (no implied partnership / endorsement).
- [ ] Confirm any blog post / conference talk / academic paper has
      been emailed to `apis@transitapp.com` for approval.
- [ ] After launch: monitor `~/.config/osm/transit_api_usage.json`
      monthly. If approaching the cap, raise quota with Transit
      rather than evading the local guard.

## Quota uplift (granted 2026-05-11)

The ToS-compliance email to Transit asked for either a 5,000 call/month
civic/accessibility free-tier uplift or a scoped MetroNow partnership.
David Block-Schachter (Transit's Chief Business Officer) replied on
2026-05-11: he noted a methodological caveat — Transit's MetroNow
integration receives only the operator-supplied pickup/drop-off/ETA
parameters, **not** Via's confirmed routing or confirmed trip, so the
Transit `/plan` endpoint is not a faithful proxy for ViaAlgo's dispatch
decisions — and granted the increased monthly allowance regardless.

Code change applied:

```python
# src/osm/transit.py
MONTHLY_QUOTA_FREE_TIER = 5_000  # was 1_500
```

The 80 % budget cap rescales automatically (4,000-call effective cap);
no other code changes were needed.

**Caveat to carry forward:** the email's "Strategic Utility of Transit
Data Integration" section overclaimed on trip-planning. The
`real-time positions`, `nearby-stops`, and `alerts` use cases still
stand; the `/plan`-based "fix-impact sampling" line does not — it would
measure Transit's own routing engine, not Via's. If a future quota
request reuses that justification, drop the trip-planning claim.

## When in doubt

`apis@transitapp.com` is the contact for everything. A pre-emptive
email is always cheaper than a retrospective revocation.
