// The in-browser quick check. Each vehicle moves at the speed its characterization allows (CFD drag + propeller
// model -> power against speed, from the full simulator's ctrl._level_power), is carried by the real current or
// wind, and spends battery accordingly. The verdict rules are the full simulator's (mission.py): battery empty,
// out of time, under 15 % reserve, follow error, sea state over the boat's design category, link share in
// range; GO needs >= 90 % of runs and a 90 % Wilson lower bound >= 0.75, MARGINAL >= 60 %.
// What it leaves out: 6-DOF attitude, waves acting on the hull, autopilot dynamics. Those run on the lab server.
import { frame } from "./env.js";

const DT = 5, REC = 10, RESERVE = 0.15;

function rng(seed) {                                          // mulberry32 + Box-Muller: repeatable runs
  let a = seed >>> 0;
  const u = () => { a = (a + 0x6d2b79f5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  return () => Math.sqrt(-2 * Math.log(u() + 1e-12)) * Math.cos(2 * Math.PI * u());
}

const interp = (table, x) => {                                // table: [[x, y], ...] sorted by x
  if (x <= table[0][0]) return table[0][1];
  for (let k = 0; k < table.length - 1; k++) if (x <= table[k + 1][0]) {
    const [x0, y0] = table[k], [x1, y1] = table[k + 1];
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0);
  }
  return table[table.length - 1][1];                          // the table ends at max speed; speeds are capped there
};
const norm = (x, y) => Math.hypot(x, y);
const clampVec = (x, y, m) => { const n = norm(x, y); return n > m ? [x * m / n, y * m / n] : [x, y]; };

export function wilson(ok) {
  const n = ok.length, k = ok.filter(Boolean).length, p = k / Math.max(n, 1), z = 1.645;
  const c = (p + z * z / (2 * n)) / (1 + z * z / n), h = z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n);
  return { p, lo: Math.max(0, c - h), hi: Math.min(1, c + h) };
}
export const verdictOf = ({ p, lo }) => p >= 0.9 && lo >= 0.75 ? "GO" : p >= 0.6 ? "MARGINAL" : "NO-GO";

function runOnce(plan, env, V, seed, record) {
  const g = rng(seed), nominal = seed === 0;
  const k = s => nominal ? 0 : g() * s;                       // perturbation, zero on the nominal run
  const windScale = 1 + k(0.15), windTurn = k(8) * Math.PI / 180;
  const curErr = [k(0.05), k(0.05)], hsScale = 1 + k(0.1);
  const loc = frame(...plan.site);
  const T = plan.hours * 3600;
  const gl = V["sample-petrel"], bt = V["sample-tern"], qd = V["sample-quad"];
  const batt = { glider: gl.battery_wh * (1 + k(0.03)), boat: bt.battery_wh * (1 + k(0.03)), drone: qd.battery_wh * (1 + k(0.03)) };
  const pwr = 1 + k(0.05), spd = Math.min(1, 1 + k(0.05));          // max speed is a ceiling, not a target
  const wind = (n, e, t) => {
    const [u, v] = env.windAt(...loc.toLL(n, e), t);
    const c = Math.cos(windTurn), s = Math.sin(windTurn);
    return [(u * c - v * s) * windScale, (u * s + v * c) * windScale];
  };
  const current = (n, e, t, z) => { const [u, v] = env.currentAt(...loc.toLL(n, e), t, z); return [u + curErr[0], v + curErr[1]]; };

  const S = {
    glider: { n: plan.glider.start[0], e: plan.glider.start[1], z: -plan.glider.band[0], dir: 1, wh: 0, why: "", done: false, arrive: null, vel: [0, 0], hdg: 0 },
    boat: { n: plan.boat.start[0], e: plan.boat.start[1], z: 0, wh: 0, why: "", done: false, err: [], vel: [0, 0], hdg: 0, hsMax: 0 },
    drone: { n: plan.drone.start[0], e: plan.drone.start[1], z: 2, wh: 0, why: "", done: false, err: [], vel: [0, 0], hdg: 0, phase: "follow", landedAt: null },
  };
  const yoW = 2 * (plan.glider.band[1] - plan.glider.band[0]) / gl.yo_s;    // vertical speed from the 6-DOF yo
  const rec = record ? { t: [], glider: [], boat: [], drone: [] } : null;
  const links = plan.links.map(l => ({ ...l, inRange: 0, total: 0, sep: [] }));
  const zOf = id => S[id].z;

  for (let t = 0; t <= T + 1e-9; t += DT) {
    // ---- glider: saw-tooth between its band, through the water toward its goal, carried by the band-mean current
    const G = S.glider;
    if (!G.why) {
      const depth = -G.z;
      let nd = depth + G.dir * yoW * DT;
      if (nd >= plan.glider.band[1]) { nd = plan.glider.band[1]; G.dir = -1; G.wh += 0.445 * plan.glider.band[1] / 100; }  // pump at the bottom
      if (nd <= plan.glider.band[0]) { nd = plan.glider.band[0]; G.dir = 1; }
      G.z = -nd;
      const cs = [25, 50, 75].map(z => current(G.n, G.e, t, z));
      const c = [(cs[0][0] + cs[1][0] + cs[2][0]) / 3, (cs[0][1] + cs[1][1] + cs[2][1]) / 3];
      const dn = plan.glider.goal[0] - G.n, de = plan.glider.goal[1] - G.e, d = norm(dn, de);
      if (!G.done && d < 50) { G.done = true; G.arrive = t; }
      const vw = G.done ? 0 : gl.glide_speed * spd;
      const vn = vw * dn / (d || 1), ve = vw * de / (d || 1);
      G.vel = [vn + c[1], ve + c[0]];
      G.n += G.vel[0] * DT; G.e += G.vel[1] * DT;
      if (vw) G.hdg = Math.atan2(ve, vn);
      G.wh += gl.hotel_w * DT / 3600;
      if (plan.glider.band[1] > gl.rated_depth) G.why = `went below rated depth (${Math.round(gl.rated_depth)} m)`;
      if (G.wh >= batt.glider) G.why = "battery empty";
    }

    // ---- boat: follows the glider on the surface, through the surface current, against the wind on its topsides
    const B = S.boat;
    if (!B.why) {
      const c = current(B.n, B.e, t, 0);
      const en = G.n - B.n, ee = G.e - B.e;
      B.err.push(norm(en, ee));
      let [dn, de] = clampVec(G.vel[0] + en / 120, G.vel[1] + ee / 120, bt.vmax * spd);
      let [wn, we] = clampVec(dn - c[1], de - c[0], bt.vmax * spd);       // through the water
      B.vel = [wn + c[1], we + c[0]];
      B.n += B.vel[0] * DT; B.e += B.vel[1] * DT;
      const vw = norm(wn, we);
      if (vw > 0.05) B.hdg = Math.atan2(we, wn);
      const [wu, wv] = wind(B.n, B.e, t);
      const rn = wv - B.vel[0], re = wu - B.vel[1], rs = norm(rn, re);
      const F = 0.5 * 1.2 * bt.windage_cda * rs * rs;                     // N on the topsides
      const hx = Math.cos(B.hdg), hy = Math.sin(B.hdg), along = rs ? -(rn * hx + re * hy) / rs * F : 0;
      const extra = Math.max(along, 0) * Math.max(vw, 0.3) / bt.drive_eff;
      B.wh += (interp(bt.power, vw) * pwr + extra) * DT / 3600;
      B.hsMax = Math.max(B.hsMax, env.hsAt(...loc.toLL(B.n, B.e), t) * hsScale);
      if (B.wh >= batt.boat) B.why = "battery empty";
    }

    // ---- drone: holds station above the boat for its minutes, then flies home and lands; wind is what it fights
    const D = S.drone;
    if (!D.why && !D.done) {
      const [wu, wv] = wind(D.n, D.e, t);
      if (D.phase === "follow" && t >= plan.drone.minutes * 60) D.phase = "home";
      const tn = D.phase === "follow" ? B.n : plan.drone.start[0], te = D.phase === "follow" ? B.e : plan.drone.start[1];
      const en = tn - D.n, ee = te - D.e, dist = norm(en, ee);
      if (D.phase === "follow" && t > 120) D.err.push(Math.hypot(dist, D.z - plan.drone.height));
      const lead = D.phase === "follow" ? B.vel : [0, 0];
      const [dn, de] = clampVec(lead[0] + en / 8, lead[1] + ee / 8, qd.cruise);
      let [an, ae] = [dn - wv, de - wu];                                  // air-relative velocity needed
      [an, ae] = clampVec(an, ae, qd.vmax * spd);
      D.vel = [an + wv, ae + wu];
      D.n += D.vel[0] * DT; D.e += D.vel[1] * DT;
      if (norm(an, ae) > 0.5) D.hdg = Math.atan2(D.vel[1], D.vel[0]);
      const targetZ = D.phase === "follow" ? plan.drone.height : dist < 15 ? 0 : plan.drone.height;
      D.z += Math.max(-2 * DT, Math.min(2 * DT, targetZ - D.z));
      D.wh += interp(qd.power, norm(an, ae)) * pwr * DT / 3600;
      if (D.phase === "home" && dist < 5 && D.z <= 0.5) { D.done = true; D.landedAt = t; }
      if (D.wh >= batt.drone) { D.why = "battery empty"; D.z = 0; }
    }

    // ---- links, every 10 s
    if (Math.round(t) % REC === 0) {
      for (const l of links) {
        const a = S[l.a], b = S[l.b];
        const sep = l.mode === "3d" ? Math.hypot(a.n - b.n, a.e - b.e, zOf(l.a) - zOf(l.b)) : Math.hypot(a.n - b.n, a.e - b.e);
        // a planned return home is not a link outage (mission.py masks the final "go to start" leg the same way)
        const homeward = (l.a === "drone" || l.b === "drone") && S.drone.phase === "home";
        const active = !homeward && t >= (l.from ?? 0) * 60 && (l.until == null || t <= l.until * 60);
        if (active) { l.total++; if (sep <= l.max) l.inRange++; }
        if (record) l.sep.push(Math.round(sep));
      }
      if (record) {
        rec.t.push(t);
        for (const id of ["glider", "boat", "drone"]) {
          const s = S[id];
          rec[id].push([+s.n.toFixed(1), +s.e.toFixed(1), +s.z.toFixed(1), +s.hdg.toFixed(3), +(1 - s.wh / batt[id]).toFixed(3)]);
        }
      }
    }
  }

  // ---- what each vehicle achieved, in the full simulator's words
  const p95 = a => { if (!a.length) return 0; const s = [...a].sort((x, y) => x - y); return s[Math.floor(0.95 * (s.length - 1))]; };
  const G = S.glider, B = S.boat, D = S.drone;
  if (!G.why && !G.done) G.why = "ran out of time";
  if (!B.why && p95(B.err) > plan.boat.tol) B.why = `follow error over ${plan.boat.tol} m`;
  if (!B.why && B.hsMax > bt.hs_limit) B.why = `seas over design category ${bt.design_category} limit (${bt.hs_limit} m wave height)`;
  if (!D.why && !D.done) D.why = "ran out of time";
  if (!D.why && p95(D.err) > 10) D.why = "follow error over 10 m";
  const left = { glider: 1 - G.wh / batt.glider, boat: 1 - B.wh / batt.boat, drone: 1 - D.wh / batt.drone };
  for (const id of ["glider", "boat", "drone"]) if (!S[id].why && left[id] < RESERVE) S[id].why = "under 15% battery reserve";
  return {
    why: { glider: G.why, boat: B.why, drone: D.why }, left, arrive: G.arrive, hsMax: B.hsMax,
    links: links.map(l => ({ share: l.total ? l.inRange / l.total : 1, ok: !l.total || l.inRange / l.total >= l.need })),
    rec, linkSep: record ? links.map(l => l.sep) : null,
  };
}

export function simulate(plan, env, V, runs = 24) {
  const t0 = performance.now();
  const out = [];
  for (let s = 0; s < runs; s++) out.push(runOnce(plan, env, V, s, s < 7));
  const mc = out.slice(1);                                     // run 0 is the nominal one: shown, not counted
  const reasons = whys => {
    const c = {};
    whys.filter(Boolean).forEach(w => { c[w] = (c[w] || 0) + 1; });
    return Object.entries(c).sort((a, b) => b[1] - a[1]).map(([reason, n]) => ({ reason, n }));
  };
  const vehicles = {};
  for (const id of ["glider", "boat", "drone"]) {
    const ok = mc.map(r => !r.why[id]), w = wilson(ok);
    const lefts = mc.map(r => r.left[id]).sort((a, b) => a - b);
    vehicles[id] = { ...w, verdict: verdictOf(w), reasons: reasons(mc.map(r => r.why[id])), left50: lefts[Math.floor(lefts.length / 2)] };
  }
  const arrivals = mc.map(r => r.arrive).filter(x => x != null).sort((a, b) => a - b);
  vehicles.glider.eta = arrivals.length ? arrivals[Math.floor(arrivals.length / 2)] / 60 : null;
  vehicles.boat.hs = [...mc.map(r => r.hsMax)].sort((a, b) => a - b)[Math.floor(mc.length / 2)];
  const links = plan.links.map((l, i) => {
    const w = wilson(mc.map(r => r.links[i].ok));
    return { ...l, ...w, verdict: verdictOf(w), share: out[0].links[i].share };
  });
  const fleetOk = mc.map(r => !r.why.glider && !r.why.boat && !r.why.drone && r.links.every(l => l.ok));
  const fw = wilson(fleetOk);
  const names = { glider: "glider", boat: "boat", drone: "drone" };
  const fleetWhy = reasons(mc.map(r => ["glider", "boat", "drone"].map(id => r.why[id] ? `${names[id]}: ${r.why[id]}` : "")
    .concat(r.links.map((l, i) => l.ok ? "" : `${plan.links[i].a}–${plan.links[i].b} out of range`)).find(Boolean) || ""));
  return {
    runs, ms: performance.now() - t0, nominal: out[0].rec, ghosts: out.slice(1, 7).map(r => r.rec), linkSep: out[0].linkSep,
    vehicles, links, fleet: { ...fw, verdict: verdictOf(fw), reasons: fleetWhy },
  };
}
