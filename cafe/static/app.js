// cafe — UI. No framework: small helpers, one state object per page.
const $ = (s, r = document) => r.querySelector(s);
const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v; else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) n.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) n.append(k.nodeType ? k : document.createTextNode(k));
  return n;
};
const svgEl = (tag, attrs = {}) => { const n = document.createElementNS("http://www.w3.org/2000/svg", tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); return n; };
async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  const body = r.headers.get("content-type")?.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error(body?.detail || body || r.statusText);
  return body;
}
const post = (path, body) => api(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
const fmt = (x, d = 1) => x == null || Number.isNaN(x) ? "—" : Number(x).toFixed(d);
const mmss = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const KIND = { uuv: "under water", usv: "on the water", uav: "over the water" };
const COLORS = ["#B0277D", "#0F47AF", "#1F6E43", "#B86A00", "#5B3FA0", "#0E7C86"];
const INK = "#13202B";

// ---------------------------------------------------------------- signal flags (International Code of Signals)
const FLAGS = { GO: ["C", "“Affirmative.”"], MARGINAL: ["U", "“You are running into danger.”"], "NO-GO": ["N", "“Negative.”"] };
function flagSVG(verdict) {
  const s = svgEl("svg", { viewBox: "0 0 4 3", preserveAspectRatio: "none", role: "img", "aria-label": `${verdict}: signal flag ${FLAGS[verdict]?.[0]}` });
  const r = (x, y, w, h, f) => s.append(svgEl("rect", { x, y, width: w, height: h, fill: f }));
  const B = "#0F47AF", W = "#FFFFFF", R = "#D52B1E";
  if (verdict === "GO") [B, W, R, W, B].forEach((c, i) => r(0, i * 0.6, 4, 0.6, c));
  else if (verdict === "MARGINAL") { r(0, 0, 2, 1.5, R); r(2, 0, 2, 1.5, W); r(0, 1.5, 2, 1.5, W); r(2, 1.5, 2, 1.5, R); }
  else for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) r(i, j * 0.75, 1, 0.75, (i + j) % 2 ? W : B);
  return s;
}

// ---------------------------------------------------------------- routing
const views = ["plan", "hangar", "emulator", "receipts"];
function route() {
  const v = views.includes(location.hash.slice(1)) ? location.hash.slice(1) : "plan";
  views.forEach(x => { $(`#view-${x}`).hidden = x !== v; $(`nav a[data-view=${x}]`).classList.toggle("on", x === v); });
  if (v === "plan") setTimeout(() => chart.invalidateSize(), 0);
  if (v === "hangar") loadDesigns();
  if (v === "receipts") loadReceipts();
  if (v === "emulator") loadEmulator();
}
addEventListener("hashchange", route);

// ---------------------------------------------------------------- data coverage + what's real vs assumed
let coverage = null;
async function loadCoverage() {
  coverage = await api("/api/env/coverage");
  if (!coverage.hours) { $("#coverage").textContent = "no weather data on the server"; return; }
  const d = s => s.slice(0, 13).replace("T", " ") + "h";
  // one entry per contiguous run of hours, so a gap of years never reads as continuous weather
  const span = ([a, b]) => a === b ? `${d(a)} (one snapshot)` : `${d(a)} → ${d(b)}`;
  $("#coverage").textContent = `WRF · ${coverage.spans.map(span).join(" · ")} UTC`;
  const t0 = $("#t0");
  t0.min = coverage.first.slice(0, 16); t0.max = coverage.last.slice(0, 16);
  if (!t0.value) t0.value = coverage.spans[coverage.spans.length - 1][0].slice(0, 16);
}
function chips(sources) {
  const box = $("#data-chips");
  if (!sources) { box.replaceChildren(); return; }
  const c = (label, text, kind) => el("span", { class: `chip ${kind}`, title: text }, label);
  const snap = /snapshot/.test(sources.wind), nocur = /assumed/.test(sources.current), estw = /estimated/.test(sources.waves);
  box.replaceChildren(
    c("Wind: weather model" + (snap ? " (one hour, held constant)" : ""), sources.wind, snap ? "warn" : "ok"),
    c(nocur ? "Currents: not in data — assumed 0 ± 0.25 m/s" : "Currents: ocean model", sources.current, nocur ? "warn" : "ok"),
    c(estw ? "Waves: estimated from wind" : "Waves: wave model", sources.waves, estw ? "warn" : "ok"));
}

// ---------------------------------------------------------------- chart
const chart = L.map("chart", { zoomControl: true, worldCopyJump: true }).setView([10, -95], 11);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "© OpenStreetMap contributors", maxZoom: 18, className: "basemap" }).addTo(chart);
const layers = { field: L.layerGroup(), reach: L.layerGroup(), plan: L.layerGroup(), tracks: L.layerGroup(), now: L.layerGroup() };
Object.values(layers).forEach(l => l.addTo(chart));
let fieldInfo = null;

function barb(speed, toN, toE) {   // wind barb: staff points to where the wind comes FROM; half 5 kt, full 10, pennant 50
  const kt = speed * 1.94384, from = Math.atan2(-toE, -toN) * 180 / Math.PI;
  if (kt < 2.5) return `<svg width="14" height="14" viewBox="-7 -7 14 14"><circle r="4" fill="none" stroke="${INK}"/></svg>`;
  let p = "M0 0 L0 -22", y = -22, rest = Math.round(kt / 5) * 5, shapes = "";
  while (rest >= 50) { shapes += `<path d="M0 ${y} L9 ${y + 3} L0 ${y + 6} Z" fill="${INK}"/>`; y += 7; rest -= 50; }
  while (rest >= 10) { p += ` M0 ${y} L9 ${y - 4}`; y += 4; rest -= 10; }
  if (rest >= 5) p += ` M0 ${y} L5 ${y - 2}`;
  return `<svg width="50" height="50" viewBox="-25 -25 50 50"><g transform="rotate(${from})">${shapes}<path d="${p}" stroke="${INK}" stroke-width="1.3" fill="none"/></g></svg>`;
}
function currentArrow(n, e) {
  const sp = Math.hypot(n, e), ang = Math.atan2(e, n) * 180 / Math.PI, len = 6 + Math.min(sp, 2) * 16;
  return `<svg width="50" height="50" viewBox="-25 -25 50 50"><g transform="rotate(${ang})" stroke="#0F47AF" stroke-width="1.6" fill="none"><path d="M0 ${len / 2} L0 ${-len / 2} M-3.5 ${-len / 2 + 5} L0 ${-len / 2} L3.5 ${-len / 2 + 5}"/></g></svg>`;
}
let fieldTimer;
function refreshField() {
  clearTimeout(fieldTimer);
  fieldTimer = setTimeout(async () => {
    const b = chart.getBounds(), t = $("#t0").value;
    layers.field.clearLayers();
    if (!t || b.getNorth() - b.getSouth() > 6) return;
    try {
      const f = await api(`/api/env/field?t=${t}:00&lat0=${b.getSouth()}&lat1=${b.getNorth()}&lon0=${b.getWest()}&lon1=${b.getEast()}&n=9`);
      fieldInfo = f; chips(f.sources);
      const showCurrents = !/assumed/.test(f.sources.current);       // never draw arrows for data we don't have
      f.lat.forEach((la, i) => {
        if (f.land[i]) return;
        const [wn, we] = f.wind[i], [cn, ce] = f.current[i], sp = Math.hypot(wn, we);
        L.marker([la, f.lon[i]], { icon: L.divIcon({ html: barb(sp, wn, we), className: "", iconSize: [50, 50], iconAnchor: [25, 25] }), keyboard: false })
          .bindTooltip(`wind ${fmt(sp)} m/s from ${fmt((Math.atan2(-we, -wn) * 180 / Math.PI + 360) % 360, 0)}°` +
            (showCurrents ? ` · current ${fmt(Math.hypot(cn, ce), 2)} m/s` : "") + ` · seas ~${fmt(f.hs[i])} m`).addTo(layers.field);
        if (showCurrents) L.marker([la, f.lon[i]], { icon: L.divIcon({ html: currentArrow(cn, ce), className: "", iconSize: [50, 50], iconAnchor: [25, 25] }), interactive: false, keyboard: false }).addTo(layers.field);
      });
      legend();
    } catch (e) { layers.field.clearLayers(); }
  }, 350);
}
chart.on("moveend", refreshField);
$("#t0").addEventListener("change", refreshField);
let legendExtra = [];
function legend(extra) {
  if (extra) legendExtra = extra;
  const items = [el("span", {}, el("i", { class: "k-barb" }), "wind (barb: flag 50 kt, line 10, half 5)")];
  if (fieldInfo && !/assumed/.test(fieldInfo.sources.current)) items.push(el("span", {}, el("i", { class: "k-cur" }), "surface current"));
  $("#legend").replaceChildren(...items, ...legendExtra);
}

// ---------------------------------------------------------------- fleet + links editor
let designs = [];
const fleet = [];
const links = [];
let pick = null;
const defaultZ = k => ({ uuv: 20, usv: 0, uav: 30 }[k] ?? 0);
function setMode(text) { const m = $("#chart-mode"); m.hidden = !text; m.textContent = text || ""; chart.getContainer().style.cursor = text ? "crosshair" : ""; }
chart.on("click", e => {
  if (!pick) return;
  const { lat, lng } = e.latlng, d = pick.drone;
  if (pick.what === "start") d.start = [lat, lng, d.start?.[2] ?? defaultZ(d.kind)];
  else d.legs.push({ type: "goto", to: [lat, lng, d.kind === "uuv" ? 100 : defaultZ(d.kind)] });
  pick = null; setMode(null); renderFleet();
});
addEventListener("keydown", e => { if (e.key === "Escape" && pick) { pick = null; setMode(null); } });

$("#add-drone").onclick = async () => {
  designs = await api("/api/designs");
  const ready = designs.filter(x => x.status === "done");
  if (!ready.length) return say("No characterized designs yet — the Hangar is still working on them.", true);
  const used = new Set(fleet.map(f => f.design));
  const dsg = ready.find(x => !used.has(x.id)) || ready[0];
  const base = dsg.name.toLowerCase().replace(/[^a-z0-9]+/g, "-");
  const n = { id: fleet.some(f => f.id === base) ? `${base}-${fleet.length + 1}` : base, design: dsg.id, kind: dsg.kind, start: null, legs: [],
    color: COLORS[fleet.length % COLORS.length] };
  fleet.push(n);
  pick = { drone: n, what: "start" }; setMode(`Click the chart where ${n.id} is deployed`);
  renderFleet();
};
const num = (v, on, attrs = {}) => el("input", { type: "number", value: v, step: "any", class: "inline", onchange: e => on(+e.target.value), ...attrs });
const designOf = d => designs.find(x => x.id === d.design);
const isGlider = d => designOf(d)?.shape === "glider";

function legRow(d, l, i) {
  let what;
  if (l.type === "goto" && l.to === "start") what = "Come back to the deployment point";
  else if (l.type === "goto") {
    const z = d.kind === "usv" ? null : num(l.to[2], v => l.to[2] = v, { "aria-label": d.kind === "uuv" ? "depth" : "altitude" });
    what = el("span", {}, `Go to ${fmt(l.to[0], 4)}, ${fmt(l.to[1], 4)}`, z ? (isGlider(d) ? ", gliding down to " : " at ") : "", z, z ? (d.kind === "uuv" ? " m deep" : " m up") : "");
  } else if (l.type === "hold") {
    what = el("span", {}, "Hold there for ", num(l.minutes, v => l.minutes = v), " min, within ", num(l.tol_m, v => l.tol_m = v), " m");
  } else {
    const others = fleet.filter(f => f !== d);
    if (!l.target && others[0]) l.target = others[0].id;
    what = el("span", {}, "Stay ", num(l.offset[2], v => l.offset[2] = v), " m above ",
      el("select", { class: "inline", onchange: e => l.target = e.target.value }, others.map(o => el("option", { value: o.id, selected: o.id === l.target || null }, o.id))),
      " for ", num(l.minutes, v => l.minutes = v), " min, within ", num(l.tol_m, v => l.tol_m = v), " m");
  }
  return el("div", { class: "leg" }, el("span", { class: "what" }, what), el("button", { class: "link", onclick: () => { d.legs.splice(i, 1); renderFleet(); } }, "remove"));
}

function renderFleet() {
  $("#fleet").replaceChildren(...fleet.map((d, idx) => {
    const dsg = designOf(d);
    return el("div", { class: "drone", style: `--c:${d.color}` },
      el("header", {}, el("span", { class: "name" }, d.id), el("span", { class: "kind" }, KIND[d.kind]),
        el("button", { class: "link x", onclick: () => { fleet.splice(idx, 1); links.splice(0, links.length, ...links.filter(l => l.a !== d.id && l.b !== d.id)); renderFleet(); } }, "remove")),
      el("select", { "aria-label": "design", onchange: e => { d.design = e.target.value; d.kind = designs.find(x => x.id === d.design).kind; renderFleet(); } },
        designs.filter(x => x.status === "done").map(x => el("option", { value: x.id, selected: x.id === d.design || null }, `${x.name} — ${KIND[x.kind]}`))),
      el("div", { class: "leg" }, el("span", { class: "what" }, d.start
          ? el("span", {}, `Deploy at ${fmt(d.start[0], 4)}, ${fmt(d.start[1], 4)}`, d.kind !== "usv" ? el("span", {}, ", ", num(d.start[2], v => d.start[2] = v), d.kind === "uuv" ? " m deep" : " m up") : null)
          : el("em", {}, "No deployment point yet")),
        el("button", { class: "link", onclick: () => { pick = { drone: d, what: "start" }; setMode(`Click where ${d.id} is deployed`); } }, d.start ? "move" : "place")),
      d.legs.map((l, i) => legRow(d, l, i)),
      el("div", { class: "adds" },
        el("button", { class: "link", onclick: () => { pick = { drone: d, what: "goto" }; setMode(`Click where ${d.id} should go`); } }, "+ go to a point"),
        el("button", { class: "link", onclick: () => { d.legs.push({ type: "hold", minutes: 20, tol_m: d.kind === "uav" ? 3 : 25 }); renderFleet(); } }, "+ hold there"),
        fleet.length > 1 ? el("button", { class: "link", onclick: () => { d.legs.push({ type: "follow", target: null, offset: [0, 0, d.kind === "uav" ? 30 : 0], minutes: 20, tol_m: d.kind === "uav" ? 5 : 100 }); renderFleet(); } }, "+ stay above another drone") : null,
        el("button", { class: "link", onclick: () => { d.legs.push({ type: "goto", to: "start" }); renderFleet(); } }, "+ come back"),
        d.start ? el("button", { class: "link", onclick: () => showReach(d) }, "where can it get to?") : null),
      dsg ? el("p", { class: "hint" }, `${fmt(dsg.cruise, 2)} m/s cruise · ${fmt(dsg.vmax, 2)} m/s max · ${dsg.battery_wh} Wh`) : null);
  }));
  renderLinks(); drawPlan();
}

function renderLinks() {
  const ids = fleet.map(f => f.id);
  $("#add-link").hidden = fleet.length < 2;
  $("#links").replaceChildren(...links.map((l, i) => el("div", { class: "linkrow" },
    el("select", { class: "inline", onchange: e => l.a = e.target.value }, ids.map(id => el("option", { value: id, selected: id === l.a || null }, id))),
    " ↔ ",
    el("select", { class: "inline", onchange: e => l.b = e.target.value }, ids.map(id => el("option", { value: id, selected: id === l.b || null }, id))),
    " within ", num(l.max_m, v => l.max_m = v), " m ",
    el("select", { class: "inline", onchange: e => l.mode = e.target.value }, [["horizontal", "horizontally"], ["3d", "in 3-D"]].map(([v, t]) => el("option", { value: v, selected: v === l.mode || null }, t))),
    ", ", num(Math.round(l.need * 100), v => l.need = v / 100, { min: 1, max: 100 }), "% of the time ",
    el("button", { class: "link", onclick: () => { links.splice(i, 1); renderLinks(); } }, "remove"))));
}
$("#add-link").onclick = () => {
  if (fleet.length < 2) return;
  links.push({ a: fleet[0].id, b: fleet[1].id, max_m: 1000, mode: "horizontal", need: 0.95 });
  renderLinks();
};

function drawPlan() {
  layers.plan.clearLayers();
  for (const d of fleet) {
    if (!d.start) continue;
    const pts = [d.start.slice(0, 2)];
    L.circleMarker(d.start.slice(0, 2), { radius: 6, color: d.color, weight: 2, fillColor: "#fff", fillOpacity: 1 }).bindTooltip(`${d.id} deployed here`).addTo(layers.plan);
    for (const l of d.legs) if (l.type === "goto") { const p = l.to === "start" ? d.start.slice(0, 2) : l.to.slice(0, 2); pts.push(p); L.circleMarker(p, { radius: 4, color: d.color, weight: 2, fillOpacity: 0 }).addTo(layers.plan); }
    L.polyline(pts, { color: d.color, weight: 1.5, dashArray: "4 5" }).addTo(layers.plan);
  }
}

// ---------------------------------------------------------------- where can it get to? (reachability)
async function showReach(d) {
  layers.reach.clearLayers();
  say(`Working out where ${d.id} can get to…`);
  try {
    const hours = +$("#max-hours").value || 6;
    const r = await api(`/api/reach?design=${d.design}&lat=${d.start[0]}&lon=${d.start[1]}&t=${$("#t0").value}:00&hours=${hours}&z=${d.start[2] || 0}`);
    const n = r.lat.length, cv = document.createElement("canvas"); cv.width = n; cv.height = n;
    const ctx = cv.getContext("2d"), img = ctx.createImageData(n, n);
    for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
      const h = r.hours[i][j], p = r.pessimistic_hours?.[i]?.[j], k = ((n - 1 - i) * n + j) * 4;   // canvas rows run north -> south
      if (h == null) { if (r.why[i][j] !== "land") img.data.set([213, 43, 30, 40], k); continue; }
      img.data.set(p != null || !r.pessimistic_hours ? [176, 39, 125, 115] : [176, 39, 125, 45], k);
    }
    ctx.putImageData(img, 0, 0);
    const bounds = [[r.lat[0], r.lon[0]], [r.lat[n - 1], r.lon[n - 1]]];
    L.imageOverlay(cv.toDataURL(), bounds, { interactive: false, className: "reach" }).addTo(layers.reach);
    legend([el("span", {}, el("i", { class: "k-reach" }), r.pessimistic_hours ? `${d.id} gets there even against 0.25 m/s of current` : `${d.id} gets there within ${fmt(r.horizon_h, 1)} h`),
      r.pessimistic_hours ? el("span", {}, el("i", { class: "k-reach2" }), "only if the water is slack") : null,
      el("span", {}, el("i", { class: "k-cant" }), "can't get there"),
      el("button", { class: "link", onclick: () => { layers.reach.clearLayers(); legend([]); } }, "clear")].filter(Boolean));
    say(`${d.id}: ${fmt(r.speed_through_fluid, 2)} m/s through the ${r.flow_kind === "wind" ? "air" : "water"}, endurance ${fmt(r.endurance_h, 1)} h, horizon ${fmt(r.horizon_h, 1)} h.` + (r.note ? ` ${r.note}` : "") + (r.warning ? ` Note: ${r.warning}.` : ""));
    chart.fitBounds(bounds, { padding: [10, 10] });
  } catch (e) { say(e.message, true); }
}

// ---------------------------------------------------------------- run + results
function say(t, err) { const h = $("#run-status"); h.textContent = t; h.classList.toggle("err", !!err); }
$("#run").onclick = async () => {
  if (!fleet.length) return say("Add a drone first.", true);
  const bad = fleet.find(d => !d.start);
  if (bad) return say(`${bad.id} has no deployment point.`, true);
  const body = {
    t0: $("#t0").value + ":00", max_hours: +$("#max-hours").value, samples: +$("#samples").value, reserve: +$("#reserve").value / 100,
    drones: fleet.map(d => ({ id: d.id, design: d.design, start: d.start, legs: d.legs.length ? d.legs : [{ type: "hold", minutes: 10, tol_m: 50 }] })),
    links: links.map(l => ({ ...l })),
  };
  $("#run").disabled = true; $("#results").replaceChildren(); layers.tracks.clearLayers(); layers.now.clearLayers();
  try { const { id } = await post("/api/missions", body); await pollMission(id); } catch (e) { say(e.message, true); }
  $("#run").disabled = false;
};
async function pollMission(id) {
  for (;;) {
    const m = await api(`/api/missions/${id}`), st = m.status || {};
    if (st.state === "done") {
      say(`Simulated ${mmss(m.result.t_sim)} of mission × ${m.result.samples} runs.`); showResult(m);
      history.replaceState(null, "", `?mission=${id}#plan`);      // the address bar is now a link to this result
      return m;
    }
    if (st.state === "failed") { say(st.error || "The simulation failed.", true); return; }
    say(`${st.state === "queued" ? "Waiting for the simulator…" : "Simulating…"} ${Math.round((st.progress || 0) * 100)}% of the time budget`);
    await new Promise(r => setTimeout(r, 2000));
  }
}

let current = null;
function verdictBlock(r, title, sub) {
  return el("div", { class: "verdict" }, flagSVG(r.verdict),
    el("div", {}, el("div", { class: "head" }, el("span", { class: "who" }, title), el("span", { class: "call" }, r.verdict)),
      el("div", { class: "meaning" }, `Flag ${FLAGS[r.verdict][0]}: ${FLAGS[r.verdict][1]}`)),
    el("p", { class: "why" }, sub));
}
const pct = r => r.p_interval && r.runs ? `${Math.round(r.p_success * 100)}% of ${r.runs} runs (90% sure the true rate is ${Math.round(r.p_interval[0] * 100)}–${Math.round(r.p_interval[1] * 100)}%)` : `${Math.round(r.p_success * 100)}%`;

function showResult(m) {
  const res = m.result, ids = m.mission.drones.map(x => x.id);
  const color = id => fleet.find(f => f.id === id)?.color || COLORS[ids.indexOf(id) % COLORS.length];
  const kindOf = id => fleet.find(f => f.id === id)?.kind || designs.find(x => x.id === m.mission.drones.find(y => y.id === id)?.design)?.kind;
  if (res.env) chips(res.env);
  current = { m, ids, color, kindOf, tmax: Math.max(...ids.map(id => res.drones[id].track.at(-1)?.t || 0), 1) };
  const parts = [];
  if (res.mode === "emulator") parts.push(el("p", { class: "chip ok" }, `Flown by real autopilot firmware: ${Object.values(res.firmware).join(", ")}`));
  if (res.fleet) {
    const why = res.fleet.reasons.length ? res.fleet.reasons.slice(0, 3).map(x => `${x.reason} (${Math.round(x.share * 100)}% of runs)`).join("; ") : "Every drone did its job and every range requirement held, in every run.";
    parts.push(el("h3", {}, "Can the fleet do it?"), verdictBlock(res.fleet, "Whole deployment", `${pct(res.fleet)}. ${why}`));
  }
  if (res.links?.length) { parts.push(el("h3", {}, "Staying in range")); for (const lk of res.links) parts.push(linkCard(lk)); }
  parts.push(el("h3", {}, "Depth and altitude over time"), profileChart(res, ids, color, kindOf));
  parts.push(el("h3", {}, "Each drone"));
  for (const id of ids) {
    const r = res.drones[id];
    const legs = (r.legs || []).map(l => l.type === "goto" ? (l.eta_min_p50 != null ? `arrives in ${fmt(l.eta_min_p50, 0)} min` : "doesn't arrive") : `${l.type} within ${fmt(l.err95_m_p50, 0)} m`).join(" → ");
    const why = r.reasons?.length ? r.reasons.slice(0, 2).map(x => x.reason).join("; ") : "did its job in every run";
    const card = verdictBlock(r, id, `${pct(r)}. ${why[0].toUpperCase() + why.slice(1)}.`);
    card.querySelector(".who").style.color = color(id);
    card.append(el("dl", {},
      el("div", {}, el("dt", {}, "legs"), el("dd", {}, legs || "—")),
      el("div", {}, el("dt", {}, "battery left"), el("dd", {}, `${fmt(r.battery_left_p50 * 100, 0)}%`)),
      el("div", {}, el("dt", {}, "speed"), el("dd", {}, r.cruise_mps != null ? `${fmt(r.cruise_mps, 2)} m/s` : "—"))));
    parts.push(card);
  }
  $("#results").replaceChildren(...parts);
  layers.tracks.clearLayers();
  const all = [];
  for (const id of ids) {
    const tr = res.drones[id].track;
    for (let s = Math.min(8, tr[0]?.lat.length || 0) - 1; s >= 0; s--) {
      const pts = tr.map(row => [row.lat[s], row.lon[s]]);
      L.polyline(pts, { color: color(id), weight: s ? 1 : 2.5, opacity: s ? 0.25 : 1 }).addTo(layers.tracks);
      if (!s) all.push(...pts);
    }
  }
  legend([el("span", {}, el("i", { class: "k-trk" }), "track (faint: other Monte Carlo runs)"), el("span", {}, el("i", { class: "k-ok" }), "in range now"), el("span", {}, el("i", { class: "k-bad" }), "out of range now"),
    ...((res.links || []).some(l => l.from_min || l.until_min != null) ? [el("span", {}, el("i", { class: "k-off" }), "not required now")] : [])]);
  if (all.length) chart.fitBounds(all, { padding: [40, 40], maxZoom: 17 });
  $("#scrubber").hidden = false;
  scrub(current.tmax);
}

function rowAt(track, t) { let lo = 0, hi = track.length - 1; while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (track[mid].t <= t) lo = mid; else hi = mid - 1; } return track[lo]; }
function scrub(t) {
  if (!current) return;
  const { m, ids, color, kindOf } = current, res = m.result;
  $("#tslider").value = t / current.tmax; $("#tclock").textContent = mmss(t);
  layers.now.clearLayers();
  const pos = {};
  for (const id of ids) {
    const r = rowAt(res.drones[id].track, t);
    pos[id] = [r.lat[0], r.lon[0], r.z[0]];
    const where = kindOf(id) === "uuv" ? `${fmt(-r.z[0], 0)} m deep` : kindOf(id) === "uav" ? `${fmt(r.z[0], 0)} m up` : "on the surface";
    L.circleMarker(pos[id].slice(0, 2), { radius: 7, color: "#fff", weight: 2, fillColor: color(id), fillOpacity: 1 }).bindTooltip(`${id} · ${where}`).addTo(layers.now);
  }
  for (const lk of res.links || []) {
    const a = pos[lk.a], b = pos[lk.b]; if (!a || !b) continue;
    const dh = chart.distance(a.slice(0, 2), b.slice(0, 2)), d = lk.mode === "3d" ? Math.hypot(dh, a[2] - b[2]) : dh, ok = d <= lk.max_m;
    const off = t < (lk.from_min || 0) * 60 || (lk.until_min != null && t > lk.until_min * 60);   // outside its window: not judged
    L.polyline([a.slice(0, 2), b.slice(0, 2)], off ? { color: "#8a8f98", weight: 1.5, dashArray: "2 6" }
      : { color: ok ? "#1F6E43" : "#D52B1E", weight: 3, dashArray: ok ? null : "6 6" })
      .bindTooltip(`${lk.a} ↔ ${lk.b}: ${fmt(d, 0)} m` + (off ? " (not required now)" : ` (needs ≤ ${lk.max_m} m)`)).addTo(layers.now);
  }
  document.querySelectorAll(".cursor").forEach(c => { const W = +c.dataset.w, x = 40 + (t / current.tmax) * (W - 50); c.setAttribute("x1", x); c.setAttribute("x2", x); });
}
let playing = false;
$("#tslider").oninput = e => { playing = false; $("#play").textContent = "Play"; scrub(+e.target.value * current.tmax); };
$("#play").onclick = () => {
  if (!current) return;
  playing = !playing; $("#play").textContent = playing ? "Pause" : "Play";
  let last = performance.now(), t = +$("#tslider").value * current.tmax;
  if (t >= current.tmax) t = 0;
  const speed = Math.max(current.tmax / 40, 1);    // the whole mission plays in ~40 s
  (function loop(now) { if (!playing) return; t = Math.min(t + (now - last) / 1000 * speed, current.tmax); last = now; scrub(t); if (t < current.tmax) requestAnimationFrame(loop); else { playing = false; $("#play").textContent = "Play"; } })(last);
};

// small SVG time-series charts: x = mission time, a cursor line follows the scrubber
function axes(W, H, ylo, yhi, label) {
  const s = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "tchart" });
  const T = current?.tmax || 1;
  const X = t => 40 + (t / T) * (W - 50), Y = v => 8 + (1 - (v - ylo) / ((yhi - ylo) || 1)) * (H - 26);
  s.append(svgEl("line", { x1: 40, x2: W - 10, y1: H - 18, y2: H - 18, class: "axis" }));
  const txt = (x, y, a, t) => { const n = svgEl("text", { x, y, "text-anchor": a, class: "tick" }); n.textContent = t; s.append(n); };
  txt(36, Y(ylo) + 4, "end", fmt(ylo, 0)); txt(36, Y(yhi) + 4, "end", fmt(yhi, 0));
  txt(W - 10, H - 4, "end", mmss(T)); txt(40, H - 4, "start", label);
  return { s, X, Y, txt };
}
function cursor(s, X, H, W) { s.append(svgEl("line", { x1: X(0), x2: X(0), y1: 4, y2: H - 18, class: "cursor", "data-w": W })); }
function linkCard(lk) {
  const tl = lk.timeline, W = 380, H = 120;
  const hi = Math.max(lk.max_m * 1.4, ...(tl.p90.length ? tl.p90 : [0]), ...(tl.nominal.length ? tl.nominal : [0]));
  const { s, X, Y, txt } = axes(W, H, 0, hi, "separation (m)");
  s.append(svgEl("rect", { x: 40, y: 8, width: W - 50, height: Math.max(Y(lk.max_m) - 8, 0), class: "toofar" }));
  if (tl.t.length) {
    const band = tl.t.map((t, i) => `${X(t)},${Y(tl.p90[i])}`).join(" ") + " " + tl.t.map((t, i) => `${X(t)},${Y(tl.p10[i])}`).reverse().join(" ");
    s.append(svgEl("polygon", { points: band, class: "band" }));
    s.append(svgEl("polyline", { points: tl.t.map((t, i) => `${X(t)},${Y(tl.nominal[i])}`).join(" "), class: "nominal" }));
  }
  s.append(svgEl("line", { x1: 40, x2: W - 10, y1: Y(lk.max_m), y2: Y(lk.max_m), class: "limit" }));
  txt(W - 12, Y(lk.max_m) - 4, "end", `limit ${lk.max_m} m`);
  cursor(s, X, H, W);
  const v = lk.verdict || (lk.p_success >= 0.9 ? "GO" : "NO-GO");     // older results carry no verdict
  return el("div", { class: "linkcard" },
    el("div", { class: "head" }, el("span", { class: "who" }, `${lk.a} ↔ ${lk.b}`),
      el("span", { class: `call ${v === "GO" ? "good" : "bad"}` }, `${v}: within ${lk.max_m} m for ${Math.round(lk.need * 100)}% of the time in ${Math.round(lk.p_success * 100)}% of runs`)),
    s,
    el("p", { class: "hint" }, `In range ${fmt(lk.in_range_p50 * 100, 0)}% of the time in a typical run (worst 10% of runs: ${fmt(lk.in_range_p10 * 100, 0)}%). ` +
      `Longest gap: ${fmt(lk.longest_outage_s_p50, 0)} s typical, ${fmt(lk.longest_outage_s_p90, 0)} s in a bad run.` +
      (lk.never_acquired > 0 ? ` Never got within range in ${fmt(lk.never_acquired * 100, 0)}% of runs.` : "") +
      ` Line: the nominal run. Shaded: the middle 80% of runs. Red zone: too far apart.`));
}
function profileChart(res, ids, color, kindOf) {
  const W = 380, H = 160;
  let lo = 0, hi = 0;
  for (const id of ids) for (const r of res.drones[id].track) { lo = Math.min(lo, r.z[0]); hi = Math.max(hi, r.z[0]); }
  hi = Math.max(hi * 1.1, 5); lo = Math.min(lo * 1.1, -5);
  const { s, X, Y } = axes(W, H, lo, hi, "height above sea level (m); below 0 is depth");
  s.insertBefore(svgEl("rect", { x: 40, y: Y(0), width: W - 50, height: Math.max(Y(lo) - Y(0), 0), class: "sea" }), s.firstChild);
  s.append(svgEl("line", { x1: 40, x2: W - 10, y1: Y(0), y2: Y(0), class: "surface" }));
  for (const id of ids) {
    const tr = res.drones[id].track, step = Math.max(1, Math.floor(tr.length / 400));
    s.append(svgEl("polyline", { points: tr.filter((_, i) => i % step === 0).map(r => `${X(r.t)},${Y(r.z[0])}`).join(" "), fill: "none", stroke: color(id), "stroke-width": 1.8 }));
  }
  cursor(s, X, H, W);
  return el("div", { class: "linkcard" }, s, el("p", { class: "hint" }, ...ids.flatMap((id, i) => [i ? " · " : "", el("span", { style: `color:${color(id)}` }, "■ "), `${id} (${KIND[kindOf(id)] || ""})`])));
}

// ---------------------------------------------------------------- hangar
let designTimer = null, shapeDefs = null;
async function loadDesigns() {
  designs = await api("/api/designs");
  $("#designs").replaceChildren(...designs.map(d => el("div", { class: "design", tabindex: 0, onclick: () => showDesign(d.id), onkeydown: e => e.key === "Enter" && showDesign(d.id) },
    el("div", {}, el("div", { class: "dname" }, d.name), el("div", { class: "meta" }, `${KIND[d.kind]} · ${fmt(d.mass, 1)} kg · ${d.power_w} W · ${d.battery_wh} Wh`)),
    el("span", { class: `state ${d.status}` }, d.status === "running" ? d.step : d.status === "done" ? "ready" : d.status),
    d.status === "running" ? el("div", { class: "bar" }, el("i", { style: `width:${Math.round(d.progress * 100)}%` })) : null)));
  clearTimeout(designTimer);
  if (designs.some(d => d.status === "running" || d.status === "queued")) designTimer = setTimeout(() => !$("#view-hangar").hidden && loadDesigns(), 5000);
}
const SRC = v => el("span", { class: `tag ${/cfd|bem/.test(String(v)) ? "cfd" : ""}` }, v);
async function showDesign(id) {
  const d = await api(`/api/designs/${id}`);
  const r = d.result || {}, g = r.geometry || {}, f = r.fea || {}, p = r.performance || r.estimates || {}, hg = r.hangar || {};
  const facts = [];
  const fact = (k, v, extra) => facts.push(el("div", { class: "fact" }, el("dt", {}, k), el("dd", {}, v, extra || null)));
  if (g.length) fact("size", `${fmt(g.length, 2)} × ${fmt(g.beam, 2)} × ${fmt(g.height, 2)} m`);
  if (p.cruise) fact("cruise / max speed", `${fmt(p.cruise, 2)} / ${fmt(p.vmax, 2)} m/s`);
  if (g.draft) fact("draft · stability (GM)", `${fmt(g.draft, 3)} m · ${fmt(g.gm, 3)} m`);
  if (g.net_buoyancy_N != null) fact("net buoyancy", `${fmt(g.net_buoyancy_N, 1)} N`, el("small", {}, Math.abs(g.net_buoyancy_N) < 1 ? " neutral" : g.net_buoyancy_N > 0 ? " floats up" : " sinks"));
  if (hg.cfd) { const q = 0.5 * hg.cfd.rho * hg.cfd.speed ** 2; for (const [dir, x] of Object.entries(hg.cfd.dirs)) { const ax = { x: 0, y: 1, z: 2 }[dir[1]], s = dir[0] === "+" ? 1 : -1; fact(`drag area ${dir}`, `${fmt(-s * x.force[ax] / q, 4)} m²`, el("small", {}, ` ±${fmt((x.gci || 0) * 100, 0)}%`)); } }
  if (hg.fs) for (const [U, x] of Object.entries(hg.fs.speeds)) fact(`resistance @ ${fmt(+U, 2)} m/s`, `${fmt(x.resistance, 2)} N`, el("small", {}, ` ±${fmt((x.gci || 0) * 100, 0)}%`));
  if (hg.bem) { const A = hg.bem.added_mass; fact("added mass surge/sway/heave", `${fmt(A[0][0], 1)} / ${fmt(A[1][1], 1)} / ${fmt(A[2][2], 1)} kg`); }
  const cases = f.cases || [];
  const sfClass = sf => sf == null ? "" : sf < 1 ? "bad" : sf < 1.5 ? "warn" : "good";
  const viewer = el("div", { id: "viewer" });
  const caseSel = cases.length ? el("select", { class: "inline", onchange: e => { viewer.replaceChildren(); showModel(id, viewer, e.target.value); } },
    cases.map(c => el("option", { value: c.key, selected: c.name === f.worst_case || null }, c.name))) : null;
  $("#design-detail").replaceChildren(
    el("h1", {}, d.name), el("p", { class: "lede" }, `${KIND[d.kind]} · ${fmt(d.spec.mass, 1)} kg · ${d.spec.power_w} W · ${d.spec.battery_wh} Wh${d.spec.shape ? ` · built from a ${d.spec.shape} shape` : ""}`),
    ...(d.errors || []).map(e => el("div", { class: "error" }, e)), ...(d.warnings || []).map(w => el("div", { class: "warnbox" }, w)),
    caseSel ? el("p", { class: "hint" }, "Stress shown for: ", caseSel) : null, viewer,
    cases.length ? el("h3", {}, "Structure (FEA)") : null,
    cases.length ? el("table", { class: "cases" }, el("thead", {}, el("tr", {}, ["load case", "what it means", "safety factor", "stress", "deflection"].map(h => el("th", {}, h)))),
      el("tbody", {}, cases.map(c => el("tr", {}, el("td", {}, c.name),
        el("td", { class: "src" }, c.what + (c.crush_depth_m ? ` — collapses at ~${fmt(c.crush_depth_m, 0)} m, rated to ${fmt(c.rated_depth_m, 0)} m (limited by ${c.limited_by})` : "") + (c.note ? ` (${c.note})` : "")),
        el("td", { class: `n ${sfClass(c.safety_factor)}` }, fmt(c.safety_factor, 2)), el("td", { class: "n" }, `${fmt(c.vm_p99_mpa, 1)} MPa`), el("td", { class: "n" }, `${fmt(c.u_max_mm, 2)} mm`))))) : null,
    f.frequencies_hz ? el("p", { class: "hint" }, `Frame's first vibration mode ${fmt(f.frequencies_hz[0], 0)} Hz vs rotors ${fmt(f.hover_rotor_hz, 0)}–${fmt(f.max_rotor_hz, 0)} Hz${f.resonance ? " — RESONANCE RISK" : " — clear of each other"}.`) : null,
    el("h3", {}, "Performance"), el("dl", { class: "facts" }, facts),
    p.sources ? el("p", {}, "Where each number comes from: ", ...Object.entries(p.sources).map(([k, v]) => el("span", {}, ` ${k.replace("_", " ")}`, SRC(v)))) : null,
    el("h3", {}, d.status === "done" ? "Characterization log" : `Working: ${d.step || d.status}`),
    el("div", { class: "log" }, (d.log || []).join("\n") || "waiting in the queue"),
    el("p", {}, d.sample ? null : el("button", { class: "link", onclick: async () => { if (confirm(`Delete ${d.name}?`)) { await api(`/api/designs/${id}`, { method: "DELETE" }); $("#design-detail").replaceChildren(); loadDesigns(); } } }, "delete this design"),
      " ", el("button", { class: "link", onclick: async () => { await api(`/api/designs/${id}/rerun`, { method: "POST" }); loadDesigns(); } }, "characterize again")));
  showModel(id, viewer, caseSel?.value || "");
}

// ---------------------------------------------------------------- 3D model + stress (three.js, vendored)
let THREE, Orbit;
async function three() { if (!THREE) { THREE = await import("/static/vendor/three.module.min.js"); Orbit = (await import("/static/vendor/OrbitControls.js")).OrbitControls; } return THREE; }
const RAMP = ["#1E3B52", "#2E7FA8", "#B0277D", "#D52B1E"];
function rampColor(T, f) { const x = Math.min(Math.max(f, 0), 1) * (RAMP.length - 1), i = Math.min(Math.floor(x), RAMP.length - 2); return new T.Color(RAMP[i]).lerp(new T.Color(RAMP[i + 1]), x - i); }
async function showModel(id, box, kase) {
  const T = await three();
  const m = await api(`/api/designs/${id}/mesh?case=${encodeURIComponent(kase || "")}`);
  const g = new T.BufferGeometry();
  g.setAttribute("position", new T.Float32BufferAttribute(m.vertices, 3)); g.setIndex(m.faces); g.computeVertexNormals();
  let vmax = null;
  if (m.vm) {
    const s = [...m.vm].sort((a, b) => a - b); vmax = s[Math.floor(s.length * 0.99)] || 1;
    const c = new Float32Array(m.vm.length * 3); m.vm.forEach((v, i) => rampColor(T, v / vmax).toArray(c, i * 3));
    g.setAttribute("color", new T.Float32BufferAttribute(c, 3));
  }
  g.computeBoundingBox(); const ctr = new T.Vector3(); g.boundingBox.getCenter(ctr); g.translate(-ctr.x, -ctr.y, -ctr.z);
  const scene = new T.Scene(), cam = new T.PerspectiveCamera(35, box.clientWidth / box.clientHeight, 0.001, 200);
  const r = new T.WebGLRenderer({ antialias: true, alpha: true }); r.setSize(box.clientWidth, box.clientHeight); r.setPixelRatio(devicePixelRatio);
  box.append(r.domElement);
  const mesh = new T.Mesh(g, new T.MeshStandardMaterial({ color: vmax ? 0xffffff : 0x9fb6c3, vertexColors: !!vmax, metalness: 0.1, roughness: 0.7, side: T.DoubleSide }));
  mesh.rotation.x = -Math.PI / 2;                 // model frame: x forward, z up  ->  three.js: y up
  scene.add(mesh, new T.HemisphereLight(0xffffff, 0x445566, 2.2), new T.DirectionalLight(0xffffff, 1.2));
  g.computeBoundingSphere(); const R = g.boundingSphere.radius;
  cam.position.set(R * 1.4, R * 1.0, R * 2.0); cam.lookAt(0, 0, 0);
  const ctl = new Orbit(cam, r.domElement); ctl.enableDamping = true;
  const len = g.boundingBox.max.x - g.boundingBox.min.x;
  box.append(el("div", { class: "scale" }, vmax ? el("div", {}, "von Mises stress", el("div", { class: "ramp" }), `0 — ${fmt(vmax, 1)} MPa (99th pct)`) : el("div", {}, "shape only (no FEA yet)"), el("div", {}, `${fmt(len, 2)} m long · drag to rotate`)));
  (function loop() { if (!box.isConnected) return r.dispose(); ctl.update(); r.render(scene, cam); requestAnimationFrame(loop); })();
}

// ---------------------------------------------------------------- add a design (shape or file)
const dlg = $("#design-dialog"), form = $("#design-form");
$("#new-design").onclick = async () => {
  if (!$("#material").options.length) for (const [k, v] of Object.entries({ al6061: "Aluminium 6061-T6", ti6al4v: "Titanium Ti-6Al-4V", ss316: "Stainless 316", cfrp: "Carbon fibre", gfrp: "Glass fibre", abs: "ABS", pla: "PLA", petg: "PETG", hdpe: "HDPE", pmma: "Acrylic", pom: "Acetal (POM)" })) $("#material").append(el("option", { value: k }, v));
  if (!shapeDefs) { shapeDefs = await api("/api/shapes"); $("#shape-select").replaceChildren(...Object.entries(shapeDefs).map(([k, v]) => el("option", { value: k }, `${v.label} — ${KIND[v.kind]}`))); }
  syncForm(); dlg.showModal();
};
function syncForm() {
  const src = form.source.value, shape = form.shape.value, sd = shapeDefs?.[shape];
  document.querySelectorAll(".only-shape").forEach(n => n.hidden = src !== "shape");
  document.querySelectorAll(".only-file").forEach(n => n.hidden = src !== "file");
  form.mesh.required = src === "file";
  const kind = src === "shape" ? sd?.kind : form.kind.value, glider = src === "shape" && shape === "glider";
  document.querySelectorAll(".k-glider").forEach(n => n.hidden = !glider);
  document.querySelectorAll(".k-prop").forEach(n => n.hidden = glider);
  form.mass.required = kind !== "uuv";
  form.mass.placeholder = kind === "uuv" ? "blank = neutrally buoyant" : "";
  form.structure.value = kind === "uav" ? "solid" : "shell";
  if (src === "shape" && sd) $("#shape-dims").replaceChildren(...Object.entries(sd.params).map(([k, p]) =>
    el("label", {}, `${p.label} (m)`, el("input", { name: `dim_${k}`, type: "number", step: "any", value: p.default, min: p.min, max: p.max }))));
}
form.addEventListener("change", e => { if (["source", "shape", "kind"].includes(e.target.name)) syncForm(); });
form.addEventListener("submit", async e => {
  if (e.submitter?.value !== "ok") return;
  e.preventDefault();
  const fd = new FormData(form), spec = {};
  for (const [k, v] of fd) if (!["mesh", "source", "shape"].includes(k) && !k.startsWith("dim_") && v !== "") spec[k] = v;
  $("#design-submit").disabled = true; $("#design-error").textContent = "Working…"; $("#design-error").classList.remove("err");
  try {
    let d;
    if (fd.get("source") === "shape") {
      const dims = {}; for (const [k, v] of fd) if (k.startsWith("dim_")) dims[k.slice(4)] = +v;
      delete spec.kind; delete spec.units; delete spec.forward; delete spec.up;
      d = await post("/api/designs/shape", { shape: fd.get("shape"), dims, spec });
    } else {
      const body = new FormData(); body.append("mesh", fd.get("mesh")); body.append("spec", JSON.stringify(spec));
      d = await api("/api/designs", { method: "POST", body });
    }
    dlg.close(); form.reset(); $("#design-error").textContent = "";
    await loadDesigns(); showDesign(d.id);
  } catch (err) { $("#design-error").textContent = err.message; $("#design-error").classList.add("err"); }
  $("#design-submit").disabled = false;
});

// ---------------------------------------------------------------- receipts
async function loadReceipts() {
  const rows = await api("/api/receipts");
  const scored = rows.filter(r => r.kind !== "context"), pass = scored.filter(r => r.ok).length;
  $("#receipt-summary").textContent = rows.length ? `${pass} of ${scored.length} checks pass · ${rows.length - scored.length} context rows` : "No receipts yet: they are produced by the test run on the server.";
  const body = []; let group = null;
  for (const r of rows) {
    if (r.group !== group) { group = r.group; body.push(el("tr", { class: "group-row" }, el("td", { colspan: 6 }, group))); }
    const ref = r.kind === "bracket" ? `${fmt(r.lo, 3)} … ${fmt(r.hi, 3)}` : fmt(r.reference, 4);
    const err = r.kind === "bracket" || r.kind === "context" ? "" : r.rel ? `${fmt(r.error * 100, 1)}% (≤${fmt(r.tol * 100, 0)}%)` : fmt(r.error, 3);
    body.push(el("tr", { class: r.kind === "context" ? "context" : r.ok ? "" : "fail" },
      el("td", {}, r.claim), el("td", { class: "n" }, `${fmt(r.value, 4)} ${r.unit || ""}`), el("td", { class: "n" }, ref), el("td", { class: "n" }, err),
      el("td", {}, r.kind === "context" ? "" : el("span", { class: r.ok ? "pass" : "failt" }, r.ok ? "PASS" : "FAIL")), el("td", { class: "src" }, r.source)));
  }
  $("#receipt-table").replaceChildren(el("thead", {}, el("tr", {}, ["claim", "ours", "reference", "error", "", "source"].map(h => el("th", {}, h)))), el("tbody", {}, body));
}

// ---------------------------------------------------------------- emulator: ArduPilot SITL, and your own code
async function loadEmulator() {
  const list = await api("/api/missions");
  const sel = $("#emu-mission");
  sel.replaceChildren(...list.filter(m => m.state === "done").map(m => el("option", { value: m.id }, `${m.t0?.replace("T", " ").slice(0, 16) || ""} · ${m.drones.join(", ")}`)));
  sel.onchange = () => renderSitl(sel.value);
  if (sel.value) renderSitl(sel.value); else $("#sitl").replaceChildren();
  $("#api-snippet").textContent = `import requests
API = "${location.origin}/api"
s = requests.post(f"{API}/live", json={
    "t0": "${$("#t0").value || "2023-03-07T17:00"}:00",
    "drones": [{"id": "glider", "design": "sample-petrel", "start": [10.0, -95.0, 5]},
               {"id": "boat",   "design": "sample-tern",   "start": [9.998, -95.0, 0]}],
    "links":  [{"a": "glider", "b": "boat", "max_m": 1000}]}).json()
sid, state = s["id"], s["state"]
for _ in range(180):                         # 30 minutes in 10 s steps
    g = state["drones"]["glider"]
    targets = {"glider": {"lat": 10.02, "lon": -95.0, "z": 100},
               "boat":   {"lat": g["lat"], "lon": g["lon"]}}     # your logic here
    state = requests.post(f"{API}/live/{sid}/step",
                          json={"seconds": 10, "targets": targets}).json()
    print(state["t"], state["links"])
requests.delete(f"{API}/live/{sid}")`;
}
function renderSitl(missionId) {
  const status = el("p", { class: "hint" }), msgs = el("div", { class: "log", hidden: true });
  const btn = el("button", { class: "go wide", onclick: async () => {
    btn.disabled = true; status.textContent = "Booting ArduPilot…"; status.classList.remove("err");
    try {
      const { id } = await post("/api/emulations", { mission: missionId });
      for (;;) {
        const e = await api(`/api/emulations/${id}`), st = e.status || {};
        if (st.state === "failed") { status.textContent = st.error; status.classList.add("err"); break; }
        if (st.state === "done") {
          status.textContent = Object.entries(e.result.drones).map(([k, d]) => `${k} (${e.result.firmware[k]}): ${d.verdict}${d.reasons.length ? " — " + d.reasons[0].reason : ""}`).join(" · ");
          const all = Object.entries(e.result.drones).flatMap(([k, d]) => (d.autopilot_messages || []).map(m => `${k} t=${m.t}s  ${m.text}`));
          msgs.textContent = all.join("\n"); msgs.hidden = !all.length;
          $("#emu-detail").replaceChildren(el("p", {}, "The firmware-flown run is loaded on the Plan page: ", el("a", { href: "#plan" }, "see it there"), "."));
          location.hash = "plan"; showResult({ mission: e.mission, result: e.result });
          break;
        }
        status.textContent = `${st.step || st.state} · ${Math.round((st.progress || 0) * 100)}%`;
        await new Promise(r => setTimeout(r, 2000));
      }
    } catch (err) { status.textContent = err.message; status.classList.add("err"); }
    btn.disabled = false;
  } }, "Fly it with ArduPilot");
  $("#sitl").replaceChildren(el("h3", {}, "Real autopilot firmware"),
    el("p", { class: "hint" }, "ArduCopter for quads, ArduRover for boats, ArduSub for thruster-driven subs. Gliders and finned torpedoes have no ArduPilot firmware; they fly with the built-in autopilot. QGroundControl can watch on TCP 5762 (+10 per extra drone)."),
    btn, status, msgs);
}

// ---------------------------------------------------------------- boot
(async () => {
  route();
  try { await loadCoverage(); refreshField(); } catch (e) { $("#coverage").textContent = "server unreachable"; }
  designs = await api("/api/designs").catch(() => []);
  legend([]);
  const q = new URLSearchParams(location.search);       // ?mission=<id> or ?emulation=<id> opens a finished run
  for (const kind of ["mission", "emulation"]) {
    const id = q.get(kind);
    if (!id) continue;
    try {
      const m = await api(`/api/${kind}s/${id}`);
      if (m.result) { if (m.mission?.t0) $("#t0").value = m.mission.t0.slice(0, 16); showResult({ mission: m.mission, result: m.result }); say(`Showing ${kind} ${id}.`); }
      else say(`That ${kind} hasn't finished (${m.status?.state}).`, true);
    } catch (e) { say(e.message, true); }
  }
})();
