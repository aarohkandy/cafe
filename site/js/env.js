// Real weather and ocean at any point and time: WRF wind (hourly, or one held snapshot), HYCOM currents at
// 0, 50 and 100 m (3-hourly), WAVEWATCH III wave height (hourly). Bilinear in space, linear in time.
const DEG = Math.PI / 180;

function bilinear(lat, lon, lats, lons, get) {
  const fi = (lons.length - 1) * (lon - lons[0]) / (lons[lons.length - 1] - lons[0]);
  const fj = (lats.length - 1) * (lat - lats[0]) / (lats[lats.length - 1] - lats[0]);
  const i = Math.max(0, Math.min(lons.length - 2, Math.floor(fi))), j = Math.max(0, Math.min(lats.length - 2, Math.floor(fj)));
  const x = Math.min(Math.max(fi - i, 0), 1), y = Math.min(Math.max(fj - j, 0), 1);
  const a = get(j, i), b = get(j, i + 1), c = get(j + 1, i), d = get(j + 1, i + 1);
  return a * (1 - x) * (1 - y) + b * x * (1 - y) + c * (1 - x) * y + d * x * y;
}

function timeIndex(ts, t) {
  if (ts.length === 1 || t <= ts[0]) return [0, 0, 0];
  for (let k = 0; k < ts.length - 1; k++) if (t <= ts[k + 1]) return [k, k + 1, (t - ts[k]) / (ts[k + 1] - ts[k])];
  return [ts.length - 1, ts.length - 1, 0];
}

export class Env {
  // date: "2018" (hourly from 2018-02-03 12 UTC) or "2023" (one snapshot, 2023-03-07 17 UTC); startHour: UTC hour
  constructor({ wind, ocean, depth }, date, start) {
    this.date = date;
    this.start = start;                                      // Date of mission start
    const frames = wind.frames.filter(f => (date === "2023") === f.snapshot);
    this.windT = frames.map(f => (new Date(f.t + "Z") - start) / 1000);
    this.wind = { lat: wind.lat, lon: wind.lon, frames };
    this.frozen = frames.length === 1;
    const o = ocean && ocean[date];
    this.noOcean = !o;                                         // ocean data not exported yet: calm water, and the page says so
    if (o) {
      const t0 = new Date(date === "2018" ? "2018-02-03T12:00:00Z" : "2023-03-07T12:00:00Z");
      const off = (t0 - start) / 1000;
      this.cur = { ...o.currents, t: o.currents.t.map(t => t + off) };
      this.wav = { ...o.waves, t: o.waves.t.map(t => t + off) };
    }
    this.depth = depth;
  }

  windAt(lat, lon, t) {                                       // m/s east, north
    const { lat: la, lon: lo, frames } = this.wind, n = lo.length;
    const [k0, k1, f] = timeIndex(this.windT, t);
    const one = (k, c) => bilinear(lat, lon, la, lo, (j, i) => frames[k][c][j * n + i] / 10);
    return [one(k0, "u") * (1 - f) + one(k1, "u") * f, one(k0, "v") * (1 - f) + one(k1, "v") * f];
  }

  currentAt(lat, lon, t, depth) {                             // m/s east, north at a depth (m)
    if (this.noOcean) return [0, 0];
    const c = this.cur, n = c.lon.length, m = c.lat.length, D = c.depths.length;
    const [k0, k1, f] = timeIndex(c.t, t);
    const dz = Math.min(Math.max(depth, c.depths[0]), c.depths[D - 1]);
    let d = 0; while (d < D - 2 && dz > c.depths[d + 1]) d++;
    const fz = (dz - c.depths[d]) / (c.depths[d + 1] - c.depths[d]);
    const val = (arr, k, dd) => bilinear(lat, lon, c.lat, c.lon, (j, i) => {
      const x = arr[((k * D + dd) * m + j) * n + i];
      return x === -9999 ? 0 : x / 100;
    });
    const at = (arr, k) => val(arr, k, d) * (1 - fz) + val(arr, k, d + 1) * fz;
    return [at(c.u, k0) * (1 - f) + at(c.u, k1) * f, at(c.v, k0) * (1 - f) + at(c.v, k1) * f];
  }

  hsAt(lat, lon, t) {                                         // significant wave height, m
    if (this.noOcean) return 0;
    const w = this.wav, n = w.lon.length, m = w.lat.length;
    const [k0, k1, f] = timeIndex(w.t, t);
    const one = k => bilinear(lat, lon, w.lat, w.lon, (j, i) => Math.max(w.hs[(k * m + j) * n + i], 0) / 10);
    return one(k0) * (1 - f) + one(k1) * f;
  }

  seaDepthAt(lat, lon) {                                      // m below sea level; negative on land
    const { lat0, dlat, lon0, dlon, nx, ny, z } = this.depth;
    const i = Math.round((lon - lon0) / dlon), j = Math.round((lat - lat0) / dlat);
    if (i < 0 || j < 0 || i >= nx || j >= ny) return NaN;
    return -z[j * nx + i];
  }
}

// local metres (north, east) around an origin, and back
export const frame = (lat0, lon0) => ({
  toNE: (lat, lon) => [(lat - lat0) * 111320, (lon - lon0) * 111320 * Math.cos(lat0 * DEG)],
  toLL: (n, e) => [lat0 + n / 111320, lon0 + e / (111320 * Math.cos(lat0 * DEG))],
});
