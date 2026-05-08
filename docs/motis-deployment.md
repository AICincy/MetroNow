# MOTIS deployment notes

`src/osm/motis.py` is a prototype HTTP client for a MOTIS routing
instance. MOTIS (https://github.com/motis-project/motis) is a public-
transit routing engine that can ingest OSM and GTFS into a single
graph — the property that makes it the right next step beyond BRouter
for MetroNow's `route_diff` harness, since it surfaces both
walking-network changes (BRouter's domain) and transit-schedule
effects (which BRouter can't see) in one comparison.

The pipeline does **not** bundle a MOTIS server. Operators must point
`MOTIS_BASE` at an instance they control or accept the silent fallback
to BRouter. This file documents the minimum stand-up.

## When you'd actually want MOTIS

You want MOTIS instead of BRouter when:

- The fix being tested affects a **transit corridor** (e.g.
  `oneway_conflict` finding marked `transit_corridor=true` by
  `osm.bus_routes`). BRouter is car-only; the impact on a SORTA bus
  riding that corridor is invisible to it.
- You need to compare **before/after on a full intermodal trip**
  (walk-to-stop + transit + walk-from-stop). MOTIS reports the
  itinerary as a sequence of legs; the diff harness can then attribute
  the delta to the right leg.

For the bulk Class A maxspeed/oneway fix workload, BRouter is faster
and produces equivalent outcomes. Don't replace BRouter wholesale.

## Stand-up — one-shot binary

The official quick-start:

```sh
# Download the latest pre-built binary (Linux x86_64).
# Replace VERSION with the latest tag from the MOTIS releases page.
curl -L -o motis.tar.bz2 \
  https://github.com/motis-project/motis/releases/download/VERSION/motis-linux-amd64.tar.bz2
tar xjf motis.tar.bz2

# Configure the data directory: drop OSM .pbf and GTFS .zip files in.
mkdir -p data
cp ~/OSM/ohio-latest.osm.pbf data/
cp ~/sorta-gtfs.zip data/

# Run MOTIS — it ingests data/ on first start (slow, gigabytes of RAM)
# and serves on http://localhost:8080
./motis server
```

## Stand-up — Docker

The MOTIS project does not publish an official image at the time of
writing; community images vary in patch level. The safest pattern is
a thin Dockerfile that downloads the same binary into a `debian:slim`
base, mounts a host data dir, and exposes 8080. Until there's an
official image, treat the binary path above as the supported route.

## Pointing the pipeline at the instance

```sh
# If MOTIS is on the same host (the default), nothing to set:
osm motis-status                       # probes http://localhost:8080

# If MOTIS is on a different host or port:
export MOTIS_BASE=http://transit.lan:8080
osm motis-status

# To skip the probe (e.g. in CI where you only want to verify the URL
# parses correctly):
osm motis-status --no-probe
```

`osm motis-status` exits 1 if the probe fails, which makes it safe to
use as a pre-condition in scripts that intend to run a MOTIS-backed
diff.

## Cache + rate-limit story

MOTIS is self-hosted, so there's no rate-limit ceiling — the only
constraint is the box's CPU. The client still caches `/api/v5/plan`
responses under `~/.config/osm/motis_cache/` with a 24-hour TTL
matching BRouter's, so repeated identical queries never hit the
server. Cache is keyed by `(origin, destination, mode)`; perturbed-
graph queries naturally produce different keys via the mode
parameter.

## Data freshness

MOTIS ingests OSM and GTFS at startup. To pick up a CAGIS-driven
edit you submitted to OSM upstream, you need to:

1. Wait for the next OSM planet replication (≈1 minute) to propagate
   the edit
2. Re-download `ohio-latest.osm.pbf` (Geofabrik publishes daily)
3. Restart MOTIS with the new file

There is no live OSM replication into MOTIS the way there is into,
say, Nominatim. For "did this fix actually change routing?" diffs,
that's fine: you want to compare the **pre-edit** graph with a
**hypothetical post-edit** graph, both static. The diff harness's
nogo-perturbation strategy (BRouter inheritance) achieves this without
requiring a re-ingest.

## What's *not* in the prototype

- No engine-dispatcher in `route_diff.py`. The MOTIS client returns
  the same shape as `osm.route_diff.fetch_route` so the swap is
  one-line, but the swap itself is deferred until there's a
  side-by-side comparison harness on a representative fixture set.
- No MOTIS-specific perturbation strategy. BRouter's `nogos` mechanism
  doesn't have a direct MOTIS equivalent; pre-edit-vs-post-edit must
  be done by re-ingesting the modified .pbf, which takes minutes.
- No bundled deployment automation. The stand-up above is the
  manual reference; productionising it (systemd unit, restart-on-
  ingest hook, healthcheck loop) is left to the operator.
