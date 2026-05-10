# Routing engine dispatch: BRouter default, MOTIS opt-in

**Summary.** MetroNow uses a routing engine to filter false positives out
of the rider-impact detector findings. If a candidate fix doesn't change
the routing graph, the finding is most likely noise; if it does, it
likely needs human review. Today the project ships **two** routing
engines with deliberately matching call shapes: **BRouter** (the
default; OSM-only, car-fast profile, GPL) and **MOTIS** (opt-in;
multi-modal: OSM + GTFS in the same graph). Both expose `fetch_route()`
that returns `{length_m, duration_s, cost, geometry}`. The "next-session
item" referenced in `CLAUDE.md` is wiring a single dispatcher line in
`route_diff.py` that picks the engine based on `motis.is_available()`,
so the future swap is one conditional, not a refactor.

---

## What this is

Some of the eight rider-impact detectors emit findings that look like
defects but don't actually change rider-routing outcomes. The canonical
example: a `oneway=-1` tag on a way nobody routes through anyway. The
*finding* is real (the tag is unusual), but the *impact* is zero.
Surfacing it to a human reviewer wastes attention.

The route-diff harness asks a routing engine the question: "if this
candidate fix were applied, would the chosen route between two
endpoints change?" If yes → real defect, escalate. If no → likely false
positive, suppress.

The two engines answer that question differently:

- **BRouter** ([route_diff.py](../../src/osm/route_diff.py)) is OSM-only.
  It re-routes through a perturbed graph (e.g., re-issuing the route in
  the suspect way's start→end direction; if BRouter declares the
  destination unreachable, the only thing stopping it is the
  directional tag the candidate fix would change). Car-fast profile.
  Cheap, fast, ships under GPL.
- **MOTIS** ([motis.py](../../src/osm/motis.py)) is multi-modal: OSM
  *and* GTFS in the same graph. The advantage for MetroNow's purposes
  is that a route between two stops can reflect both walking-network
  changes AND transit schedule effects in a single comparison: the
  right engine for "what if SORTA changed this corridor's frequency on
  its next ingest" questions.

The two engines are independent processes (BRouter is a public-mirror
HTTP service; MOTIS is a self-hosted instance). They don't share data
or caches. They just share an interface.

## How it works

The two engines were designed with deliberate API congruence so a future
dispatcher can swap them without changing call sites:

1. **Identical signature.** Both expose
   `fetch_route(origin, destination, *, profile/mode_kwargs..., timeout)`
   and return `{length_m, duration_s, cost, geometry}` or `None` on any
   error ([route_diff.py:376-383](../../src/osm/route_diff.py#L376-L383),
   [motis.py:175](../../src/osm/motis.py#L175)).
2. **Identical degradation behavior.** On HTTP / JSON / connection
   error, both log at warning/info level and return `None`. The pipeline
   never sees an exception bubble up; it just sees a missing route and
   skips that finding's filter step.
3. **Identical cache layer.** Both cache 24h-TTL keyed by
   `(origin, destination, mode/profile)`. BRouter under
   `~/.config/osm/brouter_cache/`, MOTIS under
   `~/.config/osm/motis_cache/`. Same JSON-on-disk shape.
4. **Independent base URLs.** BRouter's `BROUTER_BASE` is hardcoded to
   the public BRouter server; MOTIS reads `MOTIS_BASE` env var,
   defaulting to `http://localhost:8080`
   ([motis.py:58, 74-75](../../src/osm/motis.py#L58)). MOTIS won't
   work without a self-hosted or operator-pointed instance: the
   pipeline degrades to BRouter-only if MOTIS isn't reachable.
5. **Health probe gates engagement.** `motis.is_available()`
   ([motis.py:328](../../src/osm/motis.py#L328)) sends a near-trivial
   query (origin == destination, walk mode) and returns `True` only on
   a clean response. Today this probe is called by `osm motis-status`;
   tomorrow's dispatcher will call it from `route_diff.fetch_route()`
   before falling back to BRouter.

The "next-session item" from `CLAUDE.md` § Phase status is exactly the
dispatcher line. It would replace `route_diff.fetch_route(origin, dest)`
direct calls with something like:

```python
def fetch_route(origin, destination, **kwargs):
    if motis.is_available():
        result = motis.fetch_route(origin, destination, **kwargs)
        if result is not None:
            return result
    return brouter.fetch_route(origin, destination, **kwargs)
```

That's the entire change. Every other callsite remains untouched
because the return shape matches.

## The flow, visually

```mermaid
---
title: Two engines, one shape: current state and the next-session dispatcher
---
flowchart TD
    Caller["route-diff caller<br/>(detector false-positive filter)"]

    subgraph Today["Today: explicit engine choice per call site"]
        direction TB
        BR1["route_diff.fetch_route()<br/>route_diff.py:376"]
        Mot1["motis.fetch_route()<br/>motis.py:175"]
    end

    subgraph Future["Next-session: single dispatcher in route_diff.py"]
        direction TB
        Probe{"motis.is_available()<br/>motis.py:328<br/>(/api/v5/plan health probe)"}
        Mot2["motis.fetch_route()"]
        BR2["brouter (delegate)"]
        Probe -- "MOTIS reachable<br/>and returns result" --> Mot2
        Probe -- "MOTIS down<br/>or returned None" --> BR2
    end

    BRouter["BRouter public service<br/>OSM only<br/>car-fast profile<br/>HTTP at brouter.de"]
    MOTIS["MOTIS self-hosted<br/>OSM + GTFS in same graph<br/>multi-modal<br/>HTTP at MOTIS_BASE<br/>(localhost:8080 default)"]

    Caller -. "today" .-> BR1
    Caller -. "today (opt-in)" .-> Mot1
    Caller --> Probe

    BR1 --> BRouter
    BR2 --> BRouter
    Mot1 --> MOTIS
    Mot2 --> MOTIS

    Output["{length_m, duration_s,<br/>cost, geometry} or None"]
    BRouter --> Output
    MOTIS --> Output

    classDef shipped fill:#1f4d2b,stroke:#3b8c5a,color:#e8f3ec
    classDef pending fill:#5b3a1c,stroke:#a06632,color:#f5ead7
    classDef ext fill:#3a3a3a,stroke:#888,color:#eee
    class Today,BR1,Mot1 shipped
    class Future,Probe,Mot2,BR2 pending
    class BRouter,MOTIS,Output ext
```

*What this shows: the two engines are equivalent at the call-shape
level: both end at the same `{length_m, duration_s, cost, geometry}`
output. Today, callers pick one engine explicitly per site. Tomorrow,
a single `is_available()` probe in `route_diff.py` will pick MOTIS
when reachable and BRouter otherwise. What this hides: the 24-hour
cache layer (both engines), the BRouter `nogos` parameter (deltas
to perturb the routing graph), the MOTIS GTFS schedule layer.*

## Why two engines, not one

BRouter's strengths and limitations are different from MOTIS's. The
project keeps both because each answers a different routing question
better:

- **BRouter is car-only.** It models the road network without
  knowledge of transit schedules. For most rider-impact detectors
  (`oneway_minus_one`, `oneway_conflicts`, `access_blocked_residential`,
  `barriers_without_access`) this is exactly enough: the question is
  "does this tag change the road graph for vehicles that route
  through it?" BRouter answers that with high fidelity and at low
  operational cost (public service, no self-host).
- **MOTIS is multi-modal.** It ingests OSM and GTFS in a single graph,
  so a route between two stops reflects both walking and transit
  legs. For detectors like `misplaced_bus_stops` and the future
  ViaMapping-cadence questions ("if SORTA changed this corridor's
  frequency, would routing materially change?"), MOTIS answers
  questions BRouter literally cannot. The cost is operational:
  someone has to stand up MOTIS, point `MOTIS_BASE` at it, and keep
  it fed with current GTFS.
- **Neither is right for everything.** The dispatcher pattern (try
  MOTIS, fall back to BRouter) lets the pipeline use the better
  engine when available without forcing operators to run MOTIS.

The shape match is what makes the dispatcher cheap. If the engines
returned different schemas, the dispatcher would be a translator. The
fact that both return `{length_m, duration_s, cost, geometry}`
verbatim means the caller never knows which engine answered.

## Edge cases and gotchas

- **There is no MOTIS server bundled.** The project ships a *client*
  ([motis.py:26-30](../../src/osm/motis.py#L26-L30)). Operators must
  either point `MOTIS_BASE` at a hosted instance or stand up their own
  per the upstream `motis-project/motis` deployment docs. Until then,
  `motis.fetch_route()` returns `None` and any caller that explicitly
  uses MOTIS silently falls back.
- **`is_available()` is a near-trivial query, not a deep health
  check.** It sends `fromPlace == toPlace` (origin == destination) so
  the response is small and fast
  ([motis.py:328-349](../../src/osm/motis.py#L328-L349)). Don't try
  to make this probe more elaborate; the failure mode it catches is
  "MOTIS isn't running," not "MOTIS is misconfigured."
- **BRouter has rate-limit politeness baked in.** `_polite_sleep()`
  ([route_diff.py:128](../../src/osm/route_diff.py#L128)) inserts a
  small delay between consecutive BRouter calls. The public BRouter
  service is community-maintained; we are not the only consumer.
- **The 24h cache is correctness-aware, not just performance.** A
  scan run at noon and a re-run at 4pm should produce the same
  routes; routing answers don't change minute-to-minute. The TTL is
  long enough to survive a reasonable scan-and-review session.
- **MOTIS's `time` parameter matters.** The `is_available()` probe
  passes the current UTC time to MOTIS so the schedule layer is
  consulted, even though origin == destination. A future
  `fetch_route()` call needs a real time too: pure spatial
  routing isn't a MOTIS use case.
- **The dispatcher lives in `route_diff.py`, not in a new module.**
  When the next-session work happens, don't introduce a new
  `engine_dispatcher.py`. The dispatcher is one conditional in
  `route_diff.fetch_route` (or a thin wrapper); separate-module
  abstraction would be premature.
- **`fetch_route` returns `None` for unreachable destinations.** This
  is not an error: it's a signal that the routing graph cannot find
  a path. The route-diff caller treats that signal as evidence that a
  candidate fix matters
  ([route_diff.py:18-22](../../src/osm/route_diff.py#L18-L22)).

## Code references

- [`src/osm/route_diff.py:1-22`](../../src/osm/route_diff.py#L1-L22):
  module docstring explaining the BRouter false-positive-filter design.
- [`src/osm/route_diff.py:376`](../../src/osm/route_diff.py#L376):
  BRouter `fetch_route()`. Returns
  `{length_m, duration_s, cost, geometry}` or `None`.
- [`src/osm/route_diff.py:128`](../../src/osm/route_diff.py#L128):
  `_polite_sleep()` rate-limit honor.
- [`src/osm/motis.py:1-30`](../../src/osm/motis.py#L1-L30): module
  docstring explaining the prototype + degrade-to-BRouter posture.
- [`src/osm/motis.py:58, 74-75`](../../src/osm/motis.py#L58):
  `MOTIS_DEFAULT_BASE = "http://localhost:8080"` and `MOTIS_BASE` env
  override.
- [`src/osm/motis.py:175`](../../src/osm/motis.py#L175): MOTIS
  `fetch_route()`. Same return shape as BRouter.
- [`src/osm/motis.py:328-349`](../../src/osm/motis.py#L328-L349):
  `is_available()` health probe (`/api/v5/plan` round-trip with origin
  == destination).
- [`docs/motis-deployment.md`](../motis-deployment.md): honest
  stand-up notes for the MOTIS prototype (out-of-scope for this
  explainer; covers operator setup).

## See also

- [`CLAUDE.md` § Layout / Routing](../../CLAUDE.md): the dense
  reference this explainer decompresses.
- [`CLAUDE.md` § Phase status / MOTIS prototype](../../CLAUDE.md):
  the "next-session item" pointer to the dispatcher line.
- [`docs/explainers/phase-status.md`](phase-status.md): where MOTIS
  fits as a cross-cutting workstream alongside Phases 2-4.
- [`docs/explainers/detector-taxonomy.md`](detector-taxonomy.md):
  the eight rider-impact detectors whose findings the route-diff
  filter applies to.
- [BRouter project](https://brouter.de/brouter): upstream OSM
  routing engine.
- [MOTIS project](https://github.com/motis-project/motis): upstream
  multi-modal routing engine.
