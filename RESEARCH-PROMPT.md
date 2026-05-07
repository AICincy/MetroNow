# OSM TIGER Audit — Research Prompt

Use this prompt to conduct focused research across the three areas below. Each section includes context, specific questions, and what to look for.

---

## 1. MetroNow / Via Transportation Data Pipelines

MetroNow is SORTA's on-demand microtransit service in Hamilton County, OH, operated by Via Transportation. The service covers four zones: Blue Ash/Montgomery, Springdale/Sharonville, Northgate/Mt. Healthy, and Forest Park/Pleasant Run.

**Research questions:**

- What data pipelines and routing systems does Via Transportation use for its microtransit platform? Specifically: GTFS, GTFS-Flex, GTFS-RT, GBFS, or proprietary feeds.
- Does Via consume OpenStreetMap data for routing, geocoding, or service area definitions? If so, which OSM data layers (road network, address points, POIs, admin boundaries)?
- What third-party map data providers does Via integrate with (Mapbox, HERE, TomTom, Google, Valhalla, OSRM)?
- Does SORTA/Metro publish any open data feeds for MetroNow (GTFS-Flex exports, API endpoints, rider data portals)?
- What is Via's data ingestion cadence — how often does Via pull updated road network data for its routing engine?
- Are there any known data quality requirements or validation steps Via applies to incoming road network data?

**Where to look:**

- Via Transportation developer docs, engineering blog, published white papers
- SORTA/Cincinnati Metro open data portal and GTFS feeds
- National RTAP, FTA microtransit program documentation
- Via's partnership announcements with transit agencies that describe technical architecture
- OpenStreetMap wiki pages on routing engines that Via or its subcontractors use

---

## 2. Corrupted Pipelines Affecting the TIGER Audit

The 2007-2008 TIGER/Line Census import into OpenStreetMap introduced road geometry and attributes (name, highway class, oneway) for Hamilton County. Many segments were never reviewed. The `tiger:reviewed=no` tag is unreliable — most mappers don't remove it even after correcting the data.

**Research questions:**

- Which TIGER/Line attribute fields are known to have systematic errors in Hamilton County or Ohio generally? Focus on: `oneway=yes` applied incorrectly to residential streets, `name` fields with abbreviation inconsistencies, `highway` classification errors.
- Are there known issues with the TIGER-to-OSM import scripts (the 2007 Cloudmade import, 2008 updates) that produced specific classes of bad data in Ohio?
- What other bulk imports or automated edits have touched Hamilton County road data since the TIGER import? (e.g., ESRI imports, NHD imports, USGS imports, bot edits)
- Has Via or any MetroNow routing system been affected by incorrect OSM oneway tags, missing road connections, or wrong highway classifications in the Hamilton County service zones?
- What TIGER/Line vintages does the US Census Bureau currently publish for Hamilton County, and do they contain corrections that could cross-reference against the OSM data to identify remaining import artifacts?
- Are there Ohio DOT, Hamilton County GIS, or CAGIS (Cincinnati Area GIS) open datasets that could serve as ground truth for validating TIGER-import road attributes?

**Where to look:**

- OpenStreetMap wiki: TIGER, TIGER fixup, Ohio TIGER cleanup pages
- OSM changeset discussions and diary entries about Hamilton County edits
- US Census Bureau TIGER/Line Shapefiles current vintage for Hamilton County (39061)
- CAGIS open data portal (Cincinnati Area Geographic Information System)
- Hamilton County Auditor GIS data
- ODOT TIMS (Transportation Information Mapping System)
- Overpass queries filtered to `tiger:source` or `tiger:upload_uuid` tags in the four MetroNow zone bboxes

---

## 3. Claude Code + OpenStreetMap Capabilities

This project uses a Python pipeline (`osm` package) with an Express.js web UI to scan, classify, and correct TIGER-import defects via the OSM API v0.6. The pipeline is authenticated with OAuth 2.0 (write_api, read_prefs scope).

**Research questions:**

- What Claude Code skills, MCP servers, or tool integrations exist for working with OpenStreetMap data? (e.g., Overpass API querying, OSM API editing, JOSM remote control, Nominatim geocoding)
- Can Claude Code interact with the OSM API v0.6 to: fetch node/way/relation data, read revision history, create changesets, upload modifications? What are the rate limits and best practices?
- What approaches exist for bulk harvesting OSM node points within a bounding box while respecting API etiquette? Compare: Overpass API (out meta geom), OSM API map call (/api/0.6/map), planet file extracts (Geofabrik), Overpass turbo exports.
- For making corrections at scale: what is the recommended changeset size, tagging convention for automated/semi-automated edits, and community notification process (mechanical edit guidelines)?
- What OSM community tools could augment this pipeline? Consider: MapRoulette (for crowdsourcing reviews), OSMCha (for monitoring changesets), JOSM validation rules, iD editor integration.
- Are there existing MCP servers or Claude Code extensions for geospatial work (GeoJSON processing, coordinate transforms, spatial queries)?

**Where to look:**

- Claude Code documentation on MCP servers and custom tool creation
- OpenStreetMap API v0.6 documentation
- OSM wiki: Automated Edits code of conduct, Import/Guidelines, Mechanical Edits
- MapRoulette API documentation
- Overpass API documentation and query language reference
- Anthropic MCP server registry
- GitHub repositories for OSM-related MCP servers

---

## How to Use This Prompt

Investigate each section independently. For each finding:

1. **Source** — where the information came from (URL, document, API response)
2. **Relevance** — how it connects to the TIGER audit pipeline in Hamilton County
3. **Actionable** — what specific change, integration, or workflow it suggests for the `osm` project

Prioritize findings that would improve defect detection accuracy, reduce false positives, or enable safer automated corrections in the four MetroNow service zones.
