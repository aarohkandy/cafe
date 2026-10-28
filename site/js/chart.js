// The Gulf of Tehuantepec as a hydrographic chart: Mercator, buff land, blue tints inside the 200 m and 1000 m
// contours, italic soundings, a graduated border, a magenta rose, and WRF wind as barbs. Fills its box.
const DATA = { lon: [-101, -88], lat: [7.5, 17.5] };          // where every layer has data
const KN = 1.94384, P = 26;

export function drawRegional(svg, { land, depth, wind }, { site, frame, onPick }) {
  const box = svg.node().parentNode.getBoundingClientRect();
  const W = Math.max(320, box.width - 12), H = Math.max(260, box.height - 12);
  svg.selectAll("*").remove();
  svg.attr("viewBox", `0 0 ${W} ${H}`).classed("local", false);

  // cover the box with the data area, centred on the gulf
  const merc = la => Math.log(Math.tan(Math.PI / 4 + la * Math.PI / 360));
  const s = Math.max((W - 2 * P) / ((DATA.lon[1] - DATA.lon[0]) * Math.PI / 180), (H - 2 * P) / (merc(DATA.lat[1]) - merc(DATA.lat[0])));
  // centred on the gulf, but moved just enough that the chosen spot sits in the middle 60 % of the frame, never on its edge
  const hv = (H - 2 * P) / (2 * s), hh = (W - 2 * P) / (2 * s) * 180 / Math.PI;
  const cy = Math.min(Math.max(merc(12.4), merc(site[0]) - 0.6 * hv), merc(site[0]) + 0.6 * hv);
  const cLat = (Math.atan(Math.exp(cy)) - Math.PI / 4) * 360 / Math.PI, cLon = Math.min(Math.max(-94.5, site[1] - 0.6 * hh), site[1] + 0.6 * hh);
  const proj = d3.geoMercator().center([cLon, cLat]).scale(s).translate([W / 2, H / 2]);
  const p = (lo, la) => proj([lo, la]);
  const [lonA, latA] = proj.invert([P, H - P]), [lonB, latB] = proj.invert([W - P, P]);     // A = south-west corner, B = north-east
  const ring = pts => "M" + pts.map(([lo, la]) => p(lo, la).map(v => v.toFixed(1)).join(",")).join("L") + "Z";

  svg.append("defs").append("clipPath").attr("id", "map-clip").append("rect").attr("x", P).attr("y", P).attr("width", W - 2 * P).attr("height", H - 2 * P);
  const map = svg.append("g").attr("clip-path", "url(#map-clip)");

  const { nx, ny, lon0, lat0, dlon, dlat, z } = depth;
  const gridRing = r => "M" + r.map(([gx, gy]) => p(lon0 + (gx - 0.5) * dlon, lat0 + (gy - 0.5) * dlat).map(v => v.toFixed(1)).join(",")).join("L") + "Z";
  const contour = d3.contours().size([nx, ny]);
  const band = t => contour.contour(z, t).coordinates.map(poly => poly.map(gridRing).join("")).join("");
  map.append("path").attr("class", "shelf").attr("d", band(-1000)).attr("fill-rule", "evenodd");
  map.append("path").attr("class", "shoal").attr("d", band(-200)).attr("fill-rule", "evenodd");
  for (const t of [-200, -1000, -2000]) map.append("path").attr("class", "contour").attr("d", band(t));

  const sound = map.append("g");
  for (let la = latA + 0.35, row = 0; la < latB - 0.2; la += 0.62, row++)
    for (let lo = lonA + 0.4 + (row % 2) * 0.45; lo < lonB - 0.3; lo += 0.9) {
      const d = z[Math.round((la - lat0) / dlat) * nx + Math.round((lo - lon0) / dlon)];
      if (!(d < -40)) continue;
      const [x, y] = p(lo, la);
      sound.append("text").attr("class", "sounding").attr("x", x).attr("y", y).attr("text-anchor", "middle").text(Math.round(-d));
    }

  map.append("path").attr("class", "land").attr("fill-rule", "evenodd").attr("d", land.polygons.map(poly => poly.map(ring).join("")).join(""));
  for (let lo = Math.ceil(lonA); lo <= lonB; lo++) map.append("line").attr("class", "grid-line").attr("x1", p(lo, 0)[0]).attr("x2", p(lo, 0)[0]).attr("y1", P).attr("y2", H - P);
  for (let la = Math.ceil(latA); la <= latB; la++) map.append("line").attr("class", "grid-line").attr("y1", p(0, la)[1]).attr("y2", p(0, la)[1]).attr("x1", P).attr("x2", W - P);

  const name = (cls, lo, la, text, size) => map.append("text").attr("class", cls).attr("x", p(lo, la)[0]).attr("y", p(lo, la)[1])
    .attr("font-size", size).attr("text-anchor", "middle").text(text);
  name("water-name", -94.95, 15.45, "Gulf of Tehuantepec", 16);
  name("water-name", -97.6, 12.3, "Pacific Ocean", 22);
  name("land-name", -97.9, 16.55, "Mexico", 12);
  name("land-name", -90.75, 15.35, "Guatemala", 12);

  // wind barbs, staggered ~100 km apart
  const { lat: wl, lon: wo } = wind, f = frame;
  let d = "";
  for (let j = 0; j < wl.length; j += 2) for (let i = (j / 2) % 2; i < wo.length; i += 2) {
    const [x, y] = p(wo[i], wl[j]);
    if (x < P + 6 || x > W - P - 6 || y < P + 6 || y > H - P - 6) continue;
    const k = j * wo.length + i;
    d += barb(x, y, f.u[k] / 10, f.v[k] / 10, 23);
  }
  map.append("path").attr("class", "barb").attr("d", d);

  if (W > 560) drawRose(map, p(lonB - 1.5, latA + 1.35), Math.min(62, W / 18));
  drawBorder(svg, p, proj, W, H, [lonA, lonB], [latA, latB]);

  // the chosen spot
  const [sx, sy] = p(site[1], site[0]);
  map.append("circle").attr("class", "site").attr("cx", sx).attr("cy", sy).attr("r", 9);
  map.append("circle").attr("cx", sx).attr("cy", sy).attr("r", 2.4).style("fill", "var(--magenta)");
  map.append("text").attr("class", "site-label").attr("x", sx + 14).attr("y", sy + 5).text("deploy here");

  svg.on("click", ev => {
    const [x, y] = d3.pointer(ev, svg.node());
    if (x < P || y < P || x > W - P || y > H - P) return;
    const [lo, la] = proj.invert([x, y]);
    const gi = Math.round((lo - lon0) / dlon), gj = Math.round((la - lat0) / dlat);
    onPick([la, lo], -z[gj * nx + gi]);
  });
}

// Wind barb in knots; staff points to where the wind comes from, feathers on the clockwise side (N hemisphere)
export function barb(x, y, u, v, L = 23) {
  const kn = Math.hypot(u, v) * KN;
  if (kn < 2.5) return `M${(x + 2.6).toFixed(1)},${y.toFixed(1)}a2.6,2.6 0 1,0 -5.2,0a2.6,2.6 0 1,0 5.2,0`;
  const m = Math.hypot(u, v), sx = -u / m, sy = v / m, nx = -sy, ny = sx, sc = L / 23;
  const tx = x + sx * L, ty = y + sy * L;
  let d = `M${x.toFixed(1)},${y.toFixed(1)}L${tx.toFixed(1)},${ty.toFixed(1)}`;
  let rest = Math.round(kn / 5) * 5, pos = 0;
  const at = k => [tx - sx * k, ty - sy * k];
  while (rest >= 50) {
    const [ax, ay] = at(pos), [bx, by] = at(pos + 5 * sc);
    d += `M${ax.toFixed(1)},${ay.toFixed(1)}L${(ax + nx * 9 * sc).toFixed(1)},${(ay + ny * 9 * sc).toFixed(1)}L${bx.toFixed(1)},${by.toFixed(1)}Z`;
    rest -= 50; pos += 6.5 * sc;
  }
  if (pos === 0 && rest === 5) pos = 3.5 * sc;
  while (rest >= 5) {
    const len = (rest >= 10 ? 9 : 4.8) * sc, [ax, ay] = at(pos);
    d += `M${ax.toFixed(1)},${ay.toFixed(1)}l${(nx * len + sx * len * 0.33).toFixed(1)},${(ny * len + sy * len * 0.33).toFixed(1)}`;
    rest -= rest >= 10 ? 10 : 5; pos += 3.4 * sc;
  }
  return d;
}

function drawRose(g, [cx, cy], R) {
  const r = g.append("g").attr("class", "rose");
  r.append("circle").attr("cx", cx).attr("cy", cy).attr("r", R).attr("stroke-width", 1.1);
  r.append("circle").attr("cx", cx).attr("cy", cy).attr("r", R - 9).attr("stroke-width", 0.5);
  for (let a = 0; a < 360; a += 5) {
    const t = (a - 90) * Math.PI / 180, len = a % 30 === 0 ? 9 : a % 10 === 0 ? 6 : 3;
    r.append("line").attr("x1", cx + Math.cos(t) * R).attr("y1", cy + Math.sin(t) * R)
      .attr("x2", cx + Math.cos(t) * (R - len)).attr("y2", cy + Math.sin(t) * (R - len)).attr("stroke-width", 0.6);
    if (a % 30 === 0) r.append("text").attr("x", cx + Math.cos(t) * (R + 9)).attr("y", cy + Math.sin(t) * (R + 9) + 3)
      .attr("text-anchor", "middle").text(String(a).padStart(3, "0"));
  }
  r.append("path").attr("d", `M${cx},${cy - R + 12}l5,16h-10z`).style("fill", "var(--magenta)").style("stroke", "none");
}

function drawBorder(svg, p, proj, W, H, [lonA, lonB], [latA, latB]) {
  const b = svg.append("g"), t = 6, step = 1 / 6;
  b.append("rect").attr("x", P - t).attr("y", P - t).attr("width", W - 2 * P + 2 * t).attr("height", H - 2 * P + 2 * t).attr("fill", "none").attr("stroke", "var(--ink)").attr("stroke-width", 0.8);
  for (let lo = Math.floor(lonA * 6) / 6, k = Math.floor(lonA * 6); lo < lonB; lo += step, k++) {
    const xa = Math.max(P, p(lo, 0)[0]), xb = Math.min(W - P, p(lo + step, 0)[0]);
    if (xb <= xa) continue;
    for (const y of [P - t, H - P]) b.append("rect").attr("class", k % 2 ? "frame-tick-b" : "frame-tick-a").attr("x", xa).attr("y", y).attr("width", xb - xa).attr("height", t);
  }
  for (let la = Math.floor(latA * 6) / 6, k = Math.floor(latA * 6); la < latB; la += step, k++) {
    const ya = Math.max(P, p(0, la + step)[1]), yb = Math.min(H - P, p(0, la)[1]);
    if (yb <= ya) continue;
    for (const x of [P - t, W - P]) b.append("rect").attr("class", k % 2 ? "frame-tick-b" : "frame-tick-a").attr("x", x).attr("y", ya).attr("width", t).attr("height", yb - ya);
  }
  for (let lo = Math.ceil(lonA); lo <= lonB; lo++) b.append("text").attr("class", "graticule-label").attr("x", p(lo, 0)[0]).attr("y", P - t - 5).attr("text-anchor", "middle").text(`${-lo}° W`);
  for (let la = Math.ceil(latA); la <= latB; la++) b.append("text").attr("class", "graticule-label").attr("x", P - t - 3).attr("y", p(0, la)[1] + 3.5).attr("text-anchor", "end").text(`${la}°`);
}
