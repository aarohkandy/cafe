### C-1. `remote.download` resumes a `.part` file without checking that the server's file is still the one the `.part` came from; with no known hash it splices two versions and the manifest then records the splice's hash
severity: minor
lane: data
where: cafe/pm/env/remote.py:151-176 (`download`); caller cafe/pm/env/tao.py:164-172 (`fetch_tao`, which then writes `sha256=remote.sha256(p)` into the manifest)
reproduction: offline fake, run on cafe-orca (proot, 2 CPUs) from a detached worktree: an in-process `http.server` with Range support serves v1 (1 MiB); a `.part` holding `v1[:400000]` is left in place (an interrupted download); the server's file then changes to v2 (1 052 672 bytes, other content); `remote.download(url, path, None)` returns without error and `path.read_bytes() == v1[:400000] + v2[400000:]` (True), `== v2` (False). `size(url)` is taken from the new file, `have` from the old `.part`, and the resume appends the new tail to the old head. Nothing compares the two (no `If-Range`/ETag, no length check against the version the `.part` started from) when `sha` is None, which is every first fetch of a file.
why it matters: TAO real-time files are rewritten by NOAA (P-40); an interrupted fetch resumed on a later day yields a file that is neither version, and `fetch_tao` then stores its hash in `manifest.json` as the truth, so `tao.verify` and the audit pass on it.

### C-2. A TAO file that is missing or damaged locally, whose upstream copy has since changed, can never be fetched again: every attempt fails with "SHA-256 mismatch ... rerun to fetch it again"
severity: minor
lane: data
where: cafe/pm/env/remote.py:171-173 (`download` deletes the finished `.part` on a hash mismatch and raises); cafe/pm/env/tao.py:164 (passes the OLD manifest's hash `old.get(key, {}).get("sha256")` as the expected one)
reproduction: same fake server on orca: v1 is what the old manifest hashed (`sha1 = sha256(v1)`), the local file is gone, the server now serves v2. `remote.download(url, path, sha1)` raises `ValueError: ... SHA-256 mismatch, partial file removed; rerun to fetch it again`, twice in a row (tries 0 and 1 printed the same), `path` and `.part` absent after each. The message tells the user to rerun, which repeats it forever; the only way out is to delete `manifest.json` (not said anywhere in the message or the RUNBOOK).
why it matters: the disk is about 97 % full (CLAUDE.md), so deleting cache files is a normal act, and P-40 says the files do change; the state is a hard stop in `fetch` with advice that does not work. `fetch_tao` should treat the old hash as "the file I last had", not "the file I must receive".

### C-3. The plan prints "6.78e+08 cell-updates per window" for a stage 3 that has no share and runs no window; no window gets that number
severity: minor
lane: honesty
where: cafe/pm/budget.py:426-428 (`cell_steps_per_window = SHARE["stage3"] * B * rate / max(K * len(classes), 1)`), 605-606 (`describe` prints it), 585-587 (`wall_estimate`, called by nothing outside tests/test_budget.py)
reproduction: q12 `plan.json` / `report/index.html` "stage 3: 1 window(s)/vehicle on native-jax-cpu at 7.53e+06 cell-updates/s (...); 6.78e+08 cell-updates per window". Recompute: 0.30 x 1200 s x 7.5345e6 / (1 x 4 vehicles) = 6.781e8. In the same plan.json `shares.stage3` is 0.0 (the five parts were not run and their 360 s went to stage 1), and each part's own `afford_cell_updates` is 2.21e8 (glider bodies) or 3.11e8 (USV hull/wing, UAS body), computed over 5 parts (not 4 vehicles), less the FEA reserve and the 10 s compile guess. So the printed figure divides the full share by vehicles while the windows divide it by parts, takes nothing off for FEA or compile, and ignores that the share was given away.
why it matters: a number in the report that traces to no window and no share; a reader takes "6.78e+08 per window" as what stage 3 would have been given. `stage3_plan` already has the per-part figures; print those, or drop the line when `shares.stage3` is 0.

### C-4. `python -m cafe.pm.stage1 --members N` (a documented command) ends in a raw traceback for an odd or non-positive N and for an unknown `--prior`, after the whole environment has been loaded
severity: minor
lane: robustness
where: cafe/pm/stage1.py:868 (`--members` is any int), 878 (`sensitivity_case`), 879 (`except (ConfigError, ResourceError)` is the only handler); the raising lines are stats/sampling `lhs_unit` ("antithetic pairs need an even n"), stage1.py:442 (`members[0]`), 843 (`pri[prior]`)
reproduction: on orca with the CI mission and `AnalyticEnv`: `stage1.sensitivity_case(MISSION, AnalyticEnv(), n=7)` -> `ValueError: antithetic pairs need an even n`; `n=0` and `n=-2` -> `IndexError: list index out of range`; `prior="nope"` -> `KeyError: 'nope'`. `main` builds `pipeline.Context(...)` (and so the environment) before any of these, and catches only ConfigError and ResourceError, so the user gets a traceback, exit 1, not the `error:` line and exit 2 of every other command.
why it matters: the robustness rule of this repo (a bad value is an `error:` line). Validate `--members` (even, at least 2) and `--prior` (a key of perturbations.yaml) before building the context.

### C-5. An RF link's margin depends on which end the mission names first: the roughness reads Hs at end `a` only, not at the specular point
severity: minor
lane: physics
where: cafe/pm/stage1.py:626-630 (`hs = env.waves(lonA.T, latA.T, tt.T)["Hs"]`, then `comms.rf_margin(d, A[2], B[2], hs.T, ...)`); the in-sortie hook (stage1.py:294) reads Hs at the ship instead
reproduction: orca, CI scene of tests/test_stage1.py (`rf_scene`, USV north of the ship), an environment whose Hs is 0.2 m at the ship and 3 m at the USV; `evaluate_link` with `a=usv,b=uas` against `a=uas,b=usv` gives margins that differ by -0.32 dB (USV 3 km out), -0.03 dB (8 km), +0.02 dB (15 km) at every airborne sample. The existing test of swapping the ends (test_stage1.py:543-551) uses a uniform Hs and cannot see it. The size of the effect where it matters: for ht 48.1 m, hr 2.2 m at 915 MHz, over d = 0.5 to 30 km every 5 m, `|L(Hs 0.2) - L(Hs 3)|` has a median 0.02 dB, a 95th percentile 1.0 dB and a maximum 35.1 dB (1.1 % of the distances differ by more than 3 dB; 2.8 % for hr 15 m), because the roughness fills the interference nulls.
why it matters: the verdict of a link must not depend on the order of `a` and `b` in the YAML; the Hs of the surface that reflects is the one half way between the antennas (the Kerr specular point), or at least the same for both orders (for example the mean of the two ends). Not a verdict mover in the demo (see C-6), but a null-edge sample can flip.

### C-6. Quantified: the sea reflection coefficient -1 of the vertical-polarised UAS link against the Fresnel coefficient; the claim "valid below 1-2 deg" is wrong by a factor of two in |G| at 1 deg, and no verdict of the demo can move
severity: minor
lane: physics
where: cafe/pm/physics/comms.py:110 (docstring: "reflection coefficient -1 (valid for grazing angles below ~1-2 deg ...)"), 9, 119 (`field = np.abs(1.0 - rho * ...)`); docs/PHYSICS.md 12.1 (line 784), DECISIONS 65, 244 (no Fresnel anywhere in the repo: `grep -ri fresnel` finds nothing)
reproduction: script run on orca (the repo's `kerr_reflection`, `ament_rho`, `divergence_factor` with G(psi) in place of -1; with G = -1 it reproduces `two_ray_curved_db` to 0.0 dB over 4000 distances). Seawater at 915 MHz: eps_c = 72.8 - j118.9 (T 29 C, S 35, sigma 5.9 S/m, assumed); vertical polarisation, G = (eps_c sin(psi) - sqrt(eps_c - cos^2 psi)) / (eps_c sin(psi) + sqrt(...)):

| grazing psi | 0.05 | 0.1 | 0.25 | 0.5 | 1 | 2 | 3 | 5 | 8 | 12 | 20 deg |
|---|---|---|---|---|---|---|---|---|---|---|---|
| abs(G) | 0.98 | 0.97 | 0.91 | 0.84 | 0.70 | 0.49 | 0.35 | 0.26 | 0.36 | 0.49 | 0.65 |
| arg(G) deg | -179 | -179 | -177 | -174 | -168 | -154 | -136 | -86 | -43 | -25 | -14 |

(pseudo-Brewster angle 4.8 deg, |G| 0.26.) |G| is within 10 % of 1 only below 0.3 deg. The demo's geometry (UAS 18.1, 38.1, 68.1, 108.1 m above the sea, USV whip 2.2 m): psi at 1 / 5 / 10 / 20 / 40 km = 1.16 / 0.22 / 0.09 / 0.01 / 0.00 deg for the 18 m UAS and 6.3 / 1.25 / 0.60 / 0.25 / 0.04 deg for the 108 m UAS, so G = -1 is a good model from about 5 to 10 km out and not inside 3 km; the UAS-ship hook inside a sortie (ranges of a few hundred metres to a few km to a 15 m mast) is at psi of 2 to 30 deg where |G| is 0.26 to 0.5. Effect on the margin (budget 152 dB): hook, d 0.05-6 km, Hs 0.5 m: minimum margin 6.3 to 13.2 dB with G = -1, 33 to 47 dB with Fresnel (nulls 7.5 dB lower to 34.7 dB higher, never a sign change); Hs 1.5 m: 18.9 to 28.7 dB against 33 to 47 dB. Mission link UAS-USV, d 0.2 km to the horizon of each height (23.6 to 48.9 km): minimum margin 12.8 to 21.8 dB with G = -1 and 13.3 to 22.5 dB with Fresnel; change in [-7.4, +23.6] dB at Hs 0.5, [-2.8, +6.9] dB at Hs 1.5 (peaks fall by up to 7.4 dB where |G| is 0.26-0.5, nulls rise); zero samples change sign in any of 4 UAS heights x 3 Hs x 4 permittivity/conductivity choices (sigma 5.0 and 6.5 S/m, eps_r 70). Verdicts: usv-uas-rf is NO-GO 64/64 because 88.85 % of the needed samples are beyond the 4/3-earth horizon (q12 `frac_beyond_horizon` 0.8885, `distance_km_median` 80.4), so even if every in-horizon sample passed the success fraction cannot exceed 0.112 against the required 0.95; G cannot change it. The UAS `lost_link` mode is 0 of 64 with a worst-case hook margin of +6.3 dB under G = -1, and Fresnel only raises that. The model is conservative at nulls and optimistic at peaks (by at most 7.6 dB), so it can bias a GO only on a link whose budget is within about 8 dB at a peak, which the demo's is not.
why it matters: no verdict of the demo moves, but the docstring's validity limit and PHYSICS 12.1 state a range that is wrong (|G| 0.70 and 168 deg at 1 deg, not 1), and nothing in the repo quantifies it. Add the Fresnel coefficient (one line given eps_c) or state the measured error band in PHYSICS 12.1 and QUESTIONS_FOR_LAB (antenna polarisation, sea temperature).

### C-7. The orca manifest lists every per-hour part in the directory, not the window's, so its hash (an input of the derived-layer key and of the ledger) depends on what an earlier, longer ingest left there
severity: minor
lane: reproducibility
where: cafe/pm/env/orca.py:369 (`parts = sorted((out / "hours").glob("*.npz"))` -> `parts={p.name: sha256}`), 300-313 (`_drop_stale_parts`); used by cafe/pm/pipeline.py:489-510 (`sha256(orca_snap)` into `key = digest(...)` and `L.input`)
reproduction: by reading (a network ingest was not run): ingest a 6-day window for a box, then a 3-day window of the same box. `_drop_stale_parts` (orca.py:300-313) deletes parts only when the box or the 3-D hours change, so the 3-day manifest has `hours` 73 but `parts` for the 6-day window (about 2 x 73 + 24 files), `bytes_fetched` for the new `ts` only. The manifest bytes, hence `sha256(orca_snap)` and the derived-surface key, differ from those of a clean cache for the same window, box and code, so the 1-minute `surface.build` reruns and the recorded input hash is history-dependent.
why it matters: "same seed, same report" and the input hashes should depend on what the run read, not on what the cache once held. List the parts of `ts` (and `ST`) only.

total: 7 findings (0 critical, 0 major, 7 minor)
