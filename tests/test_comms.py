import copy

import numpy as np
import pytest
import yaml
from hypothesis import given, settings, strategies as st

from cafe.pm.physics import comms as c

F915 = 915e6
LAM = c.C0 / F915
fl = st.floats(allow_nan=False, allow_infinity=False)


# ---------------------------------------------------------------- RF
def test_free_space_when_fully_rough_and_reciprocity():
    assert np.isclose(c.two_ray_loss_db(1e3, 2.0, 5.0, 1e3, F915), 32.44 + 20 * np.log10(915.0), atol=0.02)   # Friis, rho = 0
    assert np.isclose(c.two_ray_loss_db(2e3, 2.0, 5.0, 1.0, F915), c.two_ray_loss_db(2e3, 5.0, 2.0, 1.0, F915))


def test_two_ray_beats_free_space_penalty_far_out_and_has_null():
    fs = 20 * np.log10(4 * np.pi * 5e3 / LAM)
    assert c.two_ray_loss_db(5e3, 2.0, 5.0, 0.0, F915) > fs + 20                 # 4th-power law is far worse than 1/d^2
    d = np.linspace(40, 90, 50001)
    assert 0.99 * 2 * 2 * 5 / LAM < d[np.argmax(c.two_ray_loss_db(d, 2.0, 5.0, 0.0, F915))] < 1.01 * 2 * 2 * 5 / LAM


@given(st.floats(1, 10), st.floats(1, 10), st.floats(0, 3), st.floats(1, 4), st.floats(1.01, 20))
@settings(deadline=None)
def test_loss_grows_with_range_past_last_null(ht, hr, hs, mult, grow):
    d1 = 4 * mult * ht * hr / LAM + 100
    assert c.two_ray_loss_db(d1 * grow, ht, hr, hs, F915) > c.two_ray_loss_db(d1, ht, hr, hs, F915)


def test_ament_roughness_limits_and_direction():
    assert c.ament_rho(0.0, 0.1, LAM) == 1.0
    r = c.ament_rho(np.array([0.5, 1.0, 3.0]), 0.3, LAM)
    assert np.all(np.diff(r) < 0) and np.all((r > 0) & (r < 1))
    assert c.ament_rho(2.0, 0.5, LAM) < c.ament_rho(2.0, 0.05, LAM)             # steeper grazing -> rougher
    assert c.ament_rho(2.0, 0.5, LAM) < c.ament_rho(2.0, 0.5, 2 * LAM)          # shorter wavelength -> rougher


def test_rough_sea_changes_loss_where_the_reflection_matters():
    near = [c.two_ray_loss_db(80.0, 2.0, 5.0, h, F915) for h in (0.0, 2.0)]
    assert abs(near[0] - near[1]) > 1.0


def test_radio_horizon_and_rf_margin():
    assert np.isclose(c.radio_horizon_km(2.0, 5.0), 4.12 * (2 ** 0.5 + 5 ** 0.5))
    assert c.radio_horizon_km(-1.0) == 0.0
    d = np.array([[1e3, 5e3, 14e3, 16e3]] * 2)                                  # (members, time)
    m = c.rf_margin(d, 2.0, 5.0, np.array([[0.5], [3.0]]))
    assert m.shape == d.shape and np.all(m[:, :3] > 0) and np.all(m[:, 3] == c.NO_LINK_DB)
    assert np.all(np.diff(m[:, :3], axis=1) < 0)
    assert c.rf_margin(8e3, 2, 5, 1.0, "xbee_pro_24") < c.rf_margin(8e3, 2, 5, 1.0, "rfd900x")
    assert c.rf_margin(8e3, 2, 5, 1.0, "rfd900x_fast") < c.rf_margin(8e3, 2, 5, 1.0, "rfd900x")
    weak = dict(c._yaml("radios.yaml")["radios"]["rfd900x"], tx_dbm=20.0)
    assert c.rf_margin(8e3, 2, 5, 1.0, weak) == c.rf_margin(8e3, 2, 5, 1.0) - 10


# ---------------------------------------------------------------- Iridium
def _yaml_with(monkeypatch, service, **kv):
    y = copy.deepcopy(c._yaml("radios.yaml"))
    y["iridium"][service].update(kv)
    monkeypatch.setattr(c, "_yaml", lambda name: y if name == "radios.yaml" else c._yaml.__wrapped__(name))


def test_iridium_sbd_segments_and_availability(monkeypatch):
    rng = np.random.default_rng
    ok1, t1 = c.iridium_session(100, rng(1), 20000)
    ok3, t3 = c.iridium_session(700, rng(1), 20000)                              # 340 + 340 + 20 B: three sessions
    assert t1.shape == (20000,) and np.all(t1 > 0) and np.median(t3) > 2.2 * np.median(t1)
    assert ok3.mean() < ok1.mean()
    _, tmo = c.iridium_session(300, rng(2), 5000, direction="MO")
    _, tmt = c.iridium_session(300, rng(2), 5000, direction="MT")               # 270 B MT limit: 300 B needs two sessions
    assert np.median(tmt) > 1.5 * np.median(tmo)
    ok, t = c.iridium_session(np.array([10, 700]), rng(3), 2)
    assert ok.shape == (2,) and t[1] > 0
    _yaml_with(monkeypatch, "sbd", p_success=0.0)
    ok, t = c.iridium_session(100, rng(4), 50)
    assert not ok.any() and np.allclose(t, 3 * 60.0)
    _yaml_with(monkeypatch, "sbd", p_success=1.0, session_setup_sigma=0.0)
    ok, t = c.iridium_session(340, rng(5), 50)
    assert ok.all() and np.allclose(t, 10.0 + 20.0)                              # setup median + full-message transfer


def test_iridium_rudics_scales_with_bytes(monkeypatch):
    _yaml_with(monkeypatch, "rudics", p_success=1.0, session_setup_sigma=0.0)
    _, t = c.iridium_session(np.array([0, 2400, 24000]), np.random.default_rng(0), 3, service="rudics")
    assert np.allclose(t, [30.0, 38.0, 110.0])                                   # setup 30 s + 8 n / 2400 bps


@given(st.integers(1, 5000), st.integers(0, 2**32 - 1))
@settings(deadline=None, max_examples=40)
def test_iridium_outputs_are_physical(n, seed):
    ok, t = c.iridium_session(n, np.random.default_rng(seed), 8)
    assert ok.dtype == bool and np.all(t > 0) and np.all(np.isfinite(t))


# ---------------------------------------------------------------- acoustics
def test_thorp_values_and_units():
    assert np.isclose(c.thorp_db_per_km(10.0), 1.18703, atol=1e-4)
    assert np.isclose(c.thorp_db_per_km(1.0), 0.11 / 2 + 44 / 4101 + 2.75e-4 + 0.003)
    assert c.thorp_db_per_km(24.5) > c.thorp_db_per_km(18.5) > c.thorp_db_per_km(11.5) > 0


@given(st.floats(0.5, 100), st.floats(0.5, 100))
def test_thorp_monotonic(a, b):
    lo, hi = sorted((a, b))
    assert c.thorp_db_per_km(lo) <= c.thorp_db_per_km(hi)


def test_acoustic_tl_spreading_and_absorption():
    assert np.isclose(c.acoustic_tl_db(10.0, 0.0, 2.0), 20.0, atol=0.01)         # f -> 0: pure spherical spreading re 1 m
    assert np.isclose(c.acoustic_tl_db(1000.0, 10.0, 1.0), 30 + 1.18703, atol=1e-3)
    assert c.acoustic_tl_db(1000.0, 10.0, 2.0) - c.acoustic_tl_db(1000.0, 10.0, 1.0) == pytest.approx(30.0)


def test_noise_components_and_wind_dependence():
    f = np.logspace(0, 2.5, 50)
    assert np.all(np.diff(c.stojanovic_noise_db(10.0, np.array([0.0, 2.0, 5.0, 10.0, 20.0]))) > 0)
    assert np.isclose(c.stojanovic_noise_db(500.0, 0.0), -15 + 20 * np.log10(500.0), atol=1.0)   # thermal wins far up
    assert c.stojanovic_noise_db(0.1, 5.0, 0.9) > c.stojanovic_noise_db(0.1, 5.0, 0.1) + 5   # shipping matters at 100 Hz
    assert abs(c.stojanovic_noise_db(20.0, 5.0, 0.9) - c.stojanovic_noise_db(20.0, 5.0, 0.1)) < 0.2   # but not at 20 kHz
    mins = [f[np.argmin(c.stojanovic_noise_db(f, w))] for w in (0.0, 5.0, 15.0)]
    assert mins[0] < mins[1] < mins[2]                                            # the minimum moves up with wind


def test_band_noise_integrates_the_psd():
    one = c.band_noise_db(20.0, 21.0, 5.0)
    assert np.isclose(one, c.stojanovic_noise_db(20.5, 5.0) + 30.0, atol=0.1)    # 1 kHz = +30 dB
    w = np.array([[0.0, 5.0], [10.0, 15.0]])
    n = c.band_noise_db(16.0, 21.0, w)
    assert n.shape == (2, 2) and np.all(np.diff(n.ravel()) > 0)


def test_benthos_margins_follow_the_published_ranges():
    for band, km in (("LF", 6.0), ("MF", 4.0), ("HF", 2.0)):
        assert c.acoustic_margin(km * 1e3, band=band) == pytest.approx(3.0)      # the anchor
        assert c.acoustic_margin(1.5 * km * 1e3, band=band) < 0 < c.acoustic_margin(0.5 * km * 1e3, band=band)
    assert c.acoustic_margin(4e3, wind=10.0) < c.acoustic_margin(4e3, wind=5.0) < c.acoustic_margin(4e3, wind=1.0)
    assert c.acoustic_margin(8e3) < 0 < c.acoustic_margin(4e3)
    assert c.acoustic_margin(4e3, tl_extra=10.0) == pytest.approx(c.acoustic_margin(4e3) - 10.0)
    assert c.acoustic_margin(4e3, k=2.0) == pytest.approx(3.0)                    # anchored for any k...
    assert c.acoustic_margin(8e3, k=2.0) < c.acoustic_margin(8e3, k=1.0)          # ...but k changes the extrapolation


def test_micromodem_has_no_table_range_but_a_budget():
    assert c.implementation_loss_db("whoi_micromodem", "long_10k") == c.implementation_loss_db("benthos_atm960", "MF")
    r = np.array([1e3, 20e3])
    lo, hi = (c.acoustic_margin(r, "whoi_micromodem", b) for b in ("long_10k", "short_25k"))
    assert lo[0] > 0 > lo[1] and hi[0] > hi[1]


def test_sound_speed_profile_teos10():
    z = np.array([0.0, -1000.0])
    cs = c.sound_speed_profile(z, 10.0, SA=35.165)
    assert cs[0] == pytest.approx(1489.8, abs=0.6)                                # Chen-Millero: 10 C, S=35, surface
    assert 15.0 < cs[1] - cs[0] < 19.0                                            # ~1.7 m/s per 100 m of pressure
    sp = c.sound_speed_profile(z, 10.0, SP=35.0, lon=-170.0, lat=0.0)
    assert np.allclose(sp, cs, atol=0.5)


# ---------------------------------------------------------------- Bellhop and the Thorp-only fallback
Z = np.array([0.0, -50.0, -200.0, -1000.0, -4000.0])
C = np.array([1540.0, 1538.0, 1520.0, 1495.0, 1520.0])


def _fake_bellhop(monkeypatch, excess=7.0):
    monkeypatch.setattr(c, "bellhop_available", lambda: True)
    monkeypatch.setattr(c, "_run_bellhop", lambda r, f, z, cc, *a: 20 * np.log10(r) + (excess if cc[-1] != cc[0] else 0.0))


def test_link_clear_cases_never_call_bellhop(monkeypatch):
    monkeypatch.setattr(c, "bellhop_available", lambda: pytest.fail("Bellhop was asked about a clear case"))
    out = c.acoustic_link(np.array([1e3, 9e3]), ssp=(Z, C))
    assert list(out["method"]) == ["thorp", "thorp"] and not out["ambiguous"].any() and out["margin"].kind == "modelled"
    assert out["label"] == "Thorp budget decides every link" and np.isnan(out["tl_bellhop_db"]).all()


def test_link_fallback_is_labelled_and_decided_by_thorp(monkeypatch):
    monkeypatch.setattr(c, "bellhop_available", lambda: False)
    r = np.array([1e3, 4.5e3, 5.5e3])
    out = c.acoustic_link(r, ssp=(Z, C))
    assert out["label"] == c.THORP_ONLY_LABEL and list(out["ambiguous"]) == [False, True, True]
    assert out["method"][1] == out["method"][2] == "thorp-only (bellhop unavailable)" and out["method"][0] == "thorp"
    assert np.array_equal(out["margin"].value, out["thorp_margin"]) and "Bellhop" not in out["margin"].source
    assert c.acoustic_link(r)["label"] == "Thorp only, no sound-speed profile supplied"
    assert c.acoustic_link(r)["method"][1] == "thorp-only (no sound-speed profile)"


def test_link_bellhop_replaces_only_the_ambiguous_ones(monkeypatch):
    _fake_bellhop(monkeypatch)
    r = np.array([[1e3, 4.5e3], [5.5e3, 9e3]])
    wind = np.array([[5.0], [5.0]])
    out = c.acoustic_link(r, wind=wind, ssp=(Z, C))
    assert out["ambiguous"].tolist() == [[False, True], [True, False]]
    assert out["method"].tolist() == [["thorp", "bellhop"], ["bellhop", "thorp"]]
    m, mt = out["margin"].value, out["thorp_margin"]
    amb = out["ambiguous"]
    assert np.allclose(m[~amb], mt[~amb]) and np.allclose(m[amb], mt[amb] - 7.0)
    assert np.allclose(out["tl_bellhop_db"][out["ambiguous"]] - out["tl_bellhop_iso_db"][out["ambiguous"]], 7.0)
    assert out["label"] == "Bellhop refined the ambiguous links" and out["margin"].source.endswith("+ Bellhop")
    s = c.acoustic_link(4.5e3, ssp=(Z, C), ambiguous_db=0.1)                      # scalar in, scalar out; 0.1 dB window: clear
    assert s["margin"].value.shape == () and s["method"][()] == "thorp"


@given(st.lists(st.floats(100, 9000), min_size=1, max_size=6), st.floats(0.0, 9000.0))
@settings(deadline=None, max_examples=40)
def test_bellhop_tl_interpolates_the_range_grid(rs, extra):
    r = np.array(rs + [extra])
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(c, "_run_bellhop", lambda g, f, z, cc, *a: 20 * np.log10(g))   # smooth stand-in: must be reproduced
        tl = c.bellhop_tl(r, 18.5, Z, C, n_grid=400)
    inside = r >= 100
    assert tl.shape == r.shape and np.allclose(tl[inside], 20 * np.log10(r[inside]), atol=0.2)


def test_bellhop_dir_search(tmp_path, monkeypatch):
    find = c._bellhop_dir.__wrapped__
    monkeypatch.setenv("CAFE_DATA", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path / "nowhere"))
    assert find() is None
    (tmp_path / "bin").mkdir()
    exe = tmp_path / "bin" / "bellhop.exe"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    assert find() == str(tmp_path / "bin")


def test_real_bellhop_or_labelled_fallback():
    rg = np.array([500.0, 3000.0, 6000.0])
    iso = np.array([1500.0, 1500.0])
    if c.bellhop_available():
        tl = c.bellhop_tl(rg, 18.5, np.array([0.0, -4000.0]), iso)
        assert np.all(np.diff(tl) > 0)
        ref = c.acoustic_tl_db(rg, 18.5, 2.0) - 10 * np.log10(2)
        assert np.all(np.abs(tl - ref) < 3.0)
        # profile branches: starts below the surface, ends above the bottom, a single node, deeper than the water
        for z, cc in ((np.array([-5.0, -3000.0]), iso), (np.array([0.0]), np.array([1500.0])), (Z, C),
                      (np.array([0.0, -100.0, -9000.0]), np.array([1500.0, 1500.0, 1500.0]))):
            assert np.all(np.isfinite(c.bellhop_tl(rg, 18.5, z, cc, water_depth=4000.0)))
        # a thermocline duct changes the loss relative to isovelocity: Bellhop sees what Thorp cannot
        out = c.acoustic_link(np.array([4.2e3]), ssp=(Z, C))
        assert out["method"][0] == "bellhop" and np.isfinite(out["tl_bellhop_db"][0])
    else:
        with pytest.raises(RuntimeError):
            c.bellhop_tl(rg, 18.5, np.array([0.0, -4000.0]), iso)
        assert c.acoustic_link(np.array([4.2e3]), ssp=(Z, C))["label"] == c.THORP_ONLY_LABEL


def test_bellhop_without_field_raises(monkeypatch):
    import arlpy.uwapm as pm
    monkeypatch.setattr(pm, "compute_transmission_loss", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="no field"):
        c._run_bellhop(np.array([500.0, 1000.0]), 18500.0, Z, C, 1.0, 5.0, 4000.0)


# ---------------------------------------------------------------- receipts, and that each can fail
def _claims(patches=(), monkeypatch=None):
    for name, fn in patches:
        monkeypatch.setattr(c, name, fn(getattr(c, name)))
    out = c.receipts()
    return {o["claim"]: o["ok"] for o in out}


def _failed(monkeypatch, *patches):
    return [k for k, ok in _claims(patches, monkeypatch).items() if ok is False]


def test_receipts_pass_on_the_real_physics():
    out = c.receipts()
    assert len(out) >= 15 and all(o["ok"] is not False for o in out)
    assert sum(o["ok"] is True for o in out) >= 14
    assert any("Bellhop" in o["claim"] for o in out)


def test_receipts_fall_back_to_a_labelled_context_without_bellhop(monkeypatch):
    monkeypatch.setattr(c, "bellhop_available", lambda: False)
    out = c.receipts()
    b = [o for o in out if "Bellhop" in o["claim"]]
    assert len(b) == 1 and b[0]["kind"] == "context" and c.THORP_ONLY_LABEL in b[0]["claim"] and b[0]["ok"] is None


def test_receipt_fails_on_wrong_log_base(monkeypatch):
    def ten_log(orig):
        return lambda d, ht, hr, hs, f: orig(d, ht, hr, hs, f) / 2.0            # 10 log10 where 20 log10 belongs
    bad = _failed(monkeypatch, ("two_ray_loss_db", ten_log))
    assert any("loss rise per decade" in k for k in bad) and any("free space" in k for k in bad)


def test_receipt_fails_on_hz_instead_of_khz(monkeypatch):
    bad = _failed(monkeypatch, ("thorp_db_per_km", lambda o: lambda f: o(np.asarray(f) * 1000.0)))
    assert any("Thorp absorption at 10 kHz" in k for k in bad) and any("Benthos" in k for k in bad)


def test_receipt_fails_on_reflection_sign(monkeypatch):
    def plus_one(orig):                                                          # reflection coefficient +1 instead of -1
        def f(d, ht, hr, hs, fr):
            lam, r1, r2 = c.C0 / fr, np.hypot(d, ht - hr), np.hypot(d, ht + hr)
            return 20 * np.log10(4 * np.pi * r1 / lam) - 20 * np.log10(np.abs(1 + np.exp(-2j * np.pi * (r2 - r1) / lam)))
        return f
    assert any("last null" in k for k in _failed(monkeypatch, ("two_ray_loss_db", plus_one)))


def test_receipt_fails_on_roughness_sign(monkeypatch):
    bad = _failed(monkeypatch, ("ament_rho", lambda o: lambda *a: 2.0 - o(*a)))
    assert any("Ament" in k for k in bad)


def test_receipt_fails_on_horizon_units(monkeypatch):
    bad = _failed(monkeypatch, ("radio_horizon_km", lambda o: lambda ht, hr=0.0: o(ht, hr) * 1.852))   # nautical miles read as km
    assert sum("horizon" in k for k in bad) == 3


def test_receipt_fails_on_noise_errors(monkeypatch):
    in_hz = lambda o: lambda f, w, s=0.5: o(np.asarray(f) * 1000.0, w, s)
    bad = _failed(monkeypatch, ("stojanovic_noise_db", in_hz))
    assert any("minimum" in k for k in bad)
    flat = lambda o: lambda f, w, s=0.5: o(f, 0.0, s)                           # wind term lost
    bad = _failed(monkeypatch, ("stojanovic_noise_db", flat))
    assert any("Wind noise" in k for k in bad)


def test_receipt_fails_on_margin_sign(monkeypatch):
    bad = _failed(monkeypatch, ("acoustic_margin", lambda o: lambda *a, **k: -o(*a, **k)))
    assert any("Benthos ATM-960 MF margin at 4 km" in k for k in bad) and any("MF margin at 6 km" in k for k in bad)


def test_receipt_fails_when_bellhop_disagrees(monkeypatch):
    monkeypatch.setattr(c, "bellhop_available", lambda: True)
    monkeypatch.setattr(c, "bellhop_tl", lambda r, f, *a, **k: c.acoustic_tl_db(r, f, 2.0) - 10 * np.log10(2) + 5.0)
    assert any("Bellhop vs Thorp" in k for k in _failed(monkeypatch))


def test_receipt_fails_on_iridium_errors(monkeypatch):
    y = copy.deepcopy(c._yaml("radios.yaml"))
    real = c._yaml
    y["iridium"]["sbd"]["latency_short_s"] = 100.0
    y["iridium"]["sbd"]["latency_full_s"] = 200.0
    monkeypatch.setattr(c, "_yaml", lambda name: y if name == "radios.yaml" else real(name))
    assert any("Iridium SBD median latency" in k for k in _failed(monkeypatch))
    real_sess = c.iridium_session
    one_shot = lambda n, rng, m, **k: (rng.random(m) < 0.95, real_sess(n, rng, m)[1])      # no retries
    monkeypatch.setattr(c, "iridium_session", one_shot)
    assert any("Iridium SBD success" in k for k in _failed(monkeypatch))


# ---------------------------------------------------------------- assumed radio numbers are marked leaf by leaf

def test_radios_yaml_marks_every_assumed_number_and_the_models_still_read_bare_numbers():
    import pathlib
    raw = yaml.safe_load((pathlib.Path(c.PLATFORMS) / "radios.yaml").read_text())
    for r in ("rfd900x", "rfd900x_fast", "xbee_pro_24"):
        for k in ("gt_dbi", "gr_dbi", "misc_loss_db"):
            leaf = raw["radios"][r][k]
            assert leaf["assumed"] is True and len(leaf["why"]) > 30 and "value" in leaf and "unit" in leaf, (r, k)
    for svc in ("sbd", "rudics"):
        for k in ("session_setup_median_s", "session_setup_sigma", "p_success", "max_attempts", "fail_cost_s"):
            assert raw["iridium"][svc][k]["assumed"] is True and raw["iridium"][svc][k]["why"], (svc, k)
    plain = c._yaml("radios.yaml")
    assert plain["radios"]["rfd900x"]["gt_dbi"] == 2.0 and plain["radios"]["rfd900x"]["misc_loss_db"] == 3.0 and plain["iridium"]["sbd"]["max_attempts"] == 3
    assert plain["radios"]["rfd900x"]["center_mhz"] == 915.0 and isinstance(plain["iridium"]["sbd"]["max_bytes"], dict)             # sourced numbers untouched
    assert c._yaml("modems.yaml") == yaml.safe_load((pathlib.Path(c.PLATFORMS) / "modems.yaml").read_text())
    assert np.isfinite(c.rf_margin(5000.0, 10.0, 15.0, 1.0, "rfd900x"))


def test_the_credibility_report_counts_the_assumed_radio_numbers():
    from cafe.pm import credibility
    items = credibility.assumed_inputs()
    ids = {i["id"] for i in items if i["kind"] == "assumed" and i["file"] == "platforms/radios.yaml"}
    assert len(ids) == 19 and "radios.yaml:radios.rfd900x.misc_loss_db" in ids and "radios.yaml:iridium.sbd.p_success" in ids
