/* MetroNow Atlas — main app logic.
   Wires the redesigned UI to the existing /api/* endpoints served by web/server.js. */
(function () {
  "use strict";

  const $ = (s, root) => (root || document).querySelector(s);
  const $$ = (s, root) => Array.from((root || document).querySelectorAll(s));

  function esc(str) {
    const d = document.createElement("div");
    d.textContent = str == null ? "" : String(str);
    return d.innerHTML;
  }

  // ports legacy formatTimeAgo for ledger render
  function formatTimeAgo(ts) {
    if (!ts) return "—";
    const t = new Date(ts).getTime();
    if (!Number.isFinite(t)) return String(ts);
    const diff = Date.now() - t;
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    if (days < 7) return `${days}d ago`;
    return new Date(ts).toLocaleDateString();
  }

  // accessibility helper: surface scan completion etc to assistive tech
  function announceToScreenReader(msg) {
    let live = document.getElementById("sr-live-region");
    if (!live) {
      live = document.createElement("div");
      live.id = "sr-live-region";
      live.setAttribute("role", "status");
      live.setAttribute("aria-live", "polite");
      live.className = "sr-only";
      document.body.appendChild(live);
    }
    live.textContent = "";
    // brief delay so AT picks up the change
    setTimeout(() => { live.textContent = msg; }, 60);
  }

  // --------------------------------------------------------------- state
  const state = {
    zones: {},
    zoneKeys: [],
    currentZone: null,
    results: null,           // last loaded scan-results.json for current zone
    pendingFixes: [],        // [{way, fix}, ...]
    classFilters: { AB: true, A: true, B: true, C: false, GAPS: true },
    scanInProgress: false,
    scanStartedAt: 0,
    scanTimerId: null,
    auth: { authenticated: false, scope: null },
    authFlowId: null,
    discussKey: () => `metronow.discuss.${state.currentZone || "_"}`,
    formalityKey: "metronow.formality",
  };

  // --------------------------------------------------------------- API helper
  async function api(url, opts) {
    const o = opts || {};
    const init = {
      method: o.method || "GET",
      headers: { "Content-Type": "application/json" },
    };
    if (o.body !== undefined) init.body = JSON.stringify(o.body);
    const res = await fetch(url, init);
    let data = null;
    try { data = await res.json(); } catch { data = null; }
    if (!res.ok) {
      const msg = (data && data.error) || `HTTP ${res.status}`;
      throw new Error(msg);
    }
    return data;
  }

  // --------------------------------------------------------------- toast
  let toastTimer = null;
  function toast(msg, kind) {
    const t = $("#toast");
    if (!t) return;
    t.textContent = msg;
    t.className = "toast show" + (kind ? " " + kind : "");
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      t.className = "toast";
    }, 3200);
  }

  // --------------------------------------------------------------- console (left rail)
  function consoleLog(line, kind) {
    const body = $("#consoleBody");
    if (!body) return;
    const div = document.createElement("div");
    div.className = "console-line" + (kind ? " " + kind : "");
    const ts = new Date().toLocaleTimeString();
    div.textContent = `[${ts}] ${line}`;
    body.appendChild(div);
    body.scrollTop = body.scrollHeight;
  }
  function consoleClear() {
    const body = $("#consoleBody");
    if (body) body.innerHTML = "";
  }
  function consoleStatus(label, dotClass) {
    const lab = $("#ckLabel");
    const dot = $("#ckDot");
    if (lab) lab.textContent = label;
    if (dot) {
      dot.className = "ck-dot " + (dotClass || "idle");
    }
  }
  function consoleShow(show) {
    const p = $("#consolePanel");
    if (p) p.style.display = show ? "" : "none";
  }

  // --------------------------------------------------------------- API health
  async function pingApi() {
    const dot = $("#apiDot");
    const text = $("#apiText");
    try {
      await api("/api/zones");
      if (dot) dot.classList.remove("offline");
      if (text) text.textContent = "API connected";
    } catch (e) {
      if (dot) dot.classList.add("offline");
      if (text) text.textContent = "API offline";
    }
  }

  // --------------------------------------------------------------- zones
  async function loadZones() {
    const data = await api("/api/zones");
    state.zones = data.zones || {};
    state.zoneKeys = data.keys || Object.keys(state.zones);
    const def = data.default || state.zoneKeys[0];
    state.currentZone = def;
    renderZoneList();
    renderCrumb();
    const meta = $("#zoneCount");
    if (meta) meta.textContent = `${state.zoneKeys.length} zones`;
  }

  function renderZoneList() {
    const list = $("#zoneList");
    if (!list) return;
    list.innerHTML = "";
    state.zoneKeys.forEach((k) => {
      const z = state.zones[k];
      const btn = document.createElement("button");
      btn.className = "zone-card";
      btn.setAttribute("data-zone", k);
      btn.setAttribute("aria-pressed", k === state.currentZone ? "true" : "false");
      btn.innerHTML =
        `<span class="zone-name">${esc(z.name)}</span>` +
        `<span class="zone-desc">${esc(z.description || "")}</span>`;
      btn.addEventListener("click", () => selectZone(k));
      list.appendChild(btn);
    });
  }

  function renderCrumb() {
    const z = state.zones[state.currentZone];
    const el = $("#crumbZone");
    if (el) el.textContent = z ? z.name : "—";
  }

  async function selectZone(k) {
    if (k === state.currentZone) return;
    state.currentZone = k;
    renderZoneList();
    renderCrumb();
    fitToZoneBounds();
    state.results = null;
    state.pendingFixes = [];
    // If a scan was running on the previous zone, the user has navigated
    // away from it; clear the in-progress flag so the new zone's scan
    // button isn't blocked. The actual scan request will still complete
    // in the background; this just unblocks the UI.
    state.scanInProgress = false;
    // reset class filters so prior zone's toggles don't leak across
    state.classFilters = { AB: true, A: true, B: true, C: false, GAPS: true };
    state.tablePages = { ab: 1, a: 1 };
    setReportsEnabled(false);
    clearMap();
    renderStats(null);
    renderClasses(null);
    updateInvestigationsBadge();
    setLastRun("—");
    closeAllPanels();
    await tryLoadExistingResults();
  }

  function fitToZoneBounds() {
    const z = state.zones[state.currentZone];
    if (!z || !z.bbox || !mapRef) return;
    const [s, w, n, e] = z.bbox;
    mapRef.fitBounds([[s, w], [n, e]], { padding: [40, 40] });
  }

  // --------------------------------------------------------------- map
  let mapRef = null;
  const baseLayers = {};
  const BASEMAP_KEY = "metronow.basemap";
  const VALID_BASES = ["positron", "dark", "voyager", "esri"];
  let currentBase = (() => {
    try {
      const v = localStorage.getItem(BASEMAP_KEY);
      return VALID_BASES.includes(v) ? v : "positron";
    } catch { return "positron"; }
  })();
  const wayLayer = L.layerGroup();
  const gapLayer = L.layerGroup();

  // Phase 2c: CAGIS centerlines overlay (Esri FeatureServer/26 via esri-leaflet).
  // Lazy-loaded — created on first toggle-on. Keeps the basemap fast for users
  // who never need ground-truth comparison.
  const CAGIS_FEATURE_LAYER_URL =
    "https://services.arcgis.com/JyZag7oO4NteHGiq/arcgis/rest/services/Open_Data/FeatureServer/26";
  const CAGIS_ATTRIBUTION =
    'CAGIS Open Data Hub, Hamilton County (<a href="https://cagisonline.hamilton-co.org/" target="_blank" rel="noopener">cagisonline</a>)';
  let cagisOverlay = null;
  let cagisOverlayVisible = false;

  function initMap() {
    mapRef = L.map("map", { zoomControl: false, preferCanvas: true }).setView([39.20, -84.39], 11);

    baseLayers.positron = L.tileLayer(
      "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
      { attribution: '&copy; OpenStreetMap, &copy; CARTO', maxZoom: 19 }
    );
    baseLayers.dark = L.tileLayer(
      "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
      { attribution: '&copy; OpenStreetMap, &copy; CARTO', maxZoom: 19 }
    );
    baseLayers.voyager = L.tileLayer(
      "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png",
      { attribution: '&copy; OpenStreetMap, &copy; CARTO', maxZoom: 19 }
    );
    baseLayers.esri = L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      { attribution: 'Imagery &copy; Esri', maxZoom: 19 }
    );

    baseLayers[currentBase].addTo(mapRef);
    wayLayer.addTo(mapRef);
    gapLayer.addTo(mapRef);

    // sync .bm-btn aria-pressed with persisted choice
    $$(".bm-btn").forEach((b) => {
      b.setAttribute("aria-pressed", b.dataset.base === currentBase ? "true" : "false");
    });

    $$(".bm-btn").forEach((btn) => {
      btn.addEventListener("click", () => switchBase(btn.dataset.base));
    });
    $("#zoomIn")?.addEventListener("click", () => mapRef.zoomIn());
    $("#zoomOut")?.addEventListener("click", () => mapRef.zoomOut());
    $("#zoomFit")?.addEventListener("click", () => fitToZoneBounds());
  }

  function switchBase(name) {
    if (!baseLayers[name] || name === currentBase) return;
    mapRef.removeLayer(baseLayers[currentBase]);
    baseLayers[name].addTo(mapRef);
    currentBase = name;
    try { localStorage.setItem(BASEMAP_KEY, name); } catch {}
    $$(".bm-btn[data-base]").forEach((b) => {
      b.setAttribute("aria-pressed", b.dataset.base === name ? "true" : "false");
    });
  }

  // Phase 2c: toggle the CAGIS centerlines overlay. The featureLayer is
  // built lazily on first toggle-on so users who never need ground-truth
  // comparison don't pay the FeatureServer fetch.
  function toggleCagisOverlay() {
    if (!mapRef) return;
    const btn = document.getElementById("cagisOverlayToggle");
    if (cagisOverlayVisible) {
      if (cagisOverlay) mapRef.removeLayer(cagisOverlay);
      cagisOverlayVisible = false;
      if (btn) btn.setAttribute("aria-pressed", "false");
      return;
    }
    if (!cagisOverlay) {
      // Guard against esri-leaflet not loading (CDN block, offline, etc.).
      if (!window.L || !window.L.esri || !window.L.esri.featureLayer) {
        toast("Esri Leaflet plugin not available; CAGIS overlay disabled.", "warn");
        return;
      }
      cagisOverlay = window.L.esri.featureLayer({
        url: CAGIS_FEATURE_LAYER_URL,
        attribution: CAGIS_ATTRIBUTION,
        style: () => ({
          color: "#2c5282", // matches --accent
          weight: 1.5,
          opacity: 0.65,
          dashArray: "4 3",
        }),
      });
      cagisOverlay.bindPopup((feat) => {
        const p = (feat && feat.feature && feat.feature.properties) || {};
        const label = p.STRLABEL || p.MAPLABEL || "(unnamed)";
        const speed = p.SPEEDLIMIT ? `${p.SPEEDLIMIT} mph` : "—";
        const trvl = p.TRVL_DIR;
        const direction = trvl === 1 || trvl === -1 ? `oneway (${trvl})` : "two-way";
        return `<div style="font-family: var(--sans, sans-serif); font-size: 12.5px;">
          <div style="font-weight: 600; margin-bottom: 4px;">${label}</div>
          <div>Speed: ${speed}</div>
          <div>Direction: ${direction}</div>
          <div style="margin-top: 6px; font-size: 11px; color: #847e72;">CAGIS feature ${p.OBJECTID ?? "?"}</div>
        </div>`;
      });
    }
    cagisOverlay.addTo(mapRef);
    cagisOverlayVisible = true;
    if (btn) btn.setAttribute("aria-pressed", "true");
  }

  // class colors / weights — read from CSS custom properties so theme/tweaks update naturally
  function classColor(cls) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(`--cls-${cls.toLowerCase()}`).trim();
    return v || "#888";
  }
  function classWeight(cls) {
    const w = (window.atlasWeight || "med");
    const base = { thin: 2, med: 3, thick: 4 }[w] || 3;
    if (cls === "AB") return base + 2;
    if (cls === "A") return base + 1;
    if (cls === "B") return base;
    return Math.max(1, base - 1);
  }

  function clearMap() {
    wayLayer.clearLayers();
    gapLayer.clearLayers();
  }

  function classFilterAllowsWay(w) {
    const cls = (w.defect_class || "C").toUpperCase();
    return !!state.classFilters[cls];
  }

  // chunked render guard prevents races when zone/filter changes mid-render
  let currentUpdateId = 0;
  const RENDER_CHUNK = 150;

  function drawResults(data) {
    clearMap();
    currentUpdateId++;
    const updateId = currentUpdateId;
    const ways = (data && data.all_ways) || [];
    const counts = { AB: 0, A: 0, B: 0, C: 0 };
    const drawList = [];
    for (let i = 0; i < ways.length; i++) {
      const w = ways[i];
      const cls = (w.defect_class || "C").toUpperCase();
      if (counts[cls] !== undefined) counts[cls]++;
      if (!w.geometry || w.geometry.length < 2) continue;
      if (!classFilterAllowsWay(w)) continue;
      drawList.push(w);
    }

    function drawChunk(start) {
      if (updateId !== currentUpdateId) return; // superseded by newer call
      const end = Math.min(start + RENDER_CHUNK, drawList.length);
      for (let i = start; i < end; i++) {
        const w = drawList[i];
        const cls = (w.defect_class || "C").toUpperCase();
        const poly = L.polyline(w.geometry, {
          color: classColor(cls),
          weight: classWeight(cls),
          opacity: cls === "C" ? 0.55 : 0.9,
        });
        poly.on("click", () => showInspector(w));
        poly.bindTooltip(
          `<b>${esc(w.name_display || "Way " + w.id)}</b><br>${cls} · ${esc(w.highway || "?")}`,
          { sticky: true }
        );
        const wayUrl = `https://www.openstreetmap.org/way/${encodeURIComponent(w.id || "")}`;
        poly.bindPopup(
          `<div class="map-popup">
            <div class="mp-title">${esc(w.name_display || "Way " + w.id)}</div>
            <div class="mp-meta">${cls} · ${esc(w.highway || "?")}${w.oneway ? " · oneway=" + esc(w.oneway) : ""}</div>
            <div class="mp-actions">
              <a href="${wayUrl}" target="_blank" rel="noopener">Open in OSM ↗</a>
              <a href="http://127.0.0.1:8111/load_object?objects=w${encodeURIComponent(w.id || "")}" target="_blank" rel="noopener">JOSM</a>
            </div>
          </div>`,
          { closeButton: true, autoPan: true }
        );
        wayLayer.addLayer(poly);
      }
      if (end < drawList.length) {
        if (typeof window.requestAnimationFrame === "function") {
          window.requestAnimationFrame(() => drawChunk(end));
        } else {
          setTimeout(() => drawChunk(end), 0);
        }
      }
    }
    if (drawList.length) drawChunk(0);
    const drawn = drawList.length;
    const gaps = (data && data.gaps) || [];
    const gapColor = classColor("a");
    gaps.forEach((g) => {
      const lat = g.lat || (g.point && g.point[0]);
      const lon = g.lon || (g.point && g.point[1]);
      if (typeof lat !== "number" || typeof lon !== "number") return;
      const m = L.circleMarker([lat, lon], {
        radius: 5,
        color: gapColor,
        fillColor: gapColor,
        fillOpacity: 0.85,
        weight: 1.5,
      });
      const wayIds = Array.isArray(g.way_ids) ? g.way_ids : [];
      const distLabel = g.distance_m ? g.distance_m.toFixed(1) + "m" : "";
      m.bindTooltip(`Gap${distLabel ? " · " + distLabel : ""}`);
      const wayLinks = wayIds.length
        ? wayIds.slice(0, 6).map((id) =>
            `<a href="https://www.openstreetmap.org/way/${encodeURIComponent(id)}" target="_blank" rel="noopener">${esc(id)}</a>`
          ).join(", ")
        : "<span class=\"mp-meta\">no way ids</span>";
      const osmNode = `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=19/${lat}/${lon}`;
      m.bindPopup(
        `<div class="map-popup">
          <div class="mp-title">Node disconnect</div>
          <div class="mp-meta">${esc(distLabel || "")}${esc(g.street || "")}</div>
          <div class="mp-meta"><strong>Ways:</strong> ${wayLinks}</div>
          <div class="mp-actions">
            <a href="${osmNode}" target="_blank" rel="noopener">Open at OSM ↗</a>
            <a href="http://127.0.0.1:8111/load_and_zoom?left=${lon-0.001}&right=${lon+0.001}&top=${lat+0.001}&bottom=${lat-0.001}" target="_blank" rel="noopener">JOSM</a>
          </div>
        </div>`,
        { closeButton: true, autoPan: true }
      );
      gapLayer.addLayer(m);
    });

    // legend counters
    $("#legAB") && ($("#legAB").textContent = counts.AB.toLocaleString());
    $("#legA") && ($("#legA").textContent = counts.A.toLocaleString());
    $("#legB") && ($("#legB").textContent = counts.B.toLocaleString());
    $("#legC") && ($("#legC").textContent = counts.C.toLocaleString());
    $("#legGaps") && ($("#legGaps").textContent = (gaps.length || 0).toLocaleString());
    $("#legendTotal") && ($("#legendTotal").textContent = drawn ? `${drawn.toLocaleString()} drawn` : "");
  }

  // --------------------------------------------------------------- right rail (inspector)
  function showInspector(w) {
    const r = $("#rrail");
    if (!r) return;
    document.getElementById("app").setAttribute("data-rrail", "open");
    const wayId = w.id || "?";
    const cls = w.defect_class || "C";
    const review = w.review_status
      ? `<div class="ins-row"><span class="ins-k">Review</span><span class="ins-v">${esc(w.review_status)} (${(w.review_confidence ?? 0).toFixed(2)})</span></div>`
      : "";
    const reason = w.review_reason
      ? `<div class="ins-row"><span class="ins-k">Reason</span><span class="ins-v">${esc(w.review_reason)}</span></div>`
      : "";

    // CAGIS ground-truth section. The conflate step (osm conflate / scan
    // --with-conflation) attaches w.cagis_match keyed off the authoritative
    // Hamilton County street centerlines.
    let cagisBlock = "";
    if (w.cagis_match) {
      const cm = w.cagis_match;
      const conf = Number(cm.confidence ?? 0);
      const pct = Math.round(conf * 100);
      const tone = conf >= 0.85 ? "ok" : (conf >= 0.6 ? "warn" : "err");
      const cagisUrl = "https://services.arcgis.com/JyZag7oO4NteHGiq/arcgis/rest/services/Open_Data/FeatureServer/26/" + encodeURIComponent(cm.cagis_id);
      const onewayLabel = (cm.cagis_oneway === "yes" || cm.cagis_oneway === "-1")
        ? `oneway (${esc(cm.cagis_oneway)})`
        : "two-way";
      const speed = cm.cagis_speed_limit ? (esc(cm.cagis_speed_limit) + " mph") : "—";
      cagisBlock = `
        <div class="ins-section">
          <div class="ins-section-head">
            Ground-truth (CAGIS)
            <span class="conf-badge conf-${tone}">${pct}%</span>
          </div>
          <div class="ins-row"><span class="ins-k">CAGIS name</span><span class="ins-v">${esc(cm.cagis_name || "—")}</span></div>
          <div class="ins-row"><span class="ins-k">Direction</span><span class="ins-v">${onewayLabel}</span></div>
          <div class="ins-row"><span class="ins-k">Speed</span><span class="ins-v">${speed}</span></div>
          <div class="ins-row"><span class="ins-k">Func. class</span><span class="ins-v">${esc(cm.cagis_functional_class || "—")}</span></div>
          <div class="ins-row"><span class="ins-k">Hausdorff</span><span class="ins-v">${esc((cm.hausdorff_m ?? "—").toString())} m</span></div>
          <div class="ins-row"><span class="ins-k">CAGIS ID</span><span class="ins-v"><a href="${cagisUrl}" target="_blank" rel="noopener">${esc(cm.cagis_id)} ↗</a></span></div>
          <div class="ins-attrib muted">Source: CAGIS Open Data Hub</div>
        </div>
      `;
    }

    // TIGER 2024 fallback evidence — only shown when CAGIS has nothing for
    // this way (TIGER is fallback, not co-equal). The conflate-tiger step
    // attaches w.tiger_match keyed off the U.S. Census Bureau TIGER/Line
    // 2024 county-roads shapefile.
    let tigerBlock = "";
    if (w.tiger_match && !w.cagis_match) {
      const tm = w.tiger_match;
      const conf = Number(tm.confidence ?? 0);
      const pct = Math.round(conf * 100);
      const tone = conf >= 0.85 ? "ok" : (conf >= 0.6 ? "warn" : "err");
      const mtfcc = tm.tiger_mtfcc ? esc(tm.tiger_mtfcc) : "—";
      tigerBlock = `
        <div class="ins-section ins-section-tiger">
          <div class="ins-section-head">
            Ground-truth (TIGER 2024)
            <span class="conf-badge conf-${tone}">${pct}%</span>
          </div>
          <div class="ins-row"><span class="ins-k">TIGER name</span><span class="ins-v">${esc(tm.tiger_name || "—")}</span></div>
          <div class="ins-row"><span class="ins-k">MTFCC</span><span class="ins-v">${mtfcc}</span></div>
          <div class="ins-row"><span class="ins-k">Route type</span><span class="ins-v">${esc(tm.tiger_rttyp || "—")}</span></div>
          <div class="ins-row"><span class="ins-k">Hausdorff</span><span class="ins-v">${esc((tm.hausdorff_m ?? "—").toString())} m</span></div>
          <div class="ins-row"><span class="ins-k">LINEARID</span><span class="ins-v">${esc(tm.tiger_id || "—")}</span></div>
          <div class="ins-attrib muted">Source: U.S. Census Bureau, TIGER/Line 2024 (public domain) — fallback evidence only</div>
        </div>
      `;
    }

    r.innerHTML = `
      <div class="ins-head">
        <div class="ins-title">${esc(w.name_display || "Way " + wayId)}</div>
        <button class="icon-btn" id="rrailClose" title="Close">
          <svg viewBox="0 0 14 14" fill="none"><path d="M3 3l8 8M11 3l-8 8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
        </button>
      </div>
      <div class="ins-body">
        <div class="ins-row"><span class="ins-k">Way ID</span><span class="ins-v"><a href="https://www.openstreetmap.org/way/${encodeURIComponent(wayId)}" target="_blank" rel="noopener">${esc(wayId)}</a></span></div>
        <div class="ins-row"><span class="ins-k">Class</span><span class="ins-v">${esc(cls)}</span></div>
        <div class="ins-row"><span class="ins-k">Highway</span><span class="ins-v">${esc(w.highway || "—")}</span></div>
        <div class="ins-row"><span class="ins-k">Oneway</span><span class="ins-v">${esc(w.oneway || "—")}</span></div>
        <div class="ins-row"><span class="ins-k">Surface</span><span class="ins-v">${esc(w.surface || "—")}</span></div>
        <div class="ins-row"><span class="ins-k">Lanes</span><span class="ins-v">${esc(w.lanes || "—")}</span></div>
        <div class="ins-row"><span class="ins-k">Last edit</span><span class="ins-v">${esc(w.user || "—")} · v${esc(w.version || "?")}</span></div>
        ${review}${reason}
        ${cagisBlock}
        ${tigerBlock}
        <div class="ins-actions">
          <a class="btn btn-sm" href="https://www.openstreetmap.org/way/${encodeURIComponent(wayId)}" target="_blank" rel="noopener">Open in OSM ↗</a>
          <a class="btn btn-sm" href="http://127.0.0.1:8111/load_object?objects=w${encodeURIComponent(wayId)}" target="_blank" rel="noopener">Edit in JOSM</a>
        </div>
      </div>
    `;
    $("#rrailClose")?.addEventListener("click", () => {
      document.getElementById("app").setAttribute("data-rrail", "closed");
    });
  }

  // --------------------------------------------------------------- stats & classes
  function renderStats(stats) {
    const grid = $("#statsGrid");
    const section = $("#statsSection");
    const empty = $("#emptySection");
    if (!grid || !section) return;
    if (!stats) {
      grid.innerHTML = "";
      section.style.display = "none";
      if (empty) empty.style.display = "";
      const d = $("#dockResults"); if (d) d.style.display = "none";
      return;
    }
    if (empty) empty.style.display = "none";
    section.style.display = "";
    const items = [
      { k: "Total ways", v: stats.total || 0 },
      { k: "Residential", v: stats.residential || 0 },
      { k: "AB compound", v: stats.class_ab_count || 0, kind: "ab" },
      { k: "A false 1-way", v: stats.class_a_count || 0, kind: "a" },
      { k: "B multi-seg", v: stats.class_b_way_count || 0, kind: "b" },
      { k: "Node gaps", v: stats.gaps_found || 0, kind: "gaps" },
    ];
    grid.innerHTML = items.map((it) => `
      <div class="stat ${it.kind || ""}">
        <div class="stat-v">${Number(it.v).toLocaleString()}</div>
        <div class="stat-l">${esc(it.k)}</div>
      </div>
    `).join("");
    const dockFix = $("#dockFix");
    const dockResults = $("#dockResults");
    const fixable = (stats.class_a_count || 0); // class A + AB get oneway fix
    if (dockResults) {
      const total = (stats.class_ab_count || 0) + (stats.class_a_count || 0);
      dockResults.style.display = total > 0 ? "" : "none";
      dockResults.textContent = total.toLocaleString();
    }
    if (dockFix) {
      dockFix.style.display = fixable > 0 ? "" : "none";
      dockFix.textContent = fixable.toLocaleString();
    }
    const cs = $("#clearScanBtn"); if (cs) cs.style.display = "";
  }

  function renderClasses(stats) {
    const list = $("#classList");
    const section = $("#classSection");
    if (!list || !section) return;
    if (!stats) { list.innerHTML = ""; section.style.display = "none"; return; }
    section.style.display = "";
    const rows = [
      { c: "AB", k: "Compound", v: stats.class_ab_count || 0 },
      { c: "A",  k: "False 1-way", v: stats.class_a_count || 0 },
      { c: "B",  k: "Multi-segment", v: stats.class_b_way_count || 0 },
      { c: "C",  k: "Residual", v: (stats.total || 0) - (stats.class_ab_count || 0) - (stats.class_a_count || 0) - (stats.class_b_way_count || 0) },
      { c: "GAPS", k: "Node gaps", v: stats.gaps_found || 0 },
    ];
    list.innerHTML = rows.map((r) => `
      <button class="class-row${state.classFilters[r.c] ? " on" : ""}" data-class="${r.c}" aria-pressed="${state.classFilters[r.c]}">
        <span class="class-swatch" style="background:${r.c === "GAPS" ? "var(--accent)" : "var(--cls-" + r.c.toLowerCase() + ")"};"></span>
        <span class="class-label"><strong>${r.c}</strong> ${esc(r.k)}</span>
        <span class="class-count">${Number(r.v).toLocaleString()}</span>
      </button>
    `).join("");
    $$("#classList .class-row").forEach((btn) => {
      btn.addEventListener("click", () => toggleClassFilter(btn.dataset.class));
    });
    // and wire legend
    // Idempotent assignment — `renderClasses` re-runs on every stats update.
    // Using addEventListener here would accumulate one extra listener per
    // render; `onclick =` cleanly replaces the previous handler. Keep this
    // pattern even though the rest of the file uses addEventListener.
    $$(".leg-item").forEach((el) => {
      el.onclick = () => toggleClassFilter(el.dataset.class);
    });
  }

  // Rider-impact findings (counts per detector kind from summary_stats).
  // Each row, when clicked, opens the inventory panel with focus scrolled to
  // that finding kind. We deliberately do NOT toggle map filters here — the
  // findings overlay nodes/relations that the map layer doesn't currently
  // render, and human review is required before any mechanical fix.
  const FINDINGS_ROWS = [
    { kind: "oneway_minus_one",          stat: "findings_oneway_minus_one",          label: "oneway=-1 (reversed-tag)" },
    { kind: "oneway_conflict",           stat: "findings_oneway_conflicts",          label: "Same-name oneway conflicts" },
    { kind: "access_blocked",            stat: "findings_access_blocked",            label: "access=private/no on residential" },
    { kind: "barrier_unqualified",       stat: "findings_barriers_unqualified",      label: "Barriers w/o access qualifier" },
    { kind: "broken_turn_restriction",   stat: "findings_broken_turn_restrictions",  label: "Broken turn-restriction relations" },
    { kind: "arterial_named_residential",stat: "findings_arterial_named_residential",label: "Resi w/ arterial-suffix name" },
    { kind: "missing_maxspeed",          stat: "findings_missing_maxspeed",          label: "Tert/uncl missing maxspeed" },
    { kind: "bus_stop_misplaced",        stat: "findings_bus_stops_misplaced",       label: "Bus stops >20 m from drivable" },
  ];

  function renderFindings(stats) {
    const list = document.getElementById("findingsList");
    const section = document.getElementById("findingsSection");
    if (!list || !section) return;
    if (!stats) { list.innerHTML = ""; section.style.display = "none"; return; }
    const total = FINDINGS_ROWS.reduce((s, r) => s + (Number(stats[r.stat]) || 0), 0);
    if (total === 0) { section.style.display = "none"; return; }
    section.style.display = "";
    list.innerHTML = FINDINGS_ROWS.map((r) => {
      const v = Number(stats[r.stat]) || 0;
      const dim = v === 0 ? " dim" : "";
      return `
        <button class="class-row${dim}" data-finding-kind="${r.kind}"
                title="Open inventory and scroll to ${esc(r.label)}. Findings need human review and are not auto-fixable.">
          <span class="class-swatch" style="background: var(--accent); opacity: ${v ? 1 : 0.35};"></span>
          <span class="class-label">${esc(r.label)}</span>
          <span class="class-count">${v.toLocaleString()}</span>
        </button>
      `;
    }).join("");
    list.querySelectorAll(".class-row[data-finding-kind]").forEach((btn) => {
      btn.addEventListener("click", () => {
        openPanel("results");
        const id = "rs-finding-" + btn.dataset.findingKind;
        // Scroll the row into view once the panel renders.
        setTimeout(() => {
          const target = document.getElementById(id);
          if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
        }, 50);
      });
    });
  }

  function toggleClassFilter(c) {
    state.classFilters[c] = !state.classFilters[c];
    // class-row and leg-item presses
    $$(`.class-row[data-class="${c}"]`).forEach((b) => {
      b.classList.toggle("on", state.classFilters[c]);
      b.setAttribute("aria-pressed", state.classFilters[c]);
    });
    $$(`.leg-item[data-class="${c}"]`).forEach((b) => {
      b.setAttribute("aria-pressed", state.classFilters[c]);
    });
    if (state.results) drawResults(state.results);
  }

  function setLastRun(label) {
    const el = $("#lastRun");
    if (el) el.textContent = label;
  }

  // Bug 5: surface stale-cache state to the UI when fetch fell back to disk.
  function applyCacheBadge(stats) {
    const el = $("#lastRun");
    if (!el) return;
    const prior = el.querySelector(".cache-badge");
    if (prior) prior.remove();
    if (!stats || !stats.cache_used) return;
    const ageS = stats.cache_age_seconds;
    let ageLabel = "";
    if (typeof ageS === "number") {
      ageLabel = ageS < 3600
        ? ` (${Math.round(ageS / 60)}m old)`
        : ageS < 86400
          ? ` (${(ageS / 3600).toFixed(1)}h old)`
          : ` (${(ageS / 86400).toFixed(1)}d old)`;
    }
    const badge = document.createElement("span");
    badge.className = "cache-badge";
    badge.textContent = `stale cache${ageLabel}`;
    badge.style.cssText = "margin-left:.5rem;padding:.1rem .4rem;border-radius:4px;background:#f59e0b;color:#1a1a1a;font-size:.75em;font-weight:600;";
    el.appendChild(badge);
    toast(`Using stale cached data${ageLabel} — live Overpass query failed`, "warn");
  }

  // --------------------------------------------------------------- scan
  async function tryLoadExistingResults() {
    if (!state.currentZone) return;
    try {
      const data = await api("/api/results/" + state.currentZone);
      if (!data || !data.all_ways) return;
      state.results = data;
      drawResults(data);
      renderStats(data.summary_stats || {});
      renderClasses(data.summary_stats || {});
      updateInvestigationsBadge();
      setLastRun(new Date().toLocaleString());
      applyCacheBadge(data.summary_stats || {});
      setReportsEnabled(true);
      consoleLog("Loaded existing scan results", "ok");
      consoleShow(true);
      consoleStatus("audit · idle", "idle");
    } catch (_) {
      // 404 = no scan yet, silently leave empty
    }
  }

  function setReportsEnabled(on) {
    const a = $("#genReportsBtn"); if (a) a.disabled = !on;
    const b = $("#openDashBtn"); if (b) b.disabled = !on;
  }

  function startScanTimer() {
    state.scanStartedAt = Date.now();
    if (state.scanTimerId) clearInterval(state.scanTimerId);
    state.scanTimerId = setInterval(() => {
      const s = (Date.now() - state.scanStartedAt) / 1000;
      const el = $("#ckElapsed");
      if (el) el.textContent = s < 60 ? `${s.toFixed(1)}s` : `${Math.floor(s/60)}m ${Math.floor(s%60)}s`;
    }, 200);
  }
  function stopScanTimer() {
    if (state.scanTimerId) { clearInterval(state.scanTimerId); state.scanTimerId = null; }
  }

  async function runScan() {
    if (state.scanInProgress) return;
    if (!state.currentZone) { toast("Pick a zone first", "warn"); return; }
    state.scanInProgress = true;
    const btn = $("#scanBtn");
    if (btn) btn.disabled = true;
    consoleShow(true);
    consoleClear();
    consoleStatus("audit · running", "live");
    consoleLog(`Starting scan for ${state.zones[state.currentZone].name}`);
    consoleLog("Querying Overpass API…");
    startScanTimer();
    const skip = $("#skipHistory")?.checked === true;
    const includeUnnamedService = $("#includeUnnamedService")?.checked === true;
    // staged progress messages mirror the legacy timing (0/5/15/30s)
    const stageTimers = [];
    stageTimers.push(setTimeout(() => consoleLog("Fetching way data…"), 5000));
    stageTimers.push(setTimeout(() => consoleLog("Classifying defects…"), 15000));
    if (!skip) {
      stageTimers.push(setTimeout(() => consoleLog("Analyzing revision history…"), 30000));
    }
    if (includeUnnamedService) {
      consoleLog("Including unnamed service-oneway ways in Class A (exhaustive audit)", "warn");
    }
    const clearStageTimers = () => stageTimers.forEach(clearTimeout);
    try {
      const result = await api("/api/scan", {
        method: "POST",
        body: {
          zone: state.currentZone,
          skip_history: skip,
          include_unnamed_service: includeUnnamedService,
        },
      });
      clearStageTimers();
      consoleLog(`Scan complete — ${(result.stats.total || 0).toLocaleString()} ways analyzed`, "ok");
      consoleStatus("audit · complete", "ok");
      // pull full results so we can draw the map
      const full = await api("/api/results/" + state.currentZone);
      state.results = full;
      drawResults(full);
      renderStats(full.summary_stats || {});
      renderClasses(full.summary_stats || {});
      renderFindings(full.summary_stats || {});
      updateInvestigationsBadge();
      setLastRun(new Date().toLocaleString());
      applyCacheBadge(full.summary_stats || {});
      setReportsEnabled(true);
      toast(`Scan finished — ${(result.stats.class_ab_count || 0)} compound, ${(result.stats.class_a_count || 0)} false 1-way`);
      announceToScreenReader(`Scan complete. ${(result.stats.total || 0)} ways analyzed, ${(result.stats.class_ab_count || 0)} compound defects found.`);
    } catch (e) {
      clearStageTimers();
      consoleLog("Scan failed: " + e.message, "error");
      consoleStatus("audit · error", "error");
      toast("Scan failed: " + e.message, "error");
    } finally {
      stopScanTimer();
      state.scanInProgress = false;
      if (btn) btn.disabled = false;
    }
  }

  // --------------------------------------------------------------- panels / dock
  // Focus trap state: the element that had focus before a panel opened, so we
  // can restore it on close. Only the active panel is treated as a dialog.
  let focusReturnTarget = null;
  let trappedPanel = null;

  function focusableWithin(root) {
    if (!root) return [];
    const sel = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
    return Array.from(root.querySelectorAll(sel)).filter((el) => el.offsetParent !== null);
  }

  function trapFocus(panel) {
    trappedPanel = panel;
    const items = focusableWithin(panel);
    if (items.length) items[0].focus();
  }

  function onTrapKeydown(e) {
    if (!trappedPanel) return;
    if (e.key === "Escape") { closeAllPanels(); return; }
    if (e.key !== "Tab") return;
    const items = focusableWithin(trappedPanel);
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }
  document.addEventListener("keydown", onTrapKeydown);

  function openPanel(name) {
    // Only capture the return target on the *first* open. Panel-switching
    // (e.g. submitFixes() opening "auth" while the Fix panel is already
    // up) would otherwise overwrite the target with an element inside the
    // panel that is about to be hidden, leaving closeAllPanels with a
    // detached / unfocusable target.
    if (!trappedPanel) focusReturnTarget = document.activeElement;
    $$(".overlay-panel").forEach((p) => p.classList.add("hidden"));
    const p = $("#panel-" + name);
    if (p) p.classList.remove("hidden");
    $$(".dock-btn").forEach((b) => {
      const active = b.dataset.view === name;
      b.setAttribute("aria-pressed", active ? "true" : "false");
      if (active) b.setAttribute("aria-current", "page");
      else b.removeAttribute("aria-current");
    });
    if (name === "results") renderResultsPanel();
    if (name === "investigations") renderInvestigationsPanel();
    if (name === "history") renderHistoryPanel();
    if (name === "discuss") renderDiscussPanel();
    if (name === "formality") renderFormalityPanel();
    if (name === "auth") renderAuthPanel();
    if (p) trapFocus(p);
  }
  function closeAllPanels() {
    $$(".overlay-panel").forEach((p) => p.classList.add("hidden"));
    $$(".dock-btn").forEach((b) => {
      const active = b.dataset.view === "map";
      b.setAttribute("aria-pressed", active ? "true" : "false");
      if (active) b.setAttribute("aria-current", "page");
      else b.removeAttribute("aria-current");
    });
    trappedPanel = null;
    // Restore focus only if the original opener is still in the DOM and
    // focusable. document.body is a safe fallback if the opener is gone.
    if (focusReturnTarget && focusReturnTarget.isConnected
        && typeof focusReturnTarget.focus === "function") {
      focusReturnTarget.focus();
    } else if (document.body && typeof document.body.focus === "function") {
      document.body.focus();
    }
    focusReturnTarget = null;
  }

  // --------------------------------------------------------------- Osmose overlay
  // One-shot fetch of the Osmose-flagged ways for the current zone. Used
  // to show "Also flagged by Osmose" badges in the inventory & fix tables.
  // Map shape: { wayId(number) -> {issue_id, item, item_title, url} }
  const osmoseMatchByWay = new Map();
  let osmoseFetchedZone = null;

  async function ensureOsmoseLoaded() {
    if (!state.currentZone) return;
    if (osmoseFetchedZone === state.currentZone) return;
    osmoseFetchedZone = state.currentZone;
    osmoseMatchByWay.clear();
    try {
      const data = await api(`/api/osmose/${encodeURIComponent(state.currentZone)}`);
      const issues = Array.isArray(data && data.issues) ? data.issues : [];
      for (const issue of issues) {
        const ways = (issue.osm_ids && issue.osm_ids.ways) || [];
        for (const wid of ways) {
          if (!osmoseMatchByWay.has(wid)) {
            osmoseMatchByWay.set(wid, {
              issue_id: issue.id,
              item: issue.item,
              item_title: issue.item_title,
              url: issue.url,
            });
          }
        }
      }
    } catch (e) {
      // Non-fatal — graceful degradation just like the Python side.
      consoleLog("Osmose fetch failed: " + e.message, "warn");
    }
  }

  function osmoseBadge(wayId) {
    if (wayId == null) return "";
    const m = osmoseMatchByWay.get(Number(wayId));
    if (!m) return "";
    const tip = `Osmose-QA flagged this way (item ${m.item || "?"}${m.item_title ? ": " + m.item_title : ""}). ` +
      "Osmose is a community quality-assurance tool that mirrors OSM and reports defects independently.";
    return ` <a class="osmose-badge" href="${esc(m.url || "https://osmose.openstreetmap.fr/")}" target="_blank" rel="noopener" title="${esc(tip)}">Osmose</a>`;
  }

  // --------------------------------------------------------------- results panel
  async function renderResultsPanel() {
    const body = $("#resultsBody");
    if (!body) return;
    if (!state.results) {
      body.innerHTML = `<div class="empty"><div class="em-title">No scan yet</div>Run a scan to see the defect inventory.</div>`;
      return;
    }
    // Kick off Osmose fetch in parallel; render once, then re-render to
    // attach badges (avoids a perceived hang on slow links).
    const ab = (state.results.class_ab || []);
    const a = (state.results.class_a_only || []);
    const findings = (state.results.extra_findings || []);
    const draw = () => {
      body.innerHTML =
        sectionTable("Class AB — compound (highest risk)", ab, "ab") +
        sectionTable("Class A — false oneway", a, "a") +
        findingsSection(findings);
      // Re-bind the route-diff button after every redraw — innerHTML wipes
      // event listeners.
      const rdBtn = $("#runRouteDiffBtn");
      if (rdBtn) rdBtn.addEventListener("click", runRouteDiff);
      // Wire the pagination buttons.
      $$("button.rs-more-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
          const k = btn.dataset.kind;
          const action = btn.dataset.action;
          const ways = k === "ab" ? ab : a;
          if (action === "all") {
            state.tablePages[k] = Math.ceil(ways.length / tablePageSize) + 1;
          } else {
            state.tablePages[k] = (state.tablePages[k] || 1) + 1;
          }
          draw();
        });
      });
    };
    draw();
    await ensureOsmoseLoaded();
    draw();
  }

  // -------------------------------------------------- Investigations panel
  // Phase 2c: surface the CAGIS review-band (0.6 ≤ confidence < 0.85) and
  // the unmatched-way subset (no cagis_match at all). Without this view,
  // the 8.7% match rate is just a number — here it becomes a triage queue
  // that joins routing_impact from the rider-impact detectors.
  const INVEST_FILTER_KEY = "metronow.investFilter";
  let investFilter = (() => {
    try {
      const v = localStorage.getItem(INVEST_FILTER_KEY);
      return ["review", "unmatched", "all"].includes(v) ? v : "review";
    } catch { return "review"; }
  })();

  function investWays() {
    const all = (state.results && state.results.all_ways) || [];
    if (investFilter === "all") return all;
    return all.filter((w) => {
      const cm = w.cagis_match;
      if (investFilter === "unmatched") return !cm;
      if (investFilter === "review") {
        return cm && Number(cm.confidence) >= 0.6 && Number(cm.confidence) < 0.85;
      }
      return false;
    });
  }

  function routingImpactFor(wayId) {
    // Join: extra_findings carries routing_impact per detector hit, keyed
    // by way_id. Take the max so the worst detector dominates this row.
    const findings = (state.results && state.results.extra_findings) || [];
    let best = 0;
    for (const f of findings) {
      const wid = (f.way && f.way.id) || f.way_id || (f.subject && f.subject.id);
      if (Number(wid) === Number(wayId) && typeof f.routing_impact === "number") {
        if (f.routing_impact > best) best = f.routing_impact;
      }
    }
    return best;
  }

  // Lightweight: update only the dock badge without rendering the panel
  // body. Used after drawResults() so the badge stays accurate even when
  // the user never opens Investigations.
  function updateInvestigationsBadge() {
    const dockBadge = $("#dockInvestigate");
    if (!dockBadge) return;
    if (!state.results) {
      dockBadge.style.display = "none";
      return;
    }
    const n = investWays().length;
    dockBadge.textContent = String(n);
    dockBadge.style.display = n ? "inline-flex" : "none";
  }

  function renderInvestigationsPanel() {
    const body = $("#investigationsBody");
    if (!body) return;
    if (!state.results) {
      body.innerHTML = `<div class="empty"><div class="em-title">No scan yet</div>Run a scan with conflation to populate the Investigations queue.</div>`;
      $("#investCount") && ($("#investCount").textContent = "");
      return;
    }
    const rows = investWays()
      .map((w) => ({ w, impact: routingImpactFor(w.id) }))
      .sort((a, b) => b.impact - a.impact);

    const counter = $("#investCount");
    if (counter) counter.textContent = `${rows.length} way(s) — filter: ${investFilter}`;
    const dockBadge = $("#dockInvestigate");
    if (dockBadge) {
      dockBadge.textContent = String(rows.length);
      dockBadge.style.display = rows.length ? "inline-flex" : "none";
    }
    if (rows.length === 0) {
      body.innerHTML = `<div class="empty"><div class="em-title">Nothing to investigate</div>No ways match this filter. Try "Unmatched" or "All".</div>`;
      return;
    }

    const PAGE = 100;
    const visible = rows.slice(0, PAGE);
    const more = rows.length - visible.length;

    // Baseline-diff block — empty placeholder; populated asynchronously
    // from /api/baseline-diff/:zone after the panel paints. Keeps the
    // initial render fast even when the diff requires reading two
    // 40-MB manifests.
    const lines = [
      `<div class="bd-block" id="bdBlock" style="margin: 6px 0 12px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--bg-elevated);">`,
      `<div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">`,
      `<strong style="font-family: var(--mono); font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--ink-mute);">Matcher tuning</strong>`,
      `<span id="bdHeadline" style="font-size: 12.5px; color: var(--ink-soft);">Loading baseline-diff…</span>`,
      `</div>`,
      `<div id="bdBody" style="margin-top: 8px; font-size: 12.5px; color: var(--ink-mute); font-family: var(--mono);"></div>`,
      `</div>`,
    ];

    // MapRoulette generator block — surfaces the Phase 3 task generator
    // alongside the same population it operates on. The button kicks off
    // the server-side regeneration; the result is downloadable as a
    // line-delimited GeoJSON for upload via the MapRoulette UI.
    lines.push(
      `<div class="mr-block" id="mrBlock" style="margin: 6px 0 14px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--bg-elevated);">`,
      `<div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">`,
      `<strong style="font-family: var(--mono); font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--ink-mute);">MapRoulette</strong>`,
      `<span style="font-size: 12.5px; color: var(--ink-soft);">Generate a community-review challenge for Class A/AB ways below the auto-submit threshold.</span>`,
      `<button class="btn btn-sm" id="mrGenerateBtn" style="margin-left: auto;">Generate challenge</button>`,
      `<a class="btn btn-sm" id="mrDownloadBtn" href="/api/maproulette/${encodeURIComponent(state.currentZone)}" download style="display: none;">Download .geojsonl</a>`,
      `</div>`,
      `<div id="mrStatus" style="margin-top: 8px; font-size: 12.5px; color: var(--ink-mute); font-family: var(--mono);"></div>`,
      `</div>`,
      `<table class="rs-table"><thead><tr>`,
      `<th>Way</th><th>Class</th><th>Name</th><th>CAGIS conf.</th>`,
      `<th>Hausdorff (m)</th><th>Name sim.</th><th>Routing impact</th>`,
      `</tr></thead><tbody>`,
    );
    for (const { w, impact } of visible) {
      const cm = w.cagis_match;
      const conf = cm && typeof cm.confidence === "number" ? Math.round(cm.confidence * 100) + "%" : "—";
      const haus = cm && typeof cm.hausdorff_m === "number" ? cm.hausdorff_m.toFixed(1) : "—";
      const nameSim = cm && typeof cm.name_similarity === "number" ? cm.name_similarity.toFixed(2) : "—";
      const cls = (w.defect_class || "C").toUpperCase();
      const name = esc(w.name_display || w.name || "(unnamed)");
      const tone = !cm ? "err" : (cm.confidence >= 0.6 ? "warn" : "err");
      const osmUrl = `https://www.openstreetmap.org/way/${encodeURIComponent(w.id)}`;
      lines.push(
        `<tr>`,
        `<td><a href="${osmUrl}" target="_blank" rel="noopener">${esc(w.id)} ↗</a></td>`,
        `<td><span class="cls-pill cls-${cls.toLowerCase()}">${cls}</span></td>`,
        `<td>${name}</td>`,
        `<td><span class="conf-badge conf-${tone}">${conf}</span></td>`,
        `<td>${haus}</td>`,
        `<td>${nameSim}</td>`,
        `<td>${impact || "—"}</td>`,
        `</tr>`,
      );
    }
    lines.push("</tbody></table>");
    if (more > 0) {
      lines.push(`<div class="rs-more"><span>${more} more way(s) hidden — refine the filter or use the inventory CSV export.</span></div>`);
    }
    body.innerHTML = lines.join("");

    // Wire MapRoulette generate button — re-bind every render since
    // innerHTML wipes event listeners.
    const mrBtn = $("#mrGenerateBtn");
    const mrStatus = $("#mrStatus");
    const mrDownload = $("#mrDownloadBtn");
    if (mrBtn) {
      mrBtn.addEventListener("click", async () => {
        if (!state.currentZone) return;
        mrBtn.disabled = true;
        if (mrStatus) mrStatus.textContent = "Generating…";
        try {
          const data = await api(
            "/api/maproulette/" + encodeURIComponent(state.currentZone),
            { method: "POST" },
          );
          if (mrStatus) {
            const meta = data.metadata || {};
            mrStatus.innerHTML =
              `Wrote <strong>${data.task_count || 0}</strong> task(s). ` +
              `Suggested challenge name: <em>${esc(meta.name || "")}</em>. ` +
              `Tags: <code>${esc(meta.tags || "")}</code>`;
          }
          if (mrDownload && (data.task_count || 0) > 0) {
            mrDownload.style.display = "inline-flex";
          }
        } catch (e) {
          if (mrStatus) mrStatus.textContent = "Failed: " + (e && e.message || e);
        } finally {
          mrBtn.disabled = false;
        }
      });
    }

    // Asynchronously load and render the baseline-diff. Failures are
    // silent on purpose — the panel works fine without it; the diff is
    // a tuning aid, not load-bearing for the queue.
    loadBaselineDiff();
  }

  function fmtDelta(n) {
    if (typeof n !== "number" || Number.isNaN(n)) return "—";
    const sign = n > 0 ? "+" : (n < 0 ? "" : "±");
    return `${sign}${n}`;
  }

  function fmtDeltaPct(n) {
    if (typeof n !== "number" || Number.isNaN(n)) return "—";
    const sign = n > 0 ? "+" : (n < 0 ? "" : "±");
    return `${sign}${n.toFixed(2)}pp`;
  }

  async function loadBaselineDiff() {
    const headline = $("#bdHeadline");
    const body = $("#bdBody");
    if (!headline || !body || !state.currentZone) return;
    try {
      const data = await api(
        "/api/baseline-diff/" + encodeURIComponent(state.currentZone),
      );
      const pair = data && data.pair;
      if (!pair) {
        headline.textContent =
          "Need ≥2 cagis_baseline_*.json manifests to diff. " +
          "Run 'osm conflate --baseline-manifest' twice between matcher tweaks.";
        body.innerHTML = "";
        return;
      }
      const head = pair.headline || {};
      const ar = head.auto_submit_rate_pct || {};
      const mr = head.match_rate_pct || {};
      const shaA = (pair.git_sha_a || "?").slice(0, 7);
      const shaB = (pair.git_sha_b || "?").slice(0, 7);
      const arDelta = typeof ar.delta === "number" ? fmtDeltaPct(ar.delta) : "—";
      const mrDelta = typeof mr.delta === "number" ? fmtDeltaPct(mr.delta) : "—";
      headline.innerHTML =
        `<code>${esc(shaA)}</code> → <code>${esc(shaB)}</code> · ` +
        `auto-submit <strong>${arDelta}</strong> · ` +
        `match-rate <strong>${mrDelta}</strong>`;
      const buckets = pair.buckets || {};
      const rows = Object.keys(buckets).sort().map((k) => {
        const v = buckets[k] || {};
        const cls = (v.delta || 0) > 0
          ? "color: var(--ok, #2a7a2a);"
          : ((v.delta || 0) < 0 ? "color: var(--err, #b34040);" : "");
        return (
          `<tr>` +
          `<td style="padding: 2px 8px 2px 0;">${esc(k)}</td>` +
          `<td style="padding: 2px 8px; text-align: right;">${v.a || 0}</td>` +
          `<td style="padding: 2px 8px; text-align: right;">${v.b || 0}</td>` +
          `<td style="padding: 2px 8px; text-align: right; ${cls}">${esc(fmtDelta(v.delta))}</td>` +
          `</tr>`
        );
      }).join("");
      const alerts = (pair.alerts || []).map((a) =>
        `<div style="margin-top: 6px; color: var(--err, #b34040);">⚠ ${esc(a)}</div>`
      ).join("");
      body.innerHTML =
        `<table style="border-collapse: collapse;"><thead><tr>` +
        `<th style="text-align: left; padding: 2px 8px 4px 0; font-weight: 600;">Bucket</th>` +
        `<th style="text-align: right; padding: 2px 8px 4px;">A</th>` +
        `<th style="text-align: right; padding: 2px 8px 4px;">B</th>` +
        `<th style="text-align: right; padding: 2px 8px 4px;">Δ</th>` +
        `</tr></thead><tbody>${rows}</tbody></table>` +
        alerts;
    } catch (e) {
      headline.textContent = "baseline-diff unavailable: " + ((e && e.message) || e);
      body.innerHTML = "";
    }
  }

  // Rider-impact findings — top 50 across all extra_findings, sorted by
  // routing_impact desc. These are intentionally NOT shown in the Fix panel:
  // node, relation, and tag-rewrite changes need human review before
  // mechanical edits. The "Run route-diff" button (rendered below) hits
  // BRouter to verify which of these change real routing behaviour and
  // tags each row with a green/amber/grey decision badge.
  const ROUTE_DIFF_TESTABLE_KINDS = new Set([
    "oneway_minus_one", "oneway_conflict",
    "broken_turn_restriction", "barrier_unqualified",
  ]);

  function routeDiffBadge(rd, kind) {
    if (!rd || typeof rd !== "object") {
      if (ROUTE_DIFF_TESTABLE_KINDS.has(kind)) {
        return '<span class="rd-badge rd-untested" title="Not yet route-diff tested">—</span>';
      }
      return '<span class="rd-badge rd-na" title="This finding kind is not testable with BRouter alone">n/a</span>';
    }
    const decision = rd.decision || "?";
    const delta = typeof rd.delta_pct === "number" ? `Δ ${rd.delta_pct.toFixed(1)}%` : "";
    const tip = `BRouter route-diff: decision=${decision}, ${delta}, confidence=${rd.confidence ?? "?"}`;
    let cls = "rd-untested";
    let label = decision;
    if (decision === "real") { cls = "rd-real"; label = "real"; }
    else if (decision === "noisy") { cls = "rd-noisy"; label = "noisy"; }
    else if (decision === "inconclusive") { cls = "rd-inconclusive"; label = "?"; }
    return `<span class="rd-badge ${cls}" title="${esc(tip)}">${esc(label)}</span>`;
  }

  function findingsSection(findings) {
    if (!Array.isArray(findings) || findings.length === 0) return "";
    const sorted = findings.slice().sort((x, y) => {
      const dx = (Number(y.routing_impact) || 0) - (Number(x.routing_impact) || 0);
      if (dx !== 0) return dx;
      const sevOrder = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 };
      return (sevOrder[x.severity] ?? 9) - (sevOrder[y.severity] ?? 9);
    });
    const top = sorted.slice(0, 50);
    // Anchor rows by kind so the sidebar findings buttons can scroll to them.
    const seenKinds = new Set();
    const rows = top.map((f) => {
      const kind = f.kind || "?";
      const id = f.id || "?";
      const elemType =
        kind === "barrier_unqualified" || kind === "bus_stop_misplaced" ? "node" :
        kind === "broken_turn_restriction" ? "relation" :
        "way";
      const url = `https://www.openstreetmap.org/${elemType}/${encodeURIComponent(id)}`;
      const anchorAttr = !seenKinds.has(kind) ? ` id="rs-finding-${esc(kind)}"` : "";
      seenKinds.add(kind);
      const rdBadge = routeDiffBadge(f.route_diff, kind);
      return `<tr${anchorAttr}>
        <td>${esc(kind)}</td>
        <td><a href="${url}" target="_blank" rel="noopener">${esc(elemType)}/${esc(id)}</a></td>
        <td>${esc(f.name || "—")}</td>
        <td>${esc(f.severity || "—")}</td>
        <td>${esc(String(f.routing_impact ?? "—"))}</td>
        <td>${rdBadge}</td>
        <td>${esc(f.description || "")}</td>
      </tr>`;
    }).join("");
    const tip = "Rider-impact findings are surfaced for review but not auto-fixed. " +
      "Node, relation, and tag-rewrite edits need human verification before submission.";
    const testableCount = findings.filter((f) => ROUTE_DIFF_TESTABLE_KINDS.has(f.kind)).length;
    const rdHist = (state.results && state.results.summary_stats &&
      state.results.summary_stats.route_diff_decisions) || null;
    const rdSummary = rdHist
      ? `Last route-diff: real=${rdHist.real || 0} · inconclusive=${rdHist.inconclusive || 0} · noisy=${rdHist.noisy || 0} · untested=${rdHist.untested || 0}`
      : "Route-diff has not been run for this zone yet.";
    return `
      <div class="rs-section findings" title="${esc(tip)}">
        <h3>Rider-impact findings <span class="rs-count">${findings.length.toLocaleString()}</span>
          <span class="muted" style="margin-left:6px;font-weight:normal;font-size:11px;">(read-only — see tooltip)</span>
        </h3>
        <p class="muted" style="margin:4px 0 8px;">${esc(tip)}</p>
        <div class="rd-controls" style="display:flex;gap:8px;align-items:center;margin:6px 0 10px;">
          <button id="runRouteDiffBtn" class="rd-run-btn"
                  title="Hit BRouter to test which of the ${testableCount.toLocaleString()} testable findings change real routing behaviour."
                  ${testableCount === 0 ? "disabled" : ""}>
            Run route-diff (${testableCount.toLocaleString()} testable)
          </button>
          <span id="rdStatus" class="muted" style="font-size:12px;">${esc(rdSummary)}</span>
        </div>
        <table class="rs-table">
          <thead><tr><th>Kind</th><th>Element</th><th>Name</th><th>Severity</th><th>Impact</th><th>Route-diff</th><th>Description</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
        ${findings.length > 50 ? `<p class="muted">Showing top 50 of ${findings.length.toLocaleString()} by routing impact.</p>` : ""}
      </div>
    `;
  }

  async function runRouteDiff() {
    if (!state.currentZone) {
      toast("Pick a zone first", "warn");
      return;
    }
    const btn = $("#runRouteDiffBtn");
    const status = $("#rdStatus");
    if (btn) btn.disabled = true;
    if (status) status.textContent = "Running route-diff (1s/call rate-limited)…";
    try {
      const data = await api(`/api/route-diff/${encodeURIComponent(state.currentZone)}`, {
        method: "POST",
        body: { profile: "car-fast" },
      });
      const dec = (data && data.decisions) || {};
      const summary = `Route-diff complete: real=${dec.real || 0} · inconclusive=${dec.inconclusive || 0} · noisy=${dec.noisy || 0} · untested=${dec.untested || 0}`;
      if (status) status.textContent = summary;
      toast(summary, "ok");
      // Refresh the inventory so badges show up.
      await tryLoadExistingResults();
    } catch (e) {
      toast("Route-diff failed: " + e.message, "err");
      if (status) status.textContent = "Route-diff failed: " + e.message;
    } finally {
      if (btn) btn.disabled = false;
    }
  }
  // Pagination state for the inventory tables. Keyed by section kind so AB and
  // A-only paginate independently. Reset whenever a new scan loads.
  const tablePageSize = 200;
  state.tablePages = state.tablePages || { ab: 1, a: 1 };

  function nameCell(w) {
    // If the way has a real name, render plain. Otherwise show the descriptor
    // produced by classify._unnamed_label, italicized so a reviewer can scan
    // a column and still tell unnamed rows apart by their kind.
    if (w.name) return esc(w.name);
    return `<span class="name-unnamed">${esc(w.name_display || "Unnamed way")}</span>`;
  }

  function sectionTable(title, ways, kind) {
    if (!ways.length) {
      return `<div class="rs-section"><h3>${esc(title)}</h3><p class="muted">None found.</p></div>`;
    }
    const page = Math.max(1, state.tablePages[kind] || 1);
    const shown = Math.min(page * tablePageSize, ways.length);
    const rows = ways.slice(0, shown).map((w) => {
      const review = w.review_status ? `<span class="badge">${esc(w.review_status)}</span>` : "";
      const wayId = w.id || "?";
      return `<tr>
        <td><a href="https://www.openstreetmap.org/way/${encodeURIComponent(wayId)}" target="_blank" rel="noopener">${esc(wayId)}</a>${osmoseBadge(wayId)}</td>
        <td>${nameCell(w)}</td>
        <td>${esc(w.highway || "—")}${w.service ? ` <span class="muted">(${esc(w.service)})</span>` : ""}</td>
        <td>${esc(w.oneway || "—")}</td>
        <td>${review}</td>
      </tr>`;
    }).join("");
    const hasMore = shown < ways.length;
    const more = hasMore
      ? `<div class="rs-more">
           <button class="rs-more-btn" data-kind="${esc(kind)}" data-action="more">Show ${Math.min(tablePageSize, ways.length - shown).toLocaleString()} more</button>
           <button class="rs-more-btn" data-kind="${esc(kind)}" data-action="all">Show all ${ways.length.toLocaleString()}</button>
           <span class="muted">Showing ${shown.toLocaleString()} of ${ways.length.toLocaleString()}</span>
         </div>`
      : `<p class="muted">Showing ${ways.length.toLocaleString()}.</p>`;
    return `
      <div class="rs-section ${kind}">
        <h3>${esc(title)} <span class="rs-count">${ways.length.toLocaleString()}</span></h3>
        <table class="rs-table">
          <thead><tr><th>Way ID</th><th>Street</th><th>Highway</th><th>Oneway</th><th>Review</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
        ${more}
      </div>
    `;
  }

  // --------------------------------------------------------------- fix panel
  async function loadFixes() {
    if (!state.currentZone) return;
    const btn = $("#loadFixesBtn");
    if (btn) btn.disabled = true;
    try {
      const data = await api("/api/review/" + state.currentZone);
      state.pendingFixes = data.fixes || [];
      $("#dryRunBtn").disabled = state.pendingFixes.length === 0;
      $("#submitBtn").disabled = state.pendingFixes.length === 0;
      // The route-impact harness only operates on oneway fixes; enable
      // when at least one is in the pending queue.
      const hasOnewayFix = state.pendingFixes.some(
        (f) => f.kind === "set_oneway_cagis" || f.kind === "remove_oneway_cagis",
      );
      $("#routeImpactBtn").disabled = !hasOnewayFix;
      // Make sure Osmose data is in cache before we render so the badge
      // is visible on first paint.
      await ensureOsmoseLoaded();
      renderFixPanel();
      toast(`${data.count.toLocaleString()} fixable defect(s) loaded`);
    } catch (e) {
      toast("Load failed: " + e.message, "error");
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  // Phase 4b: surface the BRouter route-impact value-story payload in
  // the Fix panel — same data the CLI's `osm fix-impact` produces, just
  // wired into the panel the maintainer is already looking at.
  async function runRouteImpact() {
    if (!state.currentZone) return;
    const btn = $("#routeImpactBtn");
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Running…";
    }
    try {
      const data = await api(
        "/api/fix-impact/" + encodeURIComponent(state.currentZone),
        { method: "POST" },
      );
      const s = (data && data.summary) || {};
      const lines = [
        `${s.real || 0} fix(es) measurably change routing.`,
      ];
      if ((s.real || 0) > 0) {
        lines.push(
          `Avg delta: ${s.avg_delta_pct_real || 0}% of route cost; ` +
          `max ${s.max_delta_pct_real || 0}%; ` +
          `avg duration shift ${s.avg_duration_delta_s_real || 0} s.`,
        );
      }
      if ((s.fixes_skipped || 0) > 0) {
        lines.push(
          `${s.fixes_skipped} fix(es) skipped (maxspeed/name don't perturb routing).`,
        );
      }
      toast(lines.join(" "), "ok");
      // Refresh the fix panel so per-fix route_impact badges (if any)
      // pick up the new data.
      const data2 = await api("/api/review/" + state.currentZone);
      state.pendingFixes = data2.fixes || state.pendingFixes;
      renderFixPanel();
    } catch (e) {
      toast("Route-impact failed: " + (e && e.message || e), "error");
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = "Routing impact";
      }
    }
  }

  function renderFixPanel() {
    const body = $("#fixBody");
    if (!body) return;
    if (!state.pendingFixes.length) {
      body.innerHTML = `<div class="empty"><div class="em-title">No proposals loaded</div>Click <strong>Load proposals</strong> to fetch automatically-fixable defects from the most recent scan.</div>`;
      return;
    }
    const rows = state.pendingFixes.slice(0, 500).map((p, i) => {
      const w = p.way || {};
      const f = p.fix || {};
      const wayId = w.id || "?";
      const ev = f.source_evidence || null;
      let evidenceCell = "—";
      if (ev && ev.cagis_id != null) {
        const cagisUrl = "https://services.arcgis.com/JyZag7oO4NteHGiq/arcgis/rest/services/Open_Data/FeatureServer/26/" + encodeURIComponent(ev.cagis_id);
        const conf = Number(ev.confidence ?? 0);
        const pct = Math.round(conf * 100);
        const tone = conf >= 0.85 ? "ok" : (conf >= 0.6 ? "warn" : "err");
        evidenceCell = `<a href="${cagisUrl}" target="_blank" rel="noopener" title="View CAGIS feature">CAGIS ${esc(ev.cagis_id)}</a> <span class="conf-badge conf-${tone}">${pct}%</span>`;
      } else if (ev && ev.tiger_id != null) {
        // TIGER evidence — gray badge styling reflects fallback authority
        // (CAGIS is primary, TIGER is federal baseline used where CAGIS
        // is absent).
        const conf = Number(ev.confidence ?? 0);
        const pct = Math.round(conf * 100);
        evidenceCell = `<span class="ev-tiger" title="TIGER/Line 2024 LINEARID — fallback evidence">TIGER ${esc(ev.tiger_id)}</span> <span class="conf-badge conf-tiger">${pct}%</span>`;
      } else if (f.requires_human_review) {
        evidenceCell = `<span class="muted">heuristic — review</span>`;
      }
      return `<tr>
        <td><input type="checkbox" class="fix-check" data-i="${i}" ${(ev && Number(ev.confidence ?? 0) >= 0.85) || !f.requires_human_review ? "checked" : ""}></td>
        <td><a href="https://www.openstreetmap.org/way/${encodeURIComponent(wayId)}" target="_blank" rel="noopener">${esc(wayId)}</a>${osmoseBadge(wayId)}</td>
        <td>${esc(w.name_display || "—")}</td>
        <td>${esc(w.defect_class || "?")}</td>
        <td>${esc(f.description || "")}</td>
        <td>${evidenceCell}</td>
      </tr>`;
    }).join("");
    body.innerHTML = `
      <div class="fx-toolbar">
        <label class="opt-row"><input type="checkbox" id="fxSelectAll" checked> <span>Select all</span></label>
        <span class="muted" id="fxSelected">${state.pendingFixes.length.toLocaleString()} selected</span>
      </div>
      <table class="rs-table">
        <thead><tr><th></th><th>Way ID</th><th>Street</th><th>Class</th><th>Proposed fix</th><th>Evidence</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
      ${state.pendingFixes.length > 500 ? `<p class="muted">Showing 500 of ${state.pendingFixes.length.toLocaleString()}; all will be submitted when you click Submit.</p>` : ""}
      <p class="muted fx-attrib">Fixes marked CAGIS-verified cite Hamilton County's authoritative street centerlines. TIGER-verified fixes cite the U.S. Census Bureau's TIGER/Line 2024 — a less-current but federally-maintained baseline used where CAGIS coverage is absent.</p>
      <div id="fxResult"></div>
    `;
    $("#fxSelectAll")?.addEventListener("change", (ev) => {
      const on = ev.target.checked;
      $$(".fix-check").forEach((cb) => (cb.checked = on));
      updateSelectedCount();
    });
    $$(".fix-check").forEach((cb) => cb.addEventListener("change", updateSelectedCount));
  }

  function updateSelectedCount() {
    const checked = $$(".fix-check").filter((c) => c.checked).length;
    const el = $("#fxSelected");
    if (el) el.textContent = `${checked.toLocaleString()} selected`;
  }

  function getSelectedFixes() {
    const checks = $$(".fix-check");
    if (!checks.length) return state.pendingFixes.map((p) => p.fix); // nothing rendered yet → all
    const set = new Set();
    checks.forEach((cb) => { if (cb.checked) set.add(parseInt(cb.dataset.i, 10)); });
    return state.pendingFixes
      .map((p, i) => (set.has(i) ? p.fix : null))
      .filter(Boolean)
      // also include any > 500 not rendered, since "select all" implies all
      .concat($("#fxSelectAll")?.checked && state.pendingFixes.length > 500
        ? state.pendingFixes.slice(500).map((p) => p.fix)
        : []);
  }

  async function submitFixes(dryRun) {
    const fixes = getSelectedFixes();
    if (!fixes.length) { toast("No fixes selected", "warn"); return; }
    if (!dryRun && !state.auth.authenticated) {
      toast("Sign in with OpenStreetMap first", "warn");
      openPanel("auth");
      return;
    }
    if (!dryRun && !confirm(`Submit ${fixes.length.toLocaleString()} correction(s) to OpenStreetMap?\n\nThis modifies live map data and cannot be undone.`)) {
      return;
    }
    const btn = dryRun ? $("#dryRunBtn") : $("#submitBtn");
    if (btn) btn.disabled = true;
    try {
      const result = await api("/api/fix", {
        method: "POST",
        body: { zone: state.currentZone, fixes, dry_run: !!dryRun },
      });
      const fr = $("#fxResult");
      if (dryRun) {
        if (fr) fr.innerHTML = `<div class="fx-result ok">[DRY RUN] Would submit <strong>${esc(result.fixes_applied)}</strong> fix(es). No changes made.</div>`;
        toast("Dry run complete");
      } else {
        const ids = (result.changeset_ids || [])
          .map((id) => `<a href="https://www.openstreetmap.org/changeset/${encodeURIComponent(id)}" target="_blank" rel="noopener">${esc(id)}</a>`)
          .join(", ");
        let html = `<div class="fx-result ok">Submitted <strong>${esc(result.fixes_applied)}</strong> fix(es).</div>`;
        if (ids) html += `<div class="muted">Changeset(s): ${ids}</div>`;
        if (result.errors && result.errors.length)
          html += `<div class="fx-result err">${result.errors.length} error(s): ${esc(result.errors.join("; "))}</div>`;
        if (fr) fr.innerHTML = html;
        toast("Corrections submitted to OSM");
      }
    } catch (e) {
      const fr = $("#fxResult");
      if (fr) fr.innerHTML = `<div class="fx-result err">${esc(e.message)}</div>`;
      toast((dryRun ? "Dry run failed: " : "Submit failed: ") + e.message, "error");
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  // --------------------------------------------------------------- history panel
  async function renderHistoryPanel() {
    const body = $("#historyBody");
    if (!body) return;
    body.innerHTML = `<p class="muted">Loading…</p>`;
    try {
      const entries = await api("/api/history");
      if (!entries.length) {
        body.innerHTML = `<div class="empty"><div class="em-title">No activity yet</div>Scans, dry runs, and submissions appear here.</div>`;
        return;
      }
      body.innerHTML = `<ol class="ledger">${entries.slice().reverse().map(ledgerItem).join("")}</ol>`;
    } catch (e) {
      body.innerHTML = `<div class="fx-result err">${esc(e.message)}</div>`;
    }
  }
  function ledgerItem(e) {
    const ts = e.ts || e.timestamp || "";
    const tsDisplay = formatTimeAgo(ts);
    const tsTitle = ts ? new Date(ts).toLocaleString() : "";
    const action = e.action || "?";
    let detail = "";
    if (action === "scan") {
      const s = e.stats || {};
      detail = `${(s.total || 0).toLocaleString()} ways · ${(s.class_ab_count || 0)} AB · ${(s.class_a_count || 0)} A`;
    } else if (action === "dry_run") {
      detail = `${(e.fixes_applied || 0)} would-submit`;
    } else if (action === "submit") {
      detail = `${(e.fixes_applied || 0)} applied · ${(e.changeset_ids || []).length} changeset(s)`;
    }
    return `<li>
      <div class="lg-time" title="${esc(tsTitle)}">${esc(tsDisplay)}</div>
      <div class="lg-action">${esc(action)}</div>
      <div class="lg-zone">${esc(e.zone || "")}</div>
      <div class="lg-detail">${esc(detail)}</div>
    </li>`;
  }

  // --------------------------------------------------------------- discuss panel
  // Two tabs: live OSM Notes (public, fetched from /api/notes/:zone) and a
  // localStorage-only private board (the "New thread" workflow).

  function loadDiscuss() {
    try { return JSON.parse(localStorage.getItem(state.discussKey()) || "[]"); } catch { return []; }
  }
  function saveDiscuss(items) { localStorage.setItem(state.discussKey(), JSON.stringify(items)); }

  // Per-tab cache so re-opening the panel doesn't re-fetch every time.
  const discussTabState = {
    tab: "osm-notes",
    osmNotes: null,        // [{id, lat, lon, status, ...}]
    osmNotesError: null,
  };

  async function loadOsmNotes(force) {
    if (!state.currentZone) return [];
    if (!force && discussTabState.osmNotes) return discussTabState.osmNotes;
    try {
      const data = await api(`/api/notes/${encodeURIComponent(state.currentZone)}${force ? "?force=1" : ""}`);
      const list = Array.isArray(data && data.notes) ? data.notes : [];
      discussTabState.osmNotes = list;
      discussTabState.osmNotesError = null;
      return list;
    } catch (e) {
      discussTabState.osmNotesError = e.message || String(e);
      discussTabState.osmNotes = [];
      return [];
    }
  }

  function renderDiscussPanel() {
    const body = $("#discussBody");
    if (!body) return;
    const tab = discussTabState.tab;
    const localItems = loadDiscuss();
    body.innerHTML = `
      <div class="discuss-tabs" role="tablist">
        <button class="discuss-tab" data-tab="osm-notes" role="tab" aria-selected="${tab === "osm-notes"}">
          OSM Notes (public)
        </button>
        <button class="discuss-tab" data-tab="local" role="tab" aria-selected="${tab === "local"}">
          Private board (this browser)
          ${localItems.length ? `<span class="rs-count">${localItems.length}</span>` : ""}
        </button>
      </div>
      <div id="discuss-tab-body"></div>
    `;
    $$(".discuss-tab", body).forEach((b) => {
      b.addEventListener("click", () => {
        discussTabState.tab = b.dataset.tab;
        renderDiscussPanel();
      });
    });

    const tabBody = $("#discuss-tab-body", body);
    if (tab === "local") {
      renderLocalBoard(tabBody, localItems);
    } else {
      renderOsmNotes(tabBody);
    }

    // Dock chip: show count = open OSM notes + local items.
    const dock = $("#dockDiscuss");
    if (dock) {
      const remoteCount = (discussTabState.osmNotes || []).filter((n) => n.status === "open").length;
      const total = remoteCount + localItems.length;
      dock.style.display = total ? "" : "none";
      dock.textContent = String(total);
    }
  }

  function renderLocalBoard(host, items) {
    if (!host) return;
    if (!items.length) {
      host.innerHTML = `
        <div class="empty">
          <div class="em-title">No private notes yet</div>
          The private board is saved to this browser only and is scoped to the active zone.
          The OSM Notes tab shows the public feed any mapper can see.
        </div>`;
      return;
    }
    host.innerHTML = `<ol class="threads">${items.slice().reverse().map((it) => `
      <li class="thread">
        <div class="th-head"><span class="th-author">${esc(it.author || "you")}</span><span class="th-time">${esc(it.ts || "")}</span></div>
        <div class="th-title">${esc(it.title || "")}</div>
        <div class="th-body">${esc(it.body || "")}</div>
      </li>`).join("")}</ol>`;
  }

  async function renderOsmNotes(host) {
    if (!host) return;
    host.innerHTML = `<p class="muted">Loading OSM Notes…</p>`;
    const notes = await loadOsmNotes(false);
    if (discussTabState.osmNotesError) {
      host.innerHTML = `<div class="fx-result err">Could not fetch OSM Notes: ${esc(discussTabState.osmNotesError)}</div>`;
      return;
    }
    if (!notes.length) {
      host.innerHTML = `
        <div class="empty">
          <div class="em-title">No OSM Notes in this zone</div>
          Open notes from the public OSM Notes feed will appear here.
          <a href="https://wiki.openstreetmap.org/wiki/Notes" target="_blank" rel="noopener">About OSM Notes</a>.
        </div>`;
      return;
    }
    const open = notes.filter((n) => n.status === "open");
    const closed = notes.filter((n) => n.status !== "open");
    const tip = "OSM Notes is the public, ODbL-licensed feedback feed any visitor can drop on the map. Use these to deduplicate or elevate the pipeline's findings.";
    host.innerHTML = `
      <p class="muted" title="${esc(tip)}">${esc(tip)}</p>
      <p class="muted">${open.length} open, ${closed.length} closed.</p>
      <ol class="threads">${notes.slice(0, 200).map(noteItem).join("")}</ol>
      ${notes.length > 200 ? `<p class="muted">Showing 200 of ${notes.length.toLocaleString()}.</p>` : ""}
    `;
  }

  function noteItem(n) {
    const comments = Array.isArray(n.comments) ? n.comments : [];
    const first = comments[0] || {};
    const ts = n.date_created || first.date || "";
    const status = n.status === "open" ? "open" : "closed";
    const author = first.user || "anonymous";
    const text = first.text || "";
    return `<li class="thread">
      <div class="th-head">
        <span class="th-author">${esc(author)}</span>
        <span class="badge badge-${status}">${esc(status)}</span>
        <span class="th-time">${esc(formatTimeAgo(ts))}</span>
        <span class="muted"> · ${comments.length} comment${comments.length === 1 ? "" : "s"}</span>
      </div>
      <div class="th-title">
        <a href="${esc(n.url || ("https://www.openstreetmap.org/note/" + n.id))}" target="_blank" rel="noopener">
          Note #${esc(n.id)}
        </a>
      </div>
      <div class="th-body">${esc(text)}</div>
    </li>`;
  }

  function newThread() {
    const title = prompt("Thread title (saved locally to this browser only)");
    if (!title) return;
    const body = prompt("Notes / context");
    const items = loadDiscuss();
    items.push({ title, body: body || "", author: "you", ts: new Date().toLocaleString() });
    saveDiscuss(items);
    discussTabState.tab = "local";
    renderDiscussPanel();
  }
  function clearDiscuss() {
    if (!confirm("Clear all private (local) discussion threads for this zone?\n\nThis only clears the local-board tab, not OSM Notes.")) return;
    saveDiscuss([]);
    renderDiscussPanel();
  }

  // --------------------------------------------------------------- formality panel
  const FORMALITY_DEFAULTS = {
    audience: "OSM community + SORTA stakeholders",
    tone: "Neutral, evidence-led",
    citations: true,
    glossary: true,
    cagis_credit: true,
  };
  function loadFormality() {
    try {
      const v = JSON.parse(localStorage.getItem(state.formalityKey) || "null");
      return v || { ...FORMALITY_DEFAULTS };
    } catch { return { ...FORMALITY_DEFAULTS }; }
  }
  function saveFormality(v) { localStorage.setItem(state.formalityKey, JSON.stringify(v)); }

  function renderFormalityPanel() {
    const body = $("#formalityBody");
    if (!body) return;
    const v = loadFormality();
    body.innerHTML = `
      <form class="formality-form" id="formalityForm">
        <label class="opt-row col"><span>Audience</span><input class="input" id="fmAudience" value="${esc(v.audience)}"></label>
        <label class="opt-row col"><span>Tone</span><input class="input" id="fmTone" value="${esc(v.tone)}"></label>
        <label class="opt-row"><input type="checkbox" id="fmCit" ${v.citations ? "checked" : ""}> <span>Include numbered citations</span></label>
        <label class="opt-row"><input type="checkbox" id="fmGlo" ${v.glossary ? "checked" : ""}> <span>Append glossary section</span></label>
        <label class="opt-row"><input type="checkbox" id="fmCAG" ${v.cagis_credit ? "checked" : ""}> <span>Include CAGIS Open Data Hub credit</span></label>
      </form>
    `;
  }
  function saveFormalityFromForm() {
    const v = {
      audience: $("#fmAudience")?.value || FORMALITY_DEFAULTS.audience,
      tone: $("#fmTone")?.value || FORMALITY_DEFAULTS.tone,
      citations: !!$("#fmCit")?.checked,
      glossary: !!$("#fmGlo")?.checked,
      cagis_credit: !!$("#fmCAG")?.checked,
    };
    saveFormality(v);
    toast("Formality saved");
  }
  function resetFormality() {
    saveFormality({ ...FORMALITY_DEFAULTS });
    renderFormalityPanel();
    toast("Formality reset to defaults");
  }

  // --------------------------------------------------------------- auth panel
  async function refreshAuth() {
    try {
      const s = await api("/api/auth/status");
      state.auth.authenticated = !!s.authenticated;
      state.auth.scope = s.scope || null;
    } catch {
      state.auth.authenticated = false;
    }
    const txt = $("#authText");
    if (txt) txt.textContent = state.auth.authenticated ? "Signed in" : "Sign in";
    const chip = $("#authChip");
    if (chip) chip.classList.toggle("connected", state.auth.authenticated);
  }

  function renderAuthPanel() {
    const body = $("#authBody");
    if (!body) return;
    if (state.auth.authenticated) {
      body.innerHTML = `
        <div class="auth-block">
          <div class="auth-status ok">
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none"><circle cx="9" cy="9" r="9" fill="#dcfce7"/><path d="M5 9l3 3 5-6" stroke="#16a34a" stroke-width="2" fill="none" stroke-linecap="round"/></svg>
            <span>Connected to OpenStreetMap. Ready to submit corrections.</span>
          </div>
          <p class="muted">Scope: <code>${esc(state.auth.scope || "?")}</code></p>
          <button class="btn btn-sm btn-danger" id="logoutBtn">Log out</button>
        </div>`;
      $("#logoutBtn")?.addEventListener("click", logout);
    } else {
      body.innerHTML = `
        <div class="auth-block">
          <p>Sign in with OpenStreetMap to submit corrections via API v0.6 (OAuth 2.0).</p>
          <ol class="auth-steps">
            <li>
              <strong>1. Authorize</strong> &middot; opens openstreetmap.org in a new tab.
              <div><button class="btn btn-brand btn-sm" id="authStartBtn">Authorize with OSM</button></div>
            </li>
            <li>
              <strong>2. Paste the code</strong> &middot; OSM will display a one-time code; paste it below.
              <div class="code-row">
                <input class="input" id="authCode" placeholder="Paste the authorization code" autocomplete="off">
                <button class="btn btn-brand btn-sm" id="authSubmitBtn" disabled>Submit</button>
              </div>
            </li>
          </ol>
        </div>`;
      $("#authStartBtn")?.addEventListener("click", startAuth);
      const code = $("#authCode");
      const sub = $("#authSubmitBtn");
      code?.addEventListener("input", () => { if (sub) sub.disabled = !code.value.trim(); });
      sub?.addEventListener("click", finishAuth);
    }
  }

  async function startAuth() {
    try {
      const data = await api("/api/auth/url", { method: "POST" });
      // Server now returns flow_id only; the PKCE verifier stays
      // server-side per RFC 7636 §1.
      state.authFlowId = data.flow_id;
      window.open(data.url, "_blank", "noopener");
      toast("OSM authorization opened");
      const sub = $("#authSubmitBtn"); if (sub) sub.disabled = false;
    } catch (e) {
      toast("Auth start failed: " + e.message, "error");
    }
  }
  async function finishAuth() {
    const code = $("#authCode")?.value.trim();
    if (!code) return;
    if (!state.authFlowId) { toast("Click Authorize first", "warn"); return; }
    try {
      await api("/api/auth/exchange", { method: "POST", body: { code, flow_id: state.authFlowId } });
      toast("Signed in to OSM");
      state.authFlowId = null;
      await refreshAuth();
      renderAuthPanel();
    } catch (e) {
      toast("Auth failed: " + e.message, "error");
    }
  }
  async function logout() {
    try {
      await api("/api/auth/logout", { method: "POST" });
      toast("Logged out");
      await refreshAuth();
      renderAuthPanel();
    } catch (e) {
      toast("Logout failed: " + e.message, "error");
    }
  }

  // --------------------------------------------------------------- reports
  async function generateReports() {
    if (!state.currentZone) return;
    const btn = $("#genReportsBtn");
    if (btn) btn.disabled = true;
    consoleLog("Generating reports…");
    try {
      const format = $("#reportFormat")?.value || "xlsx+html";
      const data = await api("/api/reports", { method: "POST", body: { zone: state.currentZone, format } });
      consoleLog(`Reports saved (${(data.files || []).length} file(s))`, "ok");
      toast("Reports generated");
      const open = $("#openDashBtn"); if (open) open.disabled = false;
    } catch (e) {
      consoleLog("Reports failed: " + e.message, "error");
      toast("Reports failed: " + e.message, "error");
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  // --------------------------------------------------------------- share summary (copy to clipboard)
  async function shareSummary() {
    if (!state.currentZone) return toast("Pick a zone first", "warn");
    const zoneName = (state.zones[state.currentZone] && state.zones[state.currentZone].name) || state.currentZone;
    try {
      const data = state.results || await api("/api/results/" + state.currentZone);
      const stats = (data && data.summary_stats) || {};
      const summary = [
        `OSM TIGER Audit — ${zoneName}`,
        `Date: ${new Date().toLocaleDateString()}`,
        ``,
        `Total ways: ${stats.total || 0}`,
        `Class AB (compound): ${stats.class_ab_count || 0}`,
        `Class A (false oneway): ${stats.class_a_count || 0}`,
        `Class B (multi-segment): ${stats.class_b_way_count || 0}`,
        `Gaps found: ${stats.gaps_found || 0}`,
        ``,
        `Generated by MetroNow TIGER Audit Pipeline`,
      ].join("\n");
      if (navigator.clipboard) {
        await navigator.clipboard.writeText(summary);
        toast("Summary copied to clipboard");
      } else {
        const subject = encodeURIComponent(`OSM TIGER Audit — ${zoneName}`);
        const body = encodeURIComponent(summary);
        window.open(`mailto:?subject=${subject}&body=${body}`);
      }
    } catch (e) {
      toast("Share failed: " + e.message, "error");
    }
  }

  // --------------------------------------------------------------- search (basic name + way-id filter)
  function wireSearch() {
    const input = $("#search");
    if (!input) return;
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") doSearch(input.value.trim());
      if (e.key === "Escape") { input.value = ""; doSearch(""); }
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "/" && document.activeElement !== input) { e.preventDefault(); input.focus(); }
    });
  }

  function doSearch(q) {
    if (!state.results) return;
    if (!q) { drawResults(state.results); return; }
    q = q.toLowerCase();
    const ways = state.results.all_ways.filter((w) => {
      const id = String(w.id || "");
      const name = (w.name_display || w.name || "").toLowerCase();
      return id.includes(q) || name.includes(q);
    });
    drawResults({ all_ways: ways, gaps: [] });
    if (ways.length) {
      const first = ways.find((w) => w.geometry && w.geometry.length);
      if (first) mapRef.fitBounds(first.geometry, { padding: [60, 60] });
    } else {
      toast("No matches", "warn");
    }
  }

  // --------------------------------------------------------------- wire everything up
  function wire() {
    $("#scanBtn")?.addEventListener("click", runScan);
    $("#exportCsvBtn")?.addEventListener("click", () => {
      window.open("/api/export/" + state.currentZone + "/csv", "_blank");
    });
    $("#clearScanBtn")?.addEventListener("click", () => {
      state.results = null; clearMap(); renderStats(null); renderClasses(null); setLastRun("—"); setReportsEnabled(false);
      toast("Cleared current scan view");
    });
    $("#genReportsBtn")?.addEventListener("click", generateReports);
    $("#openDashBtn")?.addEventListener("click", () => {
      window.open("/api/dashboard/" + state.currentZone, "_blank");
    });

    // dock
    $$(".dock-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const v = btn.dataset.view;
        if (v === "map") closeAllPanels();
        else openPanel(v);
      });
    });
    $$(".overlay-panel [data-close-panel]").forEach((b) => {
      b.addEventListener("click", () => closeAllPanels());
    });

    // results
    $("#resCsv")?.addEventListener("click", () => window.open("/api/export/" + state.currentZone + "/csv", "_blank"));
    $("#resJson")?.addEventListener("click", () => window.open("/api/export/" + state.currentZone + "/json", "_blank"));
    $("#resShare")?.addEventListener("click", shareSummary);

    // Phase 2c — CAGIS overlay toggle (Esri FeatureServer/26 via esri-leaflet)
    $("#cagisOverlayToggle")?.addEventListener("click", toggleCagisOverlay);

    // Phase 2c — Investigations filter buttons
    $$("#investFilterSeg .seg-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        investFilter = btn.dataset.v || "review";
        try { localStorage.setItem(INVEST_FILTER_KEY, investFilter); } catch {}
        $$("#investFilterSeg .seg-btn").forEach((b) => {
          b.setAttribute("aria-pressed", b.dataset.v === investFilter ? "true" : "false");
        });
        renderInvestigationsPanel();
      });
      // Sync the persisted choice on first paint.
      btn.setAttribute("aria-pressed", btn.dataset.v === investFilter ? "true" : "false");
    });

    // fix
    $("#loadFixesBtn")?.addEventListener("click", loadFixes);
    $("#dryRunBtn")?.addEventListener("click", () => submitFixes(true));
    $("#routeImpactBtn")?.addEventListener("click", runRouteImpact);
    $("#submitBtn")?.addEventListener("click", () => submitFixes(false));

    // history
    $("#histRefresh")?.addEventListener("click", renderHistoryPanel);
    $("#histClear")?.addEventListener("click", async () => {
      if (!confirm("Clear all activity history? This cannot be undone.")) return;
      try {
        await api("/api/history", { method: "DELETE" });
        toast("History cleared");
        renderHistoryPanel();
      } catch (e) {
        toast("Clear failed: " + e.message, "error");
      }
    });

    // discuss
    $("#newThreadBtn")?.addEventListener("click", newThread);
    $("#clearDiscussBtn")?.addEventListener("click", clearDiscuss);

    // formality
    $("#saveFormalityBtn")?.addEventListener("click", saveFormalityFromForm);
    $("#resetFormalityBtn")?.addEventListener("click", resetFormality);
    $("#openFormalityBtn")?.addEventListener("click", () => openPanel("formality"));

    // auth chip
    $("#authChip")?.addEventListener("click", () => openPanel("auth"));

    wireSearch();
  }

  // --------------------------------------------------------------- boot
  async function boot() {
    initMap();
    wire();
    await pingApi();
    try {
      await loadZones();
      fitToZoneBounds();
      await refreshAuth();
      await tryLoadExistingResults();
    } catch (e) {
      consoleShow(true);
      consoleLog("Init failed: " + e.message, "error");
      toast("Init failed: " + e.message, "error");
    }
  }

  // expose for atlas-extras.js to trigger redraw on weight change
  window.atlasRedraw = () => { if (state.results) drawResults(state.results); };
  window.atlasState = state;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
