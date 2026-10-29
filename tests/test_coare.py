import numpy as np
import pytest
from hypothesis import given, settings, strategies as st
from pycoare import coare_35

from cafe.pm.env import coare

QA = lambda tc, rh, p=1010.0: float(coare.qair(tc, p, rh))  # noqa: E731


def run(u=7.0, tc=27.0, dT=0.5, rh=0.8, **kw):
    a = dict(
        u=u,
        zu=10.0,
        t=tc + 273.15,
        zt=2.0,
        q=QA(tc, rh),
        zq=2.0,
        P=101000.0,
        ts=tc + dT + 273.15,
        Rs=300.0,
        Rl=420.0,
        lat=0.0,
        zi=600.0,
    )
    a.update(kw)
    return coare.coare35(**a)


@pytest.fixture(scope="module")
def recs():
    return coare.receipts()


def test_receipts_pass(recs):
    assert len(recs) > 20
    bad = [r["claim"] for r in recs if r["ok"] is False]
    assert not bad, bad


def _fails(monkeypatch, name, fn):
    monkeypatch.setattr(coare, name, fn)
    return [r["claim"] for r in coare.receipts() if r["ok"] is False]


def test_receipts_fail_on_wind_stability_sign_flip(monkeypatch):
    orig = coare.psiu
    assert any("pycoare" in c for c in _fails(monkeypatch, "psiu", lambda z: -orig(z)))


def test_receipts_fail_on_temperature_stability_sign_flip(monkeypatch):
    orig = coare.psit
    assert any("pycoare" in c for c in _fails(monkeypatch, "psit", lambda z: -orig(z)))


def test_receipts_fail_on_warm_layer_unit_error(monkeypatch):
    orig = coare.warm_layer

    def bad(t, sw, *a, **k):  # shortwave passed in kW/m2 x 1000 -> 1000x too strong forcing
        return orig(t, sw * 3.0, *a, **k)

    c = _fails(monkeypatch, "warm_layer", bad)
    assert any("warm-layer" in x for x in c)


def test_receipts_fail_on_charnock_slope(monkeypatch):
    monkeypatch.setattr(coare, "CH1", 0.0017 * 3)
    assert any("pycoare" in c or "closure" in c for c in [r["claim"] for r in coare.receipts() if r["ok"] is False])


@given(
    u=st.floats(1.0, 20.0),
    tc=st.floats(5.0, 32.0),
    dT=st.floats(-4.0, 4.0),
    rh=st.floats(0.4, 0.95),
    sw=st.floats(0.0, 1000.0),
    lat=st.floats(-60.0, 60.0),
)
@settings(max_examples=60, deadline=None)
def test_state_agreement_with_pycoare(u, tc, dT, rh, sw, lat):
    ref = coare_35(
        [u],
        t=[tc],
        rh=[rh * 100],
        zu=[10.0],
        zt=[2.0],
        zq=[2.0],
        ts=[tc + dT],
        p=[1010.0],
        lat=[lat],
        zi=[600.0],
        rs=[sw],
        rl=[400.0],
    )
    m = run(u=u, tc=tc, dT=dT, rh=rh, Rs=sw, lat=lat, Rl=400.0)
    assert np.isclose(m["ustar"], ref.velocities.usr[0], rtol=1e-6)
    assert np.isclose(m["hsb"], ref.fluxes.hsb[0], rtol=1e-6, atol=1e-9)
    assert np.isclose(m["hlb"], ref.fluxes.hlb[0], rtol=1e-6, atol=1e-9)


@given(u=st.floats(2.0, 18.0), dT=st.floats(-3.0, 3.0))
@settings(max_examples=40, deadline=None)
def test_profile_returns_the_input_at_zu_and_is_monotone(u, dT):
    r = run(u=u, dT=dT)
    assert np.isclose(float(coare.profile(r, 10.0)), u, rtol=0.02)
    z = np.array([0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 100.0])
    p = coare.profile(r, z)
    assert np.all(np.diff(p) > 0) and p[0] >= 0


def test_profile_stable_has_more_shear_than_unstable():
    stable, neutral, unstable = run(u=5.0, dT=-2.0), run(u=5.0, dT=0.0, rh=0.8), run(u=5.0, dT=2.0)
    rat = lambda r: float(coare.profile(r, 100.0) / coare.profile(r, 10.0))  # noqa: E731
    assert rat(stable) > rat(neutral) > rat(unstable)
    assert stable["L"] > 0 > unstable["L"]
    assert stable["zeta"] > 0 > unstable["zeta"]


def test_profile_below_z0_is_zero_and_vectorizes_over_members():
    r = run(u=np.array([3.0, 6.0, 9.0]))
    p = coare.profile(r, np.array([[1e-9], [10.0]]).reshape(2, 1) * np.ones((1, 3)))
    assert p.shape == (2, 3) and np.all(p[0] == 0) and np.all(p[1] > 0)


def test_heat_flux_signs_and_units():
    warm_sea, cold_sea = run(dT=2.0), run(dT=-2.0)
    assert warm_sea["hsb"] > 0 > cold_sea["hsb"]  # positive = sea loses heat
    assert warm_sea["hlb"] > 0 and warm_sea["tau"] > 0
    assert 0.05 < warm_sea["ustar"] < 0.5 and 50 < warm_sea["hlb"] < 400  # W/m2, plausible for 7 m/s tropical ocean


def test_rain_heat_flux_and_default_zero():
    assert np.all(run()["rf"] == 0)
    assert run(rain=10.0)["rf"] > 0


def test_roughness_modes():
    base = run(u=10.0)
    wave = run(u=10.0, cp=12.0)
    sea = run(u=10.0, cp=12.0, sigH=2.0)
    assert not np.isclose(base["z0"], wave["z0"], rtol=0.01) and not np.isclose(wave["z0"], sea["z0"], rtol=0.01)
    assert np.isclose(
        wave["z0"] - 0.11 * 1.5e-5 / wave["ustar"],
        coare.A_WAVE * (wave["ustar"] / 12.0) ** coare.B_WAVE * wave["ustar"] ** 2 / 9.78,
        rtol=0.03,
    )
    # elements with NaN cp fall back to the wind-speed Charnock, elements with NaN sigH to the wave-age form
    mix = run(u=np.array([10.0, 10.0, 10.0]), cp=np.array([np.nan, 12.0, 12.0]), sigH=np.array([2.0, np.nan, 2.0]))
    assert (
        np.isclose(mix["z0"][0], base["z0"], rtol=1e-9)
        and np.isclose(mix["z0"][1], wave["z0"], rtol=1e-9)
        and np.isclose(mix["z0"][2], sea["z0"], rtol=1e-9)
    )
    # sea-state z0 smaller than the smooth-flow value is floored at it
    calm = run(u=2.0, cp=10.0, sigH=0.2)
    assert calm["z0"] >= 0.11 * 1.5e-5 / calm["ustar"] * 0.99


def test_strong_stable_limit_is_finite():
    r = run(u=0.5, dT=-6.0, rh=0.5)
    assert np.all(np.isfinite([r["ustar"], r["L"], r["hsb"]])) and r["L"] > 0


def test_helpers():
    assert np.isclose(coare.grav(0.0), 9.7803253359) and np.isclose(coare.grav(90.0), 9.8321849, atol=1e-6)
    assert np.isclose(float(coare.qsea(27.0, 1010.0)), 0.02183, atol=1e-4)
    assert float(coare.qair(27.0, 1010.0, 1.0)) > float(coare.qair(27.0, 1010.0, 0.5))
    assert (
        float(coare.qair(27.0, 1010.0, 1.0)) > float(coare.qsea(27.0, 1010.0)) * 0.98
    )  # fresh-water saturation exceeds sea water


@given(zeta=st.floats(-20.0, 20.0).filter(lambda z: abs(z) > 1e-3))
def test_stability_functions_have_the_right_sign_and_continuity(zeta):
    sign = np.sign(-zeta)  # psi > 0 unstable (zeta < 0), < 0 stable
    assert np.sign(coare.psiu(zeta)) == sign and np.sign(coare.psit(zeta)) == sign
    assert np.isclose(coare.psiu(1e-9), coare.psiu(-1e-9), atol=1e-6)
    assert coare.psiu_setup(0.0) == 0


# ---------------------------------------------------------------- warm layer


def forcing(days=3, wind=2.0, peak=1000.0):
    t = np.arange(0, days * 86400, 3600.0)
    return t, coare._diurnal_forcing(np.mod(t / 3600.0, 24.0), peak), np.full(t.size, wind)


def wl(t, sw, u, **kw):
    n = t.size
    a = dict(
        t=t,
        swdown=sw,
        u=u,
        tair=np.full(n, 300.0),
        q=np.full(n, 0.017),
        P=np.full(n, 101000.0),
        sst=np.full(n, 302.0),
        glw=np.full(n, 420.0),
        lat=0.0,
        lon=0.0,
    )
    a.update(kw)
    return coare.warm_layer(**a)


def test_warm_layer_diurnal_cycle():
    t, sw, u = forcing()
    w = wl(t, sw, u)
    dT = w["dT_warm"]
    hours = np.mod(t / 3600.0, 24.0)
    last = slice(48, 72)
    assert 0.3 < dT[last].max() < 3.5
    assert 12 <= hours[last][np.argmax(dT[last])] <= 18  # peak early afternoon
    assert dT[last][hours[last] == 6][0] < 0.1 * dT[last].max()  # decays overnight / reset by local midnight
    assert np.all(dT >= 0) and np.all(w["dz_warm"] <= 19.0) and w["dz_warm"][last].min() < 19.0
    assert np.all(w["dT_cool"] > 0) and np.all(w["sst_skin"] < 302.0 + dT + 1e-9)


def test_warm_layer_decreases_with_wind_and_vanishes_without_sun():
    t, sw, u = forcing()
    peak = lambda wind: wl(t, sw, np.full(t.size, wind))["dT_warm"].max()  # noqa: E731
    assert peak(1.0) > peak(3.0) > peak(6.0) > peak(12.0)
    assert np.all(wl(t, sw * 0, u)["dT_warm"] == 0)
    assert wl(t, sw * 1.5, u)["dT_warm"].max() > wl(t, sw, u)["dT_warm"].max()


def test_warm_layer_members_longitude_rain_and_sensor_depth():
    t, sw, u = forcing(2)
    uu = np.array([[1.5], [8.0]]) * np.ones(t.size)
    w = wl(t, sw, uu, lat=np.array([0.0, 5.0]), lon=np.array([160.0, -170.0]), rain=np.full(t.size, 2.0))
    assert w["dT_warm"].shape == (2, t.size) and w["dT_warm"][0].max() > w["dT_warm"][1].max()
    skin_s, skin_d = wl(t, sw, u, sst_depth=0.5)["sst_skin"], wl(t, sw, u)["sst_skin"]
    assert skin_s.max() < skin_d.max()  # a sensor inside the layer needs less correction to reach the skin
    # local time follows longitude: shifting lon by 180 deg moves the daily warming peak by 12 h
    a = wl(t, sw, u, lon=0.0)["dT_warm"]
    b = wl(t, sw, u, lon=180.0)["dT_warm"]
    assert not np.allclose(a, b)


def test_warm_layer_requires_time_last():
    t, sw, u = forcing(1)
    with pytest.raises(ValueError, match="time must be the last axis"):
        wl(
            t,
            sw[:5],
            u[:5],
            tair=np.full(5, 300.0),
            q=np.full(5, 0.017),
            P=np.full(5, 101000.0),
            sst=np.full(5, 302.0),
            glw=np.full(5, 420.0),
        )
