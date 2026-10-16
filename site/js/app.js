import { drawRegional } from "./chart.js";
import { createLocal } from "./local.js";
import { Env } from "./env.js";
import { simulate } from "./sim.js";
import { defaultPlan, DATES, NAMES } from "./plan.js";

const $ = s => document.querySelector(s);
const load = name => fetch(`data/${name}.json`).then(r => { if (!r.ok) throw new Error(`data/${name}.json ${r.status}`); return r.json(); });
const FLAG = { GO: "C", MARGINAL: "U", "NO-GO": "N" };
const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ---- Day / Night (ECDIS palettes)
const root = document.documentElement, palBtn = $("#palette");
const isNight = () => root.dataset.palette ? root.dataset.palette === "night" : matchMedia("(prefers-color-scheme: dark)").matches;
const palLabel = () => { palBtn.textContent = isNight() ? "Day" : "Night"; palBtn.setAttribute("aria-pressed", String(isNight())); };
palBtn.addEventListener("click", () => { root.dataset.palette = isNight() ? "day" : "night"; try { localStorage.setItem("palette", root.dataset.palette); } catch (e) {} palLabel(); });
palLabel();

const [land, depth, wind, V] = await Promise.all(["land", "depth", "wind", "vehicles"].map(load));
const ocean = await load("ocean").catch(() => null);           // optional: without it the water is calm, and the results say so
const data = { land, depth, wind, ocean };

let plan = defaultPlan("2023"), env = null, result = null, mode = "regional", frameIdx = 0, timer = null;
const svg = d3.select("#map"), hint = $("#hint");
const local = createLocal(svg, { onDrag });

// ---- when: 2023 snapshot, or any start hour on the 2018 day that leaves two hours of weather
const hourSel = $("#hour");
for (let h = 0; h <= 22; h++) {
  const d = new Date(Date.UTC(2018, 1, 3, 12 + h));
  const o = document.createElement("option");
  o.value = d.toISOString(); o.textContent = `${d.getUTCDate() === 4 ? "4 Feb, " : ""}${String(d.getUTCHours()).padStart(2, "0")}:00`;
  if (h === 2) o.selected = true;
  hourSel.append(o);
}
function setWhen() {
  const date = document.querySelector('input[name="date"]:checked').value;
  plan.date = date;
  plan.start = date === "2023" ? new Date(DATES["2023"].start) : new Date(hourSel.value);
  hourSel.disabled = date !== "2018";
  stale();
  render();
}
document.querySelectorAll('input[name="date"]').forEach(r => r.addEventListener("change", setWhen));
hourSel.addEventListener("change", () => { document.querySelector('input[value="2018"]').checked = true; setWhen(); });

// ---- numbers in the panel
$("#minutes").addEventListener("change", e => { plan.drone.minutes = clamp(+e.target.value, 1, 60, e.target); plan.links[1].until = plan.drone.minutes + 2; stale(); });
$("#range0").addEventListener("change", e => { plan.links[0].max = clamp(+e.target.value, 50, 20000, e.target); stale(); });
$("#range1").addEventListener("change", e => { plan.links[1].max = clamp(+e.target.value, 20, 5000, e.target); stale(); });
function clamp(v, lo, hi, input) { const x = Math.min(hi, Math.max(lo, isFinite(v) ? v : lo)); input.value = x; return x; }

// ---- picking a spot on the regional chart
$("#pick").addEventListener("click", () => { mode = "regional"; stop(); render(); say("Click the sea to deploy there."); });
function onPick([lat, lon], seaDepth) {
  if (!(seaDepth > 0)) return say("That's land. Click somewhere in the sea.");
  if (seaDepth < 150) return say(`Only ${Math.round(seaDepth)} m deep there; the glider dives to 100 m. Try deeper water.`);
  plan.site = [lat, lon];
  $("#where").textContent = `${lat.toFixed(2)}° N, ${(-lon).toFixed(2)}° W`;
  mode = "local"; stale(); render(); say("");
}

// ---- dragging on the local plan
function onDrag(what, m, done) {
  if (what === "goal") plan.glider.goal = m; else plan[what].start = m;
  if (done) { stale(); render(); }
}

function stale() {
  result = null; stop(); frameIdx = 0;
  $("#results").innerHTML = "";
  $("#play").disabled = true;
  drawStrip();
}

function render() {
  env = new Env(data, plan.date, plan.start);
  if (mode === "regional") {
    const hour = wind.frames.find(f => plan.date === "2023" ? f.snapshot : new Date(f.t + "Z").getTime() === plan.start.getTime()) || wind.frames[0];
    drawRegional(svg, data, { site: plan.site, frame: hour, onPick });
  } else {
    local.draw(plan, env, env.seaDepthAt(...plan.site));
    if (result) { local.setResult(result); local.setTime(frameIdx); }
  }
}
function say(text) { hint.textContent = text; }

// ---- run
$("#run").addEventListener("click", () => {
  const btn = $("#run");
  btn.disabled = true; btn.textContent = "Running…";
  setTimeout(() => {                                          // let the label paint before the work
    mode = "local";
    env = new Env(data, plan.date, plan.start);
    result = simulate(plan, env, V, 24);
    btn.disabled = false; btn.textContent = "Run again";
    render();
    showResults();
    $("#play").disabled = false;
    frameIdx = 0; drawStrip(); play();
  }, 30);
});

function showResults() {
  const r = result, flag = v => `<svg class="flag" viewBox="0 0 30 20" aria-hidden="true"><use href="#flag-${FLAG[v]}"/></svg>`;
  const runs = r.runs - 1;
  const why = rs => rs.length ? rs.slice(0, 2).map(x => `${esc(x.reason)} (${x.n} of ${runs} runs)`).join("; ") : "";
  const veh = (id, ok) => {
    const v = r.vehicles[id];
    const good = id === "glider" ? (v.eta ? `reaches the goal in ${Math.round(v.eta)} min` : "")
      : id === "boat" ? `stays with Petrel; waves up to ${v.hs.toFixed(1)} m` : `lands with ${Math.round(v.left50 * 100)} % battery`;
    return `<div class="res">${flag(v.verdict)}<div class="who">${NAMES[id]}</div><div class="why">${why(v.reasons) || good}</div></div>`;
  };
  let html = `<div class="res fleet">${flag(r.fleet.verdict)}<div class="who">${r.fleet.verdict === "GO" ? "Go" : r.fleet.verdict === "MARGINAL" ? "Marginal" : "No go"}</div><div class="why">${Math.round(r.fleet.p * 100)} % of ${runs} runs work${r.fleet.reasons.length ? ". Main problem: " + esc(r.fleet.reasons[0].reason) : ""}</div></div>`;
  html += ["glider", "boat", "drone"].map(id => veh(id)).join("");
  html += r.links.map(l => `<div class="res">${flag(l.verdict)}<div class="who">${NAMES[l.a]} and ${NAMES[l.b]}</div><div class="why">within ${l.max} m ${Math.round(l.share * 100)} % of the time</div></div>`).join("");
  html += `<p class="foot">${r.runs} runs with the weather, currents, batteries and speeds varied, in ${Math.max(1, Math.round(r.ms))} ms in your browser.${env.frozen ? " Wind held from one snapshot." : ""}${env.noOcean ? " Currents and waves not loaded, so the water is calm." : ""} <a href="about.html">How this is computed</a></p>`;
  $("#results").innerHTML = html;
}

// ---- playback and the depth/height strip
const strip = d3.select("#strip"), clock = $("#clock"), playBtn = $("#play");
function drawStrip() {
  const box = strip.node().getBoundingClientRect(), W = Math.max(200, box.width), H = Math.max(60, box.height);
  strip.attr("viewBox", `0 0 ${W} ${H}`).selectAll("*").remove();
  const L = 64, T = plan.hours * 3600, surf = H * 0.36;
  const x = t => L + (W - L - 8) * t / T, y = z => z >= 0 ? surf - z / 40 * (surf - 6) : surf - z / 110 * (H - surf - 16);
  strip.append("line").attr("class", "sea-surface").attr("x1", L).attr("x2", W - 8).attr("y1", surf).attr("y2", surf);
  const ax = strip.append("g").attr("class", "ax");
  ax.append("text").attr("x", L - 8).attr("y", y(30) + 4).attr("text-anchor", "end").text("30 m up");
  ax.append("text").attr("x", L - 8).attr("y", surf + 4).attr("text-anchor", "end").text("surface");
  ax.append("text").attr("x", L - 8).attr("y", y(-100) + 4).attr("text-anchor", "end").text("100 m");
  for (let m = 0; m <= plan.hours * 60; m += 20) ax.append("text").attr("x", x(m * 60)).attr("y", H - 2).attr("text-anchor", "middle").text(m ? `${m}` : "0 min");
  if (!result) {
    strip.append("text").attr("class", "lbl").attr("x", (L + W) / 2).attr("y", surf + 26).attr("text-anchor", "middle").text("Press Run to see each vehicle's depth and height here");
    clock.value = "0:00"; return;
  }
  const cls = { glider: "t-petrel", boat: "t-tern", drone: "t-gnat" };
  for (const id of ["glider", "boat", "drone"])
    strip.append("path").attr("class", `track ${cls[id]}`).attr("d", "M" + result.nominal.t.map((t, i) => `${x(t).toFixed(1)},${y(result.nominal[id][i][2]).toFixed(1)}`).join("L"));
  strip.append("line").attr("class", "cursor").attr("id", "strip-cursor").attr("y1", 2).attr("y2", H - 14);
  strip.on("pointerdown pointermove", ev => {
    if (ev.type === "pointermove" && !ev.buttons) return;
    const [mx] = d3.pointer(ev);
    stop(); seek(Math.round((Math.max(L, Math.min(W - 8, mx)) - L) / (W - L - 8) * (result.nominal.t.length - 1)));
  });
  seek(frameIdx);
}
function seek(i) {
  if (!result) return;
  frameIdx = Math.max(0, Math.min(result.nominal.t.length - 1, i));
  local.setTime(frameIdx);
  const t = result.nominal.t[frameIdx], box = strip.node().getBoundingClientRect(), W = Math.max(200, box.width), L = 64;
  d3.select("#strip-cursor").attr("x1", L + (W - L - 8) * t / (plan.hours * 3600)).attr("x2", L + (W - L - 8) * t / (plan.hours * 3600));
  clock.value = `${Math.floor(t / 3600)}:${String(Math.floor(t / 60) % 60).padStart(2, "0")}`;
}
function play() {
  if (!result) return;
  if (frameIdx >= result.nominal.t.length - 1) frameIdx = 0;
  playBtn.setAttribute("aria-pressed", "true"); playBtn.setAttribute("aria-label", "Pause");
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce) return seek(result.nominal.t.length - 1), stop();
  timer = setInterval(() => { seek(frameIdx + 2); if (frameIdx >= result.nominal.t.length - 1) stop(); }, 40);
}
function stop() { clearInterval(timer); timer = null; playBtn.setAttribute("aria-pressed", "false"); playBtn.setAttribute("aria-label", "Play"); }
playBtn.addEventListener("click", () => timer ? stop() : play());

let resizeT;
addEventListener("resize", () => { clearTimeout(resizeT); resizeT = setTimeout(() => { render(); drawStrip(); }, 150); });

setWhen();
say("Press Run, or click the sea to deploy somewhere else.");
drawStrip();
