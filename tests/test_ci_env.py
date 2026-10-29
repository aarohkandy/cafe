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
    d = ci_env.data / "tao"
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
    moor = tao.load_tao(ci_env.data / "tao", t0, t1)
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
