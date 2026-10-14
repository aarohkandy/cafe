# cafe — drone mission predictor (CFD + FEA + 6-DOF + autopilot emulator)

**Question the tool answers:** "If I push this drone out at this place and time, with this much
power, will it do its job?" — for underwater (UUV), surface (USV) and aerial quadcopter (UAV)
drones, in the real ocean/atmosphere from UWIN-CM.

**Exit condition (from the user):** an app where I upload a model, say how much power it has and
where it should be, and get a prediction of what happens to all three drone types — plus an
emulator (real autopilot firmware flying the simulated drone) — with adversarial review and tests
proving the numbers aren't made up.

---

## 1. The core idea: two speeds of work

| | Hangar (characterize a design) | Mission (fly it) |
|---|---|---|
| When | once per drone design | every "can I launch?" question |
| Cost | minutes–hours (CFD, BEM, FEA) | seconds–minutes |
| Produces | a **vehicle model**: drag, resistance curve, added mass, damping, thrust model, structural limits | tracks, energy, hold error, structural margin, P(success), verdict |

Expensive physics is paid once and cached; the mission sim reuses it hundreds of times
(Monte Carlo). "Efficient, not perfect": every coefficient comes from the cheapest method that is
known to be adequate for it, and every number carries an uncertainty.

## 2. What computes what (open source, right tool per coefficient)

| Quantity | Tool | Method | Why this and not more |
|---|---|---|---|
| Drag in x/y/z (UUV, UAV body) | **OpenFOAM** simpleFoam, k-ω SST | Steady RANS, one snappyHexMesh mesh with freestream BCs on all faces, inflow rotated per axis (3 runs, 1 mesh) | Viscous + form drag needs CFD; steady RANS is the standard cheap level |
| Calm-water resistance R(V) (USV) | **OpenFOAM** interFoam, LTS | VOF free surface, fixed attitude at hydrostatic draft, 3–4 speeds spanning Fn 0.15–0.5 | Wave-making resistance is Froude dependent; needs free surface |
| Numerical uncertainty | OpenFOAM, 2 mesh levels | Grid Convergence Index (Roache) | Every CFD number reported as value ± band |
| Added mass, radiation damping | **Capytaine** (BEM) | Potential flow on decimated hull mesh | Exact tool for this; CFD would be 100× the cost |
| Buoyancy, waves on hull (USV/UUV) | own code | Nonlinear Froude–Krylov: integrate instantaneous hydrostatic + wave pressure over hull panels every step | Gives heave/roll/pitch, capsizing, wave loads with no frequency-domain linearization |
| Propellers/rotors | own code | Momentum theory + figure of merit, thrust ∝ ω² with advance-ratio falloff, power limit from the user's watts | Validated against published thruster/rotor data |
| Structure | **CalculiX** (+ **gmsh** meshing) | Shell (hulls, given wall thickness) or solid tets (frames); static + linear buckling (+ modes for quad frames) | Hull collapse is buckling-limited, so buckling is mandatory for UUVs |
| Wind, current, temperature, pressure | **UWIN-CM** data on homebase | Hourly 12 km fields, interpolated in space and time | That's the data the user has |
| Waves | own code | JONSWAP spectrum from local wind (fully developed cap), random-phase linear superposition | UWIN-CM has no wave fields; standard wind–sea relation |
| Turbulence/gusts | own code | Dryden model (MIL-HDBK-1797 low altitude) | Standard for small UAV sim |
| Autopilot | **ArduPilot SITL** (ArduSub, Rover-boat, ArduCopter) | JSON physics backend, lockstep | Real firmware, covers all 3 types |

## 3. Vehicle model (one data structure, all three types)

Rigid body 6-DOF (Fossen form), NED world / FRD body, relative-velocity formulation:

    (M_RB + M_A) ν̇ = τ_thrusters + τ_hydro/aero(ν − ν_fluid) + τ_FK/hydrostatic + τ_gravity − C(ν)ν

- `mass`, `inertia` (mesh-derived, scaled to the user's mass; override allowed), `cog`
- `drag`: quadratic CdA per body axis from CFD (+ rotational damping from strip estimate — flagged)
- `resistance(V)` for boats (CFD table) + windage on the above-water silhouette
- `added_mass` (6×6) and `damping` from Capytaine
- `panels`: decimated hull mesh for pressure integration (water drones)
- `actuators`: list of {position, direction, prop diameter, pitch, max power, spin dir} — default
  layouts per type (quad X; boat twin-skid; sub vectored), editable
- `battery_wh`, `hotel_w`, `reserve`
- `limits` from FEA: crush depth (yield and buckling w/ knockdown), max thrust stress margin, etc.

## 4. Environment

`env.sample(lat, lon, alt_or_depth, t)` → wind (log profile from 10 m, or WRF 3-D when present),
current (HYCOM surface via coupler; below the mixed layer decays — flagged simplification),
waves (JONSWAP from local U10; orbital velocity/pressure decays e^{kz}), ρ_air from T/P,
ρ_water from SST. Auto-discovers every UWIN-CM run on disk, so new data just appears.

## 5. Missions

Kinds: go-and-hold, route (waypoints), round trip, **shadow another drone** (e.g. quad holds
above a boat; boat follows a sub's surface track). Fast mode uses built-in cascaded PID
controllers modelled on ArduPilot's; emulator mode uses ArduPilot itself.

Outputs per drone: track, ETA, energy, reserve, hold/track error (p50/p95), peak loads vs FEA
limits, environmental limits (wind > max airspeed, Hs > operability, depth > crush), and
**P(success)** from Monte Carlo over: CFD uncertainty band, propulsion efficiency, UWIN-CM error,
start-time jitter, wave/gust seeds. Verdict: GO (≥90 %) / MARGINAL (60–90 %) / NO-GO, with the
reason in a sentence.

Navigation realism: fast mode can add dead-reckoning drift for subs (no GPS underwater), since
"hold over a point" for a sub is limited by navigation as much as by thrust.

## 6. Emulator

- Physics server speaks ArduPilot's JSON SITL protocol (UDP), one socket per vehicle, one shared
  world and clock; lockstep so it runs faster than real time and is deterministic.
- Runner uses MAVLink (pymavlink) to set vehicle params derived from the hangar model (hover
  throttle, cruise throttle, …), upload the mission, arm, fly, record.
- Live 3-D view in the app (three.js) streams the same state over a websocket.
- **Bring your own firmware:** anything that speaks the JSON SITL protocol plugs in on the same
  port; QGroundControl can connect over Tailscale to watch/fly.
- Cross-check: fast mode vs emulator on the same mission must agree within tolerance — if our
  controllers are optimistic, this catches it.

## 7. Proof it isn't made up ("Receipts")

Every check is a runnable test with a published or analytic reference, shown in the app:

| Check | Reference |
|---|---|
| Hull volume, draft, BM | closed-form Wigley ✅ |
| Flat-plate skin friction | ITTC-57 line |
| REMUS-100 axial drag | Prestero 2001 (MIT) |
| REMUS-100 added mass (Capytaine) | Prestero 2001 |
| Wigley calm-water resistance vs Fn | published towing-tank data |
| Thin cylinder hoop stress & buckling (CalculiX) | pR/t, von Mises / Windenburg–Trilling |
| Cantilever arm deflection | Euler–Bernoulli |
| Hover power | momentum theory + published motor data |
| Thruster bollard pull | manufacturer datasheet |
| Roll period, free decay | analytic from GM and inertia |
| Drift with current, terminal velocity, energy conservation | analytic |
| Env sampler | independent direct xarray reads |
| Fast mode vs ArduPilot SITL | each other |
| REMUS endurance at cruise | manufacturer datasheet |

Adversarial review after each milestone: independent reviewer agents (physics/units, numerics,
red-team bad inputs: mm-vs-m, inside-out normals, non-watertight, absurd power) whose findings
get fixed and logged in `REVIEW.md`. Rule: bad input must produce an error, never a confident
number.

## 8. Milestones

| # | Deliverable | Done when |
|---|---|---|
| M0 | Image (OpenFOAM 2506, CalculiX 2.21, gmsh), geometry, samples | ✅ geom self-test passes |
| M1 | Environment sampler + waves + gusts | matches direct reads; spectra integrate to Hs |
| M2 | CFD pipeline (freestream RANS, interFoam) + GCI | REMUS, flat plate, Wigley receipts |
| M3 | Capytaine added mass/damping | REMUS added-mass receipt |
| M4 | FEA (shell/solid, static, buckling, modes) + CFD pressure mapping | cylinder + cantilever receipts |
| M5 | 6-DOF core with panels, thrusters, env | analytic dynamics receipts |
| M6 | Fast-mode missions + Monte Carlo + verdicts | REMUS endurance, quad flight time plausible |
| M7 | Emulator (ArduPilot SITL ×3, lockstep, MAVLink runner) | all 3 fly a mission; agrees with fast mode |
| M8 | App (hangar, mission, receipts, 3-D playback, emulator console), deployed on Tailscale | user flow end-to-end |
| M9 | Adversarial review rounds + fixes | REVIEW.md, all receipts green |

## 9. Constraints & known risks

- **Disk on homebase: ~6 GB free (98 %).** CFD case directories are deleted after results are
  extracted; only coefficients + surface pressure are kept. Biggest risk to the project — the user
  may need to free space or add a data disk.
- Box is shared: CFD runs capped (6 cores, memory-limited), never under sudo.
- UWIN-CM coverage: Pacific, Jan–Jul 2018. Missions outside it are refused, not extrapolated.
- ArduSub drives thrusters only (no fins), so fin-steered torpedo AUVs fly in fast mode only
  unless a custom frame is scripted.
- Deliberate simplifications are marked in code with `ponytail:` and listed in the app.
