"""Round 17, batch D: RF link physics and validation (M-5, M-6, M-16, M-20). Each test names its finding. Reference values come from calculations written
here from the published formulas (ITU-R P.526, the Fresnel coefficient), never from the code under test."""
import math
import os

import numpy as np
import pytest
import yaml

from cafe.pm import config
from cafe.pm import physics
from cafe.pm.physics import check_params, glider, uas, usv
from cafe.pm.physics import comms as c

ROOT = config.ROOT
F915 = 915e6


def copy_of(tmp_path, name, edit):
    raw = yaml.safe_load((ROOT / "platforms" / f"{name}.yaml").read_text())
    edit(raw)
    f = tmp_path / f"{name}.yaml"
    f.write_text(yaml.safe_dump(raw))
    return str(f)


# ---------------------------------------------------------------- M-16: no Bellhop is no directory on PATH
def test_m16_a_missing_bellhop_leaves_path_as_it_was_and_never_writes_none_into_it(monkeypatch):
    """`None not in PATH.split(...)` was always true, so `PATH` read `None:/usr/bin` after one call and `None:None:/usr/bin` after two."""
    import arlpy.uwapm as pm
    base = "/usr/bin" + os.pathsep + "/bin"
    monkeypatch.setenv("PATH", base)
    monkeypatch.setattr(c, "_bellhop_dir", lambda: None)

    def stop(*a, **k):
        raise RuntimeError("stop before bellhop")
    monkeypatch.setattr(pm, "create_env2d", stop)
    for _ in range(2):
        with pytest.raises(RuntimeError, match="stop before bellhop"):
            c._run_bellhop(np.array([1000.0]), 9000.0, np.array([-5.0, -50.0]), np.array([1500.0, 1490.0]), 5.0, 5.0, 100.0)
        assert os.environ["PATH"] == base


# ---------------------------------------------------------------- M-6: the floor of an RF antenna height in the platform files
RF_HEIGHT = [("seaglider", glider, "antenna_height_m", lambda r, v: r["params"]["antenna_height_m"].update(value=v)),
             ("slocum", glider, "antenna_height_m", lambda r, v: r["params"]["antenna_height_m"].update(value=v)),
             ("saildrone_explorer", usv, "rf_antenna_height_m", lambda r, v: r["params"]["rf_antenna_height_m"].update(value=v))]
IDS = [r[0] for r in RF_HEIGHT]


def load(mod, path):
    return mod.load_platform(path)


@pytest.mark.parametrize("name,mod,key,put", RF_HEIGHT, ids=IDS)
@pytest.mark.parametrize("value", [0, 0.0, 1e-9, 0.05, 0.0999, -0.3])
def test_m6_an_rf_antenna_height_below_a_tenth_of_a_metre_is_refused_naming_the_key_and_why(tmp_path, name, mod, key, put, value):
    """0 m gave `rf_margin(5e3, 0, 10, 0.5)` = -43.2 dB (and +1.4 dB at 1 km): a finite number that is not physics. The two-ray model has no meaning there."""
    with pytest.raises(ValueError, match=rf"params\.{key}: .* must be a finite number 0\.1 m or above.*two-ray link model has no meaning"):
        load(mod, copy_of(tmp_path, name, lambda r: put(r, value)))


@pytest.mark.parametrize("name,mod,key,put", RF_HEIGHT, ids=IDS)
@pytest.mark.parametrize("value", [0.1, 0.3, 0.5, 2.2])
def test_m6_the_floor_itself_and_the_shipped_heights_load(tmp_path, name, mod, key, put, value):
    assert load(mod, copy_of(tmp_path, name, lambda r: put(r, value)))[key] == value


def test_m6_the_floor_is_a_tenth_of_a_metre():
    assert physics.ANTENNA_MIN_M == 0.1


def test_m6_the_shipped_platforms_still_load_with_the_heights_the_demo_uses():
    assert glider.load_platform("slocum")["antenna_height_m"] == 0.3 and glider.load_platform("seaglider")["antenna_height_m"] == 0.5
    assert usv.load_platform()["rf_antenna_height_m"] == 2.2 and uas.load_platform()["radio"]["ship_antenna_height_m"] == 10.0


def test_m6_the_usv_rf_height_keeps_its_upper_bound():
    with pytest.raises(ValueError, match=r"rf_antenna_height_m: 51 must be a finite number 0\.1 m or above and at most 50"):
        check_params(usv.REQUIRED, dict(usv.load_platform(), rf_antenna_height_m=51), "x.yaml:params", "saildrone_explorer")


@pytest.mark.parametrize("value,ok", [(0, False), (0.2, False), (0.49, False), (0.5, True), (10, True), (100, True), (100.5, False)])
def test_m6_the_ship_antenna_of_the_uas_platform_is_the_mission_schemas_half_metre_to_a_hundred(tmp_path, value, ok):
    """It is the ship's antenna wherever the mission names none, and reaches `rf_margin` as `hr`; the mission schema refuses 0 and 0.1 for the same key."""
    path = copy_of(tmp_path, "quad_uas", lambda r: r["radio"]["ship_antenna_height_m"].update(value=value))
    if ok:
        assert uas.load_platform(path)["radio"]["ship_antenna_height_m"] == value
    else:
        with pytest.raises(ValueError, match=r"radio\.ship_antenna_height_m: .* must be a finite number from 0\.5 to 100.*mission's ship\.antenna"):
            uas.load_platform(path)


@pytest.mark.parametrize("value,ok", [(0, False), (-1.0, False), (51, False), (0.05, True), (2.0, True), (50, True)])
def test_m6_the_iridium_antenna_height_nothing_reads_is_checked_when_the_file_has_it(tmp_path, value, ok):
    path = copy_of(tmp_path, "saildrone_explorer", lambda r: r["params"]["iridium_antenna_height_m"].update(value=value))
    if ok:
        assert usv.load_platform(path)["iridium_antenna_height_m"] == value
    else:
        with pytest.raises(ValueError, match=r"params\.iridium_antenna_height_m: .* must be a finite number above 0 and at most 50"):
            usv.load_platform(path)


def test_m6_a_usv_file_without_the_iridium_antenna_still_loads(tmp_path):
    """It is in OPTIONAL: the new check must not make it required."""
    path = copy_of(tmp_path, "saildrone_explorer", lambda r: r["params"].pop("iridium_antenna_height_m"))
    assert "iridium_antenna_height_m" not in usv.load_platform(path)


def test_m6_every_antenna_height_a_platform_table_lists_refuses_zero_except_the_one_added_to_the_body_height():
    """The class: a height that reaches the RF link as an absolute height must not take 0. The UAS's whip is added to the deck height and the altitude, so
    0 is harmless there; a new `*antenna*` key with a plain `nonneg` or `pos` kind would show here."""
    tables = [("glider." + k, t) for k, t in glider.REQUIRED.items()] + [("usv", usv.REQUIRED), ("uas.radio", uas.REQUIRED["radio"])]
    seen = set()
    for where, table in tables:
        for key, kind in table.items():
            if "antenna" in key:
                seen.add(key)
                if key == "uas_antenna_height_above_body_m":
                    continue
                with pytest.raises(ValueError, match="must be a finite number"):
                    check_params({key: kind}, {key: 0.0}, where, "r")
    assert seen == {"antenna_height_m", "rf_antenna_height_m", "ship_antenna_height_m", "uas_antenna_height_above_body_m"}


# ---------------------------------------------------------------- M-5: the loss of a low antenna (the -1 reflection), documented and measured
def fresnel_loss_db(d, ht, hr, f_hz=F915, eps_r=72.8, sigma=6.05):
    """Flat-earth two-ray loss with the Fresnel coefficient of vertical polarisation over sea water, eps_c = eps_r - j 60 sigma lambda (T 29 C, S 35):
    field = |1 + R (r1 / r2) exp(-j k (r2 - r1))|, R = (eps_c sin(psi) - sqrt(eps_c - cos^2 psi)) / (eps_c sin(psi) + sqrt(eps_c - cos^2 psi)). Written here;
    no code of cafe.pm is used but the speed of light."""
    lam = c.C0 / f_hz
    eps = eps_r - 1j * 60.0 * sigma * lam
    r1, r2 = np.hypot(d, ht - hr), np.hypot(d, ht + hr)
    psi = np.arctan2(ht + hr, d)
    root = np.sqrt(eps - np.cos(psi) ** 2)
    refl = (eps * np.sin(psi) - root) / (eps * np.sin(psi) + root)
    field = np.abs(1.0 + refl * (r1 / r2) * np.exp(-2j * np.pi * (r2 - r1) / lam))
    return 20.0 * np.log10(4.0 * np.pi * r1 / lam) - 20.0 * np.log10(field)


# antenna height [m] -> (minimum, maximum) of the model's loss minus the Fresnel loss [dB] as the docstring of two_ray_curved_db gives it, each widened by
# 0.2 dB (measured: -3.3 / +0.2, -2.9 / +2.2, +1.2 / +6.0, +11.4 / +16.0; the other antenna 15 m, Hs 0, d = 300 m to 12 km, 400 points, 915 MHz)
LOW_ANTENNA_BAND = {2.2: (-3.5, 0.4), 0.5: (-3.1, 2.4), 0.3: (1.0, 6.2), 0.1: (11.2, 16.2)}


@pytest.mark.parametrize("h", sorted(LOW_ANTENNA_BAND))
def test_m5_the_loss_of_a_low_antenna_is_overstated_by_the_documented_band(h):
    d = np.linspace(300.0, 12e3, 400)
    diff = c.two_ray_loss_db(d, h, 15.0, 0.0, F915) - fresnel_loss_db(d, h, 15.0)
    lo, hi = LOW_ANTENNA_BAND[h]
    assert lo <= diff.min() and diff.max() <= hi, (h, diff.min(), np.median(diff), diff.max())
    if h <= 0.3:
        assert diff.min() > 0.0                                    # with a 15 m partner the loss is overstated at every distance (not so for 0.5 m and 2.2 m)


def test_m5_the_docstring_of_the_two_ray_model_states_the_low_antenna_band_and_the_floor():
    doc = " ".join(c.two_ray_curved_db.__doc__.split())
    for text in ("LOW ANTENNAS", "0.3 m with 15 m +1.2 / +5.1 / +6.0", "0.1 m with 15 m +11.4 / +15.1 / +16.0",
                 "about 1 to 6 dB for the Slocum with a partner of 2.2 m or 15 m", "11 to 16 dB at 0.1 m", "physics.ANTENNA_MIN_M"):
        # round 18, M-3: 11 (the minimum is +11.4), not 12; the round 18 addendum (DECISIONS 991): by pair, the Slocum with a 2.2 m or a 15 m partner
        assert text in doc, text


# ---------------------------------------------------------------- M-20: the P.526 constants, against the recommendation's formulas written here
def ref_f(x):
    """ITU-R P.526 distance function: 11 + 10 log X - 17.6 X for X >= 1.6, -20 log X - 5.6488 X^1.425 below."""
    return 11.0 + 10.0 * math.log10(x) - 17.6 * x if x >= 1.6 else -20.0 * math.log10(x) - 5.6488 * x ** 1.425


def ref_g(y, beta, k):
    """Height-gain function for B = beta Y: 17.6 sqrt(B - 1.1) - 5 log(B - 1.1) - 8 for B > 2, else 20 log(B + 0.1 B^3), never below 2 + 20 log K."""
    b = beta * y
    g = 17.6 * math.sqrt(b - 1.1) - 5.0 * math.log10(b - 1.1) - 8.0 if b > 2.0 else 20.0 * math.log10(b + 0.1 * b ** 3)
    return max(g, 2.0 + 20.0 * math.log10(k))


def ref_beyond(a_km, d_km, f_mhz, ht, hr, eps, sigma):
    """-(F(X) + G(Y_t) + G(Y_r)): K_V = 0.36 (a f)^(-1/3) [(eps - 1)^2 + s^2]^(-1/4) sqrt(eps^2 + s^2), s = 60 sigma lambda; beta; X = 2.188 beta f^(1/3)
    a^(-2/3) d; Y = 9.575e-3 beta f^(2/3) a^(-1/3) h (f in MHz, a and d in km, h in m)."""
    s = 60.0 * sigma * c.C0 / (f_mhz * 1e6)
    k = 0.36 * (a_km * f_mhz) ** (-1 / 3) * ((eps - 1.0) ** 2 + s * s) ** -0.25 * math.sqrt(eps * eps + s * s)
    beta = (1.0 + 1.6 * k ** 2 + 0.67 * k ** 4) / (1.0 + 4.5 * k ** 2 + 1.53 * k ** 4)
    x = 2.188 * beta * f_mhz ** (1 / 3) * a_km ** (-2 / 3) * d_km
    yc = 9.575e-3 * beta * f_mhz ** (2 / 3) * a_km ** (-1 / 3)
    return -(ref_f(x) + ref_g(yc * ht, beta, k) + ref_g(yc * hr, beta, k))


@pytest.mark.parametrize("x", [0.05, 0.5, 1.0, 1.5, 1.599, 1.6, 1.7, 3.0, 8.0])
def test_m20_the_distance_function_is_the_recommendations_in_both_branches(x):
    """`** 1.425` read `** 1.4` and survived: it moves F by 0.1 dB at X = 1.5 and 0.13 dB at 1.6."""
    assert float(c._p526_f(x)) == pytest.approx(ref_f(x), abs=1e-9)


def test_m20_the_two_branches_of_the_distance_function_meet_at_1_6():
    """The recommendation's own continuity (independent of the code): both formulas give -15.12 dB at X = 1.6."""
    assert abs((11.0 + 10.0 * math.log10(1.6) - 17.6 * 1.6) - (-20.0 * math.log10(1.6) - 5.6488 * 1.6 ** 1.425)) < 0.01
    assert float(c._p526_f(1.6)) == pytest.approx(float(c._p526_f(1.6 - 1e-9)), abs=1e-4)             # the two fits meet to 7e-6 dB


@pytest.mark.parametrize("y", [1e-4, 0.5, 1.9, 2.0, 2.0000001, 2.1, 2.9, 3.5, 10.0])
def test_m20_the_height_gain_switches_branch_above_b_of_2_and_floors_at_2_plus_20_log_k(y):
    """`b > 2.0` read `b > 3.0` and survived (the branches differ by 0.2 dB at B = 2.9), and so did a floor of -60 (the floor is -32.0 dB for K 0.02)."""
    k = 0.02
    got = float(c._p526_g(y, 1.0, k))
    assert got == pytest.approx(ref_g(y, 1.0, k), abs=1e-9)
    if y == 1e-4:
        assert got == pytest.approx(2.0 + 20.0 * math.log10(k), abs=1e-12) and got > 20.0 * math.log10(y)             # the floor binds


def test_m20_the_sea_constants_are_the_assumed_sea_of_the_note():
    assert (c.SEA_EPS_R, c.SEA_SIGMA_SM) == (72.8, 6.05)


A_KM = c.A_EFF / 1e3
# (frequency [MHz], ht, hr, distance [km]): the demo's UAS and USV at 915 MHz beyond the horizon; 0.1 m antennas, where the height gain is on its floor
# (G is -47 dB without it, the floor -32 dB); 3 MHz, where the sea is a good conductor and K is 2.3, so beta is 0.44 and K matters at the dB level
CASES = [(915.0, 18.1, 2.2, 60.0), (915.0, 108.1, 2.2, 100.0), (915.0, 0.1, 0.1, 15.0), (915.0, 0.1, 10.0, 30.0), (3.0, 20.0, 20.0, 80.0),
         (3.0, 2.0, 2.0, 40.0)]


@pytest.mark.parametrize("f_mhz,ht,hr,d_km", CASES)
def test_m20_the_diffraction_field_beyond_the_horizon_is_the_recommendations_over_the_sea(f_mhz, ht, hr, d_km):
    """K (`k = 0.36 *` read `0.30 *` and `0.5 *` and survived), beta, X, Y and the sea's eps and sigma, through the whole chain at two frequencies."""
    got = float(c._diffraction_beyond_db(A_KM, d_km, f_mhz, ht, hr))
    assert got == pytest.approx(ref_beyond(A_KM, d_km, f_mhz, ht, hr, 72.8, 6.05), abs=1e-9)


def test_m20_the_floor_of_the_height_gain_binds_in_the_cases_that_say_so():
    f_mhz = 915.0
    s = 60.0 * 6.05 * c.C0 / (f_mhz * 1e6)
    k = 0.36 * (A_KM * f_mhz) ** (-1 / 3) * ((72.8 - 1.0) ** 2 + s * s) ** -0.25 * math.sqrt(72.8 ** 2 + s * s)
    beta = (1.0 + 1.6 * k ** 2 + 0.67 * k ** 4) / (1.0 + 4.5 * k ** 2 + 1.53 * k ** 4)
    y = 9.575e-3 * beta * f_mhz ** (2 / 3) * A_KM ** (-1 / 3) * 0.1
    assert 20.0 * math.log10(beta * y + 0.1 * (beta * y) ** 3) < 2.0 + 20.0 * math.log10(k) - 5.0              # the case is on the floor, not near it


def test_m20_fresh_water_at_5_ghz_goes_through_the_same_chain(monkeypatch):
    """A second medium (eps 80, sigma 0.01 S/m: the constants are module values, read at call time) at a second frequency."""
    monkeypatch.setattr(c, "SEA_EPS_R", 80.0)
    monkeypatch.setattr(c, "SEA_SIGMA_SM", 0.01)
    for ht, hr, d_km in ((18.1, 2.2, 40.0), (0.1, 5.0, 20.0)):
        assert float(c._diffraction_beyond_db(A_KM, d_km, 5000.0, ht, hr)) == pytest.approx(ref_beyond(A_KM, d_km, 5000.0, ht, hr, 80.0, 0.01), abs=1e-9)


def test_m20_the_diffraction_loss_beyond_the_horizon_is_never_negative_even_where_the_formula_is():
    """At 3 MHz over the sea, 20 m antennas: -(F + G + G) is -37 dB beyond the horizon (a gain over free space, which a diffraction field cannot be);
    `np.maximum(beyond, 0.0)` held it at 0 and was removed by a mutant that nothing caught."""
    d = 1.01 * math.sqrt(2.0 * c.A_EFF) * 2.0 * math.sqrt(20.0)
    assert float(c._diffraction_beyond_db(A_KM, d / 1e3, 3.0, 20.0, 20.0)) < -30.0                        # the formula's own value, the premise of the test
    assert float(c.smooth_earth_diffraction_db(d, 20.0, 20.0, 3e6)) == 0.0
    d915 = 1.01 * math.sqrt(2.0 * c.A_EFF) * (math.sqrt(18.1) + math.sqrt(2.2))
    want = ref_beyond(A_KM, d915 / 1e3, 915.0, 18.1, 2.2, 72.8, 6.05)
    assert float(c.smooth_earth_diffraction_db(d915, 18.1, 2.2, F915)) == pytest.approx(want, abs=1e-9)
