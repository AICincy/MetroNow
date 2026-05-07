const express = require("express");
const { execFile } = require("child_process");
const path = require("path");
const fs = require("fs");

const app = express();
const PORT = 3000;

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
const CONFIG_DIR = path.join(process.env.USERPROFILE || "", ".config", "osm");
const TOKEN_PATH = path.join(CONFIG_DIR, "token.json");
const PROJECT_ROOT = path.resolve(__dirname, "..");

app.use(express.json());
app.use(express.static(path.join(__dirname, "public")));

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
    res.status(500).json({ error: e.message });
  }
});

app.post("/api/auth/exchange", async (req, res) => {
  const { code, verifier } = req.body;
  if (!code || !verifier)
    return res.status(400).json({ error: "Missing code or verifier" });
  try {
    const safeCode = code.replace(/'/g, "\\'");
    const safeVerifier = verifier.replace(/'/g, "\\'");
    const pyCode = [
      "import json, sys",
      "sys.path.insert(0, " + JSON.stringify(OSM_PKG) + ")",
      "from osm.auth import exchange_code",
      "token = exchange_code('" + safeCode + "', '" + safeVerifier + "')",
      'print(json.dumps({"success": True, "scope": token.get("scope", "")}))',
    ].join("\n");
    const out = await runPython(pyCode);
    res.json(JSON.parse(out.trim()));
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.post("/api/auth/logout", (_req, res) => {
  try {
    if (fs.existsSync(TOKEN_PATH)) fs.unlinkSync(TOKEN_PATH);
    res.json({ success: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.get("/api/zones", async (_req, res) => {
  try {
    const pyCode = [
      "import json, sys",
      "sys.path.insert(0, " + JSON.stringify(OSM_PKG) + ")",
      "from osm.zones import ZONES, ZONE_KEYS, DEFAULT_ZONE",
      "out = {'zones': {}, 'keys': ZONE_KEYS, 'default': DEFAULT_ZONE}",
      "for k in ZONE_KEYS:",
      "    out['zones'][k] = {'name': ZONES[k]['name'], 'bbox': ZONES[k]['bbox']}",
      "print(json.dumps(out))",
    ].join("\n");
    const out = await runPython(pyCode);
    res.json(JSON.parse(out.trim()));
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.post("/api/scan", async (req, res) => {
  const zone = req.body.zone || "blue_ash_montgomery";
  const skipHistory = req.body.skip_history !== false;
  try {
    const pyCode = [
      "import json, sys, io, os",
      "sys.path.insert(0, " + JSON.stringify(OSM_PKG) + ")",
      "from pathlib import Path",
      "_real_stdout = sys.stdout",
      "sys.stdout = io.TextIOWrapper(os.fdopen(os.dup(2), 'wb'), encoding='utf-8')",
      "from osm.fetch import fetch_overpass",
      "from osm.classify import classify",
      "from osm.history_filter import filter_by_history",
      "zone_key = " + JSON.stringify(zone),
      "out_dir = Path(" + JSON.stringify(PROJECT_ROOT) + ") / f'osm_audit_{zone_key}'",
      "raw = fetch_overpass(zone_key, out_dir)",
      "classified = classify(raw)",
      "skip = " + (skipHistory ? "True" : "False"),
      "if not skip:",
      "    filter_by_history(classified['all_ways'], skip_history=False)",
      "results_path = out_dir / 'scan_results.json'",
      "results_path.parent.mkdir(parents=True, exist_ok=True)",
      "ser = {",
      "    'all_ways': classified['all_ways'],",
      "    'class_a': classified['class_a'],",
      "    'class_a_only': classified['class_a_only'],",
      "    'class_ab': classified['class_ab'],",
      "    'class_b_streets': dict(classified['class_b_streets']),",
      "    'gaps': classified['gaps'],",
      "    'summary_stats': classified['summary_stats'],",
      "}",
      "with open(results_path, 'w', encoding='utf-8') as fh:",
      "    json.dump(ser, fh, ensure_ascii=False)",
      "sys.stdout = _real_stdout",
      "print(json.dumps(classified['summary_stats']))",
    ].join("\n");
    const out = await runPython(pyCode);
    res.json({ success: true, stats: JSON.parse(out.trim()) });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.get("/api/results/:zone", (req, res) => {
  const p = path.join(
    PROJECT_ROOT,
    "osm_audit_" + req.params.zone,
    "scan_results.json"
  );
  if (!fs.existsSync(p))
    return res.status(404).json({ error: "No scan results. Run a scan first." });
  try {
    res.json(JSON.parse(fs.readFileSync(p, "utf-8")));
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.post("/api/reports", async (req, res) => {
  const zone = req.body.zone || "blue_ash_montgomery";
  try {
    const pyCode = [
      "import json, sys, io, os, datetime as dt",
      "sys.path.insert(0, " + JSON.stringify(OSM_PKG) + ")",
      "from pathlib import Path",
      "_real_stdout = sys.stdout",
      "sys.stdout = io.TextIOWrapper(os.fdopen(os.dup(2), 'wb'), encoding='utf-8')",
      "from osm.zones import ZONES",
      "from osm.csv_export import write_csvs",
      "from osm.dashboard import write_dashboard",
      "from osm.fetch import overpass_query",
      "from osm.xlsx import write_xlsx",
      "zone_key = " + JSON.stringify(zone),
      "z = ZONES[zone_key]",
      "proj = Path(" + JSON.stringify(PROJECT_ROOT) + ")",
      "out_dir = proj / f'osm_audit_{zone_key}'",
      "results_path = out_dir / 'scan_results.json'",
      "with open(results_path, 'r', encoding='utf-8') as fh:",
      "    classified = json.load(fh)",
      "audit_ts = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')",
      "zn = z['name'].replace(' / ', '-').replace(' ', '-')",
      "query_text = overpass_query(z['bbox'])",
      "xlsx_path = out_dir / 'reports' / f'OSM-Audit-{zn}.xlsx'",
      "write_xlsx(classified, zone_key, xlsx_path, query_text, audit_ts, output_root=proj)",
      "dash_path = out_dir / 'reports' / f'OSM-Audit-{zn}-Dashboard.html'",
      "write_dashboard(classified, zone_key, z['name'], dash_path, audit_ts)",
      "write_csvs(classified, out_dir / 'csv')",
      "files = []",
      "if xlsx_path.exists(): files.append(str(xlsx_path))",
      "if dash_path.exists(): files.append(str(dash_path))",
      "sys.stdout = _real_stdout",
      "print(json.dumps({'success': True, 'files': files}))",
    ].join("\n");
    const out = await runPython(pyCode);
    res.json(JSON.parse(out.trim()));
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.get("/api/dashboard/:zone", (req, res) => {
  const dir = path.join(
    PROJECT_ROOT,
    "osm_audit_" + req.params.zone,
    "reports"
  );
  if (!fs.existsSync(dir))
    return res.status(404).json({ error: "No reports found." });
  const files = fs.readdirSync(dir).filter((f) => f.endsWith("-Dashboard.html"));
  if (files.length === 0)
    return res.status(404).json({ error: "No dashboard found." });
  res.sendFile(path.join(dir, files[0]));
});

app.use((_req, res) => {
  res.sendFile(path.join(__dirname, "public", "index.html"));
});

app.listen(PORT, () => {
  console.log("OSM audit server running at http://localhost:" + PORT);
});
