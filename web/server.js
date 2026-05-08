const express = require("express");
const { execFile } = require("child_process");
const path = require("path");
const fs = require("fs");
const helmet = require("helmet");
const cors = require("cors");
const rateLimit = require("express-rate-limit");

const app = express();
const PORT = 3000;

app.use(helmet({ contentSecurityPolicy: false }));
app.use(cors({ origin: "http://localhost:3000" }));
app.use(rateLimit({ windowMs: 60000, max: 100, standardHeaders: true }));

const PYTHON = (() => {
  const { execFileSync } = require("child_process");
  for (const cmd of ["python3", "python"]) {
    try {
      const p = execFileSync(process.platform === "win32" ? "where" : "which", [cmd], {
        encoding: "utf-8",
        timeout: 5000,
      }).trim().split(/\r?\n/)[0];
      if (p) return p;
    } catch {}
  }
  return process.platform === "win32" ? "python.exe" : "python3";
})();
const OSM_PKG = path.resolve(__dirname, "..", "src");
const CONFIG_DIR = path.join(process.env.USERPROFILE || process.env.HOME || "", ".config", "osm");
const TOKEN_PATH = path.join(CONFIG_DIR, "token.json");
const PROJECT_ROOT = path.resolve(__dirname, "..");
const HISTORY_PATH = path.join(PROJECT_ROOT, "edit-history.json");

function loadHistory() {
  try {
    if (fs.existsSync(HISTORY_PATH))
      return JSON.parse(fs.readFileSync(HISTORY_PATH, "utf-8"));
  } catch {}
  return [];
}

function appendHistory(entry) {
  const history = loadHistory();
  history.unshift({
    id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
    timestamp: new Date().toISOString(),
    ...entry,
  });
  if (history.length > 500) history.length = 500;
  try {
    fs.writeFileSync(HISTORY_PATH, JSON.stringify(history, null, 2));
  } catch {}
}

app.use(express.json());
app.use(express.static(path.join(__dirname, "public")));

const SAFE_ZONE_RE = /^[a-z0-9-]+$/;
function validateZone(zone, res) {
  if (!zone || !SAFE_ZONE_RE.test(zone)) {
    res.status(400).json({ error: "Invalid zone identifier" });
    return false;
  }
  return true;
}

function safeError(e) {
  const msg = (e && e.message) || "Unknown error";
  const lines = msg.split(/\r?\n/).filter((l) => l.trim());
  const last = lines[lines.length - 1] || msg;
  return last.replace(/File ".*?",/g, "").trim();
}

function runPython(script) {
  return new Promise((resolve, reject) => {
    execFile(
      PYTHON,
      ["-c", script],
      { cwd: PROJECT_ROOT, timeout: 300000 },
      (err, stdout, stderr) => {
        if (err) return reject(new Error(stderr || err.message));
        resolve(stdout);
      }
    );
  });
}

// ---- fix validation ----

function validateFix(fix) {
  if (!fix || typeof fix !== "object") return false;
  if (typeof fix.element_id !== "number" || fix.element_id <= 0) return false;
  if (!["remove_tag", "modify_tag"].includes(fix.action)) return false;
  if (fix.action === "remove_tag" && typeof fix.tag !== "string") return false;
  if (fix.action === "modify_tag" && (typeof fix.changes !== "object" || fix.changes === null)) return false;
  return true;
}

// ---- concurrency control ----

let scanInProgress = false;

// ---- auth ----

app.get("/api/auth/status", (_req, res) => {
  try {
    if (fs.existsSync(TOKEN_PATH)) {
      const token = JSON.parse(fs.readFileSync(TOKEN_PATH, "utf-8"));
      res.json({
        authenticated: true,
        token_type: token.token_type || "?",
        scope: token.scope || "?",
      });
    } else {
      res.json({ authenticated: false });
    }
  } catch {
    res.json({ authenticated: false });
  }
});

app.post("/api/auth/url", async (_req, res) => {
  try {
    const pyCode = [
      "import json, sys",
      "sys.path.insert(0, " + JSON.stringify(OSM_PKG) + ")",
      "from osm.auth import build_auth_url",
      "url, verifier, state = build_auth_url()",
      'print(json.dumps({"url": url, "verifier": verifier, "state": state}))',
    ].join("\n");
    const out = await runPython(pyCode);
    res.json(JSON.parse(out.trim()));
  } catch (e) {
    res.status(500).json({ error: safeError(e) });
  }
});

app.post("/api/auth/exchange", async (req, res) => {
  const { code, verifier } = req.body;
  if (!code || !verifier)
    return res.status(400).json({ error: "Missing code or verifier" });
  try {
    const pyCode = [
      "import json, sys",
      "sys.path.insert(0, " + JSON.stringify(OSM_PKG) + ")",
      "from osm.auth import exchange_code",
      "_args = json.loads(" + JSON.stringify(JSON.stringify({ code, verifier })) + ")",
      "token = exchange_code(_args['code'], _args['verifier'])",
      'print(json.dumps({"success": True, "scope": token.get("scope", "")}))',
    ].join("\n");
    const out = await runPython(pyCode);
    res.json(JSON.parse(out.trim()));
    try { appendHistory({ action: "auth_login" }); } catch {}
  } catch (e) {
    res.status(500).json({ error: safeError(e) });
  }
});

app.post("/api/auth/logout", (_req, res) => {
  try {
    if (fs.existsSync(TOKEN_PATH)) fs.unlinkSync(TOKEN_PATH);
    res.json({ success: true });
    try { appendHistory({ action: "auth_logout" }); } catch {}
  } catch (e) {
    res.status(500).json({ error: safeError(e) });
  }
});

// ---- zones ----

app.get("/api/zones", async (_req, res) => {
  try {
    const pyCode = [
      "import json, sys",
      "sys.path.insert(0, " + JSON.stringify(OSM_PKG) + ")",
      "from osm.zones import ZONES, ZONE_KEYS, DEFAULT_ZONE",
      "out = {'zones': {}, 'keys': ZONE_KEYS, 'default': DEFAULT_ZONE}",
      "for k in ZONE_KEYS:",
      "    z = ZONES[k]",
      "    out['zones'][k] = {'name': z['name'], 'bbox': z['bbox'], 'description': z.get('description', '')}",
      "print(json.dumps(out))",
    ].join("\n");
    const out = await runPython(pyCode);
    res.json(JSON.parse(out.trim()));
  } catch (e) {
    res.status(500).json({ error: safeError(e) });
  }
});

// ---- scan ----

app.post("/api/scan", async (req, res) => {
  if (scanInProgress)
    return res.status(409).json({ error: "A scan is already in progress" });
  const zone = req.body.zone || "blue-ash-montgomery";
  if (!validateZone(zone, res)) return;
  const skipHistory = req.body.skip_history === true;
  const withConflation = req.body.with_conflation === true;
  scanInProgress = true;
  try {
    const pyCode = [
      "import json, sys, os",
      "sys.path.insert(0, " + JSON.stringify(OSM_PKG) + ")",
      "from pathlib import Path",
      "sys.stdout = open(os.devnull, 'w')",
      "from osm.fetch import fetch_overpass",
      "from osm.classify import classify",
      "from osm.history_filter import filter_by_history",
      "zone_key = " + JSON.stringify(zone),
      "out_dir = Path(" + JSON.stringify(PROJECT_ROOT) + ") / f'osm-audit-{zone_key}'",
      "raw = fetch_overpass(zone_key, out_dir)",
      "classified = classify(raw)",
      "skip = " + (skipHistory ? "True" : "False"),
      "if not skip:",
      "    filter_by_history(classified['all_ways'], skip_history=False)",
      "with_conflation = " + (withConflation ? "True" : "False"),
      "if with_conflation:",
      "    try:",
      "        from osm.conflate import SHAPELY_AVAILABLE, build_index, conflate, load_cagis_for_zone",
      "        if SHAPELY_AVAILABLE:",
      "            cagis = load_cagis_for_zone(zone_key)",
      "            idx = build_index(cagis)",
      "            conflate(classified['all_ways'], idx)",
      "            matched = sum(1 for w in classified['all_ways'] if w.get('cagis_match'))",
      "            classified['summary_stats']['cagis_features'] = len(cagis)",
      "            classified['summary_stats']['cagis_matched'] = matched",
      "    except Exception as exc:",
      "        classified['summary_stats']['cagis_error'] = str(exc)",
      "    try:",
      "        from osm.tiger2024 import (",
      "            SHAPELY_AVAILABLE as _T_SHP, REVIEW_CONFIDENCE as _T_REV,",
      "            build_tiger_index, conflate_with_tiger,",
      "            features_in_bbox, load_tiger2024_features,",
      "        )",
      "        from osm.zones import ZONES as _T_ZONES",
      "        if _T_SHP:",
      "            tiger_all = load_tiger2024_features()",
      "            if tiger_all:",
      "                tiger_zone = features_in_bbox(tiger_all, tuple(_T_ZONES[zone_key]['bbox']))",
      "                tiger_idx = build_tiger_index(tiger_zone)",
      "                unmatched = [w for w in classified['all_ways'] if not (w.get('cagis_match') and w['cagis_match']['confidence'] >= _T_REV)]",
      "                conflate_with_tiger(unmatched, tiger_idx)",
      "                for w in classified['all_ways']:",
      "                    w.setdefault('tiger_match', None)",
      "                classified['summary_stats']['tiger_features'] = len(tiger_zone)",
      "                classified['summary_stats']['tiger_matched'] = sum(1 for w in classified['all_ways'] if w.get('tiger_match'))",
      "    except Exception as exc:",
      "        classified['summary_stats']['tiger_error'] = str(exc)",
      "results_path = out_dir / 'scan-results.json'",
      "results_path.parent.mkdir(parents=True, exist_ok=True)",
      "ser = {",
      "    'all_ways': classified['all_ways'],",
      "    'class_a': classified['class_a'],",
      "    'class_a_only': classified['class_a_only'],",
      "    'class_ab': classified['class_ab'],",
      "    'class_b_streets': dict(classified['class_b_streets']),",
      "    'gaps': classified['gaps'],",
      "    'summary_stats': classified['summary_stats'],",
      "    'extra_findings': classified.get('extra_findings', []),",
      "}",
      "with open(results_path, 'w', encoding='utf-8') as fh:",
      "    json.dump(ser, fh, ensure_ascii=False)",
      "sys.stdout = sys.__stdout__",
      "print(json.dumps(classified['summary_stats']))",
    ].join("\n");
    const out = await runPython(pyCode);
    const stats = JSON.parse(out.trim());
    res.json({ success: true, stats });
    try { appendHistory({ action: "scan", zone, stats, with_conflation: withConflation }); } catch {}
  } catch (e) {
    res.status(500).json({ error: safeError(e) });
  } finally {
    scanInProgress = false;
  }
});

// ---- conflate ----

app.post("/api/conflate/:zone", async (req, res) => {
  const zone = req.params.zone;
  if (!validateZone(zone, res)) return;
  const resultsPath = path.join(
    PROJECT_ROOT, "osm-audit-" + zone, "scan-results.json"
  );
  if (!fs.existsSync(resultsPath))
    return res.status(404).json({ error: "No scan results for this zone. Run a scan first." });
  const forceRefresh = req.body && req.body.force_refresh === true;
  try {
    const pyCode = [
      "import json, sys, os",
      "sys.path.insert(0, " + JSON.stringify(OSM_PKG) + ")",
      "from pathlib import Path",
      "sys.stdout = open(os.devnull, 'w')",
      "from osm.conflate import SHAPELY_AVAILABLE, build_index, conflate, load_cagis_for_zone",
      "if not SHAPELY_AVAILABLE:",
      "    sys.stdout = sys.__stdout__",
      "    print(json.dumps({'error': 'shapely is not installed; cannot run conflation.'}))",
      "    sys.exit(0)",
      "zone_key = " + JSON.stringify(zone),
      "results_path = Path(" + JSON.stringify(resultsPath.replace(/\\/g, "/")) + ")",
      "with results_path.open('r', encoding='utf-8') as fh:",
      "    classified = json.load(fh)",
      "force = " + (forceRefresh ? "True" : "False"),
      "cagis = load_cagis_for_zone(zone_key, force_refresh=force)",
      "idx = build_index(cagis)",
      "conflate(classified['all_ways'], idx)",
      "matched = sum(1 for w in classified['all_ways'] if w.get('cagis_match'))",
      "classified.setdefault('summary_stats', {})",
      "classified['summary_stats']['cagis_features'] = len(cagis)",
      "classified['summary_stats']['cagis_matched'] = matched",
      "with results_path.open('w', encoding='utf-8') as fh:",
      "    json.dump(classified, fh, ensure_ascii=False)",
      "sys.stdout = sys.__stdout__",
      "print(json.dumps({'cagis_features': len(cagis), 'cagis_matched': matched, 'total_ways': len(classified['all_ways'])}))",
    ].join("\n");
    const out = await runPython(pyCode);
    const result = JSON.parse(out.trim());
    if (result.error) return res.status(500).json({ error: result.error });
    res.json({ success: true, ...result });
    try { appendHistory({ action: "conflate", zone, result }); } catch {}
  } catch (e) {
    res.status(500).json({ error: safeError(e) });
  }
});

// ---- results ----

app.get("/api/results/:zone", (req, res) => {
  if (!validateZone(req.params.zone, res)) return;
  const p = path.join(
    PROJECT_ROOT,
    "osm-audit-" + req.params.zone,
    "scan-results.json"
  );
  if (!fs.existsSync(p))
    return res.status(404).json({ error: "No scan results. Run a scan first." });
  try {
    res.json(JSON.parse(fs.readFileSync(p, "utf-8")));
  } catch (e) {
    res.status(500).json({ error: safeError(e) });
  }
});

// ---- reports ----

app.post("/api/reports", async (req, res) => {
  const zone = req.body.zone || "blue-ash-montgomery";
  if (!validateZone(zone, res)) return;
  const ALLOWED_FORMATS = new Set(["xlsx+html", "xlsx", "html", "docx", "pdf"]);
  const format = ALLOWED_FORMATS.has(req.body.format) ? req.body.format : "xlsx+html";
  const wantXlsx = format === "xlsx" || format === "xlsx+html";
  const wantHtml = format === "html" || format === "xlsx+html";
  // docx/pdf are not yet implemented in osm package; fall back to xlsx+html behaviour
  // and surface a note in the response.
  const formatNote = (format === "docx" || format === "pdf")
    ? `Format '${format}' is not yet implemented; generated XLSX + HTML instead.`
    : null;
  const effectiveWantXlsx = wantXlsx || formatNote !== null;
  const effectiveWantHtml = wantHtml || formatNote !== null;
  try {
    const pyCode = [
      "import json, sys, os, datetime as dt",
      "sys.path.insert(0, " + JSON.stringify(OSM_PKG) + ")",
      "from pathlib import Path",
      "sys.stdout = open(os.devnull, 'w')",
      "from osm.zones import ZONES",
      "from osm.csv_export import write_csvs",
      "from osm.dashboard import write_dashboard",
      "from osm.fetch import overpass_query",
      "from osm.xlsx import write_xlsx",
      "zone_key = " + JSON.stringify(zone),
      "z = ZONES[zone_key]",
      "proj = Path(" + JSON.stringify(PROJECT_ROOT) + ")",
      "out_dir = proj / f'osm-audit-{zone_key}'",
      "results_path = out_dir / 'scan-results.json'",
      "with open(results_path, 'r', encoding='utf-8') as fh:",
      "    classified = json.load(fh)",
      "audit_ts = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')",
      "zn = z['name'].replace(' / ', '-').replace(' ', '-')",
      "query_text = overpass_query(z['bbox'])",
      "want_xlsx = " + (effectiveWantXlsx ? "True" : "False"),
      "want_html = " + (effectiveWantHtml ? "True" : "False"),
      "xlsx_path = out_dir / 'reports' / f'OSM-Audit-{zn}.xlsx'",
      "dash_path = out_dir / 'reports' / f'OSM-Audit-{zn}-Dashboard.html'",
      "if want_xlsx:",
      "    write_xlsx(classified, zone_key, xlsx_path, query_text, audit_ts, output_root=proj)",
      "if want_html:",
      "    write_dashboard(classified, zone_key, z['name'], dash_path, audit_ts)",
      "write_csvs(classified, out_dir / 'csv')",
      "files = []",
      "if want_xlsx and xlsx_path.exists(): files.append(str(xlsx_path))",
      "if want_html and dash_path.exists(): files.append(str(dash_path))",
      "sys.stdout = sys.__stdout__",
      "print(json.dumps({'success': True, 'files': files}))",
    ].join("\n");
    const out = await runPython(pyCode);
    const result = JSON.parse(out.trim());
    if (formatNote) result.note = formatNote;
    result.format = format;
    res.json(result);
    try { appendHistory({ action: "report", zone, files: result.files, format }); } catch {}
  } catch (e) {
    res.status(500).json({ error: safeError(e) });
  }
});

app.get("/api/dashboard/:zone", (req, res) => {
  if (!validateZone(req.params.zone, res)) return;
  const dir = path.join(
    PROJECT_ROOT,
    "osm-audit-" + req.params.zone,
    "reports"
  );
  if (!fs.existsSync(dir))
    return res.status(404).json({ error: "No reports found." });
  const files = fs.readdirSync(dir).filter((f) => f.endsWith("-Dashboard.html"));
  if (files.length === 0)
    return res.status(404).json({ error: "No dashboard found." });
  res.sendFile(path.join(dir, files[0]));
});

// ---- review + fix ----

app.get("/api/review/:zone", async (req, res) => {
  const zone = req.params.zone;
  if (!validateZone(zone, res)) return;
  const p = path.join(PROJECT_ROOT, "osm-audit-" + zone, "scan-results.json");
  if (!fs.existsSync(p))
    return res.status(404).json({ error: "No scan results. Run a scan first." });
  try {
    const pyCode = [
      "import json, sys",
      "sys.path.insert(0, " + JSON.stringify(OSM_PKG) + ")",
      "from osm.review import proposed_fix, proposed_fixes_for_way",
      "with open(" + JSON.stringify(p.replace(/\\/g, "/")) + ") as fh:",
      "    data = json.load(fh)",
      "fixable = []",
      "for w in data['all_ways']:",
      "    for f in proposed_fixes_for_way(w):",
      "        fixable.append({'way': w, 'fix': f})",
      "print(json.dumps({'count': len(fixable), 'fixes': fixable}))",
    ].join("\n");
    const out = await runPython(pyCode);
    res.json(JSON.parse(out.trim()));
  } catch (e) {
    res.status(500).json({ error: safeError(e) });
  }
});

app.post("/api/fix", async (req, res) => {
  const { zone, fixes, dry_run } = req.body;
  if (!zone || !fixes || !fixes.length)
    return res.status(400).json({ error: "Missing zone or fixes" });
  if (!validateZone(zone, res)) return;
  const invalid = fixes.filter((f) => !validateFix(f));
  if (invalid.length)
    return res.status(400).json({ error: `${invalid.length} invalid fix(es) in payload` });
  try {
    const fixesJson = JSON.stringify(fixes);
    const pyCode = [
      "import json, sys, os",
      "sys.path.insert(0, " + JSON.stringify(OSM_PKG) + ")",
      "sys.stdout = open(os.devnull, 'w')",
      "from osm.changeset import submit_fixes",
      "_args = json.loads(" + JSON.stringify(fixesJson) + ")",
      "result = submit_fixes(_args, dry_run=" + (dry_run ? "True" : "False") + ")",
      "sys.stdout = sys.__stdout__",
      "print(json.dumps(result))",
    ].join("\n");
    const out = await runPython(pyCode);
    const result = JSON.parse(out.trim());
    res.json(result);
    try {
      appendHistory({
        action: dry_run ? "dry_run" : "submit",
        zone,
        fixes_applied: result.fixes_applied,
        changeset_ids: result.changeset_ids || [],
        errors: (result.errors || []).length,
      });
    } catch {}
  } catch (e) {
    res.status(500).json({ error: safeError(e) });
  }
});

// ---- OSM Notes ----

app.get("/api/notes/:zone", async (req, res) => {
  const zone = req.params.zone;
  if (!validateZone(zone, res)) return;
  const force = req.query && req.query.force === "1";
  try {
    const pyCode = [
      "import json, sys, os",
      "sys.path.insert(0, " + JSON.stringify(OSM_PKG) + ")",
      "sys.stdout = open(os.devnull, 'w')",
      "from osm.notes import fetch_notes_for_zone",
      "force = " + (force ? "True" : "False"),
      "out = fetch_notes_for_zone(" + JSON.stringify(zone) + ", force_refresh=force)",
      "sys.stdout = sys.__stdout__",
      "print(json.dumps({'count': len(out), 'notes': out}))",
    ].join("\n");
    const out = await runPython(pyCode);
    res.json(JSON.parse(out.trim()));
  } catch (e) {
    res.status(500).json({ error: safeError(e) });
  }
});

// ---- Osmose ----

app.get("/api/osmose/:zone", async (req, res) => {
  const zone = req.params.zone;
  if (!validateZone(zone, res)) return;
  const force = req.query && req.query.force === "1";
  try {
    const pyCode = [
      "import json, sys, os",
      "sys.path.insert(0, " + JSON.stringify(OSM_PKG) + ")",
      "sys.stdout = open(os.devnull, 'w')",
      "from osm.osmose import fetch_issues_for_zone",
      "force = " + (force ? "True" : "False"),
      "out = fetch_issues_for_zone(" + JSON.stringify(zone) + ", force_refresh=force)",
      "sys.stdout = sys.__stdout__",
      "print(json.dumps({'count': len(out), 'issues': out}))",
    ].join("\n");
    const out = await runPython(pyCode);
    res.json(JSON.parse(out.trim()));
  } catch (e) {
    res.status(500).json({ error: safeError(e) });
  }
});

app.get("/api/osmose/:zone/by-way/:wayId", async (req, res) => {
  const zone = req.params.zone;
  if (!validateZone(zone, res)) return;
  const wayId = parseInt(req.params.wayId, 10);
  if (!Number.isFinite(wayId) || wayId <= 0)
    return res.status(400).json({ error: "Invalid way id" });
  try {
    const pyCode = [
      "import json, sys, os",
      "sys.path.insert(0, " + JSON.stringify(OSM_PKG) + ")",
      "sys.stdout = open(os.devnull, 'w')",
      "from osm.osmose import fetch_issues_for_zone, index_issues_by_osm_id",
      "issues = fetch_issues_for_zone(" + JSON.stringify(zone) + ")",
      "idx = index_issues_by_osm_id(issues)",
      "wid = " + JSON.stringify(wayId),
      "matches = idx.get(('way', wid), [])",
      "sys.stdout = sys.__stdout__",
      "print(json.dumps({'count': len(matches), 'issues': matches}))",
    ].join("\n");
    const out = await runPython(pyCode);
    res.json(JSON.parse(out.trim()));
  } catch (e) {
    res.status(500).json({ error: safeError(e) });
  }
});

// ---- history ----

app.get("/api/history", (_req, res) => {
  res.json(loadHistory());
});

app.delete("/api/history", (_req, res) => {
  try {
    if (fs.existsSync(HISTORY_PATH)) {
      fs.writeFileSync(HISTORY_PATH, JSON.stringify([], null, 2));
    }
    res.json({ success: true, cleared: true });
  } catch (e) {
    res.status(500).json({ error: safeError(e) });
  }
});

// ---- export ----

app.get("/api/export/:zone/csv", (req, res) => {
  if (!validateZone(req.params.zone, res)) return;
  const p = path.join(PROJECT_ROOT, "osm-audit-" + req.params.zone, "scan-results.json");
  if (!fs.existsSync(p))
    return res.status(404).json({ error: "No scan results." });
  try {
    const data = JSON.parse(fs.readFileSync(p, "utf-8"));
    const ways = data.all_ways || [];
    const cols = ["id", "name", "highway", "oneway", "defect_class", "severity", "review_status", "review_confidence", "version", "user", "timestamp"];
    const header = cols.join(",") + "\n";
    const esc = (v) => {
      const s = String(v == null ? "" : v);
      return s.includes(",") || s.includes('"') || s.includes("\n")
        ? '"' + s.replace(/"/g, '""') + '"'
        : s;
    };
    const rows = ways.map((w) =>
      cols.map((c) => esc(c === "name" ? w.name_display : w[c])).join(",")
    ).join("\n");
    res.setHeader("Content-Type", "text/csv");
    res.setHeader("Content-Disposition", `attachment; filename="osm-audit-${req.params.zone}.csv"`);
    res.send(header + rows);
  } catch (e) {
    res.status(500).json({ error: safeError(e) });
  }
});

app.get("/api/export/:zone/json", (req, res) => {
  if (!validateZone(req.params.zone, res)) return;
  const p = path.join(PROJECT_ROOT, "osm-audit-" + req.params.zone, "scan-results.json");
  if (!fs.existsSync(p))
    return res.status(404).json({ error: "No scan results." });
  try {
    const data = JSON.parse(fs.readFileSync(p, "utf-8"));
    res.setHeader("Content-Type", "application/json");
    res.setHeader("Content-Disposition", `attachment; filename="osm-audit-${req.params.zone}.json"`);
    res.json(data);
  } catch (e) {
    res.status(500).json({ error: safeError(e) });
  }
});

// ---- fallback ----

app.use((_req, res) => {
  res.sendFile(path.join(__dirname, "public", "index.html"));
});

app.listen(PORT, () => {
  console.log("OSM audit server running at http://localhost:" + PORT);
});
