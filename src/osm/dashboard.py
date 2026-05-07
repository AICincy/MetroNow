"""Leaflet HTML dashboard generation.

Produces a self-contained HTML file with embedded data, Leaflet map,
sidebar with KPI cards, layer toggles, search, dark mode, keyboard
shortcuts, and JOSM integration.  Ported from Tiger's DASHBOARD_TEMPLATE.
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import CLASS_AB, CLASS_A, CLASS_B, CLASS_C


def _compact_ways(all_ways: list[dict]) -> list[dict]:
    """Compact way records for embedding in the dashboard."""
    return [
        {
            "id": w["id"],
            "h": w["highway"] or "",
            "n": w["name_display"],
            "o": w["oneway"] or "",
            "c": w["defect_class"],
            "s": w["severity"],
            "g": w["geometry"],
            "rs": w.get("review_status", ""),
        }
        for w in all_ways
        if w["geometry"]
    ]


def _compact_gaps(gaps: list[dict]) -> list[dict]:
    return [
        {
            "lat": g["lat"],
            "lon": g["lon"],
            "street": g["street"],
            "way1_id": g["way1_id"],
            "way2_id": g["way2_id"],
            "distance_m": g["distance_m"],
        }
        for g in gaps
    ]


def write_dashboard(
    classified: dict,
    zone_key: str,
    zone_name: str,
    out_path: Path,
    audit_ts: str,
) -> None:
    """Generate the interactive Leaflet dashboard HTML."""
    stats = classified["summary_stats"]
    ways_json = json.dumps(_compact_ways(classified["all_ways"]), separators=(",", ":"))
    gaps_json = json.dumps(_compact_gaps(classified.get("gaps", [])), separators=(",", ":"))
    stats_json = json.dumps({
        "total": stats["total"],
        "residential": stats["residential"],
        "oneway": stats["oneway_yes_total"],
        "class_a": stats["class_a_count"],
        "class_b": stats["class_b_way_count"],
        "class_ab": stats["class_ab_count"],
        "class_c": stats.get("by_class", {}).get(CLASS_C, 0),
        "multi_seg_streets": stats["class_b_street_count"],
        "gaps_found": stats["gaps_found"],
    }, separators=(",", ":"))

    html = _TEMPLATE.replace("{{ZONE_NAME}}", zone_name)
    html = html.replace("{{ZONE_KEY}}", zone_key)
    html = html.replace("{{AUDIT_TS}}", audit_ts)
    html = html.replace("{{WAYS_DATA}}", ways_json)
    html = html.replace("{{GAPS_DATA}}", gaps_json)
    html = html.replace("{{STATS_DATA}}", stats_json)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"  Dashboard saved: {out_path}")


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OSM Audit — {{ZONE_NAME}}</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css"/>
<style>
:root{--bg:#f8f9fa;--sidebar-bg:#fff;--text:#333;--card-bg:#fff;--border:#ddd;--accent:#1F4E79}
:root.dark{--bg:#1a1a2e;--sidebar-bg:#16213e;--text:#e0e0e0;--card-bg:#0f3460;--border:#2a2a4a;--accent:#4a9eff}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:Arial,sans-serif;display:flex;height:100vh;background:var(--bg);color:var(--text)}
#sidebar{width:300px;background:var(--sidebar-bg);border-right:1px solid var(--border);overflow-y:auto;padding:12px;flex-shrink:0}
#sidebar h2{font-size:14px;color:var(--accent);margin-bottom:8px;display:flex;justify-content:space-between;align-items:center}
#map{flex:1}
.kpi{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:12px}
.kpi-card{background:var(--card-bg);border:1px solid var(--border);border-radius:6px;padding:8px;text-align:center}
.kpi-card .num{font-size:20px;font-weight:bold;color:var(--accent)}
.kpi-card .label{font-size:10px;color:var(--text);opacity:.7}
.layer-toggle{margin:4px 0;font-size:12px}
.layer-toggle input{margin-right:6px}
#search{width:100%;padding:6px;margin:8px 0;border:1px solid var(--border);border-radius:4px;background:var(--card-bg);color:var(--text)}
.btn{display:block;width:100%;padding:6px;margin:4px 0;border:1px solid var(--border);border-radius:4px;background:var(--card-bg);color:var(--text);cursor:pointer;font-size:11px;text-align:center}
.btn:hover{background:var(--accent);color:#fff}
#dark-toggle{cursor:pointer;font-size:16px;border:none;background:none}
#viewport-stats{font-size:11px;margin-top:8px;padding:8px;background:var(--card-bg);border:1px solid var(--border);border-radius:4px}
#loading{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.7);display:flex;align-items:center;justify-content:center;z-index:10000;color:#fff;font-size:18px}
.spinner{border:4px solid rgba(255,255,255,.3);border-top:4px solid #fff;border-radius:50%;width:40px;height:40px;animation:spin 1s linear infinite;margin-right:12px}
@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:768px){#sidebar{position:fixed;left:-300px;z-index:1000;transition:left .3s;height:100%}#sidebar.open{left:0}#hamburger{display:block!important}}
#hamburger{display:none;position:fixed;top:10px;left:10px;z-index:1001;background:var(--sidebar-bg);border:1px solid var(--border);border-radius:4px;padding:6px 10px;cursor:pointer;font-size:18px}
#shortcut-help{display:none;position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);background:var(--sidebar-bg);border:2px solid var(--accent);border-radius:8px;padding:20px;z-index:9999;max-width:400px}
#shortcut-help table{width:100%;font-size:12px}
#shortcut-help td{padding:4px 8px}
#shortcut-help kbd{background:var(--card-bg);border:1px solid var(--border);border-radius:3px;padding:2px 6px;font-family:monospace}
@media print{#sidebar,#hamburger,.leaflet-control-zoom,.leaflet-control-attribution{display:none!important}#map{width:100%!important}body{display:block}}
@media(prefers-reduced-motion:reduce){.spinner{animation:none}*{transition:none!important}}
</style>
</head>
<body>
<div id="loading"><div class="spinner"></div>Rendering segments...</div>
<button id="hamburger" aria-label="Toggle sidebar">&#9776;</button>
<div id="sidebar" role="region" aria-label="Dashboard controls">
  <h2>OSM Audit: {{ZONE_NAME}} <button id="dark-toggle" aria-label="Switch to dark mode">&#127769;</button></h2>
  <div class="kpi" role="region" aria-label="Key metrics">
    <div class="kpi-card"><div class="num" id="kpi-total" aria-live="polite">0</div><div class="label">Total</div></div>
    <div class="kpi-card"><div class="num" id="kpi-res">0</div><div class="label">Residential</div></div>
    <div class="kpi-card"><div class="num" id="kpi-ab" style="color:#C00000">0</div><div class="label">Class AB</div></div>
    <div class="kpi-card"><div class="num" id="kpi-a" style="color:#FF4444">0</div><div class="label">Class A</div></div>
    <div class="kpi-card"><div class="num" id="kpi-b" style="color:#ED7D31">0</div><div class="label">Class B</div></div>
    <div class="kpi-card"><div class="num" id="kpi-gaps" style="color:#9C27B0">0</div><div class="label">Node Gaps</div></div>
  </div>
  <input id="search" type="text" placeholder="Search streets..." role="combobox" aria-label="Search streets" aria-expanded="false"/>
  <div id="search-results" role="listbox"></div>
  <div style="margin:8px 0;font-size:12px;font-weight:bold">Layers</div>
  <label class="layer-toggle"><input type="checkbox" id="lyr-ab" checked> Class AB</label>
  <label class="layer-toggle"><input type="checkbox" id="lyr-a" checked> Class A</label>
  <label class="layer-toggle"><input type="checkbox" id="lyr-b" checked> Class B</label>
  <label class="layer-toggle"><input type="checkbox" id="lyr-c"> Class C</label>
  <label class="layer-toggle"><input type="checkbox" id="lyr-gaps" checked> Node Gaps</label>
  <label class="layer-toggle"><input type="checkbox" id="lyr-heat"> Heatmap</label>
  <div style="margin:8px 0;font-size:12px;font-weight:bold">Basemap</div>
  <select id="basemap" style="width:100%;padding:4px;font-size:11px;background:var(--card-bg);color:var(--text);border:1px solid var(--border);border-radius:4px">
    <option value="voyager">CARTO Voyager</option>
    <option value="positron">CARTO Positron</option>
    <option value="dark">CARTO Dark Matter</option>
    <option value="osm">OpenStreetMap</option>
    <option value="esri">Esri World Imagery</option>
  </select>
  <button class="btn" id="btn-josm" aria-label="Load visible ways in JOSM">Load in JOSM</button>
  <button class="btn" id="btn-print" aria-label="Print view">Print View</button>
  <div id="viewport-stats"></div>
</div>
<div id="map" role="region" aria-label="Audit map"></div>
<div id="shortcut-help">
  <h3 style="margin-bottom:8px">Keyboard Shortcuts</h3>
  <table>
    <tr><td><kbd>/</kbd> or <kbd>Ctrl+K</kbd></td><td>Focus search</td></tr>
    <tr><td><kbd>Esc</kbd></td><td>Clear highlight/popup</td></tr>
    <tr><td><kbd>1</kbd>-<kbd>6</kbd></td><td>Toggle layers</td></tr>
    <tr><td><kbd>S</kbd></td><td>Toggle satellite</td></tr>
    <tr><td><kbd>?</kbd></td><td>This help</td></tr>
  </table>
  <p style="margin-top:8px;font-size:11px;text-align:center;cursor:pointer" onclick="this.parentElement.style.display='none'">Click to close</p>
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
<script src="https://unpkg.com/leaflet-heat@0.2.0/dist/leaflet-heat.js"></script>
<script>
var D={ways:{{WAYS_DATA}},gaps:{{GAPS_DATA}},stats:{{STATS_DATA}}};
(function(){
var map=L.map('map',{zoomControl:true}).setView([39.20,-84.385],13);
var basemaps={
  voyager:L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png',{subdomains:'abcd',attribution:'&copy; CARTO &copy; OSM contributors',maxZoom:20}),
  positron:L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',{subdomains:'abcd',attribution:'&copy; CARTO',maxZoom:20}),
  dark:L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',{subdomains:'abcd',attribution:'&copy; CARTO',maxZoom:20}),
  osm:L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'&copy; OSM contributors',maxZoom:19}),
  esri:L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{attribution:'&copy; Esri',maxZoom:19})
};
var currentBase=basemaps.voyager.addTo(map);
var classStyle={AB:{color:'#C00000',weight:4},A:{color:'#FF4444',weight:3},B:{color:'#ED7D31',weight:2.5},C:{color:'#999',weight:1.5}};
var layers={AB:L.layerGroup(),A:L.layerGroup(),B:L.layerGroup(),C:L.layerGroup()};
var streetIndex={};
var allPolylines=[];
D.ways.forEach(function(w){
  if(!w.g||!w.g.length)return;
  var latlngs=w.g.map(function(p){return[p[0],p[1]]});
  var st=classStyle[w.c]||classStyle.C;
  var line=L.polyline(latlngs,{color:st.color,weight:st.weight,opacity:0.8});
  line._wayData=w;
  var nn=(w.n||'').toLowerCase();
  if(nn){if(!streetIndex[nn])streetIndex[nn]=[];streetIndex[nn].push(line);}
  line.on('click',function(){highlightStreet(nn,w);});
  line.bindPopup(function(){
    return '<b>'+w.n+'</b><br>Class: '+w.c+' | '+w.h+'<br>Oneway: '+(w.o||'no')+
    (w.rs?'<br>Review: '+w.rs:'')+
    '<br><a href="https://www.openstreetmap.org/way/'+w.id+'" target="_blank">OSM</a> | '+
    '<a href="https://www.openstreetmap.org/edit?editor=id&way='+w.id+'" target="_blank">iD</a> | '+
    '<a href="http://localhost:8111/load_object?objects=w'+w.id+'&relation_members=true" target="_blank">JOSM</a>';
  });
  if(layers[w.c])layers[w.c].addLayer(line);
  allPolylines.push(line);
});
layers.AB.addTo(map);layers.A.addTo(map);layers.B.addTo(map);
var gapCluster=L.markerClusterGroup({iconCreateFunction:function(c){return L.divIcon({html:'<div style="background:#9C27B0;color:#fff;border-radius:50%;width:30px;height:30px;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:bold">'+c.getChildCount()+'</div>',iconSize:[30,30],className:''})},disableClusteringAtZoom:16});
D.gaps.forEach(function(g){
  var m=L.circleMarker([g.lat,g.lon],{radius:6,color:'#9C27B0',fillColor:'#9C27B0',fillOpacity:0.7,weight:2});
  m.bindPopup('<b>'+g.street+'</b><br>Gap: '+g.distance_m+'m<br>Ways: '+g.way1_id+', '+g.way2_id);
  gapCluster.addLayer(m);
});
gapCluster.addTo(map);
var heatData=D.ways.filter(function(w){return w.g&&w.g.length}).map(function(w){var mid=Math.floor(w.g.length/2);return[w.g[mid][0],w.g[mid][1],w.c==='AB'?1:w.c==='A'?0.7:0.4]});
var heatLayer=L.heatLayer(heatData,{radius:20,blur:15,maxZoom:16});
// KPIs
var S=D.stats;
document.getElementById('kpi-total').textContent=S.total.toLocaleString();
document.getElementById('kpi-res').textContent=S.residential.toLocaleString();
document.getElementById('kpi-ab').textContent=S.class_ab.toLocaleString();
document.getElementById('kpi-a').textContent=S.class_a.toLocaleString();
document.getElementById('kpi-b').textContent=S.class_b.toLocaleString();
document.getElementById('kpi-gaps').textContent=S.gaps_found.toLocaleString();
// Layer toggles
var lyrs=[['lyr-ab',layers.AB],['lyr-a',layers.A],['lyr-b',layers.B],['lyr-c',layers.C],['lyr-gaps',gapCluster],['lyr-heat',heatLayer]];
lyrs.forEach(function(pair){
  var cb=document.getElementById(pair[0]),lyr=pair[1];
  cb.addEventListener('change',function(){cb.checked?map.addLayer(lyr):map.removeLayer(lyr)});
});
// Basemap
document.getElementById('basemap').addEventListener('change',function(){
  map.removeLayer(currentBase);
  currentBase=basemaps[this.value];
  currentBase.addTo(map);
});
// Search
var searchInput=document.getElementById('search');
searchInput.addEventListener('input',function(){
  var q=this.value.toLowerCase().trim();
  if(!q){clearHighlight();return}
  var matches=Object.keys(streetIndex).filter(function(k){return k.indexOf(q)>=0}).slice(0,10);
  var res=document.getElementById('search-results');
  res.innerHTML=matches.map(function(m){return'<div style="padding:4px;cursor:pointer;font-size:12px" onclick="highlightStreet(\''+m.replace(/'/g,"\\'")+'\')">'+(streetIndex[m][0]._wayData.n||m)+'</div>'}).join('');
});
// Highlight
var highlighted=[];
window.highlightStreet=function(nn,wayData){
  clearHighlight();
  var lines=streetIndex[nn];
  if(!lines||!lines.length)return;
  var bounds=L.latLngBounds([]);
  lines.forEach(function(l){l.setStyle({weight:6,opacity:1});l.bringToFront();bounds.extend(l.getBounds())});
  highlighted=lines;
  allPolylines.forEach(function(l){if(highlighted.indexOf(l)<0)l.setStyle({opacity:0.2})});
  map.fitBounds(bounds,{padding:[50,50]});
};
window.clearHighlight=function(){
  allPolylines.forEach(function(l){var st=classStyle[l._wayData.c]||classStyle.C;l.setStyle({weight:st.weight,opacity:0.8})});
  highlighted=[];
};
map.on('click',function(e){if(!e.originalEvent._polylineClicked)clearHighlight()});
allPolylines.forEach(function(l){l.on('click',function(e){e.originalEvent._polylineClicked=true})});
// Viewport stats
function updateViewportStats(){
  var b=map.getBounds();var vc={total:0,AB:0,A:0,B:0,C:0};
  allPolylines.forEach(function(l){if(b.intersects(l.getBounds())){vc.total++;vc[l._wayData.c]=(vc[l._wayData.c]||0)+1}});
  document.getElementById('viewport-stats').innerHTML='<b>In view:</b> '+vc.total+' segs | AB:'+vc.AB+' A:'+vc.A+' B:'+vc.B+' C:'+vc.C;
}
map.on('moveend',updateViewportStats);updateViewportStats();
// JOSM
document.getElementById('btn-josm').addEventListener('click',function(){
  var b=map.getBounds();var ids=[];
  allPolylines.forEach(function(l){if(b.intersects(l.getBounds()))ids.push('w'+l._wayData.id)});
  if(!ids.length){alert('No ways in viewport');return}
  var chunk=[];var url='';
  for(var i=0;i<ids.length;i++){
    chunk.push(ids[i]);
    url='http://localhost:8111/load_object?objects='+chunk.join(',')+'&relation_members=true';
    if(url.length>7500||i===ids.length-1){fetch(url,{mode:'no-cors'}).catch(function(){});chunk=[]}
  }
});
// Dark mode
var isDark=localStorage.getItem('osm-dark-mode')==='true'||(window.matchMedia&&window.matchMedia('(prefers-color-scheme:dark)').matches&&!localStorage.getItem('osm-dark-mode'));
if(isDark)document.documentElement.classList.add('dark');
document.getElementById('dark-toggle').textContent=isDark?'☀️':'🌙';
document.getElementById('dark-toggle').addEventListener('click',function(){
  isDark=!isDark;document.documentElement.classList.toggle('dark',isDark);
  this.textContent=isDark?'☀️':'🌙';
  localStorage.setItem('osm-dark-mode',isDark);
});
// Print
document.getElementById('btn-print').addEventListener('click',function(){window.print()});
// Hamburger
document.getElementById('hamburger').addEventListener('click',function(){document.getElementById('sidebar').classList.toggle('open')});
// Keyboard shortcuts
document.addEventListener('keydown',function(e){
  if(e.target.tagName==='INPUT')return;
  if(e.key==='/'||((e.ctrlKey||e.metaKey)&&e.key==='k')){e.preventDefault();searchInput.focus();return}
  if(e.key==='Escape'){clearHighlight();map.closePopup();searchInput.blur();document.getElementById('shortcut-help').style.display='none';return}
  if(e.key==='?'){var h=document.getElementById('shortcut-help');h.style.display=h.style.display==='none'?'block':'none';return}
  if(e.key==='s'||e.key==='S'){var sel=document.getElementById('basemap');sel.value=sel.value==='esri'?'voyager':'esri';sel.dispatchEvent(new Event('change'));return}
  var layerKeys=['1','2','3','4','5','6'];var idx=layerKeys.indexOf(e.key);
  if(idx>=0&&idx<lyrs.length){var cb=document.getElementById(lyrs[idx][0]);cb.checked=!cb.checked;cb.dispatchEvent(new Event('change'))}
});
// Loading
setTimeout(function(){document.getElementById('loading').style.display='none'},100);
})();
</script>
</body>
</html>"""
