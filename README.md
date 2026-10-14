# cafe

**Can these drones do the job out there?** Say where you'll deploy each drone (under the water,
on it, or over it), what it has to do, and which pairs must stay within range of each other. cafe
flies the whole fleet together through the real wind, currents and waves for that time and place.
It gives a GO / MARGINAL / NO-GO verdict for each drone and each range requirement, with the reasons.
Then it can fly the same plan with real ArduPilot firmware, or let your own fleet code drive.

Built for TEPEX-style deployments (gliders, a support boat, a quad overhead), but any drone works.

**Open it:** http://100.108.213.121:8740 (Tailscale only).

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

- **Wind**: the WRF `wrfout_*` files under `WRF_DIR` (default `/work/wrf`). Any WRF Lambert/Mercator
  grid works. A single snapshot is held constant in time and labelled as such; it's refused if it is
  more than 6 h from the mission.
- **Currents (3-D)**: HYCOM GOFS 3.1 analysis (1/12°, 3-hourly, Dec 2018 to Sep 2024), fetched for
  the mission box and cached. This includes the seafloor depth.
- **Waves**: NOAA WAVEWATCH III (Hs, peak period, direction), fetched and cached the same way, from NOAA's
  ERDDAP or, when that copy is down (it broke on 2026-10-10), from PacIOOS directly.
- The UWIN-CM wrfout and wrfrst files checked so far have their coupled-ocean fields
  (`UOCE/VOCE`, `UE/VE_ESMF`, `HS_UMWM`) all zero, so cafe uses HYCOM and WW3 for the ocean. If those
  servers are down, the run says so and widens the current uncertainty instead of inventing a field.

## Drive it with your own code

```python
import requests
api = "http://100.108.213.121:8740/api/live"
s = requests.post(api, json={"t0": "2023-03-07T17:00", "drones": [
        {"id": "g1", "design": "sample-petrel", "start": [10.0, -95.0, 5]},
        {"id": "boat", "design": "sample-tern", "start": [10.0, -95.01, 0]}],
    "links": [{"a": "g1", "b": "boat", "max_m": 2000}]}).json()
st = requests.post(f"{api}/{s['id']}/step", json={"seconds": 60, "targets": {
        "boat": {"lat": 10.0, "lon": -95.0, "speed": 1.0}}}).json()
print(st["drones"]["boat"], st["links"])
```

The built-in autopilots fly each drone to its target, so your code is tested at the level it really
works: deciding where each drone should be. The Emulator page does the same with ArduCopter, ArduRover
or ArduSub SITL in the loop.

## Proof

The **Receipts** page checks each claim against a formula or a published measurement, for example:
Wigley hull resistance against the Kajitani towing tank, REMUS drag against Prestero, and long-tube
collapse against Bresse. It also checks a free-free tube's bending stress under inertia relief against
beam theory, and quad hover RPM against bench data. Reach is checked against exact Zermelo times, link
statistics against exact geometry, and fast mode against ArduCopter firmware on the same mission.
Context rows are shown for orientation and never count as a pass.

Run them: `./run.sh python -m cafe.receipts /work/runs`. Adversarial review notes: `REVIEW.md`.

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
- A single wrfout snapshot means wind is frozen in time. Long missions and reach maps flag this.
- Hull lift at angle of attack isn't in the CFD (on-axis runs only); finned subs rely on fin lift.
- Boat resistance is computed at Fn 0.2–0.4 and extrapolated ∝V² above that.
- Boats get a passive skeg sized for a typical directional-stability margin (1.5× the hull's Munk moment),
  because the on-axis CFD carries no hull lift. Enter `skeg_area` once the real one is known.
- Structure: boat hulls are unstiffened shells (conservative); quad frames modelled as solid overstate
  hollow tubes. Uploaded meshes with needle tips or knife edges can't carry a shell wall there; use
  the simple shapes or round them off.
- ArduSub has no fin control, so finned torpedoes and gliders run in fast mode only, not in the emulator.
- Deliberate shortcuts are marked `ponytail:` in the code.
