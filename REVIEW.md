# Adversarial review log

## Round 2 — TEPEX features (shapes, HYCOM/WW3 ocean, range requirements, reach, live API)

Same method: one reviewer for physics and numerics, with each claim backed by a derivation or a run, and
one red team on the live API. Every row below was reproduced before it was fixed. After the fixes: **45/45 receipts pass**
(plus 5 context rows) and the red-team replay shows **0 regressions**.

### Physics & numerics

| # | Finding | Effect before | Fix |
|---|---|---|---|
| 1 | **3-2-1 point supports on a thin shell are soft.** In the free-floating hull's buckling run the hull could roll about its axis and just dimple at the one pinned node. Under compressive prestress that rigid roll became the lowest "mode". | Petrel glider collapse 1.5 MPa (rated depth **49 m**); varied 1.6–6.7 MPa with mesh size | No point supports: the six mean rigid-body motions (Σm u = 0, Σm r×u = 0) are held by CalculiX equations, so any imbalance is carried mass-proportionally. Converged collapse 6.6 / 6.1 / 6.1 MPa (rated ≈ 300 m), inside Bresse 5.5 to Windenburg–Trilling 7.8. Lowest modes are now a degenerate lobar pair (8.08 / 8.09). New receipts for both. The long tube vs Bresse improved from about 10 % to 5 %. |
| 2 | Revolved hulls ended in a needle tip, then a flat hub with a 90° rim. A 7 mm wall can't fit inside a 4 mm tip, and shell expansion folds at a sharp rim. | "nonpositive jacobian" on most meshes, or a spuriously weak hull | Nose runs to a smooth pole; tail cone ends in a 0.16 D hub with a rounded cap |
| 3 | Inertia relief balanced net force only, not net moment; CalculiX GRAV used a different mass than ours on offset curved shells (wall ~t/2R thinner) | an off-centre load was carried by the supports | translation + rotation (α = I⁻¹M) applied as lumped nodal d'Alembert loads. Free-free tube with an end load: peak bending stress 4.77 vs 4PL/27 beam theory 4.72 MPa |
| 4 | The free-body receipt used a self-balanced pressure, so it could not fail | false confidence | replaced by the off-centre-load beam-theory receipt above |
| 5 | Support reaction read from CalculiX RF also contained the loads applied at those nodes | reactions off by the local load | applied loads at supports subtracted |
| 6 | Glider speed from the steady-glide formula ignores the slow turns at top and bottom | 0.277 vs 0.239 m/s (+16 %): too optimistic about reach | each glider flies one full yo in the 6-DOF model when characterized; that speed is used (receipt compares the two) |
| 7 | Glider reach used the surface current | wrong for a vehicle that spends its time at 5–100 m | current averaged over the dive band |
| 8 | Round-trip reach just halved the endurance | ignores that a current helps one way and hurts the other | second Dijkstra for the way back; out + back ≤ budget (receipt: T(V²−c²)/2V, exact) |
| 9 | Pump-energy receipt guessed the number of dives from a fixed period | per-dive energy off by the guess | counts actual bottom turns |
| 10 | Finned sub given a target straight below it floated at the surface with no warning (no forward speed, so the fins had no authority) | silent false failure | spirals down at loiter speed; "arrived" and "holding" mean circling within its turn radius |
| 11 | Glider hold error counted its own saw-tooth depth; a band under 20 m stalled the saw-tooth; a planned return counted as a link outage; acquisition gated the evaluation; mission minutes after the hour were dropped | false NO-GOs | horizontal error for gliders; band ≥ 20 m; links evaluated only in their active window; `lead` kept |
| 12 | Glider wing aspect ratio included the hull width | induced drag low | AR = (span − hull)² / wing area |
| 13 | A wrfout snapshot days away from the mission was used silently; reach didn't say the wind was frozen | stale weather presented as forecast | refused beyond 6 h; frozen-weather warning on reach |
| 14 | Weather sampled outside the WRF box was linearly extrapolated | invented wind at the edges | requests outside the domain are refused; drift past the loaded box holds the edge value |
| 15 | A crashed quad kept its velocity (kept "flying" as a ghost) | positions and links after a crash were wrong | velocity and rate zeroed at the crash |
| 16 | Boats could sail through land after the start | GO for impossible routes | ran-aground failure; goto points on land refused before the run |
| 17 | Found by the receipts while fixing the above: a helper inserted mid-class ended the `Link` class early, so `Link.summary` silently became dead code | every mission with a range requirement would have crashed at the results step (no mission ran on that build) | moved; the link receipt now goes through `summary()`, and every module is AST-scanned for methods trapped inside functions |
| 19 | Boats had no source of directional stability. On-axis CFD has no hull lift, so the slender hull's Munk moment from a little wind-driven sway (~2 N·m on the Skiff) matched the full yaw authority of twin props 7.5 cm off centre. | Skiff couldn't make a 1.1 km goto in 36 min in a 0.75 m sea (props pinned at full differential, spinning); a boat "holding" drifted 300–700 m | passive skeg pair aft (the same lifting-fin model as glider wings), sized for 1.5× the Munk moment and labelled an estimate; `skeg_area` overrides it. Same goto now takes 18.7 min. |
| 20 | WAVEWATCH III: NOAA's ERDDAP copy proxies PacIOOS, and the proxy broke (404 "unknown datasetID") mid-session. Only boxes already cached still had waves; new ones silently fell back to wind-sea estimates (labelled, but easy to miss). | the same place and time got Hs 1.76 m in one run and 0.75 m in the next | falls back to PacIOOS's own ±180° copy, with retries on 5xx and timeouts |
| 21 | CalculiX 2.21 run multithreaded (static steps had 4 threads; only buckling was single-threaded) now and then returned garbage on identical input | intermittent: a 10 N clamp reaction read as [8.3, −3.7, 4.1] N in 1 of 6 runs; a beam stress came out 1.8× in one full receipts run | every CalculiX thread count pinned to 1 (0 bad in 18 repeat solves across 3 processes); all sample designs re-characterized |
| 18 | Free-surface CFD: snappyHexMesh can't refine cells that `refineMesh` already split directionally (no hexRef8 history). It worked by luck on Wigley and the coarse grids, but Tern's fine grid crashed and fell back to estimated drag, labelled only as a warning. | the Tern example ran on a drag estimate, not CFD | on that specific failure, both grids are redone without snappy's extra surface level, so the GCI still compares like with like |

### Red team (live API) — 45 checks, replay with `./run.sh python -m cafe._redteam` (0 regressions)

| Finding | Fix |
|---|---|
| NaN / Infinity / latitude 95 / text in `start` and `goto` points passed | every point checked: 2–3 finite numbers, lat in [−90, 90] |
| Wrong-type fields (`max_hours: "abc"`, booleans, `drones: ["q"]`) gave 500s | typed checks; any ValueError from the simulator is a 400 |
| Requests outside the weather domain and `env/field?n=5000` | refused with the domain extent; n in 2..60 |
| Reach depth below the design's rated depth | refused |
| Shape specs took unknown fields (`sample: true` made a user design look like a built-in), negative electronics load, unknown materials, booleans as numbers, `rotors: 1000` | one whitelist (`clean_spec`) for uploads and shapes. Fields the shape decides (`cog`, `inertia`, `kind`, `layout`) are refused, not silently dropped. |
| Self-contradictory shapes (monohull wider than long, quad motors overlapping or thinner than their arm, glider chord > half the hull) | shape checks |
| Ids `..` and `.hidden` matched the id pattern (`/missions/..` read the parent folder) | ids may not start with a dot; emulation `mission` id validated |
| Live: NaN targets, speed 1000 or −1 m/s, negative altitude, text targets; a batch with one bad target still moved the good ones | every target validated before any is applied (atomic); speed in (0, v_max] |
| Live: 8-hex session ids (guessable), unlimited drones per session | 128-bit ids, at most 12 drones |
| The red team itself created a design through a silently-dropped field and the worker started hours of CFD on it | caught in review, job killed, design removed; the field is now refused |

## Round 1

Two independent reviewers attacked the system on 2026-10-10 (round 1): one read every module looking for wrong
physics/numerics (each claim backed by a derivation or a run), one attacked the live API with bad
inputs. Everything they found is below with its fix. Receipts after fixes: 26/26 pass, all able to fail.

## Physics & numerics

| # | Finding | Effect before | Fix |
|---|---|---|---|
| 1 | ROV hold: heading chased the target bearing (flips 180° when drifting past); thruster clipping lost the moment balance; max speed ignored reversed thrusters | ROV tumbled holding in ≥0.4 m/s current → false NO-GO; max speed 0.69 vs 0.97 m/s | face into the current when near target; allocate moments first, fit forces in remaining headroom; count aft thrusters in reverse |
| 2 | Boat Monte Carlo used placeholder uncertainty (σ 0.58) on CFD resistance, lognormal with +18.5 % mean bias | GO flipped to MARGINAL/NO-GO | σ = 10 % ⊕ free-surface GCI, mean-preserving lognormal |
| 3 | Verdict from a point estimate over 24 runs, nominal run counted | true 85 % → GO 28 % of the time | nominal excluded; 90 % Wilson interval reported; GO needs lower bound ≥ 0.75 |
| 4 | Loiter hold error measured to the moving aim point | true error up to 13 m read as < 10 m | true distance to hold point / leader+offset |
| 5 | Depth only failed at predicted collapse | dive to 95 % of collapse = GO | fail below rated depth (collapse/1.5) |
| 6 | Quad speed loop: integrator capped at 1 m/s², rotor drag not fed forward | 15 % slow, arrivals 17 % late | rotor-drag feed-forward, 10 m/s² integrator (ArduPilot-like) |
| 7 | Boat resistance linear in V below first CFD speed | 2–3× too high at low speed | R₁ (V/V₁)² |
| 8 | Three receipts couldn't fail (thrust = drag at steady state; hover power vs the figure efficiency was fitted to; buoyancy after volume correction) and one self-test always failed | false confidence | replaced: hover RPM (independent of fitted efficiency, 2.2 %), raw-panel volume error (1.9 %); fitted value shown as context only; bounds fixed |
| 9 | Emulator: ArduCopter hover throttle in wrong units; PWM capped at 95 % | takeoff overshoot, 10 % less thrust than fast mode | MOT_THST_HOVER = hover thrust fraction; spin range 0–1 |
| – | Gust intensity used 1.1·U10 for W20 (log profile gives ~0.95); one gust process shared by all quads | turbulence ~15 % high | 0.95·U10, one process per drone |

Verified correct by the same review: quaternions/kinematics/IMU specific force, rigid-body and added-mass
Coriolis (incl. Munk moment sign), current/added-mass terms, Froude–Krylov, prop torque/yaw signs vs
ArduPilot QUAD-X, ArduSub vectored table, CFD direction labels and moment transfer, BEM frame transform,
Lamb spheroid, Dryden, Pierson–Moskowitz.

## Red team (live API)

| Finding | Fix |
|---|---|
| `NaN`/`Infinity` in specs passed all checks (NaN ≤ 0 is false); one NaN design made the whole hangar list 500 | rejected at the API (`parse_constant`, `isfinite`) and again in the pipeline; list skips a damaged record |
| A drone could follow itself (or A↔B loops) and got GO with 0 m error | rejected; every follow chain must reach a drone with a real task |
| Mission design ids unchecked (path probing); missing `legs` crashed the worker | strict id format everywhere; legs required and validated |
| Unit guess (mm vs m) was silent | the guess is recorded and shown as a warning with the resulting length |

Replays of every red-team case: `./run.sh python -m cafe._redteam`.

## Found by our own tests while building (before review)

FEA pressure sign (hulls were being inflated, not crushed); drag-table frame labels; actuator positions
relative to the wrong origin; missing passive fin lift (torpedo tumbled); missing added-mass current term;
stress parser reading mode-shape stresses; CalculiX boundary conditions leaking into the modal step;
inverted shell elements at knife-edge stems; boats with GM < 0 by default CoG; a leg finishing on a stale
distance; finished drones draining batteries; finned sub slowing below fin-control speed and surfacing;
ArduCopter refusing to arm (IMU rate < 1.8× loop rate) and the runner not checking.
