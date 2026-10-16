# cafe

**Can these drones do the job out there?** Say where you'll deploy each drone (under the water,
on it, or over it), what it has to do, and which pairs must stay within range of each other. cafe
flies the whole fleet together through the real wind, currents and waves for that time and place.
It gives a GO / MARGINAL / NO-GO verdict for each drone and each range requirement, with the reasons.
Then it can fly the same plan with real ArduPilot firmware, or let your own fleet code drive.

Built for TEPEX-style deployments (gliders, a support boat, a quad overhead), but any drone works.

**Open it:** http://100.108.213.121:8740 (Tailscale only).

## Try it: the fleet demo (runs in your browser)

```bash
git clone https://github.com/aarohkandy/cafe && cd cafe/site && python3 -m http.server 8000
```

Then open http://localhost:8000. Press **Run**, drag the vehicles or the goal, pick another spot on the chart.
Everything in `site/` is static: the quick check runs on the viewer's own machine, so any static host
(GitHub Pages, Vercel, Netlify) only serves files. `site/js/sim.check.mjs` checks it against the full simulator:
`node --experimental-default-type=module site/js/sim.check.mjs`. The data in `site/data/` comes from
`./run.sh python -m cafe._site_data`.

## What you put in

| | How |
|---|---|
| **A drone** | Hangar → *Add a design*. Either a **simple shape** (torpedo AUV, buoyancy glider, cylinder pod, monohull, catamaran, quadcopter frame: a few dimensions in metres) or a **3-D model file** (STL/OBJ/PLY/glTF/3MF/STEP). Plus mass, propulsion or pump power, battery, electronics load, material and wall thickness. |
| **Where & when** | Plan → pick the time, add drones with a start point and legs (`goto`, `hold`, `follow` another drone). |
| **Keep in range** | Plan → *Add a range requirement*: drones A and B within N metres (3-D or horizontal), for at least X % of the time, optionally only during a time window. |

Each design is characterized once, and every plan reuses the result:

| Step | What runs |
|---|---|
| Added mass | Capytaine BEM |
| Drag | OpenFOAM: RANS k-ω SST in 6 directions for subs and quads, interFoam free surface at Fn 0.2/0.3/0.4 for boats |
| Hull lift | Subs: the same RANS at 5° and 10° incidence in pitch and yaw, on the bare hull (wings and fins are lifting actuators already). Gives the lift and moment the 6-direction table can't, as a cross term exact on-axis and at each computed angle |
| Grid study | Every CFD case runs on two grids; when they disagree by more than a GCI of 30 % a third, finer grid runs and the uncertainty is taken from the finest pair |
| Structure | CalculiX FEA on the named parts. Hull collapse depth (linear buckling with follower-pressure and 0.5 knockdown, rated depth = collapse / 1.5); glider wing at stall lift and when handled; boat bottom slamming (ISO 12215-5); quad arm at full thrust; frame vibration modes |
| Glider speed | One full dive/climb in the 6-DOF model |

## What comes out

- A verdict for each drone and each range requirement, as a Wilson interval over Monte Carlo runs that
  vary weather error, CFD uncertainty, propulsion and battery spread. Shown as signal flags:
  **C** GO (≥ 90 %), **U** MARGINAL, **N** NO-GO. Every failure comes with its reason: battery empty,
  out of range for 14 min, below rated depth, hit the seafloor, ran aground, capsized, current too strong.
- **Reach maps**: where a drone can get to from a point in the hours you give it, or get to and back.
  Built on Zermelo navigation over the real current or wind field. A glider sees the current averaged
  over its dive band.
- Replay of every track on the map, with a 3-D view of each design and its FEA stress field.

## Example: the TEPEX chain (`./run.sh python -m cafe._tepex_api`)

On 2023-03-07 17:00 UTC at 10° N, 95° W, using WRF wind, HYCOM currents and WAVEWATCH III waves, with 16 runs each:

| Deployment | Result |
|---|---|
| Petrel glider surveys 2 km north at 5–100 m; Tern boat stays over it (1 km modem); Gnat quad relays 30 m above the boat for 20 min, then flies home (300 m radio) | Both range requirements **GO** (the pairs peak at 222 m and 55 m apart). Glider GO (79 min); boat GO (within 11 m of the glider). Quad **MARGINAL**: it lands with 22 % battery and runs flat in 1 of 15 runs, so shorten its stint or carry more battery. |
| Same glider deployed 8 km from a boat holding station, 2 km modem | Link **NO-GO**: never in range, 9.4 km apart. The glider also can't cover its 2 km in the 1 h given (0.33 m/s). |

These are the example platforms. Swap in the real designs when their numbers arrive.

## Ocean and weather data

- **Wind**: the WRF `wrfout_*` or hourly surface `wrfsfc_*` files under `WRF_DIR` (default `/work/wrf`,
  searched recursively). Any WRF Lambert/Mercator grid works; all files must share one grid. Hourly
  data is interpolated linearly in time. A snapshot with no other hour within 3 h of it is held
  constant and labelled as such; it's refused if it is more than 6 h from the mission.
- **On disk now**: UWIN-CM `run_nosal_2018020300b` (Kerns, UW), 25 hourly files, 2018-02-03 12 UTC to
  2018-02-04 12 UTC, plus the 2023-03-07 17 UTC snapshot used for the TEPEX example. More days of the
  2018 archive (2018-01-22 to 2018-07-20) drop in the same way: download `wrfsfc_d01_*` into a folder
  under `WRF_DIR`.
- **Currents (3-D)**: HYCOM GOFS 3.1 analysis (expt_93.0, 1/12°, 3-hourly, Jan 2018 to Sep 2024: the
  GLBv grid until Feb 2020, GLBy after), fetched for the mission box and cached. This includes the
  seafloor depth.
- **Waves**: NOAA WAVEWATCH III (Hs, peak period, direction), fetched and cached the same way, from NOAA's
  ERDDAP or, when that copy is down (it broke on 2026-10-10), from PacIOOS directly.
- The UWIN-CM wrfout and wrfrst files checked so far have their coupled-ocean fields
  (`UOCE/VOCE`, `UE/VE_ESMF`, `HS_UMWM`) all zero, so cafe uses HYCOM and WW3 for the ocean. If those
  servers are down, the run says so and widens the current uncertainty instead of inventing a field.

## Drive it with your own code

```python
import requests
api = "http://100.108.213.121:8740/api/live"
s = requests.post(api, json={"t0": "2023-03-07T17:00", "hours": 2, "drones": [
        {"id": "g1", "design": "sample-petrel", "start": [10.0, -95.0, 5]},
        {"id": "boat", "design": "sample-tern", "start": [10.0, -95.01, 0]}],
    "links": [{"a": "g1", "b": "boat", "max_m": 2000}]}).json()
st = requests.post(f"{api}/{s['id']}/step", json={"seconds": 60, "targets": {
        "boat": {"lat": 10.0, "lon": -95.0, "speed": 1.0}}}).json()
print(st["drones"]["boat"], st["links"])
```

`hours` (0.5–48, default 6) is how long the session can run; its weather and ocean are loaded when it is
created, so the first session in a new area takes a few minutes while HYCOM currents download (cached
after that). The built-in autopilots fly each drone to its target, so your code is tested at the level it really
works: deciding where each drone should be. The Emulator page does the same with ArduCopter, ArduRover
or ArduSub SITL in the loop.

## Proof

The **Receipts** page checks each claim against a formula or a published measurement, for example:
Wigley hull resistance against the Kajitani towing tank, REMUS drag against Prestero, hull side force
and yaw moment at 4–12° drift against the DARPA SUBOFF captive-model tests (Roddy 1990), and long-tube
collapse against Bresse. It also checks a free-free tube's bending stress under inertia relief against
beam theory, and quad hover RPM against bench data. Reach is checked against exact Zermelo times, link
statistics against exact geometry, and fast mode against ArduCopter firmware on the same mission.
Context rows are shown for orientation and never count as a pass.

Run them: `./run.sh python -m cafe.receipts /work/runs`. The slow CFD cases are produced once with
`python -m cafe.cfd external torpedo /work/runs/t1`, `... surface wigley /work/runs/w1` and
`... incidence suboff /work/runs/s1 3.344` (three grids, about 1 h on 6 cores). Adversarial review notes: `REVIEW.md`.

## Files

`geom.py` meshes, samples, hydrostatics · `shapes.py` simple shapes and their structural parts ·
`env.py` WRF + waves + gusts · `ocean.py` HYCOM / WW3 · `cfd.py` OpenFOAM · `fea.py` CalculiX ·
`hangar.py` characterization · `vehicle.py` · `dyn.py` 6-DOF · `ctrl.py` autopilots ·
`mission.py` fleet missions, links, verdicts · `reach.py` · `live.py` your-code sessions ·
`emulator.py` ArduPilot SITL bridge · `worker.py` job queue · `receipts.py` · `app.py` + `static/`.

Server: `~/services/cafe/compose.yml` on homebase (`cafe` = API, `cafe-worker` = jobs); code at
`~/work/cafe/src` (mounted live), data at `~/work/cafe/data`. After a change, run `./sync.sh`, then
`docker restart cafe` (jobs run as fresh processes, so the worker picks up new code by itself).

## Known limits: read before trusting a GO or a NO-GO

- The example designs (Petrel glider, Tern boat, Gnat quad) are stand-ins until the real platform
  numbers arrive. Results for them describe those examples, not your drones.
- The TEPEX date (2023-03-07) has one weather snapshot, so its wind is frozen in time (flagged in the
  results). The 2018 UWIN-CM day has hourly wind.
- Hull lift is tabulated at 5° and 10° incidence and held beyond: reliable to roughly ±15°, symmetric
  about each plane, forward motion only. Against the SUBOFF captive-model drift tests (Receipts → Hull
  lift) the grid-converged side force is 5 % high at 4° and 11–21 % low at 8–12°, as RANS usually is
  past crossflow separation. A reversing hull falls back to the on-axis table. Uploaded meshes should leave fins out:
  fins are actuators, so fins in the mesh would be counted twice.
- Boat resistance is computed at Fn 0.2–0.4 and extrapolated ∝V² above that.
- Boats get a passive skeg sized for a typical directional-stability margin (1.5× the hull's Munk moment),
  because the on-axis CFD carries no hull lift. Enter `skeg_area` once the real one is known.
- Structure: boat hulls are unstiffened shells (conservative); quad frames modelled as solid overstate
  hollow tubes. Uploaded meshes with needle tips or knife edges can't carry a shell wall there; use
  the simple shapes or round them off.
- ArduSub has no fin control, so finned torpedoes and gliders run in fast mode only, not in the emulator.
- Deliberate shortcuts are marked `ponytail:` in the code.
