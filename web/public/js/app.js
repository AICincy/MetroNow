const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// ---- state ----
let authVerifier = null;
let currentZone = null;

// ---- tabs ----
$$(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    $$(".tab-btn").forEach((b) => b.classList.remove("active"));
    $$(".tab-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $(`#tab-${btn.dataset.tab}`).classList.add("active");
  });
});

// ---- toast ----
function toast(msg, type = "success") {
  const el = $("#toast");
  el.textContent = msg;
  el.className = `toast ${type} show`;
  setTimeout(() => el.classList.remove("show"), 3000);
}

// ---- log ----
function log(msg, cls = "") {
  const area = $("#logArea");
  const span = document.createElement("span");
  if (cls) span.className = cls;
  span.textContent = msg + "\n";
  area.appendChild(span);
  area.scrollTop = area.scrollHeight;
}

// ---- api helpers ----
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
      badge.className = "auth-badge ok";
      $("#authLoggedIn").classList.remove("hidden");
      $("#authFlow").classList.add("hidden");
    } else {
      badge.textContent = "Not connected";
      badge.className = "auth-badge none";
      $("#authLoggedIn").classList.add("hidden");
      $("#authFlow").classList.remove("hidden");
    }
  } catch {
    // ignore
  }
}

$("#authStartBtn").addEventListener("click", async () => {
  try {
    $("#authStartBtn").disabled = true;
    const data = await api("/api/auth/url", { method: "POST" });
    authVerifier = data.verifier;
    window.open(data.url, "_blank");
    $("#authSubmitBtn").disabled = false;
    $("#authCode").focus();
    toast("OSM authorization page opened in new tab");
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
    sel.addEventListener("change", () => {
      currentZone = sel.value;
    });
  } catch (e) {
    log("Failed to load zones: " + e.message, "err");
  }
}

// ---- scan ----
$("#scanBtn").addEventListener("click", async () => {
  const zone = $("#zoneSelect").value;
  const skipHistory = $("#skipHistory").checked;

  $("#scanBtn").disabled = true;
  $("#scanProgress").classList.remove("hidden");
  log("Starting scan for " + zone + "...", "info");

  try {
    const data = await api("/api/scan", {
      method: "POST",
      body: { zone, skip_history: skipHistory },
    });

    log("Scan complete.", "ok");
    renderStats(data.stats);
    $("#reportsBtn").disabled = false;
    $("#dashboardBtn").disabled = false;
    toast("Scan finished");
  } catch (e) {
    log("Scan failed: " + e.message, "err");
    toast("Scan failed", "error");
  } finally {
    $("#scanBtn").disabled = false;
    $("#scanProgress").classList.add("hidden");
  }
});

function renderStats(stats) {
  const grid = $("#statsGrid");
  grid.innerHTML = "";
  const items = [
    { label: "Total", value: stats.total || 0, cls: "total" },
    { label: "Residential", value: stats.residential || 0, cls: "" },
    { label: "Class AB", value: stats.class_ab_count || 0, cls: "ab" },
    { label: "Class A", value: stats.class_a_count || 0, cls: "a" },
    { label: "Class B", value: stats.class_b_way_count || 0, cls: "b" },
    { label: "Gaps", value: stats.gaps_found || 0, cls: "" },
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
  const zone = $("#zoneSelect").value;
  window.open("/api/dashboard/" + zone, "_blank");
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
      '<p style="color:var(--text-secondary);padding:8px;">No results yet. Run a scan first.</p>';
  }
}

function renderResultsStats(stats) {
  const grid = $("#resultsStats");
  grid.innerHTML = "";
  const items = [
    { label: "Total", value: stats.total || 0, cls: "total" },
    { label: "Class AB", value: stats.class_ab_count || 0, cls: "ab" },
    { label: "Class A", value: stats.class_a_count || 0, cls: "a" },
    { label: "Class B Ways", value: stats.class_b_way_count || 0, cls: "b" },
    { label: "Gaps", value: stats.gaps_found || 0, cls: "" },
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
  const colors = {
    UNREVIEWED: "var(--danger, #e53935)",
    LIKELY_REVIEWED: "var(--success, #43a047)",
    INCONCLUSIVE: "var(--warning, #f9a825)",
  };
  const color = colors[status] || "var(--text-secondary)";
  return `<span style="display:inline-block;padding:2px 6px;border-radius:3px;font-size:11px;font-weight:600;background:${color}20;color:${color};">${status.replace("_", " ")}</span>`;
}

function renderTable(sel, ways) {
  const container = $(sel);
  if (!ways || ways.length === 0) {
    container.innerHTML =
      '<p style="color:var(--text-secondary);font-size:14px;padding:4px 0;">None found.</p>';
    return;
  }
  const hasReview = ways.some((w) => w.review_status);
  const rows = ways.slice(0, 50);
  const th = "text-align:left;padding:6px 8px;border-bottom:2px solid var(--border);";
  let html =
    '<table style="width:100%;border-collapse:collapse;font-size:13px;">' +
    "<thead><tr>" +
    `<th style="${th}">Way ID</th>` +
    `<th style="${th}">Street</th>` +
    `<th style="${th}">Oneway</th>` +
    `<th style="${th}">Highway</th>` +
    (hasReview ? `<th style="${th}">Review</th>` : "") +
    "</tr></thead><tbody>";
  const td = "padding:5px 8px;border-bottom:1px solid var(--border);";
  rows.forEach((w) => {
    const wayId = w.id || "?";
    html +=
      "<tr>" +
      `<td style="${td}"><a href="https://www.openstreetmap.org/way/${wayId}" target="_blank" style="color:var(--accent);">${wayId}</a></td>` +
      `<td style="${td}">${w.name_display || w.tiger_name_base || "—"}</td>` +
      `<td style="${td}">${w.oneway || "—"}</td>` +
      `<td style="${td}">${w.highway || "—"}</td>` +
      (hasReview ? `<td style="${td}">${reviewBadge(w.review_status)}</td>` : "") +
      "</tr>";
  });
  html += "</tbody></table>";
  if (ways.length > 50)
    html += `<p style="color:var(--text-secondary);font-size:13px;margin-top:8px;">Showing 50 of ${ways.length}</p>`;
  container.innerHTML = html;
}

// Reload results when switching to results tab
$$(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (btn.dataset.tab === "results") loadResults();
  });
});

// ---- init ----
checkAuth();
loadZones();
