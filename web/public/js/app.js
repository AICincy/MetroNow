const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

function esc(str) {
  const d = document.createElement("div");
  d.textContent = str == null ? "" : String(str);
  return d.innerHTML;
}

// ---- state ----
let authVerifier = null;
let currentZone = null;
let zoneData = {};
let pendingFixes = [];
let scanTimerInterval = null;

// ---- map ----
const canvasRenderer = L.canvas({ padding: 0.5, tolerance: 8 });
const map = L.map("map", { zoomControl: true, preferCanvas: true }).setView([39.20, -84.39], 12);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>',
  maxZoom: 19,
}).addTo(map);

const mapLayers = {
  ab: L.layerGroup().addTo(map),
  a: L.layerGroup().addTo(map),
  b: L.layerGroup().addTo(map),
};

const MAP_COLORS = { AB: "#dc2626", A: "#ea580c", B: "#2563eb", C: "#94a3b8" };
const MAP_WEIGHTS = { AB: 5, A: 4, B: 3, C: 2 };

function simplifyGeom(pts, tolerance) {
  if (pts.length <= 4) return pts;
  const sq = tolerance * tolerance;
  const keep = new Uint8Array(pts.length);
  keep[0] = 1;
  keep[pts.length - 1] = 1;
  const stack = [[0, pts.length - 1]];
  while (stack.length) {
    const [start, end] = stack.pop();
    let maxDist = 0, maxIdx = start;
    const dx = pts[end][0] - pts[start][0];
    const dy = pts[end][1] - pts[start][1];
    const lenSq = dx * dx + dy * dy;
    for (let i = start + 1; i < end; i++) {
      let d;
      if (lenSq === 0) {
        const ex = pts[i][0] - pts[start][0], ey = pts[i][1] - pts[start][1];
        d = ex * ex + ey * ey;
      } else {
        const t = Math.max(0, Math.min(1, ((pts[i][0] - pts[start][0]) * dx + (pts[i][1] - pts[start][1]) * dy) / lenSq));
        const px = pts[start][0] + t * dx - pts[i][0];
        const py = pts[start][1] + t * dy - pts[i][1];
        d = px * px + py * py;
      }
      if (d > maxDist) { maxDist = d; maxIdx = i; }
    }
    if (maxDist > sq) {
      keep[maxIdx] = 1;
      if (maxIdx - start > 1) stack.push([start, maxIdx]);
      if (end - maxIdx > 1) stack.push([maxIdx, end]);
    }
  }
  const out = [];
  for (let i = 0; i < pts.length; i++) if (keep[i]) out.push(pts[i]);
  return out;
}

function updateMapBounds(bbox) {
  if (!bbox) return;
  const [s, w, n, e] = bbox;
  map.fitBounds([[s, w], [n, e]], { padding: [20, 20] });
}

const CHUNK_SIZE = 150;
let currentUpdateId = 0;

function updateMapData(ways) {
  currentUpdateId++;
  Object.values(mapLayers).forEach((l) => l.clearLayers());
  const items = [];
  for (let i = 0; i < ways.length; i++) {
    const w = ways[i];
    if (!w.geometry || w.geometry.length < 2) continue;
    const cls = w.defect_class || "C";
    if (cls === "C") continue;
    items.push(w);
  }
  if (!items.length) {
    $("#mapEmpty").classList.remove("hidden");
    return;
  }
  $("#mapEmpty").classList.add("hidden");
  const updateId = currentUpdateId;
  processMapChunk(0, updateId, items);
}

function processMapChunk(start, updateId, items) {
  if (updateId !== currentUpdateId) return;
  const end = Math.min(start + CHUNK_SIZE, items.length);
  for (let i = start; i < end; i++) {
    const w = items[i];
    const cls = w.defect_class;
    const geom = simplifyGeom(w.geometry, 0.00005);
    const line = L.polyline(geom, {
      color: MAP_COLORS[cls],
      weight: MAP_WEIGHTS[cls],
      opacity: 0.85,
      renderer: canvasRenderer,
    });
    line.wayData = w;
    line.on("click", onPolylineClick);
    const group = cls === "AB" ? "ab" : cls === "A" ? "a" : "b";
    mapLayers[group].addLayer(line);
  }
  if (end < items.length) {
    setTimeout(() => processMapChunk(end, updateId, items), 0);
  }
}

function onPolylineClick(e) {
  const w = e.target.wayData;
  if (!w) return;
  const cls = w.defect_class || "?";
  const reviewHtml = w.review_status
    ? `<br><span class="review-badge ${reviewClass(w.review_status)}">${esc(w.review_status.replace("_", " "))}</span>`
    : "";
  L.popup()
    .setLatLng(e.latlng)
    .setContent(
      `<div class="defect-popup">` +
        `<strong>${esc(w.name_display || "Unnamed")}</strong>` +
        `<span class="popup-class ${cls.toLowerCase()}">${esc(cls)}</span><br>` +
        `Way <a href="https://www.openstreetmap.org/way/${encodeURIComponent(w.id)}" target="_blank">${esc(w.id)}</a><br>` +
        `${esc(w.highway || "?")} &middot; oneway=${esc(w.oneway || "no")}` +
        `${reviewHtml}` +
        `</div>`
    )
    .openOn(map);
}

function reviewClass(status) {
  if (!status) return "";
  if (status === "UNREVIEWED") return "unreviewed";
  if (status === "LIKELY_REVIEWED") return "likely-reviewed";
  return "inconclusive";
}

// Legend toggle
$$(".legend-item").forEach((el) => {
  el.addEventListener("click", () => {
    const cls = el.dataset.cls;
    const layer = mapLayers[cls];
    if (!layer) return;
    el.classList.toggle("off");
    if (el.classList.contains("off")) map.removeLayer(layer);
    else map.addLayer(layer);
  });
});

// Map toggle
$("#mapToggle").addEventListener("click", () => {
  const mc = $("#mapContainer");
  mc.classList.toggle("collapsed");
  setTimeout(() => map.invalidateSize(), 350);
});

// ---- tabs ----
$$(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    $$(".tab-btn").forEach((b) => b.classList.remove("active"));
    $$(".tab-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $(`#tab-${btn.dataset.tab}`).classList.add("active");
    if (btn.dataset.tab === "results") loadResults();
    if (btn.dataset.tab === "history") loadHistory();
  });
});

// ---- toast ----
function toast(msg, type = "success") {
  const el = $("#toast");
  el.textContent = msg;
  el.className = `toast ${type} show`;
  setTimeout(() => el.classList.remove("show"), 3500);
}

// ---- log ----
function log(msg, cls = "") {
  const area = $("#logArea");
  const line = document.createElement("span");
  const ts = new Date().toLocaleTimeString();
  line.innerHTML = `<span class="ts">[${ts}]</span> `;
  const content = document.createElement("span");
  if (cls) content.className = cls;
  content.textContent = msg;
  line.appendChild(content);
  line.appendChild(document.createTextNode("\n"));
  area.appendChild(line);
  area.scrollTop = area.scrollHeight;
}

$("#clearLogBtn").addEventListener("click", () => {
  $("#logArea").innerHTML = "";
  log("Log cleared.", "info");
});

// ---- api ----
async function api(url, opts = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

// ---- auth ----
async function checkAuth() {
  try {
    const data = await api("/api/auth/status");
    const badge = $("#authBadge");
    if (data.authenticated) {
      badge.textContent = "Connected";
      badge.className = "badge badge-ok";
      $("#authLoggedIn").classList.remove("hidden");
      $("#authFlow").classList.add("hidden");
    } else {
      badge.textContent = "Not connected";
      badge.className = "badge badge-warn";
      $("#authLoggedIn").classList.add("hidden");
      $("#authFlow").classList.remove("hidden");
    }
  } catch {}
}

$("#authStartBtn").addEventListener("click", async () => {
  try {
    $("#authStartBtn").disabled = true;
    const data = await api("/api/auth/url", { method: "POST" });
    authVerifier = data.verifier;
    window.open(data.url, "_blank");
    $("#authSubmitBtn").disabled = false;
    $("#authCode").focus();
    toast("OSM authorization page opened");
  } catch (e) {
    toast(e.message, "error");
  } finally {
    $("#authStartBtn").disabled = false;
  }
});

$("#authSubmitBtn").addEventListener("click", async () => {
  const code = $("#authCode").value.trim();
  if (!code || !authVerifier) return;
  try {
    $("#authSubmitBtn").disabled = true;
    await api("/api/auth/exchange", {
      method: "POST",
      body: { code, verifier: authVerifier },
    });
    toast("Authentication successful");
    authVerifier = null;
    $("#authCode").value = "";
    checkAuth();
  } catch (e) {
    toast(e.message, "error");
  } finally {
    $("#authSubmitBtn").disabled = false;
  }
});

$("#logoutBtn").addEventListener("click", async () => {
  try {
    await api("/api/auth/logout", { method: "POST" });
    toast("Logged out");
    checkAuth();
  } catch (e) {
    toast(e.message, "error");
  }
});

// ---- zones ----
async function loadZones() {
  try {
    const data = await api("/api/zones");
    zoneData = data.zones;
    const sel = $("#zoneSelect");
    sel.innerHTML = "";
    data.keys.forEach((k) => {
      const opt = document.createElement("option");
      opt.value = k;
      opt.textContent = data.zones[k].name;
      if (k === data.default) opt.selected = true;
      sel.appendChild(opt);
    });
    currentZone = data.default;
    updateZoneInfo();
    updateMapBounds(zoneData[currentZone]?.bbox);
    sel.addEventListener("change", () => {
      currentZone = sel.value;
      updateZoneInfo();
      updateMapBounds(zoneData[currentZone]?.bbox);
    });

    if ("requestIdleCallback" in window) {
      requestIdleCallback(() => tryLoadExistingResults());
    } else {
      setTimeout(tryLoadExistingResults, 100);
    }
  } catch (e) {
    log("Failed to load zones: " + e.message, "err");
  }
}

function updateZoneInfo() {
  const z = zoneData[currentZone];
  if (z) {
    $("#zoneDescription").textContent = z.description || z.name;
  }
}

async function tryLoadExistingResults() {
  try {
    const data = await api("/api/results/" + currentZone);
    if (data.all_ways) {
      updateMapData(data.all_ways);
      renderStats(data.summary_stats || {});
      $("#statsCard").classList.remove("hidden");
      $("#reportsBtn").disabled = false;
      $("#dashboardBtn").disabled = false;
      $("#exportCSVBtn").disabled = false;
      log("Loaded existing scan results for " + zoneName(currentZone), "info");
    }
  } catch {}
}

// ---- scan ----
$("#scanBtn").addEventListener("click", async () => {
  const zone = $("#zoneSelect").value;
  const skipHistory = $("#skipHistory").checked;

  $("#scanBtn").disabled = true;
  $("#scanStatus").classList.remove("hidden");
  $("#scanStatusText").textContent = "Querying Overpass API...";

  let elapsed = 0;
  $("#scanTimer").textContent = "0s";
  scanTimerInterval = setInterval(() => {
    elapsed++;
    const min = Math.floor(elapsed / 60);
    const sec = elapsed % 60;
    $("#scanTimer").textContent = min > 0 ? `${min}m ${sec}s` : `${sec}s`;

    if (elapsed === 5) $("#scanStatusText").textContent = "Fetching way data...";
    if (elapsed === 15) $("#scanStatusText").textContent = "Classifying defects...";
    if (elapsed === 30 && !skipHistory) $("#scanStatusText").textContent = "Analyzing history...";
  }, 1000);

  log("Starting scan for " + zoneName(zone) + "...", "info");

  try {
    const data = await api("/api/scan", {
      method: "POST",
      body: { zone, skip_history: skipHistory },
    });

    clearInterval(scanTimerInterval);
    $("#scanStatusText").textContent = "Scan complete!";
    setTimeout(() => $("#scanStatus").classList.add("hidden"), 2000);

    log("Scan complete.", "ok");
    renderStats(data.stats);
    $("#reportsBtn").disabled = false;
    $("#dashboardBtn").disabled = false;
    $("#exportCSVBtn").disabled = false;
    toast("Scan finished — " + (data.stats.total || 0) + " ways analyzed");

    const results = await api("/api/results/" + zone);
    if (results.all_ways) updateMapData(results.all_ways);
  } catch (e) {
    clearInterval(scanTimerInterval);
    $("#scanStatusText").textContent = "Scan failed";
    log("Scan failed: " + e.message, "err");
    toast("Scan failed", "error");
  } finally {
    $("#scanBtn").disabled = false;
  }
});

function renderStats(stats) {
  const grid = $("#statsGrid");
  grid.innerHTML = "";
  const items = [
    { label: "Total Ways", value: stats.total || 0, cls: "total" },
    { label: "Residential", value: stats.residential || 0, cls: "" },
    { label: "Class AB", value: stats.class_ab_count || 0, cls: "ab" },
    { label: "Class A", value: stats.class_a_count || 0, cls: "a" },
    { label: "Class B", value: stats.class_b_way_count || 0, cls: "b" },
    { label: "Gaps Found", value: stats.gaps_found || 0, cls: "gaps" },
  ];
  items.forEach((it) => {
    const box = document.createElement("div");
    box.className = `stat-box ${it.cls}`;
    box.innerHTML =
      `<div class="stat-value">${Number(it.value).toLocaleString()}</div>` +
      `<div class="stat-label">${it.label}</div>`;
    grid.appendChild(box);
  });
  $("#statsCard").classList.remove("hidden");
  $("#scanTimestamp").textContent = new Date().toLocaleString();
}

// ---- reports ----
$("#reportsBtn").addEventListener("click", async () => {
  const zone = $("#zoneSelect").value;
  $("#reportsBtn").disabled = true;
  log("Generating reports...", "info");
  try {
    const data = await api("/api/reports", {
      method: "POST",
      body: { zone },
    });
    log("Reports saved:", "ok");
    (data.files || []).forEach((f) => log("  " + f));
    toast("Reports generated");
    $("#dashboardBtn").disabled = false;
  } catch (e) {
    log("Report generation failed: " + e.message, "err");
    toast("Reports failed", "error");
  } finally {
    $("#reportsBtn").disabled = false;
  }
});

$("#dashboardBtn").addEventListener("click", () => {
  window.open("/api/dashboard/" + $("#zoneSelect").value, "_blank");
});

// ---- export ----
$("#exportCSVBtn").addEventListener("click", () => {
  window.open("/api/export/" + $("#zoneSelect").value + "/csv");
  toast("CSV download started");
});

$("#resultExportCSV").addEventListener("click", () => {
  window.open("/api/export/" + $("#zoneSelect").value + "/csv");
  toast("CSV download started");
});

$("#resultExportJSON").addEventListener("click", () => {
  window.open("/api/export/" + $("#zoneSelect").value + "/json");
  toast("JSON download started");
});

$("#resultShare").addEventListener("click", async () => {
  const zone = $("#zoneSelect").value;
  const zoneName = zoneData[zone]?.name || zone;
  try {
    const data = await api("/api/results/" + zone);
    const stats = data.summary_stats || {};
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
});

// ---- results tab ----
async function loadResults() {
  const zone = $("#zoneSelect").value;
  try {
    const data = await api("/api/results/" + zone);
    const stats = data.summary_stats || {};
    renderResultsStats(stats);
    renderTable("#tableAB", data.class_ab || []);
    renderTable("#tableA", data.class_a_only || []);
  } catch {
    $("#resultsStats").innerHTML =
      '<p class="muted" style="padding:8px;">No results yet. Run a scan first.</p>';
  }
}

function renderResultsStats(stats) {
  const grid = $("#resultsStats");
  grid.innerHTML = "";
  const items = [
    { label: "Total", value: stats.total || 0, cls: "total" },
    { label: "Class AB", value: stats.class_ab_count || 0, cls: "ab" },
    { label: "Class A", value: stats.class_a_count || 0, cls: "a" },
    { label: "Class B", value: stats.class_b_way_count || 0, cls: "b" },
    { label: "Gaps", value: stats.gaps_found || 0, cls: "gaps" },
  ];
  items.forEach((it) => {
    const box = document.createElement("div");
    box.className = `stat-box ${it.cls}`;
    box.innerHTML =
      `<div class="stat-value">${Number(it.value).toLocaleString()}</div>` +
      `<div class="stat-label">${it.label}</div>`;
    grid.appendChild(box);
  });
}

function reviewBadge(status) {
  if (!status) return "";
  const cls = reviewClass(status);
  return `<span class="review-badge ${cls}">${esc(status.replace("_", " "))}</span>`;
}

function renderTable(sel, ways) {
  const container = $(sel);
  if (!ways || ways.length === 0) {
    container.innerHTML = '<p class="muted" style="padding:4px 0;">None found.</p>';
    return;
  }
  const hasReview = ways.some((w) => w.review_status);
  const rows = ways.slice(0, 100);
  let html =
    '<table class="data-table"><thead><tr>' +
    "<th>Way ID</th><th>Street</th><th>Oneway</th><th>Highway</th>" +
    (hasReview ? "<th>Review</th>" : "") +
    "</tr></thead><tbody>";
  rows.forEach((w) => {
    const wayId = w.id || "?";
    html +=
      "<tr>" +
      `<td><a href="https://www.openstreetmap.org/way/${encodeURIComponent(wayId)}" target="_blank">${esc(wayId)}</a></td>` +
      `<td>${esc(w.name_display || w.tiger_name_base || "—")}</td>` +
      `<td>${esc(w.oneway || "—")}</td>` +
      `<td>${esc(w.highway || "—")}</td>` +
      (hasReview ? `<td>${reviewBadge(w.review_status)}</td>` : "") +
      "</tr>";
  });
  html += "</tbody></table>";
  if (ways.length > 100)
    html += `<p class="table-count">Showing 100 of ${ways.length}</p>`;
  container.innerHTML = html;
}

// ---- fix tab ----
$("#loadFixesBtn").addEventListener("click", async () => {
  const zone = $("#zoneSelect").value;
  $("#loadFixesBtn").disabled = true;
  try {
    const data = await api("/api/review/" + zone);
    pendingFixes = data.fixes || [];
    $("#fixCount").textContent = `${data.count} fixable defect(s) found`;
    renderFixTable(pendingFixes);
    if (pendingFixes.length > 0) {
      $("#fixActions").classList.remove("hidden");
    }
  } catch (e) {
    $("#fixCount").textContent = e.message;
    pendingFixes = [];
  } finally {
    $("#loadFixesBtn").disabled = false;
  }
});

function renderFixTable(fixes) {
  const container = $("#fixTable");
  if (!fixes.length) {
    container.innerHTML = '<p class="muted">No fixable defects in scan results.</p>';
    return;
  }
  let html =
    '<table class="data-table"><thead><tr>' +
    '<th><input type="checkbox" id="fixSelectAll" checked /></th>' +
    "<th>Way ID</th><th>Street</th><th>Class</th><th>Proposed Fix</th>" +
    "</tr></thead><tbody>";
  const showCount = Math.min(fixes.length, 200);
  for (let i = 0; i < showCount; i++) {
    const f = fixes[i];
    const w = f.way;
    const wayId = w.id || "?";
    html +=
      "<tr>" +
      `<td><input type="checkbox" class="fix-check" data-idx="${i}" checked /></td>` +
      `<td><a href="https://www.openstreetmap.org/way/${encodeURIComponent(wayId)}" target="_blank">${esc(wayId)}</a></td>` +
      `<td>${esc(w.name_display || "—")}</td>` +
      `<td>${esc(w.defect_class || "?")}</td>` +
      `<td>${esc(f.fix.description)}</td>` +
      "</tr>";
  }
  html += "</tbody></table>";
  if (fixes.length > showCount)
    html += `<p class="table-count">Showing ${showCount} of ${fixes.length}. All ${fixes.length} will be included when submitting.</p>`;
  container.innerHTML = html;

  $("#fixSelectAll").addEventListener("change", (e) => {
    $$(".fix-check").forEach((cb) => (cb.checked = e.target.checked));
  });
}

function getSelectedFixes() {
  const selectAll = document.getElementById("fixSelectAll");
  if (selectAll && selectAll.checked && pendingFixes.length > $$(".fix-check").length) {
    return pendingFixes.map((f) => f.fix);
  }
  const selected = [];
  $$(".fix-check").forEach((cb) => {
    if (cb.checked) selected.push(pendingFixes[parseInt(cb.dataset.idx)].fix);
  });
  return selected;
}

$("#dryRunBtn").addEventListener("click", async () => {
  const fixes = getSelectedFixes();
  if (!fixes.length) return toast("No fixes selected", "error");
  const zone = $("#zoneSelect").value;
  $("#dryRunBtn").disabled = true;
  try {
    const data = await api("/api/fix", {
      method: "POST",
      body: { zone, fixes, dry_run: true },
    });
    $("#fixResult").innerHTML =
      `<p class="muted"><strong>[DRY RUN]</strong> Would submit <strong>${data.fixes_applied}</strong> fix(es). No changes made.</p>`;
    toast("Dry run complete");
  } catch (e) {
    $("#fixResult").innerHTML = `<p style="color:var(--danger);">${e.message}</p>`;
  } finally {
    $("#dryRunBtn").disabled = false;
  }
});

$("#submitFixesBtn").addEventListener("click", async () => {
  const fixes = getSelectedFixes();
  if (!fixes.length) return toast("No fixes selected", "error");
  if (!confirm(`Submit ${fixes.length} correction(s) to OpenStreetMap?\n\nThis will modify live map data and cannot be undone.`))
    return;
  const zone = $("#zoneSelect").value;
  $("#submitFixesBtn").disabled = true;
  try {
    const data = await api("/api/fix", {
      method: "POST",
      body: { zone, fixes, dry_run: false },
    });
    const ids = (data.changeset_ids || [])
      .map((id) => `<a href="https://www.openstreetmap.org/changeset/${id}" target="_blank">${id}</a>`)
      .join(", ");
    let html = `<p style="color:var(--success);font-weight:600;">Submitted ${data.fixes_applied} fix(es).</p>`;
    if (ids) html += `<p>Changeset(s): ${ids}</p>`;
    if (data.errors && data.errors.length)
      html += `<p style="color:var(--danger);">${data.errors.length} error(s): ${data.errors.join("; ")}</p>`;
    $("#fixResult").innerHTML = html;
    toast("Corrections submitted to OSM");
  } catch (e) {
    $("#fixResult").innerHTML = `<p style="color:var(--danger);">${e.message}</p>`;
    toast("Submission failed", "error");
  } finally {
    $("#submitFixesBtn").disabled = false;
  }
});

// ---- history tab ----
async function loadHistory() {
  try {
    const entries = await api("/api/history");
    renderHistory(entries);
  } catch {
    $("#historyList").innerHTML = '<p class="history-empty">Could not load history.</p>';
  }
}

function zoneName(key) {
  return (zoneData[key] && zoneData[key].name) || (key || "").replace(/_/g, " ");
}

function renderHistory(entries) {
  const container = $("#historyList");
  if (!entries || entries.length === 0) {
    container.innerHTML = '<p class="history-empty">No actions recorded yet. Run a scan to get started.</p>';
    return;
  }

  const icons = {
    scan: "\u{1F50D}",
    report: "\u{1F4CA}",
    submit: "\u{2705}",
    dry_run: "\u{1F9EA}",
    auth_login: "\u{1F511}",
    auth_logout: "\u{1F6AA}",
  };

  const labels = {
    scan: "Scan completed",
    report: "Reports generated",
    submit: "Corrections submitted",
    dry_run: "Dry run",
    auth_login: "Authenticated",
    auth_logout: "Logged out",
  };

  container.innerHTML = entries.map((e) => {
    const icon = icons[e.action] || "\u{2699}";
    const iconCls = e.action.startsWith("auth") ? "auth" : e.action;
    const label = labels[e.action] || e.action;
    const time = formatTimeAgo(e.timestamp);
    const fullTime = new Date(e.timestamp).toLocaleString();

    let detail = "";
    if (e.action === "scan" && e.stats) {
      detail = `${esc(zoneName(e.zone))} &middot; ${Number(e.stats.total) || 0} ways, ${Number(e.stats.class_ab_count) || 0} AB, ${Number(e.stats.class_a_count) || 0} A`;
    } else if (e.action === "submit") {
      const ids = (e.changeset_ids || [])
        .map((id) => `<a href="https://www.openstreetmap.org/changeset/${encodeURIComponent(id)}" target="_blank">#${esc(id)}</a>`)
        .join(", ");
      detail = `${Number(e.fixes_applied) || 0} fix(es) applied` + (ids ? ` &middot; Changesets: ${ids}` : "");
      if (e.errors) detail += ` &middot; ${Number(e.errors)} error(s)`;
    } else if (e.action === "dry_run") {
      detail = `${Number(e.fixes_applied) || 0} fix(es) previewed`;
    } else if (e.action === "report") {
      detail = esc(zoneName(e.zone));
    } else if (e.zone) {
      detail = esc(zoneName(e.zone));
    }

    return (
      `<div class="history-entry">` +
      `<div class="history-icon ${iconCls}">${icon}</div>` +
      `<div class="history-body">` +
      `<div class="history-title">${label}</div>` +
      (detail ? `<div class="history-detail">${detail}</div>` : "") +
      `</div>` +
      `<div class="history-time" title="${fullTime}">${time}</div>` +
      `</div>`
    );
  }).join("");
}

function formatTimeAgo(ts) {
  const diff = Date.now() - new Date(ts).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(ts).toLocaleDateString();
}

$("#refreshHistoryBtn").addEventListener("click", loadHistory);

// ---- init ----
checkAuth();
loadZones();
