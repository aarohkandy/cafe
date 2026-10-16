// node site/js/sim.check.mjs — the browser quick check against the full simulator on the same plan.
// Fails (exit 1) if a verdict differs or a headline number drifts beyond what the simpler model can claim.
import { readFileSync } from "node:fs";
import { Env } from "./env.js";
import { simulate, wilson } from "./sim.js";
import { defaultPlan } from "./plan.js";

globalThis.performance ??= { now: () => Date.now() };
const data = n => JSON.parse(readFileSync(new URL(`../data/${n}.json`, import.meta.url)));
const [wind, ocean, depth, V, missions] = ["wind", "ocean", "depth", "vehicles", "fullsim"].map(data);

// sanity of the statistics helper: 15/15 passes -> lower bound ~0.85 (GO); 12/15 -> MARGINAL
const w = wilson(Array(15).fill(true));
if (!(w.p === 1 && w.lo > 0.84 && w.lo < 0.86)) throw new Error(`wilson ${JSON.stringify(w)}`);

let bad = 0;
const check = (what, got, want, tol) => {
  const ok = typeof want === "string" ? got === want : Math.abs(got - want) <= tol;
  if (!ok) bad++;
  console.log(`${ok ? "ok  " : "FAIL"} ${what}: browser ${typeof got === "number" ? got.toFixed(2) : got}, full simulator ${typeof want === "number" ? want.toFixed(2) : want}`);
};
for (const [date, key] of [["2023", "chain2023"], ["2018", "chain2018"]]) {
  const plan = defaultPlan(date), env = new Env({ wind, ocean, depth }, date, plan.start);
  const r = simulate(plan, env, V);
  const full = missions[key];
  console.log(`\n${date}: ${r.runs} runs in ${r.ms.toFixed(0)} ms`);
  const map = { glider: "petrel", boat: "tern", drone: "gnat" };
  for (const id of Object.keys(map)) check(`${id} verdict`, r.vehicles[id].verdict, full.drones[map[id]].verdict);
  check("fleet verdict", r.fleet.verdict, full.fleet.verdict);
  check("glider arrival, min", r.vehicles.glider.eta ?? NaN, full.drones.petrel.eta ?? NaN, 10);
  check("drone battery left (median)", r.vehicles.drone.left50, full.drones.gnat.battery_p50, 0.06);
  check("boat battery left (median)", r.vehicles.boat.left50, full.drones.tern.battery_p50, 0.08);
  r.links.forEach((l, i) => check(`link ${l.a}-${l.b} verdict`, l.verdict, full.links[i].verdict));
}
process.exit(bad ? 1 : 0);
