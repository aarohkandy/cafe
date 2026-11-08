"""Read-only: the M-18 numbers on the real cache: how many points the receipt's fit/real context row has, and the stored all-node fit check. Writes nothing."""
import json
import pathlib
import numpy as np
from cafe.pm import config, receipts as PR
from cafe.pm.env import conventions as cv, waves
from cafe.pm.env.environment import GriddedEnv

cache = sorted((PR.data_root() / "cache").glob("*/orca/umwmspec.zarr"))[0].parents[1]
env = GriddedEnv(cache, config.env_sigmas())
S = env.spec
ts = np.array([x for x in S["t"] if env.tu.x[0] <= x <= env.tu.x[-1]])
ts = ts[:: max(1, len(ts) // 4)][:4]
sel = np.arange(len(S["lon"]))[:: max(1, len(S["lon"]) // 800)]
lon, lat = np.tile(S["lon"][sel], len(ts)), np.tile(S["lat"][sel], len(ts))
t = np.repeat(ts, len(sel))
ok = env.inside(lon, lat, t)
lon, lat, t = lon[ok], lat[ok], t[ok]
pick = slice(None, None, max(1, len(lon) // 200))
ratio, fit_ratio = [], []
for lo, la, tt in zip(lon[pick], lat[pick], t[pick], strict=True):
    r = env.restart_spectrum(lo, la, tt)
    thc = waves.theta_compass(r["th"])
    real = waves.stokes_profile(waves.spectrum_from_restart(r["F"], r["k"], r["f"], r["th"]), r["f"], thc, 0.0)
    pw = env.waves(np.array([lo]), np.array([la]), np.array([tt]))
    E = waves.spectrum_from_params(pw["Hs"].value, pw["Tp"].value, pw["dir_to"].value, pw["mss"].value,
                                   cv.speed(env.u10(np.array([lo]), np.array([la]), np.array([tt]))), r["f"], thc)
    par = waves.stokes_profile(E, r["f"], thc, 0.0)[0]
    fit_ratio.append(float(np.hypot(*par) / np.hypot(*real)))
fr = np.array(fit_ratio)
print("cache", cache.name, "restart times in the sample", len(ts), "points", len(fr))
print("fit/real: median %.4f  p10 %.4f  p90 %.4f  min %.4f  max %.4f" % (np.median(fr), *np.percentile(fr, [10, 90]), fr.min(), fr.max()))
print("1/median %.3f ; median |fit/real - 1| over these points %.4f" % (1 / np.median(fr), np.median(np.abs(fr - 1))))
import zarr
d = zarr.open(str(cache / "derived.zarr"), mode="r")
print("derived stokes_fit_check:", d.attrs.get("stokes_fit_check"))
