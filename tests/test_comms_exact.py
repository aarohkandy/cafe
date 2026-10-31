"""cafe.pm.physics.comms: the link budget, the yaml reader, the Bellhop hand-off and the sound-speed column checked term by term.
(tests/test_comms.py checks the physics; these pin each argument and sign so that a swapped term or a dropped argument fails.)"""
import numpy as np
import pytest

from cafe.pm.physics import comms as c

RADIO = dict(center_mhz=900.0, tx_dbm=30.0, gt_dbi=2.0, gr_dbi=3.0, cable_loss_db=1.5, misc_loss_db=0.25, rx_sens_dbm=-100.0)


def test_plain_unwraps_value_unit_leaves_and_nothing_else():
    node = {"a": {"value": 3, "unit": "m", "assumed": True, "why": "x"}, "b": 2, "c": {"value": 1}, "d": {"unit": "m"},
            "e": {"f": {"value": 7, "unit": "s"}, "g": [1, 2]}, "h": {}}
    assert c._plain(node) == {"a": 3, "b": 2, "c": {"value": 1}, "d": {"unit": "m"}, "e": {"f": 7, "g": [1, 2]}, "h": {}}
    assert c._plain(5) == 5 and c._plain("value") == "value" and c._plain({"value": 0, "unit": ""}) == 0
    assert c._plain({"value": None, "unit": "m"}) is None


def test_rf_margin_is_the_budget_term_by_term():
    d, ht, hr, hs = 3000.0, 2.0, 5.0, 1.0
    loss = c.two_ray_loss_db(d, ht, hr, hs, 900e6)
    want = 30.0 + 2.0 + 3.0 - 1.5 - 0.25 - loss + 100.0
    assert c.rf_margin(d, ht, hr, hs, RADIO) == pytest.approx(want, abs=1e-9)
    for key, delta in (("tx_dbm", 1.0), ("gt_dbi", 1.0), ("gr_dbi", 1.0), ("rx_sens_dbm", -1.0)):
        # more power, gain, sensitivity: +dB
        assert c.rf_margin(d, ht, hr, hs, dict(RADIO, **{key: RADIO[key] + delta})) - want == pytest.approx(1.0, abs=1e-9)
    for key in ("cable_loss_db", "misc_loss_db"):
        assert c.rf_margin(d, ht, hr, hs, dict(RADIO, **{key: RADIO[key] + 1.0})) - want == pytest.approx(-1.0, abs=1e-9)         # more loss: -dB
    at_450 = 30.0 + 2.0 + 3.0 - 1.5 - 0.25 + 100.0 - c.two_ray_loss_db(d, ht, hr, hs, 450e6)
    assert c.rf_margin(d, ht, hr, hs, dict(RADIO, center_mhz=450.0)) == pytest.approx(at_450)


def test_rf_margin_cuts_off_at_the_radio_horizon_and_not_before():
    h = float(c.radio_horizon_km(2.0, 5.0)) * 1e3
    assert c.rf_margin(h, 2.0, 5.0, 1.0, RADIO) != c.NO_LINK_DB                      # exactly on the horizon is still a link
    assert c.rf_margin(h * 1.0005, 2.0, 5.0, 1.0, RADIO) == c.NO_LINK_DB and c.rf_margin(h * 0.999, 2.0, 5.0, 1.0, RADIO) != c.NO_LINK_DB
    assert c.rf_margin(np.array([h, h + 1.0]), 2.0, 5.0, 1.0, RADIO).tolist()[1] == c.NO_LINK_DB


def test_named_radio_comes_from_radios_yaml_with_bare_numbers():
    r = c._yaml("radios.yaml")["radios"]["rfd900x"]
    assert all(not isinstance(v, dict) for v in r.values())
    assert c.rf_margin(2000.0, 2.0, 5.0, 1.0) == c.rf_margin(2000.0, 2.0, 5.0, 1.0, "rfd900x") == c.rf_margin(2000.0, 2.0, 5.0, 1.0, r)


def test_sound_speed_profile_converts_practical_salinity_at_the_given_place():
    import gsw
    z, t = np.array([0.0, -500.0, -2000.0]), np.array([15.0, 8.0, 3.0])
    for lon, lat in ((0.0, 0.0), (-170.0, 45.0), (30.0, -60.0)):
        p = gsw.p_from_z(z, lat)
        SA = gsw.SA_from_SP(34.5, p, lon, lat)
        want = gsw.sound_speed(SA, gsw.CT_from_t(SA, t, p), p)
        assert c.sound_speed_profile(z, t, SP=34.5, lon=lon, lat=lat) == pytest.approx(want, rel=1e-12)
    p0 = gsw.p_from_z(z, 0.0)
    SA0 = gsw.SA_from_SP(34.5, p0, 0.0, 0.0)
    # lon = lat = 0 by default
    assert c.sound_speed_profile(z, t, SP=34.5) == pytest.approx(gsw.sound_speed(SA0, gsw.CT_from_t(SA0, t, p0), p0), rel=1e-13)
    assert c.sound_speed_profile(z, t, SP=34.5, lon=1.0, lat=0.0) != pytest.approx(c.sound_speed_profile(z, t, SP=34.5), rel=1e-13)
    assert c.sound_speed_profile(z, t, SP=34.5, lat=1.0) != pytest.approx(c.sound_speed_profile(z, t, SP=34.5), rel=1e-13)
    sa = c.sound_speed_profile(z.tolist(), t, SA=35.0)                                  # a list for z is fine, SA wins over SP
    assert sa == pytest.approx(gsw.sound_speed(35.0, gsw.CT_from_t(35.0, t, gsw.p_from_z(z, 0.0)), gsw.p_from_z(z, 0.0)), rel=1e-13)
    assert c.sound_speed_profile(z, t, SA=35.0, SP=10.0) == pytest.approx(sa, rel=1e-13)


Z = np.array([0.0, -50.0, -200.0, -1000.0, -4000.0])
CSSP = np.array([1540.0, 1538.0, 1520.0, 1495.0, 1520.0])


def spy_bellhop(monkeypatch, excess=7.0):
    calls = []
    monkeypatch.setattr(c, "bellhop_available", lambda: True)

    def run(r, f_hz, z, cc, tx, rx, wd):
        calls.append(dict(r=np.asarray(r).copy(), f_hz=f_hz, z=np.asarray(z).copy(), c=np.asarray(cc).copy(), tx=tx, rx=rx, wd=wd))
        return 20 * np.log10(np.asarray(r, float)) + (excess if cc[-1] != cc[0] else 0.0)
    monkeypatch.setattr(c, "_run_bellhop", run)
    return calls


def test_acoustic_link_hands_bellhop_the_depths_the_profile_and_the_band_centre(monkeypatch):
    calls = spy_bellhop(monkeypatch)
    out = c.acoustic_link(np.array([4.5e3, 1e3]), ssp=(Z, CSSP), tx_depth=3.0, rx_depth=11.0, water_depth=3500.0)
    assert out["ambiguous"].tolist() == [True, False] and len(calls) == 2
    for call in calls:
        assert (call["tx"], call["rx"], call["wd"]) == (3.0, 11.0, 3500.0)
        assert call["f_hz"] == pytest.approx(18500.0) and np.array_equal(call["z"], Z)                              # MF band 16-21 kHz, mean 18.5
    # second run: isovelocity at the surface
    assert np.array_equal(calls[0]["c"], CSSP)
    assert np.all(calls[1]["c"] == CSSP[0])
    assert calls[1]["c"].shape == CSSP.shape
    assert out["tl_bellhop_db"][0] == pytest.approx(20 * np.log10(4.5e3) + 7.0) and out["tl_bellhop_iso_db"][0] == pytest.approx(20 * np.log10(4.5e3))
    assert np.isnan(out["tl_bellhop_db"][1]) and np.isnan(out["tl_bellhop_iso_db"][1])
    defaults = spy_bellhop(monkeypatch)
    c.acoustic_link(np.array([4.5e3]), ssp=(Z, CSSP))
    assert (defaults[0]["tx"], defaults[0]["rx"], defaults[0]["wd"]) == (1.0, 5.0, 4000.0)


def test_acoustic_link_adds_the_bellhop_excess_to_the_thorp_loss_with_the_callers_shipping_and_spreading(monkeypatch):
    spy_bellhop(monkeypatch, excess=7.0)
    r = np.array([4.5e3])
    for shipping, k in ((0.5, 1.5), (0.9, 1.5), (0.5, 1.9)):
        out = c.acoustic_link(r, ssp=(Z, CSSP), shipping=shipping, k=k, ambiguous_db=40.0)
        thorp = c.acoustic_margin(r, "benthos_atm960", "MF", 5.0, shipping, k)
        assert out["thorp_margin"] == pytest.approx(thorp, abs=1e-12)
        assert out["margin"].value == pytest.approx(c.acoustic_margin(r, "benthos_atm960", "MF", 5.0, shipping, k, tl_extra=7.0), abs=1e-12)
        assert out["margin"].value == pytest.approx(thorp - 7.0, abs=1e-12)
    lf = c.acoustic_link(r, "benthos_atm960", "LF", ssp=(Z, CSSP), ambiguous_db=60.0)["thorp_margin"]
    assert lf != pytest.approx(c.acoustic_link(r, ssp=(Z, CSSP))["thorp_margin"])


def test_acoustic_link_window_is_inclusive_and_defaults_to_the_yaml_six_db(monkeypatch):
    monkeypatch.setattr(c, "bellhop_available", lambda: False)
    r = np.array([4.5e3])
    m = float(c.acoustic_margin(r)[0])
    assert c._yaml("modems.yaml")["defaults"]["ambiguous_db"] == 6.0
    assert c.acoustic_link(r, ssp=(Z, CSSP), ambiguous_db=abs(m))["ambiguous"][0]
    assert not c.acoustic_link(r, ssp=(Z, CSSP), ambiguous_db=abs(m) - 1e-9)["ambiguous"][0]
    assert c.acoustic_link(r, ssp=(Z, CSSP))["ambiguous"][0] == (abs(m) <= 6.0)
    assert c.acoustic_link(r, ssp=(Z, CSSP), ambiguous_db=0.0)["ambiguous"][0] == (m == 0.0)


def test_acoustic_link_wind_broadcasts_against_range_and_selects_the_ambiguous_winds(monkeypatch):
    spy_bellhop(monkeypatch)
    r = np.array([4.5e3, 4.5e3])
    out = c.acoustic_link(r, wind=np.array([3.0, 20.0]), ssp=(Z, CSSP), ambiguous_db=60.0)
    want = c.acoustic_margin(r, wind=np.array([3.0, 20.0]))
    # more wind, more noise, less margin
    assert out["thorp_margin"] == pytest.approx(want, abs=1e-12)
    assert out["thorp_margin"][0] > out["thorp_margin"][1]
    assert out["margin"].value == pytest.approx(want - 7.0, abs=1e-12)
    ints = c.acoustic_link(np.array([4500, 4500]), wind=np.array([3, 20]), ssp=(Z, CSSP), ambiguous_db=60.0)
    # integer inputs are read as floats
    assert ints["thorp_margin"] == pytest.approx(want, abs=1e-12)


def test_the_source_label_names_the_modem_the_band_and_bellhop_only_when_it_ran(monkeypatch):
    spy_bellhop(monkeypatch)
    ran = c.acoustic_link(np.array([4.5e3]), "whoi_micromodem", "long_10k", ssp=(Z, CSSP), ambiguous_db=100.0)["margin"].source
    assert ran == "Thorp/Stojanovic budget whoi_micromodem/long_10k + Bellhop"
    assert c.acoustic_link(np.array([1e3]), ssp=(Z, CSSP))["margin"].source == "Thorp/Stojanovic budget benthos_atm960/MF"
    monkeypatch.setattr(c, "bellhop_available", lambda: False)
    assert c.acoustic_link(np.array([4.5e3]), ssp=(Z, CSSP))["margin"].source == "Thorp/Stojanovic budget benthos_atm960/MF"
