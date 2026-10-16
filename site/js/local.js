// The deployment at large scale: metres around the spot, like a harbour plan. Vehicles are drawn as symbols
// turned to their heading, with trails; the goal and the starting points can be dragged.
import { barb } from "./chart.js";
import { NAMES } from "./plan.js";

const P = 26, IDS = ["glider", "boat", "drone"], COLOR = { glider: "var(--sea-line)", boat: "var(--ink)", drone: "var(--magenta)" };
const KN = 1.94384;
const compass = deg => ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"][Math.round(((deg % 360) + 360) % 360 / 22.5) % 16];

export function createLocal(svg, { onDrag }) {
  let W, H, s, cn, ce, plan, result, env, depthHere;
  const px = (n, e) => [W / 2 + (e - ce) * s, H / 2 - (n - cn) * s];
  const toM = (x, y) => [cn - (y - H / 2) / s, ce + (x - W / 2) / s];

  function layout(p) {
    const box = svg.node().parentNode.getBoundingClientRect();
    W = Math.max(320, box.width - 12); H = Math.max(260, box.height - 12);
    const pts = [p.glider.start, p.glider.goal, p.boat.start, p.drone.start];
    const ns = pts.map(q => q[0]), es = pts.map(q => q[1]);
    const pad = 650;
    const spanN = Math.max(...ns) - Math.min(...ns) + 2 * pad, spanE = Math.max(...es) - Math.min(...es) + 2 * pad;
    s = Math.min((W - 2 * P - 40) / spanE, (H - 2 * P - 40) / spanN);
    // keep the view clear of the plan panel on wide screens
    const shift = W > 900 ? 330 / s / 2 : 0;
    cn = (Math.max(...ns) + Math.min(...ns)) / 2; ce = (Math.max(...es) + Math.min(...es)) / 2 - shift;
  }

  function draw(p, e, depth) {
    plan = p; env = e; depthHere = depth;
    layout(p);
    svg.selectAll("*").remove();
    svg.attr("viewBox", `0 0 ${W} ${H}`).classed("local", true).on("click", null);
    svg.append("defs").append("clipPath").attr("id", "local-clip").append("rect").attr("x", P).attr("y", P).attr("width", W - 2 * P).attr("height", H - 2 * P);
    const g = svg.append("g").attr("clip-path", "url(#local-clip)");

    // grid in round metres, labelled along the left and bottom edges inside the frame
    const span = (W - 2 * P) / s, step = [100, 250, 500, 1000, 2000].find(st => span / st <= 10) || 5000;
    const [n0, e0] = toM(P, H - P), [n1, e1] = toM(W - P, P);
    for (let x = Math.ceil(e0 / step) * step; x <= e1; x += step) {
      g.append("line").attr("class", "grid-line").attr("x1", px(0, x)[0]).attr("x2", px(0, x)[0]).attr("y1", P).attr("y2", H - P);
    }
    for (let y = Math.ceil(n0 / step) * step; y <= n1; y += step) {
      g.append("line").attr("class", "grid-line").attr("y1", px(y, 0)[1]).attr("y2", px(y, 0)[1]).attr("x1", P).attr("x2", W - P);
    }
    // scale bar and north arrow
    const sb = step * s;
    g.append("path").attr("class", "dim").style("stroke", "var(--ink)").attr("d", `M${W - P - 20 - sb},${H - P - 22}h${sb}M${W - P - 20 - sb},${H - P - 26}v8M${W - P - 20},${H - P - 26}v8`);
    g.append("text").attr("class", "lbl").attr("x", W - P - 20 - sb / 2).attr("y", H - P - 30).attr("text-anchor", "middle").text(step >= 1000 ? `${step / 1000} km` : `${step} m`);
    g.append("path").attr("d", `M${W - P - 30},${P + 46}l7,20l-7,-6l-7,6z`).style("fill", "var(--ink)");
    g.append("text").attr("class", "lbl").attr("x", W - P - 30).attr("y", P + 40).attr("text-anchor", "middle").text("N");
    g.append("text").attr("class", "sounding").attr("x", P + 14).attr("y", H - P - 14)
      .text(isFinite(depthHere) ? `water ${Math.round(depthHere).toLocaleString("en")} m deep here` : "");

    // weather box, top right
    const wx = svg.append("g").attr("class", "wx").attr("transform", `translate(${W - P - 200},${P + 82})`);
    wx.append("rect").attr("class", "cartouche-bg").attr("width", 180).attr("height", 96).attr("x", -8).attr("y", -10);
    wx.append("path").attr("class", "barb wx-barb");
    wx.append("text").attr("class", "lbl wx-wind").attr("x", 46).attr("y", 14);
    wx.append("path").attr("class", "wx-cur").style("stroke", "var(--sea-line)").style("stroke-width", 1.6).style("fill", "none");
    wx.append("text").attr("class", "lbl wx-curt").attr("x", 46).attr("y", 52);
    wx.append("text").attr("class", "lbl wx-hs").attr("x", 46).attr("y", 72);

    // goal and starts
    const [gx, gy] = px(...p.glider.goal);
    const goal = g.append("g").attr("class", "goal").attr("transform", `translate(${gx},${gy})`).style("cursor", "grab");
    goal.append("circle").attr("class", "site").attr("r", 12);
    goal.append("circle").attr("class", "site").attr("r", 4).style("fill", "var(--magenta)");
    goal.append("text").attr("class", "site-label").attr("x", 17).attr("y", 5).text("goal");
    for (const id of IDS) {
      const [x, y] = px(...p[id].start);
      g.append("path").attr("class", "dim").attr("d", `M${x - 5},${y}h10M${x},${y - 5}v10`);
    }

    // run output layers (filled by setResult / setTime)
    g.append("g").attr("class", "ghosts");
    g.append("g").attr("class", "trails");
    g.append("g").attr("class", "links");
    const syms = g.append("g").attr("class", "syms");
    for (const id of IDS) {
      const v = syms.append("g").attr("class", `veh veh-${id}`).style("color", COLOR[id]).style("cursor", "grab");
      v.append("use").attr("href", `#sym-${id}`).attr("x", -14).attr("y", -14).attr("width", 28).attr("height", 28);
      v.append("text").attr("class", "lbl").attr("x", 17).attr("y", 4).style("fill", COLOR[id]).style("font-weight", 600).text(NAMES[id]);
      v.append("text").attr("class", "dim-text veh-sub").attr("x", 17).attr("y", 17);
    }

    // dragging: the goal, and each vehicle while the clock is at zero
    const drag = (what) => d3.drag()
      .on("start", function () { d3.select(this).style("cursor", "grabbing"); })
      .on("drag", function (ev) {
        const [x, y] = d3.pointer(ev, svg.node());
        const m = toM(Math.max(P, Math.min(W - P, x)), Math.max(P, Math.min(H - P, y)));
        d3.select(this).attr("transform", `translate(${px(...m)})`);
        onDrag(what, m, false);
      })
      .on("end", function (ev) {
        d3.select(this).style("cursor", "grab");
        const [x, y] = d3.pointer(ev, svg.node());
        onDrag(what, toM(Math.max(P, Math.min(W - P, x)), Math.max(P, Math.min(H - P, y))), true);
      });
    goal.call(drag("goal"));
    for (const id of IDS) syms.select(`.veh-${id}`).call(drag(id));
    result = null;
    setTime(0);
  }

  function setResult(r) {
    result = r;
    const g = svg.select(".ghosts").html("");
    if (!r) return setTime(0);
    const line = rows => "M" + rows.map(q => px(q[0], q[1]).map(v => v.toFixed(1)).join(",")).join("L");
    for (const run of r.ghosts) for (const id of IDS)
      g.append("path").attr("class", `track ghost t-${id === "glider" ? "petrel" : id === "boat" ? "tern" : "gnat"}`).attr("d", line(run[id]));
  }

  function setTime(i) {
    const t = result ? result.nominal.t[i] : 0;
    const tr = svg.select(".trails").html(""), lk = svg.select(".links").html("");
    const pos = {};
    for (const id of IDS) {
      let n, e, z, hdg, b;
      if (result) {
        [n, e, z, hdg, b] = result.nominal[id][i];
        const rows = result.nominal[id].slice(0, i + 1);
        tr.append("path").attr("class", `track t-${id === "glider" ? "petrel" : id === "boat" ? "tern" : "gnat"}`)
          .attr("d", "M" + rows.map(q => px(q[0], q[1]).map(v => v.toFixed(1)).join(",")).join("L"));
      } else {
        [n, e] = plan[id].start; z = id === "glider" ? -plan.glider.band[0] : id === "drone" ? 2 : 0;
        hdg = id === "glider" ? Math.atan2(plan.glider.goal[1] - e, plan.glider.goal[0] - n) : 0; b = 1;
      }
      pos[id] = [n, e, z];
      const [x, y] = px(n, e);
      const v = svg.select(`.veh-${id}`).attr("transform", `translate(${x},${y})`);
      v.select("use").attr("transform", `rotate(${hdg * 180 / Math.PI})`);
      const where = id === "glider" ? `${Math.round(-z)} m deep` : id === "drone" ? (z > 0.5 ? `${Math.round(z)} m up` : "landed") : "on the surface";
      v.select(".veh-sub").text(`${where}, battery ${Math.round(Math.max(b, 0) * 100)} %`);
    }
    for (const [k, l] of plan.links.entries()) {
      const a = pos[l.a], b = pos[l.b];
      const sep = result ? result.linkSep[k][Math.min(i, result.linkSep[k].length - 1)] : (l.mode === "3d" ? Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]) : Math.hypot(a[0] - b[0], a[1] - b[1]));
      const active = t >= (l.from ?? 0) * 60 && (l.until == null || t <= l.until * 60);
      if (!active) continue;
      const [x1, y1] = px(a[0], a[1]), [x2, y2] = px(b[0], b[1]);
      lk.append("line").attr("class", `link-line ${sep <= l.max ? "link-ok" : "link-bad"}`).attr("x1", x1).attr("y1", y1).attr("x2", x2).attr("y2", y2);
      lk.append("text").attr("class", "dim-text").attr("x", (x1 + x2) / 2 + 8).attr("y", (y1 + y2) / 2).style("fill", sep <= l.max ? null : "#b3261e").text(`${Math.round(sep)} m`);
    }
    // weather at the boat, now
    if (env) {
      const [lat, lon] = [plan.site[0] + pos.boat[0] / 111320, plan.site[1] + pos.boat[1] / (111320 * Math.cos(plan.site[0] * Math.PI / 180))];
      const [u, v] = env.windAt(lat, lon, t), [cu, cv] = env.currentAt(lat, lon, t, 0), hs = env.hsAt(lat, lon, t);
      svg.select(".wx-barb").attr("d", barb(18, 30, u, v, 30));
      svg.select(".wx-wind").text(`wind ${Math.round(Math.hypot(u, v) * KN)} kn from ${compass(Math.atan2(-u, -v) * 180 / Math.PI)}`);
      const cm = Math.hypot(cu, cv), L = 26, ax = 18, ay = 48;
      svg.select(".wx-cur").attr("d", cm > 0.005 ? `M${ax - cu / cm * L / 2},${ay + cv / cm * L / 2}L${ax + cu / cm * L / 2},${ay - cv / cm * L / 2}m${(-cu / cm * 6 + cv / cm * 4).toFixed(1)},${(cv / cm * 6 + cu / cm * 4).toFixed(1)}M${ax + cu / cm * L / 2},${ay - cv / cm * L / 2}l${(-cu / cm * 6 - cv / cm * 4).toFixed(1)},${(cv / cm * 6 - cu / cm * 4).toFixed(1)}` : "");
      svg.select(".wx-curt").text(`current ${(cm * KN).toFixed(1)} kn to ${compass(Math.atan2(cu, cv) * 180 / Math.PI)}`);
      svg.select(".wx-hs").text(`waves ${hs.toFixed(1)} m`);
    }
  }

  return { draw, setResult, setTime, redraw: () => plan && draw(plan, env, depthHere) };
}
