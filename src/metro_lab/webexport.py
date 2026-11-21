"""Interactive isochrone web page: precomputed scans + a static HTML/JS page.

All routing is precomputed in Python from the theoretical timetable; the page
itself is static (no backend) and only reads the precomputed minutes. It can
be served as-is, e.g. via GitHub Pages.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import csa, gtfs

CAP_MINUTES = 90  # values above are stored as null (unreachable within cap)
STEP = 0.5  # quantization of stored minutes


def compute_arrival_matrix(
    net: gtfs.MetroNetwork,
    date: pd.Timestamp,
    times: list[int],
) -> tuple[list[str], np.ndarray]:
    """Arrival minutes from every station at each departure time.

    Returns (station_ids, matrix) with matrix[origin, time, station] in
    minutes (float32, NaN = unreachable within the day).
    """
    stations = list(net.stations.index)
    n = len(stations)
    conns = net.connections_for_date(date)
    out = np.full((n, len(times), n), np.nan, dtype=np.float32)
    for ti, t0 in enumerate(times):
        for oi, origin in enumerate(stations):
            res = csa.scan(conns, stations, net.footpaths, net.change_seconds, origin, t0)
            ok = res.earliest < csa.INF
            out[oi, ti, ok] = (res.earliest[ok] - t0) / 60.0
    return stations, out


def write_web(
    net: gtfs.MetroNetwork,
    date: pd.Timestamp,
    time_labels: list[str],
    times: list[int],
    out_dir: Path,
) -> Path:
    """Compute the matrix and write out_dir/{data.json,index.html}."""
    stations, matrix = compute_arrival_matrix(net, date, times)
    return dump_web(net, stations, matrix, date, time_labels, out_dir)


def dump_web(
    net: gtfs.MetroNetwork,
    stations: list[str],
    matrix: np.ndarray,
    date: pd.Timestamp,
    time_labels: list[str],
    out_dir: Path,
) -> Path:
    """Write out_dir/{data.json,index.html} from a precomputed matrix."""
    q = np.round(matrix / STEP) * STEP
    q[q > CAP_MINUTES] = np.nan
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": date.strftime("%Y-%m-%d"),
        "departures": time_labels,
        "stations": [
            {
                "name": net.stations.stop_name[s],
                "lat": round(float(net.stations.stop_lat[s]), 6),
                "lon": round(float(net.stations.stop_lon[s]), 6),
            }
            for s in stations
        ],
        "minutes": [
            [[None if np.isnan(v) else float(v) for v in q[oi, ti]] for ti in range(matrix.shape[1])]
            for oi in range(len(stations))
        ],
    }
    data_path = out_dir / "data.json"
    data_path.write_text(json.dumps(payload, separators=(",", ":")))
    (out_dir / "index.html").write_text(INDEX_HTML)
    return data_path


INDEX_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>paris-metro-lab — isochrones interactives</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 1.5rem; background: #fafafa; color: #222; }
  h1 { font-size: 1.2rem; margin-bottom: .2rem; }
  .sub { font-size: .85rem; color: #555; margin-bottom: .8rem; }
  label { font-size: .9rem; margin-right: .4rem; }
  select, button { font-size: .9rem; padding: .25rem .4rem; margin-right: .8rem; }
  #bar { display: flex; flex-wrap: wrap; align-items: center; gap: .3rem; margin-bottom: .6rem; }
  #map { background: #fff; border: 1px solid #ddd; border-radius: 6px; max-width: 900px; width: 100%; }
  #legend { font-size: .85rem; margin-top: .5rem; }
  .sw { display: inline-block; width: .8rem; height: .8rem; border-radius: 50%; margin: 0 .25rem 0 .8rem; vertical-align: middle; }
  #slider { width: 220px; }
  #minlabel { font-weight: 600; min-width: 5.5rem; display: inline-block; }
</style>
</head>
<body>
<h1>Métro parisien : temps de trajet depuis une station</h1>
<div class="sub">Horaires théoriques Île-de-France Mobilités (GTFS), sans perturbations.
Temps calculés depuis l'heure demandée, attente du premier train incluse. Métro uniquement (pas de RER/bus/tram).</div>
<div id="bar">
  <label>Départ <select id="origin"></select></label>
  <label>Heure <select id="dtime"></select></label>
  <input type="range" id="slider" min="0" max="60" step="1" value="30">
  <span id="minlabel"></span>
  <button id="play">▶ Animer</button>
</div>
<svg id="map" viewBox="0 0 900 900"></svg>
<div id="legend"></div>
<script>
const NS = "http://www.w3.org/2000/svg";
const svg = document.getElementById("map");
const originSel = document.getElementById("origin");
const dtimeSel = document.getElementById("dtime");
const slider = document.getElementById("slider");
const minlabel = document.getElementById("minlabel");
const legend = document.getElementById("legend");
let DATA = null, playing = null;

function color(t, maxMin) {  // viridis-like ramp, t in [0,1]
  const stops = [[68,1,84],[59,82,139],[33,145,140],[94,201,98],[253,231,37]];
  const x = Math.min(Math.max(t, 0), 1) * (stops.length - 1);
  const i = Math.floor(x), f = x - i, j = Math.min(i + 1, stops.length - 1);
  const c = stops[i].map((v, k) => Math.round(v + (stops[j][k] - v) * f));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

function project(lat, lon, bb) {
  const [minLat, maxLat, minLon, maxLon] = bb;
  const pad = 30, W = 900 - 2 * pad, H = 900 - 2 * pad;
  const x = pad + (lon - minLon) / (maxLon - minLon) * W;
  const y = pad + (1 - (lat - minLat) / (maxLat - minLat)) * H;
  return [x, y];
}

function render() {
  const oi = +originSel.value, ti = +dtimeSel.value, budget = +slider.value;
  minlabel.textContent = `≤ ${budget} min`;
  svg.innerHTML = "";
  const st = DATA.stations, mins = DATA.minutes[oi][ti];
  const bb = DATA.bbox;
  // draw reachable first (big bands under), origin last
  for (let i = 0; i < st.length; i++) {
    const m = mins[i];
    if (m === null || m > budget) continue;
    const [x, y] = project(st[i].lat, st[i].lon, bb);
    const c = document.createElementNS(NS, "circle");
    c.setAttribute("cx", x); c.setAttribute("cy", y); c.setAttribute("r", 6);
    c.setAttribute("fill", color(1 - m / 60));
    const t = document.createElementNS(NS, "title");
    t.textContent = `${st[i].name} — ${Math.round(m)} min`;
    c.appendChild(t); svg.appendChild(c);
  }
  const [ox, oy] = project(st[oi].lat, st[oi].lon, bb);
  const star = document.createElementNS(NS, "text");
  star.setAttribute("x", ox); star.setAttribute("y", oy + 8);
  star.setAttribute("font-size", "22"); star.setAttribute("text-anchor", "middle");
  star.textContent = "★"; star.setAttribute("fill", "#d62728");
  svg.appendChild(star);
  let lg = "";
  for (const b of [10, 20, 30, 40, 50, 60]) {
    lg += `<span class="sw" style="background:${color(1 - b / 60)}"></span>≤ ${b} min`;
  }
  legend.innerHTML = lg;
}

function togglePlay() {
  if (playing) { clearInterval(playing); playing = null; document.getElementById("play").textContent = "▶ Animer"; return; }
  slider.value = 0; render();
  document.getElementById("play").textContent = "⏸ Stop";
  playing = setInterval(() => {
    slider.value = +slider.value + 1; render();
    if (+slider.value >= 60) togglePlay();
  }, 120);
}

fetch("data.json").then(r => r.json()).then(d => {
  DATA = d;
  const lats = d.stations.map(s => s.lat), lons = d.stations.map(s => s.lon);
  d.bbox = [Math.min(...lats), Math.max(...lats), Math.min(...lons), Math.max(...lons)];
  d.stations.forEach((s, i) => {
    const o = document.createElement("option");
    o.value = i; o.textContent = s.name;
    if (s.name === "Châtelet") o.selected = true;
    originSel.appendChild(o);
  });
  d.departures.forEach((lbl, i) => {
    const o = document.createElement("option");
    o.value = i; o.textContent = `${d.date} ${lbl}`;
    dtimeSel.appendChild(o);
  });
  // Optional deep link: ?origin=<name>&time=<index>&min=<budget>
  const q = new URLSearchParams(location.search);
  if (q.has("origin")) {
    const i = d.stations.findIndex(s => s.name === q.get("origin"));
    if (i >= 0) originSel.value = i;
  }
  if (q.has("time")) dtimeSel.value = q.get("time");
  if (q.has("min")) slider.value = q.get("min");
  originSel.onchange = dtimeSel.onchange = slider.oninput = render;
  document.getElementById("play").onclick = togglePlay;
  render();
});
</script>
</body>
</html>
"""
