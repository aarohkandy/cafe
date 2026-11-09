"""cafe.pm.env.tao against a stand-in THREDDS tree (catalogs + OceanSITES-style files served with HTTP Range): mooring discovery,
deployment selection, QC, hashing and resume, wind lift to 10 m, mooring-vs-model statistics with injected known errors, receipts."""
import datetime as dt, json, runpy, sys, warnings

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from cafe import receipts as R
from cafe.pm.env import tao

T0 = dt.datetime(2023, 3, 1, 12, tzinfo=dt.timezone.utc).timestamp()
T1 = T0 + 6 * 86400
NS = 'xmlns="http://www.unidata.ucar.edu/namespaces/thredds/InvCatalog/v1.0" xmlns:xlink="http://www.w3.org/1999/xlink"'
BOX = (-7.0, 7.0, 163.0, -163.0)


def _t(a, b, step=600.0):
    return np.arange(a, b, step)


def write_nc(path, var, t, rng, qc, mode, depth=None, scale=1.0):
    """An OceanSITES-style file: TIME (+ HEIGHT/DEPTH), the variables of tao.NC[var], their _QC."""
    import xarray as xr
    names, qc_of = tao.NC[var]
    n = len(t)
    z = "DEPTH" if var == "SST" else "HEIGHT"
    ds = xr.Dataset(coords={"TIME": ("TIME", t.astype("datetime64[s]").astype("datetime64[ns]")), z: (z, np.array([1.0 if var == "SST" else 4.0], "f4"))})
    for nm in names:
        ds[nm] = (("TIME", z), (rng(nm, t) * scale).astype("f4")[:, None])
    if qc is not None:                                                       # None: a file without its flag variable
        ds[qc_of + "_QC"] = (("TIME", z), np.full((n, 1), qc, "f4"))
    ds.to_netcdf(path)


def series(nm, t):
    x = (t - T0) / 86400.0
    return {"UWND": -6.0 + np.sin(x), "VWND": 1.0 + 0.5 * np.cos(x), "SST": 28.0 + 0.2 * np.sin(x), "AIRT": 27.0 + 0 * x, "RELH": 80.0 + 0 * x}[nm]


class Tree:
    """Builds the stand-in THREDDS tree under a conftest Server. add(mooring, deployment, mode, var, qc, t0=, t1=) -> file name."""

    def __init__(self, server, tmp):
        self.s, self.tmp, self.entries, self.refs = server, tmp, {}, []
        self.base = server.base + "/thredds"

    def mooring(self, name):
        if name not in self.refs:
            self.refs.append(name)
        self.entries.setdefault(name, [])

    def add(self, name, dep, mode, var, qc, a=T0 - 3 * 86400, b=T1 + 86400, res="10min", real=True):
        fn = f"OS_{name}_{dep}_{mode}_{var}_{res}.nc"
        self.mooring(name)
        self.entries[name].append(fn)
        if real:
            p = self.tmp / fn
            write_nc(p, var, _t(a, b), series, qc, mode)
            self.s.put(f"thredds/fileServer/oceansites/DATA/{name}/{fn}", p.read_bytes())
        return fn

    def publish(self):
        refs = "".join(f'<catalogRef xlink:href="{n}/catalog.xml" xlink:title="{n}" ID="oceansites/DATA/{n}" name="{n}"/>' for n in self.refs)
        wrap = lambda name, body: f'<?xml version="1.0"?><catalog {NS}><dataset name="{name}">{body}</dataset></catalog>'.encode()
        self.s.put("thredds/catalog/oceansites/DATA/catalog.xml", wrap("DATA/", refs))
        for n, files in self.entries.items():
            ds = "".join(f'<dataset name="{f}" ID="oceansites/DATA/{n}/{f}" urlPath="oceansites/DATA/{n}/{f}"/>' for f in files)
            self.s.put(f"thredds/catalog/oceansites/DATA/{n}/catalog.xml", wrap(f"DATA/{n}/", ds))
        return self.base


@pytest.fixture
def tree(server, tmp_path):
    t = Tree(server, tmp_path)
    t.mooring("ALOHA")                                                   # a station that is not a TAO mooring name
    t.mooring("T8N165E"); t.mooring("T0N140W")                              # outside the box in latitude and in longitude
    t.mooring("T5S170W")
    # T0N165E: an old deployment (never needed), the one in the water at t0 with delayed-mode winds, a later one inside the window
    t.add("T0N165E", "DM100A-20220101", "D", "WIND", 5)
    t.add("T0N165E", "DM200A-20230201", "D", "WIND", 5)
    t.add("T0N165E", "DM200A-20230201", "R", "WIND", 3)                       # real-time winds are flagged 3: dropped
    t.add("T0N165E", "DM200A-20230201", "R", "SST", 1)
    t.add("T0N165E", "DM200A-20230201", "D", "AIRT", 5)
    t.add("T0N165E", "DM200A-20230201", "D", "RH", 5)
    t.add("T0N165E", "DM300A-20230305", "D", "WIND", 5, a=T0 + 4 * 86400, b=T1 + 86400)   # starts inside the window, covers 2 days of it
    t.add("T0N165E", "DM400A-20230901", "D", "WIND", 5, a=T1 + 86400, b=T1 + 2 * 86400)   # starts after the window: never fetched
    t.add("T0N165E", "DM200A-20230201", "D", "WIND", 5, res="hourly", real=False)          # another resolution: ignored
    t.add("T5S170W", "DM500A-20230101", "R", "WIND", 3)                       # only flagged-3 winds: no WIND selected
    t.add("T5S170W", "DM500A-20230101", "R", "SST", 2)
    return t


# ------------------------------------------------------------------ discovery, download, QC


def test_mooring_position():
    assert tao.mooring_position("T2S165E") == (-2.0, 165.0) and tao.mooring_position("T0N170W") == (0.0, 190.0)
    assert tao.mooring_position("T5N180W") == (5.0, 180.0) and tao.mooring_position("T8N95W") == (8.0, 265.0)
    with pytest.raises(ValueError, match="not a TAO"):
        tao.mooring_position("ALOHA")


def test_moorings_in_the_box_across_the_dateline(tree):
    base = tree.publish()
    assert tao.moorings(BOX, base) == [("T0N165E", 0.0, 165.0), ("T5S170W", -5.0, 190.0)]
    assert tao.moorings((-1, 1, 160, 170), base) == [("T0N165E", 0.0, 165.0)]


def test_fetch_picks_the_right_deployments_and_files_and_never_fetches_the_rest(tree, server, tmp_path):
    base = tree.publish()
    m = tao.fetch_tao(BOX, T0, T1, tmp_path / "tao", base)
    man = json.loads(m.read_text())
    got = sorted(k.split("/")[1] for k in man["files"])
    assert "OS_T0N165E_DM100A-20220101_D_WIND_10min.nc" not in got and "OS_T0N165E_DM400A-20230901_D_WIND_10min.nc" not in got
    assert len(got) == 8 and not any("hourly" in k for k in got)
    assert man["selected"]["T0N165E"]["WIND"] == "T0N165E/OS_T0N165E_DM200A-20230201_D_WIND_10min.nc"       # most good samples; D beats the flagged R
    assert set(man["selected"]["T0N165E"]) == {"WIND", "SST", "AIRT", "RH"}
    assert man["selected"]["T5S170W"] == {"SST": "T5S170W/OS_T5S170W_DM500A-20230101_R_SST_10min.nc"}
    assert man["positions"]["T5S170W"] == [-5.0, 190.0] and man["box"] == [-7.0, 7.0, 163.0, 197.0]
    for k, r in man["files"].items():
        assert tao.remote.sha256(tmp_path / "tao" / k) == r["sha256"] and r["bytes"] > 0 and r["time_start"] < r["time_end"] and r["mode"] in "DR"
    assert not [n for n, _ in server.log if "DM100A" in n or "DM400A" in n or "hourly" in n]
    assert tao.verify(tmp_path / "tao") == len(man["files"])


def test_fetch_is_resumable_without_refetching(tree, server, tmp_path):
    base = tree.publish()
    tao.fetch_tao(BOX, T0, T1, tmp_path / "tao", base)
    n = len([1 for name, _ in server.log if "fileServer" in name])
    tao.fetch_tao(BOX, T0, T1, tmp_path / "tao", base)
    assert len([1 for name, _ in server.log if "fileServer" in name]) == n


def test_r12_m26_a_file_missing_here_whose_upstream_copy_changed_is_fetched_and_recorded(tree, server, tmp_path):
    """The manifest holds the hash of the copy it fetched. Upstream replaced that file (NOAA adds delayed-mode data after the fact) and the local one is gone:
    the fetch used to refuse the new copy with 'SHA-256 mismatch' on every try, and nothing said that deleting manifest.json breaks the loop."""
    base = tree.publish()
    out = tmp_path / "tao"
    first = json.loads(tao.fetch_tao(BOX, T0, T1, out, base).read_text())
    assert "replaced" not in first
    key = "T0N165E/OS_T0N165E_DM200A-20230201_D_WIND_10min.nc"
    (out / key).unlink()
    new = tmp_path / "new.nc"
    write_nc(new, "WIND", _t(T0 - 3 * 86400, T1 + 86400), series, 5, "D", scale=1.1)
    server.put(f"thredds/fileServer/oceansites/DATA/T0N165E/{key.split('/')[1]}", new.read_bytes())
    with pytest.warns(UserWarning, match="upstream replaced it"):
        man = json.loads(tao.fetch_tao(BOX, T0, T1, out, base).read_text())
    now = tao.remote.sha256(out / key)
    assert now != first["files"][key]["sha256"] and man["files"][key]["sha256"] == now
    assert man["replaced"] == {key: dict(old=first["files"][key]["sha256"], new=now)}
    assert tao.verify(out) == len(man["files"])
    again = json.loads(tao.fetch_tao(BOX, T0, T1, out, base).read_text())          # nothing is replaced the second time
    assert "replaced" not in again and again["files"] == man["files"]


@pytest.mark.parametrize("damage", [b"", b'{"files": {"T0N165E/OS_T0'])
def test_an_empty_or_truncated_manifest_is_fetched_again_not_a_traceback(tree, tmp_path, damage):
    """Round 6 integration of M-8: `_tao_cached` sends a damaged TAO manifest back to `fetch_tao`, which then read it with json.loads and raised
    JSONDecodeError every time. It is no record now: the files are checked against the server again and the manifest is rewritten."""
    base = tree.publish()
    good = json.loads(tao.fetch_tao(BOX, T0, T1, tmp_path / "tao", base).read_text())
    (tmp_path / "tao" / "manifest.json").write_bytes(damage)
    again = json.loads(tao.fetch_tao(BOX, T0, T1, tmp_path / "tao", base).read_text())
    assert again["files"] == good["files"] and again["selected"] == good["selected"] and tao.verify(tmp_path / "tao") == len(good["files"])


def test_a_later_deployment_inside_the_window_is_a_candidate_but_the_fuller_series_wins(tree, tmp_path):
    base = tree.publish()
    man = json.loads(tao.fetch_tao(BOX, T0, T1, tmp_path / "tao", base).read_text())
    assert "T0N165E/OS_T0N165E_DM300A-20230305_D_WIND_10min.nc" in man["files"]            # fetched (starts 2 days into the window) ...
    assert man["selected"]["T0N165E"]["WIND"].endswith("DM200A-20230201_D_WIND_10min.nc")  # ... but covers less of it


def test_verify_names_a_changed_or_missing_file(tree, tmp_path):
    base = tree.publish()
    out = tmp_path / "tao"
    man = json.loads(tao.fetch_tao(BOX, T0, T1, out, base).read_text())
    k = sorted(man["files"])[0]
    (out / k).write_bytes((out / k).read_bytes() + b"x")
    with pytest.raises(ValueError, match="differ from the manifest") as e:
        tao.verify(out)
    assert k in str(e.value)
    (out / k).unlink()
    with pytest.raises(ValueError, match="1 of"):
        tao.verify(out)


def test_load_keeps_only_qc_good_samples_in_the_window_and_converts_units(tree, tmp_path):
    base = tree.publish()
    out = tmp_path / "tao"
    tao.fetch_tao(BOX, T0, T1, out, base)
    d = tao.load_tao(out)
    assert set(d) == {"T0N165E", "T5S170W"} and d["T5S170W"]["lon"] == 190.0 and d["T5S170W"]["lat"] == -5.0 and "wind" not in d["T5S170W"]
    w = d["T0N165E"]["wind"]
    assert w["z"] == 4.0 and w["t"].min() >= T0 and w["t"].max() <= T1 and len(w["t"]) == 6 * 144 + 1
    assert np.allclose(w["u"], series("UWND", w["t"]), atol=1e-5)
    assert np.allclose(d["T0N165E"]["sst"]["value"], series("SST", d["T0N165E"]["sst"]["t"]) + 273.15, atol=1e-4) and d["T0N165E"]["sst"]["z"] == 1.0
    assert np.allclose(d["T0N165E"]["rh"]["value"], 0.8, atol=1e-6) and np.allclose(d["T0N165E"]["airt"]["value"], 300.15, atol=1e-4)
    sub = tao.load_tao(out, T0 + 86400, T0 + 2 * 86400)
    assert sub["T0N165E"]["wind"]["t"].min() >= T0 + 86400 and sub["T0N165E"]["wind"]["t"].max() <= T0 + 2 * 86400
    assert d["T0N165E"]["wind"]["t"].shape == w["t"].shape


def test_load_refuses_a_tampered_file(tree, tmp_path):
    base = tree.publish()
    out = tmp_path / "tao"
    man = json.loads(tao.fetch_tao(BOX, T0, T1, out, base).read_text())
    k = next(iter(man["files"]))
    (out / k).write_bytes(b"not the file")
    with pytest.raises(ValueError, match="differ from the manifest"):
        tao.load_tao(out)


def test_r9_m31_a_file_without_its_qc_variable_is_refused_naming_file_and_variable(tmp_path):
    """Round 9 M-31: a missing QC variable used to keep every sample, so a renamed or dropped variable switched the filter off without a word."""
    import xarray as xr
    t = _t(T0, T0 + 3600)
    ds = xr.Dataset(coords=dict(TIME=("TIME", t.astype("datetime64[s]").astype("datetime64[ns]")), DEPTH=("DEPTH", np.array([1.0], "f4"))))
    ds["SST"] = (("TIME", "DEPTH"), np.full((len(t), 1), 28.0, "f4"))
    ds.to_netcdf(tmp_path / "x.nc")
    with pytest.raises(ValueError, match=r"x\.nc: variable SST_QC is missing"):
        tao._series(tmp_path / "x.nc", "SST", "R", T0, T0 + 3600)
    write_nc(tmp_path / "w.nc", "WIND", t, series, 5, "D")                                   # the wind's flags are WSPD_QC, not UWND_QC
    assert len(tao._series(tmp_path / "w.nc", "WIND", "D", T0, T0 + 3600)["t"]) == len(t)
    write_nc(tmp_path / "n.nc", "WIND", t, series, None, "D")
    with pytest.raises(ValueError, match=r"n\.nc: variable WSPD_QC is missing"):
        tao._series(tmp_path / "n.nc", "WIND", "D", T0, T0 + 3600)


def test_r9_m31_fetch_picks_another_deployment_when_the_fuller_file_has_no_qc_variable(server, tmp_path):
    t = Tree(server, tmp_path)
    t.add("T2N165E", "DM100A-20230201", "D", "WIND", None)                                  # covers the whole window; unflagged, so it would score every sample
    t.add("T2N165E", "DM100B-20230201", "R", "WIND", 1, a=T0, b=T0 + 3 * 86400)             # covers half of it, flagged good
    man = json.loads(tao.fetch_tao((1, 3, 163, 167), T0, T1, tmp_path / "tao", t.publish()).read_text())
    assert man["selected"]["T2N165E"]["WIND"] == "T2N165E/OS_T2N165E_DM100B-20230201_R_WIND_10min.nc"
    bad = "T2N165E/OS_T2N165E_DM100A-20230201_D_WIND_10min.nc"
    assert list(man["unusable"]) == [bad] and "variable WSPD_QC is missing" in man["unusable"][bad] and bad in man["files"]     # kept in the hashes, never used
    assert len(tao.load_tao(tmp_path / "tao")["T2N165E"]["wind"]["t"]) == 3 * 144


def test_waves_are_absent_for_tao_and_say_so(tree, tmp_path):
    base = tree.publish()
    out = tmp_path / "tao"
    tao.fetch_tao(BOX, T0, T1, out, base)
    with pytest.warns(UserWarning, match="no wave data.*files listed"):
        assert tao.waves_available(out) is False
    tree.add("T0N165E", "DM200A-20230201", "D", "HS", 5, real=False)                 # a wave file appears in the catalog
    base = tree.publish()
    tao.fetch_tao(BOX, T0, T1, out, base)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert tao.waves_available(out) is True


# ------------------------------------------------------------------ wind at 10 m


def test_wind_lift_is_neutral_log_and_monotone():
    u = np.array([2.0, 5.0, 10.0])
    up = tao.wind_to_10m(u, 4.0)
    assert (up > u).all() and np.allclose(up / u, 1.08, atol=0.03)
    assert np.allclose(tao.wind_to_10m(u, 10.0), u, rtol=1e-9) and (tao.wind_to_10m(u, 20.0) < u).all()
    assert (np.diff(up) > 0).all() and np.isclose(tao.wind_to_10m(0.0 + 1e-9, 4.0), 0.0, atol=1e-6)
    z0 = 0.011 * (0.4 * 8.0 / np.log(4.0 / 2e-4)) ** 2 / 9.80665          # the roughness the iteration lands on: Charnock's, a few 1e-4 m
    assert 5e-5 < z0 < 1e-3


@given(st.floats(0.5, 25.0), st.floats(2.0, 30.0))
@settings(max_examples=60, deadline=None)
def test_wind_lift_goes_the_right_way_for_any_height(u, z):
    v = float(tao.wind_to_10m(u, z))
    assert (v >= u * 0.999999) == (z <= 10.0 + 1e-9) or np.isclose(v, u, rtol=1e-6)


def test_wind_lift_methods_and_their_errors():
    with pytest.raises(ValueError, match="method must be"):
        tao.wind_to_10m(5.0, 4.0, "bulk")
    with pytest.raises(ValueError, match="needs air="):
        tao.wind_to_10m(5.0, 4.0, "coare")
    air = dict(t=301.15, rh=0.8, sst=301.15, p=101000.0, lat=0.0)
    c = float(tao.wind_to_10m(6.0, 4.0, "coare", air))
    log = float(tao.wind_to_10m(6.0, 4.0))
    assert 6.0 * 1.03 < c < log < 6.0 * 1.12 and abs(c / log - 1) < 0.04                      # stability-aware lift is a little smaller than the neutral one
    more = float(tao.wind_to_10m(6.0, 4.0, "coare", dict(air, sst=303.15)))
    assert more < c                                                                            # warmer sea, more unstable: less shear


@given(st.floats(-50, 50), st.integers(1, 40))
@settings(max_examples=40, deadline=None)
def test_bin_of_a_constant_is_the_constant_and_sparse_bins_are_nan(c, n):
    t = np.arange(0, 7200.0, 600.0)
    v = tao._bin(t, np.full_like(t, c), np.array([3600.0]))
    assert np.allclose(v, c)
    assert np.isnan(tao._bin(t, np.full_like(t, c), np.array([3600.0]), need=n + 7)).all()


def test_r9_m30_the_bin_takes_half_an_hour_each_side_and_three_samples_by_default():
    """Round 9 M-30: the defaults half=1800 and need=3 (BRIEF 5.4's +-30 min mean of at least 3 samples) were never exercised without arguments."""
    tt = np.array([36000.0])
    t = tt + np.array([-1800.0, -1200.0, -600.0, 0.0, 600.0, 1200.0, 1800.0])
    v = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 1000.0])
    assert tao._bin(t, v, tt)[0] == pytest.approx(3.5)                                          # [tt - 1800, tt + 1800): the left end in, the right end out
    assert np.isnan(tao._bin(tt + [0.0, 600.0], [1.0, 2.0], tt)).all()                          # two samples are too few ...
    assert tao._bin(tt + [0.0, 600.0, 1200.0], [1.0, 2.0, 3.0], tt)[0] == pytest.approx(2.0)    # ... three are enough
    assert np.isnan(tao._bin(t, np.array([1.0, np.nan, np.nan, 4.0, np.nan, np.nan, 7.0]), tt)).all()          # only valid samples count


def day_start(offset_days):
    return dt.datetime.fromtimestamp(T0 - T0 % 86400 + offset_days * 86400, dt.timezone.utc).strftime("%Y%m%d")


def test_r9_m30_candidates_are_the_deployment_in_the_water_its_twins_within_ten_days_and_the_later_ones_that_start_in_the_window():
    """Round 9 M-30: with `- 10 * 86400` replaced by `- 0` the A/B twin of a deployment was dropped and the tests stayed green."""
    t0 = T0 - T0 % 86400                                                                         # a UTC midnight: the file dates are days
    files = [dict(date=day_start(d), file=f"d{d}", var="WIND", res="10min") for d in (-30, -14, -13, -12, -3, 2, 6, 7)]
    got = [f["file"] for f in tao._candidates(files, t0, t0 + 6 * 86400)]
    # latest start at or before t0 is -3; its twins reach back to -13 (exactly ten days is in); -14 and -30 are out;
    # 2 and 6 (= t1) start in the window; 7 after it
    assert got == ["d-13", "d-12", "d-3", "d2", "d6"]
    on_t0 = [dict(date=day_start(d), file=f"d{d}", var="WIND", res="10min") for d in (-12, -8, 0)]
    assert [f["file"] for f in tao._candidates(on_t0, t0, t0 + 86400)] == ["d-8", "d0"]       # a file dated t0 is the one in the water: twins -10 days from it
    later = [dict(date=day_start(1), file="later", var="WIND", res="10min")]
    assert [f["file"] for f in tao._candidates(later, t0, t0 + 2 * 86400)] == ["later"]       # none before t0: all up to t1


def test_r10_m19_the_deployment_in_the_water_is_found_per_variable_and_resolution():
    """Round 10 M-19: a sensor re-deployed after the wind sensor (SST dated 20230220, WIND 20230101, t0 1 March) moved the one window for every
    variable to 10 Feb, so the only wind file in the water was never a candidate. The hourly twin of a 10-minute file must not move it either."""
    t0 = T0 - T0 % 86400
    f = lambda var, d, res="10min", mode="D": dict(date=day_start(d), file=f"{var}{res}{mode}{d}", var=var, res=res, mode=mode)
    wind, sst = f("WIND", -59), f("SST", -9)
    assert [x["file"] for x in tao._candidates([wind, sst], t0, t0 + 6 * 86400)] == [wind["file"], sst["file"]]
    hourly = f("WIND", -2, res="hourly")                                                          # a later hourly file: not the 10-minute wind's start
    assert wind in tao._candidates([wind, hourly], t0, t0 + 6 * 86400)
    twin = [f("SST", -9, mode="D"), f("SST", -15, mode="R"), f("SST", -30, mode="R")]               # D and R of one variable still share the window
    assert [x["file"] for x in tao._candidates(twin, t0, t0 + 86400)] == [twin[0]["file"], twin[1]["file"]]


def test_r10_m19_fetch_keeps_the_wind_of_a_mooring_whose_sst_was_redeployed_later(server, tmp_path):
    t = Tree(server, tmp_path)
    t.add("T2N165E", "DM100A-20230101", "D", "WIND", 5)
    t.add("T2N165E", "DM200A-20230220", "D", "SST", 5)
    man = json.loads(tao.fetch_tao((1, 3, 163, 167), T0, T1, tmp_path / "tao", t.publish()).read_text())
    assert man["selected"]["T2N165E"] == {"WIND": "T2N165E/OS_T2N165E_DM100A-20230101_D_WIND_10min.nc",
                                          "SST": "T2N165E/OS_T2N165E_DM200A-20230220_D_SST_10min.nc"}
    assert man["selection"] == tao.SELECTION == 2                     # the rule that picked them is on the manifest (a cache of the old rule is told apart)


def test_bin_ignores_nan_and_unsorted_input():
    t = np.array([3600.0, 3000.0, 3300.0, 3900.0, 4200.0, 9000.0])
    v = np.array([4.0, 1.0, np.nan, 5.0, 6.0, 99.0])
    assert np.allclose(tao._bin(t, v, np.array([3600.0]), half=900.0, need=3), [(1 + 4 + 5 + 6) / 4])


# ------------------------------------------------------------------ compare


def moored(speed=6.0, direction_from=100.0, sst=301.0, with_air=False):
    t = _t(T0, T0 + 8 * 3600)
    u = np.full(len(t), speed * -np.sin(np.radians(direction_from)))
    v = np.full(len(t), speed * -np.cos(np.radians(direction_from)))
    r = dict(lat=0.0, lon=180.0, wind=dict(t=t, u=u, v=v, z=10.0), sst=dict(t=t, value=np.full(len(t), sst), z=1.0))
    if with_air:
        r.update(airt=dict(t=t, value=np.full(len(t), 301.0), z=3.0), rh=dict(t=t, value=np.full(len(t), 0.8), z=3.0))
    return r


def model_of(truth, tt, scale=1.0, rot_cw=0.0, dsst=0.0):
    u, v = np.interp(tt, truth["wind"]["t"], truth["wind"]["u"]), np.interp(tt, truth["wind"]["t"], truth["wind"]["v"])
    r = np.radians(rot_cw)               # rotating a wind-from direction clockwise by r turns the vector the same way (compass)
    return dict(t=tt, wind10=scale * np.column_stack([u * np.cos(r) + v * np.sin(r), -u * np.sin(r) + v * np.cos(r)]),
                sst=np.interp(tt, truth["sst"]["t"], truth["sst"]["value"]) + dsst)


def test_compare_recovers_injected_speed_direction_and_sst_errors():
    truth = moored()
    tt = np.arange(3600.0, 7 * 3600, 3600.0) + T0
    c = tao.compare({"M": model_of(truth, tt, 1.1, 10.0, 0.4)}, {"M": truth})["M"]
    assert c["n"] == len(tt) and np.isclose(c["speed_bias"], 0.6, atol=1e-6) and np.isclose(c["speed_rmse"], 0.6, atol=1e-6)
    assert np.isclose(c["dir_bias_deg"], 10.0, atol=1e-6) and np.isclose(c["dir_rmse_deg"], 10.0, atol=1e-6) and c["dir_n"] == len(tt)
    assert np.isclose(c["sst_bias"], 0.4, atol=1e-6) and np.isclose(c["sst_rmse"], 0.4, atol=1e-6) and c["sst_n"] == len(tt)
    # |model - mooring| for a 6 m/s wind turned by 10 deg and scaled by 1.1
    ex = np.sqrt((6.6 * np.cos(np.radians(10)) - 6) ** 2 + (6.6 * np.sin(np.radians(10))) ** 2)
    assert np.isclose(c["vector_rmse"], ex, atol=1e-6)
    ccw = tao.compare({"M": model_of(truth, tt, 1.0, -25.0)}, {"M": truth})["M"]
    assert np.isclose(ccw["dir_bias_deg"], -25.0, atol=1e-6) and np.isclose(ccw["sst_bias"], 0.0, atol=1e-9)


def test_compare_wraps_directions_through_north_and_ignores_calm():
    truth = moored(direction_from=355.0)
    tt = np.arange(3600.0, 7 * 3600, 3600.0) + T0
    assert np.isclose(tao.compare({"M": model_of(truth, tt, 1.0, 20.0)}, {"M": truth})["M"]["dir_bias_deg"], 20.0, atol=1e-6)      # 355 -> 15, not -340
    calm = moored(speed=0.4)
    c = tao.compare({"M": model_of(calm, tt, 1.0, 40.0)}, {"M": calm})["M"]
    assert c["dir_n"] == 0 and np.isnan(c["dir_bias_deg"]) and np.isclose(c["speed_bias"], 0.0, atol=1e-9)


def test_compare_pools_and_skips_what_does_not_match():
    a, b = moored(6.0, 100.0), moored(4.0, 80.0, 300.0)
    tt = np.arange(3600.0, 7 * 3600, 3600.0) + T0
    wrf = {"A": model_of(a, tt, 1.2), "B": model_of(b, tt, 0.9), "C": model_of(a, tt), "D": model_of(a, tt)}
    tao_d = {"A": a, "B": b, "D": dict(lat=0.0, lon=1.0, sst=a["sst"])}               # C has no mooring, D no wind
    r = tao.compare(wrf, tao_d)
    assert set(r) == {"A", "B", "ALL"} and r["ALL"]["n"] == 2 * len(tt)
    assert np.isclose(r["ALL"]["speed_bias"], (0.2 * 6.0 + -0.1 * 4.0) / 2, atol=1e-6)
    assert np.isclose(r["ALL"]["sst_bias"], 0.0, atol=1e-6) and tao.compare({}, tao_d) == {}
    nosst = dict(wrf["A"]); del nosst["sst"]
    assert tao.compare({"A": nosst}, {"A": a})["A"]["sst_n"] == 0
    nom = {k: v for k, v in a.items() if k != "sst"}
    assert tao.compare({"A": wrf["A"]}, {"A": nom})["A"]["sst_n"] == 0


def test_compare_height_adjusts_the_mooring_wind_to_10_m():
    a = moored(6.0, 100.0)
    a["wind"]["z"] = 4.0
    tt = np.arange(3600.0, 7 * 3600, 3600.0) + T0
    lift = float(tao.wind_to_10m(6.0, 4.0)) / 6.0
    c = tao.compare({"A": model_of(a, tt)}, {"A": a})["A"]
    assert np.isclose(c["speed_bias"], 6.0 * (1 - lift), atol=1e-6) and c["speed_bias"] < -0.3                  # the unlifted model looks too slow
    calm = moored(0.0)
    calm["wind"]["z"] = 4.0
    assert np.isclose(tao.compare({"A": model_of(calm, tt)}, {"A": calm})["A"]["speed_bias"], 0.0, atol=1e-9)


def test_compare_with_coare_uses_the_moorings_own_air_temperature_and_humidity():
    a = moored(6.0, 100.0, with_air=True)
    a["wind"]["z"] = 4.0
    tt = np.arange(3600.0, 7 * 3600, 3600.0) + T0
    cl = tao.compare({"A": model_of(a, tt)}, {"A": a}, "log")["A"]["speed_bias"]
    cc = tao.compare({"A": model_of(a, tt)}, {"A": a}, "coare")["A"]["speed_bias"]
    assert -0.7 < cc < -0.3 and 0.0 < cc - cl < 0.3 and tao.compare({"A": model_of(a, tt)}, {"A": a})["A"]["speed_bias"] == cc


def short_air_record(air_t=(0.0, 3600.0)):
    """Round 9 M-32: wind every 10 min for 6 h at 4 m, but air temperature, humidity and SST only at the times `air_t` (s after T0), unstable air."""
    a = moored(6.0, 100.0)
    a["wind"] = dict(t=_t(T0, T0 + 6 * 3600), u=np.full(36, -5.9), v=np.full(36, 1.0), z=4.0)
    at = T0 + np.array(air_t)
    for k, x, z in (("airt", 304.0, 3.0), ("rh", 0.7, 3.0), ("sst", 301.0, 1.0)):
        a[k] = dict(t=at, value=np.full(at.size, x), z=z)
    return a


def test_r9_m32_compare_lifts_with_the_neutral_profile_where_the_air_record_does_not_reach():
    a = short_air_record()
    sp = float(np.hypot(-5.9, 1.0))

    def bias(secs, method):
        return tao.compare({"A": dict(t=np.array([T0 + secs]), wind10=np.array([[-5.9, 1.0]]))}, {"A": a}, method)["A"]["speed_bias"]
    assert abs(bias(1800.0, "auto") - bias(1800.0, "log")) > 0.02                          # inside the record the unstable air changes the lift ...
    assert bias(5 * 3600.0, "auto") == pytest.approx(sp - float(tao.wind_to_10m(sp, 4.0)), abs=1e-9)      # ... at 5 h the neutral one, not 0-1 h held on
    assert bias(5 * 3600.0, "coare") == bias(5 * 3600.0, "auto")


@pytest.mark.parametrize("record,t_s,want", [((0.0, 3600.0), 3600.0 + tao.AIR_GAP_S, True), ((0.0, 3600.0), 3601.0 + tao.AIR_GAP_S, False),
                                             ((0.0, 3600.0), -tao.AIR_GAP_S, True), ((0.0, 3600.0), -tao.AIR_GAP_S - 1.0, False),
                                             ((0.0, 2 * 3600.0), 3600.0, True), ((0.0, 4 * 3600.0), 2 * 3600.0, False),
                                             ((0.0, 2 * 3600.0), 6000.0, True), ((0.0, 2 * 3600.0), 1200.0, True),   # near one neighbour only: either counts
                                             ((0.0, 2.5 * 3600.0), 4500.0, False),      # beyond both
                                             ((3600.0, 2 * 3600.0), 0.0, True), ((3600.0, 2 * 3600.0), -1.0, False)])   # before the first
def test_r9_m32_the_air_state_is_used_up_to_the_gap_limit_from_the_nearest_sample_and_not_beyond(record, t_s, want):
    air = tao._air_at(short_air_record(record), np.array([T0 + t_s]))
    for k in ("t", "rh", "sst"):
        assert bool(np.isfinite(air[k]).all()) is want
    assert air["p"] == 101000.0 and air["lat"] == 0.0


def test_r9_m32_the_air_state_is_interpolated_between_samples_and_an_empty_record_is_missing():
    a = short_air_record()
    a["airt"] = dict(t=T0 + np.array([0.0, 3600.0]), value=np.array([300.0, 302.0]), z=3.0)
    assert tao._air_at(a, np.array([T0 + 900.0]))["t"] == pytest.approx([300.5])
    a["rh"] = dict(t=np.empty(0), value=np.empty(0), z=3.0)
    air = tao._air_at(a, np.array([T0, T0 + 900.0]))
    assert np.isnan(air["rh"]).all() and np.isfinite(air["t"]).all()
    tt = np.array([T0 + 900.0])
    assert tao.compare({"A": dict(t=tt, wind10=np.array([[-5.9, 1.0]]))}, {"A": a})["A"]["speed_bias"] == pytest.approx(
        tao.compare({"A": dict(t=tt, wind10=np.array([[-5.9, 1.0]]))}, {"A": a}, "log")["A"]["speed_bias"])        # no humidity: the neutral lift, not a crash


def test_r9_m32_coare_lift_falls_back_to_the_neutral_one_only_where_the_air_state_is_missing():
    sp, z = np.array([6.0, 6.0, 6.0]), 4.0
    air = dict(t=np.array([304.0, np.nan, 304.0]), rh=np.array([0.7, 0.7, 0.7]), sst=np.array([301.0, 301.0, np.nan]), p=101000.0, lat=0.0)
    got = tao.wind_to_10m(sp, z, "coare", air)
    assert got[0] == pytest.approx(float(tao.wind_to_10m(6.0, z, "coare", {k: v[0] if k in "t rh sst" else v for k, v in air.items()})))
    assert got[1] == got[2] == float(tao.wind_to_10m(6.0, z)) and abs(got[0] - got[1]) > 0.02
    none = tao.wind_to_10m(sp, z, "coare", dict(air, t=np.full(3, np.nan)))
    assert np.array_equal(none, tao.wind_to_10m(sp, z))
    whole = dict(t=304.0, rh=0.7, sst=301.0, p=101000.0, lat=0.0)                              # scalars broadcast against the speeds, as before
    assert tao.wind_to_10m(sp, z, "coare", whole) == pytest.approx(float(tao.wind_to_10m(6.0, z, "coare", whole)))


# ------------------------------------------------------------------ receipts


def test_receipts_pass_and_each_can_fail(tree, tmp_path):
    R.OUT.clear()
    assert tao.receipts()
    mine = [r for r in R.OUT if r["group"] == "TAO / TRITON moorings"]
    assert len(mine) == 7 and all(r["ok"] is not False for r in mine) and sum(r["ok"] is None for r in mine) == 1
    cd = next(r for r in mine if "Cdn10 at COARE" in r["claim"])
    assert cd["error"] < 0.05
    base = tree.publish()
    out = tmp_path / "tao"
    tao.fetch_tao(BOX, T0, T1, out, base)
    R.OUT.clear()
    assert tao.receipts(out)
    hashed = [r for r in R.OUT if "SHA-256" in r["claim"]]
    assert len(hashed) == 1 and hashed[0]["ok"] and "of 8" in hashed[0]["claim"]


def test_lb0_the_hash_receipt_counts_the_files_of_every_cache_it_is_given_and_one_changed_file_stops_it(tree, tmp_path):
    """The receipts job passes the older rule's cache and the current one's together (receipts.jobs): one row, the files of both."""
    base = tree.publish()
    a, b = tmp_path / "a", tmp_path / "b"
    tao.fetch_tao(BOX, T0, T1, a, base)
    tao.fetch_tao(BOX, T0, T1, b, base)
    R.OUT.clear()
    assert tao.receipts([a, b])
    hashed = [r for r in R.OUT if "SHA-256" in r["claim"]]
    assert len(hashed) == 1 and hashed[0]["ok"] and "of 16" in hashed[0]["claim"]
    (b / next(iter(json.loads((b / "manifest.json").read_text())["files"]))).write_bytes(b"x")
    with pytest.raises(ValueError, match="differ from the manifest"):
        tao.receipts([a, b])


def _fails(patch, out_dir=None):
    R.OUT.clear()
    patch()
    tao.receipts(out_dir)
    return [r["claim"] for r in R.OUT if r["ok"] is False]


def test_dropping_the_height_lift_fails_the_lift_receipt(monkeypatch):
    bad = _fails(lambda: monkeypatch.setattr(tao, "wind_to_10m", lambda s, z, *a, **k: np.asarray(s, float)))
    assert bad == ["wind lift 4 m -> 10 m at 6 m/s, neutral"]


def test_a_wrong_charnock_slope_fails_the_drag_receipts(monkeypatch):
    bad = _fails(lambda: monkeypatch.setattr(tao, "CH1", 0.0))
    assert any("Cdn10 at COARE" in c for c in bad)


def test_a_compass_convention_error_fails_the_direction_receipt(monkeypatch):
    math_angle = lambda v: np.degrees(np.arctan2(np.asarray(v)[..., 1], np.asarray(v)[..., 0]))       # counter-clockwise from east, not a compass
    bad = _fails(lambda: monkeypatch.setattr(tao.cv, "from_deg", math_angle))
    assert any("direction bias" in c for c in bad) and not any("speed bias" in c for c in bad)


def test_a_sign_flip_in_model_minus_mooring_fails_the_bias_receipts(monkeypatch):
    real = tao._stats
    bad = _fails(lambda: monkeypatch.setattr(tao, "_stats", lambda wv, tv, ws=None, ts=None, **k: real(tv, wv, ts, ws, **k)))
    assert any("speed bias" in c for c in bad) and any("SST bias" in c for c in bad) and any("direction bias" in c for c in bad)


def test_a_tampered_download_stops_the_hash_receipt(tree, tmp_path):
    base = tree.publish()
    out = tmp_path / "tao"
    man = json.loads(tao.fetch_tao(BOX, T0, T1, out, base).read_text())
    (out / next(iter(man["files"]))).write_bytes(b"x")
    with pytest.raises(ValueError, match="differ from the manifest"):
        tao.receipts(out)


def test_main_runs_the_receipts(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["tao"])
    R.OUT.clear()
    runpy.run_module("cafe.pm.env.tao", run_name="__main__")
    assert capsys.readouterr().out.count("PASS") == 6


def test_r11_m9_a_run_loads_verifies_and_explains_from_the_manifest_copy_it_recorded_not_from_the_shared_file(tree, tmp_path):
    """A fetch of another run rewrites the shared manifest; the stage that copied it must use the copy for everything it reads of the manifest."""
    base = tree.publish()
    out = tmp_path / "tao"
    tao.fetch_tao(BOX, T0, T1, out, base)
    copy = json.loads((out / "manifest.json").read_text())
    want = tao.load_tao(out, T0, T1)
    (out / "manifest.json").write_text(json.dumps(dict(copy, selected={}, files={})))        # the shared one, rewritten
    assert tao.load_tao(out, T0, T1) == {} and tao.verify(out) == 0
    got = tao.load_tao(out, T0, T1, man=copy)
    assert got.keys() == want.keys() and tao.verify(out, man=copy) == len(copy["files"])
    assert tao.wind_gap(out, "T0N165E", T0, T1) == "no WIND file overlaps the window"                  # the rewritten file lists none
    assert tao.wind_gap(out, "T0N165E", T0, T1, man=copy) != "no WIND file overlaps the window"       # the copy lists them


# ---- round 13 batch C, after the adversary: a NaT in TIME was read as -9.2e18 s, a first time stamp (M-32)

def _nat_first(path, var, qc):
    import xarray as xr
    t = _t(T0, T0 + 3600)
    write_nc(path, var, t, series, qc, "D")
    with xr.open_dataset(path) as f:
        ds = f.load()
    tt = ds.TIME.values.copy()
    tt[0] = np.datetime64("NaT")
    ds.assign_coords(TIME=tt).to_netcdf(path, encoding={"TIME": {"units": "seconds since 1970-01-01", "dtype": "float64", "_FillValue": -1.0}})
    with xr.open_dataset(path) as g:
        assert np.isnat(g.TIME.values[0])


def test_r13_m32_a_file_with_a_nat_time_is_refused_naming_the_file(tmp_path):
    _nat_first(tmp_path / "n.nc", "WIND", 1)
    for call in (lambda: tao._coverage(tmp_path / "n.nc"), lambda: tao._series(tmp_path / "n.nc", "WIND", "D", T0, T0 + 3600)):
        with pytest.raises(ValueError, match=r"n\.nc: TIME: 1 of 6 time stamps are NaT"):
            call()


def test_r13_m32_fetch_takes_a_file_with_a_nat_time_as_unusable_and_picks_another_deployment(server, tmp_path, monkeypatch):
    t = Tree(server, tmp_path)
    t.add("T2N165E", "DM100A-20230201", "D", "WIND", 1)
    t.add("T2N165E", "DM100B-20230201", "R", "WIND", 1, a=T0, b=T0 + 3 * 86400)
    base = t.publish()
    real = tao.remote.download
    bad = "OS_T2N165E_DM100A-20230201_D_WIND_10min.nc"

    def download(url, p, was=None):
        r = real(url, p, was)
        if p.name == bad and not getattr(download, "done", False):
            download.done = True
            import xarray as xr
            with xr.open_dataset(p) as f:
                ds = f.load()
            tt = ds.TIME.values.copy()
            tt[0] = np.datetime64("NaT")
            ds.assign_coords(TIME=tt).to_netcdf(p, encoding={"TIME": {"units": "seconds since 1970-01-01", "dtype": "float64", "_FillValue": -1.0}})
        return r
    monkeypatch.setattr(tao.remote, "download", download)
    man = json.loads(tao.fetch_tao((1, 3, 163, 167), T0, T1, tmp_path / "tao", base).read_text())
    key = "T2N165E/" + bad
    assert "TIME: " in man["unusable"][key] and "NaT" in man["unusable"][key] and man["files"][key]["time_start"] is None
    assert man["selected"]["T2N165E"]["WIND"].endswith("DM100B-20230201_R_WIND_10min.nc")
