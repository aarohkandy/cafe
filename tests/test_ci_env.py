"""The ci_env generator itself: it refuses to write over real data, its TAO files pass the real loader's QC and its stores agree with its
own analytic functions (so a wrong fixture cannot make a wrong model look right)."""
import numpy as np
import pytest

from cafe.pm.env import tao
from tests.fixtures.ci_env import make as fx


def test_generator_refuses_a_directory_that_holds_something_else(tmp_path):
    (tmp_path / "tao").mkdir()
    (tmp_path / "tao" / "manifest.json").write_text("{}")                                          # looks like a real CAFE_DATA
    with pytest.raises(ValueError, match="refusing to write synthetic data"):
        fx.make(tmp_path)
    assert (tmp_path / "tao" / "manifest.json").read_text() == "{}"


def test_tao_files_load_with_their_bad_samples_dropped(ci_env):
    d = tao.cache_dir(ci_env.data)
    t0, t1 = ci_env.hours[[0, -1]]
    assert tao.verify(d) == 6
    m = tao.load_tao(d, t0, t1)
    assert sorted(m) == ["T0N165W", "T2S165W"] and {"wind", "sst", "airt", "rh"} <= set(m["T0N165W"]) and set(m["T2S165W"]) == {"lat", "lon", "wind", "sst"}
    w = m["T0N165W"]["wind"]
    assert np.hypot(w["u"], w["v"]).max() < 12.0 and w["z"] == 4.0 and w["t"].size == 217 - 2   # 217 ten-minute samples in the window, two flagged bad (99 m/s)
    assert m["T0N165W"]["lat"] == 0.0 and m["T0N165W"]["lon"] == 195.0 and m["T2S165W"]["lat"] == -2.0
    assert 299.0 < m["T0N165W"]["sst"]["value"].mean() < 302.0 and 0.7 < m["T0N165W"]["rh"]["value"].mean() < 0.9      # K and 0..1 as load_tao documents


def test_mooring_comparison_recovers_the_injected_three_percent_low_bias(ci_full, ci_env):
    t0, t1 = ci_env.hours[[0, -1]]
    moor = tao.load_tao(tao.cache_dir(ci_env.data), t0, t1)
    wrf = {}
    for name, m in moor.items():
        lo, la = np.full(ci_env.hours.size, m["lon"]), np.full(ci_env.hours.size, m["lat"])
        wrf[name] = dict(t=ci_env.hours, wind10=ci_full.u10(lo, la, ci_env.hours), sst=ci_full.sst(lo, la, ci_env.hours).value)
    c = tao.compare(wrf, moor)["ALL"]
    assert c["n"] > 50 and 0.0 < c["speed_bias"] < 0.5 and abs(c["dir_bias_deg"]) < 5.0              # model minus mooring: the moorings read ~3 % low
    assert abs(c["sst_bias"]) < 0.3 and c["speed_rmse"] > c["speed_bias"]


def test_ocean_store_and_wrf_sst_share_the_same_surface_temperature(ci_full):
    lon, lat = np.array([194.0, 196.0]), np.array([-1.0, 1.0])
    wrf = ci_full.W["SST"][0][np.searchsorted(ci_full.law.x, lat), np.searchsorted(ci_full.low.x, lon)] - 273.15
    assert np.allclose(wrf, ci_full.ocean.temperature(lon, lat, np.zeros(2), ci_full.tw.x[0]).value, atol=1e-3)


def test_restart_spectra_and_integrated_fields_describe_the_same_sea(ci_full):
    from cafe.pm.env import waves
    S = ci_full.spec
    for it, ip in ((0, 5), (3, 40), (6, 90)):
        hs = waves.hs_from_restart(S["F"][it, ip], S["k"][it, ip], S["f"], S["th"])
        w = ci_full.waves(float(S["lon"][ip]), float(S["lat"][ip]), float(S["t"][it]))
        assert hs == pytest.approx(float(w["Hs"].value), rel=1e-4)


# ---------------------------------------------------------------------------------------------------------------- review round 11, M-17

DEFAULT_3D = ["2023-03-02_01:00:00", "2023-03-02_02:00:00", "2023-03-03_01:00:00", "2023-03-03_02:00:00"]       # launches at 01:00Z, each with the hour after


def dateline_mission(tmp_path):
    """missions/ci_fixture.yaml moved across 180 E: a box 178.5 E to 178.5 W, the ship at 179 W (a UAS launch at 14:00 local solar time is 01:56Z there)."""
    import yaml
    from cafe.pm.config import load_mission
    d = yaml.safe_load(fx.MISSION.read_text())
    d["name"] = "ci_fixture_dateline"
    d["box"].update(lon_min=178.5, lon_max=-178.5)
    d["ship"]["lon"] = -179.0
    for v in d["vehicles"]:
        if v["id"] == "glider_eq":
            v["deploy"]["lon"] = v["task"]["lon"] = 179.5
        elif v["id"] == "glider_1n":
            v["deploy"]["lon"] = -179.5
        elif v["id"] == "usv":
            v["deploy"]["lon"] = -179.0
            v["task"]["waypoints"] = [[-179.0, -1.0], [-179.0, 1.0]]
    p = tmp_path / "ci_fixture_dateline.yaml"
    p.write_text(yaml.safe_dump(d, sort_keys=False))
    load_mission(p)                                                                          # it is a valid mission
    return p


def orca_3d_hours(ns):
    import json
    return json.loads((ns.cache / "orca" / "manifest.json").read_text())["hours3d"]


def test_r11_m17_the_default_box_still_holds_the_same_3d_hours_moorings_and_grids(ci_env):
    """The generator is now box-general; the box of missions/ci_fixture.yaml gives what it always gave."""
    from cafe.pm.env import hycom
    assert orca_3d_hours(ci_env) == DEFAULT_3D
    assert sorted(fx._moorings(ci_env.mission)) == ["T0N165W", "T2S165W"]
    lat, lon = fx._ocean_axes(ci_env.mission)
    assert (lat[0], lat[-1], lon[0], lon[-1], lat.size, lon.size) == (-2.5, 2.5, 192.5, 197.5, 21, 21)
    ds = hycom.open_store(ci_env.ocean_store)
    assert np.array_equal(ds.lat.values, lat) and np.array_equal(ds.lon.values, lon)


def test_r11_m17_a_mission_across_the_dateline_gets_its_own_3d_hours_moorings_and_stores_and_passes_the_ingest_offline(tmp_path, monkeypatch):
    """The generator built one box (OLON 192.5 to 197.5, a fixed TAO box) and a 3-D hour list of its own: a dateline mission failed orca_present,
    tao_present and ocean_store_present with 'not cached', and no test took such a mission through the ingest."""
    import json
    from cafe.pm import pipeline
    from cafe.pm.env import ocean as ocean_mod
    path = dateline_mission(tmp_path)
    ns = fx.make(tmp_path / "data", path)
    assert orca_3d_hours(ns) == [f"2023-03-0{d}_0{h}:00:00" for d in (2, 3) for h in (1, 2, 3)]      # 01:56Z + 1920 s + 60 s reaches 03
    assert sorted(fx._moorings(ns.mission)) == ["T0N180E", "T2S180E"]
    lat, lon = fx._ocean_axes(ns.mission)
    assert (lon[0], lon[-1]) == (177.5, 182.5)
    monkeypatch.setattr(pipeline, "DATA", ns.data)
    monkeypatch.setattr(ocean_mod, "DATA", ns.data)
    monkeypatch.setenv("CAFE_DATA", str(ns.data))
    monkeypatch.setenv("CAFE_OFFLINE", "1")
    run = tmp_path / "run"
    pipeline.run(path, "ci", 0, run, stop_after="ingest", log=lambda s: None)
    led = json.loads((run / "checkpoints" / "ingest" / "ledger.json").read_text())
    checks = {c["name"]: c for c in led["checks"]}
    for name in ("orca_present", "tao_present", "gebco_present", "ocean_store_present", "mission_points_inside_cached_grids"):
        assert checks[name]["ok"], (name, checks[name]["note"])
    assert led["ok"] and not [c["name"] for c in led["checks"] if not c["ok"]]


def test_r11_gate_every_name_a_test_reads_from_the_generator_exists_in_it():
    """Round 11 batch A turned the generator's module constants OLAT and OLON into the result of `_ocean_axes`, and tests/test_ocean.py went on reading
    `fx.OLAT`: it failed in the full gate only, because no run of batch A held that file. Every `fx.<name>` in the tests is a name the generator has."""
    import ast
    import pathlib
    missing = []
    for f in sorted(pathlib.Path(__file__).parent.rglob("*.py")):
        tree = ast.parse(f.read_text())
        aliases = {a.asname or a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "tests.fixtures.ci_env"
                   for a in n.names if a.name == "make"}
        missing += [f"{f.name}:{n.lineno}: {n.value.id}.{n.attr}" for n in ast.walk(tree)
                    if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in aliases and not hasattr(fx, n.attr)]
    assert not missing
