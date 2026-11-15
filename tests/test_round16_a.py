"""Round 16, batch A: the findings whose tests are not in a module's own file (link physics, USV and UAS edge inputs, the tests-only M-22)."""
import numpy as np
import pytest
import yaml
from scipy.special import ai_zeros, airy

from cafe.pm import config
from cafe.pm.physics import comms as c
from tests.test_cli import whatif_args, wi  # noqa: F401  (wi is a fixture)

F915 = 915e6
LAM = c.C0 / F915
E23 = np.exp(2j * np.pi / 3)


# ---------------------------------------------------------------- M-14: smooth-earth diffraction, against an independent solution
def _w1(t):
    """Fock's Airy function w1(t) = 2 sqrt(pi) exp(i pi/6) Ai(t exp(2 pi i/3)) and its derivative (Budden 1961, ch. 9; Fock 1965)."""
    a, ap, _, _ = airy(t * E23)
    k = 2 * np.sqrt(np.pi) * np.exp(1j * np.pi / 6)
    return k * a, k * E23 * ap


def _fock_loss_db(d_m, ht, hr, f_hz, eps_r=72.8, sigma=6.05, a=c.A_EFF, terms=8, q=None):
    """The loss [dB] below free space of the EXACT field over a smooth sphere of radius `a` with the impedance of sea water, vertical polarisation: the
    residue series W = 2 sqrt(pi x) sum_s exp(i x t_s) f(y1, t_s) f(y2, t_s) / (t_s - q^2), f(y, t) = w1(t - y) / w1(t), with t_s the roots of
    w1'(t) = q w1(t) (found by Newton's method, continued from the Dirichlet roots, the zeros of Ai, as q goes to infinity), x = (k a / 2)^(1/3) d / a,
    y = h (2 k^2 / a)^(1/3) and q = -i (k a / 2)^(1/3) sqrt(eps_c - 1) / eps_c (Fock 1965; Bremmer 1949; van der Pol & Bremmer 1937). Nothing of ITU-R P.526's
    F and G is used: this is the theory they were fitted to."""
    lam = c.C0 / f_hz
    k = 2 * np.pi / lam
    x = (k * a / 2) ** (1 / 3) * d_m / a
    h0 = (a / (2 * k * k)) ** (1 / 3)
    ec = eps_r - 1j * 60 * sigma * lam
    q = -1j * (k * a / 2) ** (1 / 3) * np.sqrt(ec - 1) / ec if q is None else q          # `q` given: the surface impedance of the caller's choice
    t = np.abs(ai_zeros(terms)[0]) * np.exp(1j * np.pi / 3)
    for s in np.linspace(0, 1 / q, 40)[1:]:
        for _ in range(30):
            w, wp = _w1(t)
            t = t - (s * wp - w) / (s * t * w - wp)
    f = lambda y: _w1(t - y)[0] / _w1(t)[0]
    total = np.sum(np.exp(1j * x * t) * f(ht / h0) * f(hr / h0) / (t - q * q))
    return -20 * np.log10(abs(2 * np.sqrt(np.pi * x) * total))


# the demo's UAS at the top of its profile, mid and low, a ship-to-ship pair, a mixed one
PAIRS = [(108.1, 2.2), (18.1, 2.2), (8.1, 2.2), (10.0, 10.0), (50.0, 5.0)]


@pytest.mark.parametrize("ht,hr", PAIRS)
def test_the_diffraction_loss_matches_the_exact_residue_series_from_half_the_horizon_to_three_times_it(ht, hr):
    """Round 16, M-14. The independent reference: the exact residue-series field (`_fock_loss_db`), not the recommendation's curve fits. The implemented
    ITU-R P.526 spherical-earth field (beyond the horizon) and P.452's line-of-sight interpolation (inside it) are within 2.8 dB of it at every
    distance from 0.5 to 3 times the radio horizon for these pairs, on the optimistic side (below the exact loss) except for the interpolation at half the
    horizon, where it is 0.3 dB above."""
    horizon = 4.12 * (ht ** 0.5 + hr ** 0.5) * 1e3
    for ratio in (0.5, 0.7, 0.8, 0.9, 1.0, 1.2, 1.5, 2.0, 3.0):
        got, exact = float(c.smooth_earth_diffraction_db(ratio * horizon, ht, hr, F915)), _fock_loss_db(ratio * horizon, ht, hr, F915)
        assert exact - 2.8 <= got <= exact + 0.3, (ht, hr, ratio, got, exact)


def test_the_residue_series_reference_has_the_distance_slope_the_p526_curve_was_fitted_to():
    """What backs the reference, apart from being exact theory: it uses none of P.526's F, G, K or beta, yet in the Dirichlet limit (q very large) its loss
    falls from X = 3 to X = 4 by the amount the recommendation's own F(X) = 11 + 10 log X - 17.6 X says (16.35 dB; X = (pi f a / c)^(1/3) d / a is Fock's x),
    to the 0.15 dB the 17.6 (the rounded 8.686 x 2.3381 x sin 60 deg = 17.59) and the second root allow. The sea's own surface impedance changes the rate
    (about 16.5 dB), which is why beta and K are in the recommendation; the implementation falls at the reference's rate."""
    per_x = (np.pi * F915 * c.A_EFF / c.C0) ** (1 / 3) / c.A_EFF                                    # x per metre
    far = lambda x, **kw: _fock_loss_db(x / per_x, 18.1, 2.2, F915, **kw)
    F = lambda x: 11.0 + 10.0 * np.log10(x) - 17.6 * x
    assert far(4.0, q=1e9) - far(3.0, q=1e9) == pytest.approx(F(3.0) - F(4.0), abs=0.15)
    sea = far(4.0) - far(3.0)
    ours = float(c.smooth_earth_diffraction_db(4.0 / per_x, 18.1, 2.2, F915) - c.smooth_earth_diffraction_db(3.0 / per_x, 18.1, 2.2, F915))
    assert ours == pytest.approx(sea, abs=1.2)


def test_the_diffraction_loss_pins_the_formula_at_the_horizon_of_the_demos_pairs():
    """The values of the implementation (F(X), G(Y), K, beta with the constants 2.188 and 9.575e-3) at the horizon, dB below free space: a change of any
    constant or branch moves one of them. The residue series gives 28.6, 31.4 and 34.0 dB there for sea constants 80 / 5 (2.3, 0.8 and 0.9 dB above)."""
    got = [float(c.smooth_earth_diffraction_db(4.12 * (ht ** 0.5 + 2.2 ** 0.5) * 1e3, ht, 2.2, F915)) for ht in (108.1, 18.1, 8.1)]
    assert got == pytest.approx([26.3, 30.6, 33.2], abs=0.1)
    # beyond the 1.6 break of F(X): 11 + 10 log X - 17.6 X
    far = float(c.smooth_earth_diffraction_db(3 * 4.12 * (108.1 ** 0.5 + 2.2 ** 0.5) * 1e3, 108.1, 2.2, F915))
    assert far == pytest.approx(109.3, abs=0.1)
    # a path with the clearance that costs nothing
    assert float(c.smooth_earth_diffraction_db(4e3, 108.1, 2.2, F915)) == 0.0


def test_the_rf_margin_at_the_horizon_is_no_more_than_the_diffraction_margin():
    """Round 16, M-14: at 0.999 of the radio horizon the loss was 140.1, 142.9 and 145.0 dB for the three UAS heights over the 2.2 m whip, 7 to 12 dB
    under the P.526 value. Now it is 151.7, 149.8 and 149.9 dB: at least the free-space loss plus the exact diffraction loss, less the 2.8 dB the formula
    is within, and more than 4.5 dB above what it was."""
    for ht, loss_before in ((108.1, 140.1), (18.1, 142.9), (8.1, 145.0)):
        d = 0.999 * 4.12 * (ht ** 0.5 + 2.2 ** 0.5) * 1e3
        got = float(c.two_ray_loss_db(d, ht, 2.2, 0.0, F915))
        fs = 20 * np.log10(4 * np.pi * np.hypot(d, ht - 2.2) / LAM)
        assert got >= fs + _fock_loss_db(d, ht, 2.2, F915) - 2.8 and got > loss_before + 4.5, (ht, got)


def test_the_diffraction_loss_is_not_applied_above_the_critical_grazing_angle_or_beyond_the_horizon():
    assert float(c.two_ray_loss_db(2e3, 108.1, 2.2, 0.0, F915)) == float(c.two_ray_curved_db(2e3, 108.1, 2.2, 0.0, F915))
    beyond = 60e3
    assert float(c.two_ray_loss_db(beyond, 18.1, 2.2, 0.0, F915)) == float(c.two_ray_curved_db(beyond, 18.1, 2.2, 0.0, F915))


# ---------------------------------------------------------------- M-27: the boundary of the RF and Iridium physics
@pytest.mark.parametrize("args", [(-3.0, 18.0, 10.0, 0.5), (np.array([5.0, -1.0]), 18.0, 10.0, 0.5)])
def test_rf_margin_refuses_a_negative_range(args):
    with pytest.raises(ValueError, match=r"rf_margin: d must be >= 0"):
        c.rf_margin(*args)


def test_rf_margin_of_a_nan_range_or_height_is_nan_not_a_number_and_a_short_range_is_one_metre():
    nan = np.nan
    assert np.isnan(c.rf_margin(nan, 18.0, 10.0, 0.5)) and np.isnan(c.rf_margin(1e3, nan, 10.0, 0.5)) and np.isnan(c.rf_margin(1e3, 18.0, nan, 0.5))
    m = c.rf_margin(np.array([nan, 1e3, 1e9, 0.0, 0.2]), 18.0, 10.0, 0.5)
    assert np.isnan(m[0]) and np.isfinite(m[1]) and m[2] == c.NO_LINK_DB and m[3] == m[4] == c.rf_margin(1.0, 18.0, 10.0, 0.5)
    assert c.rf_margin(0.0, 18.0, 10.0, 0.5) != c.NO_LINK_DB                      # a zero range is a link at 1 m


def test_rf_margin_of_antennas_at_or_below_the_surface_is_no_link_not_a_budget():
    """It was +119 dB at zero range and zero heights (the horizon test read the raw range, 0 <= 0), +102 dB for a range of -3 m."""
    assert c.rf_margin(0.0, 0.0, 0.0, 0.0) == c.NO_LINK_DB and c.rf_margin(0.5, 0.0, 0.0, 0.0) == c.NO_LINK_DB
    # one antenna on the surface: the other's horizon
    assert c.rf_margin(100.0, -1.0, -2.0, 0.5) == c.NO_LINK_DB and c.rf_margin(100.0, 0.0, 10.0, 0.5) != c.NO_LINK_DB


@pytest.mark.parametrize("n_bytes,members", [(-5, 3), (np.nan, 3), (np.inf, 3), (np.array([10.0, -1.0]), 2), (100, 0), (100, -2)])
def test_iridium_session_refuses_a_negative_or_unknown_byte_count_and_no_members(n_bytes, members):
    with pytest.raises(ValueError, match="iridium_session"):
        c.iridium_session(n_bytes, np.random.default_rng(0), members)


# ---------------------------------------------------------------- M-6: the default RF sensitivity is the best case and says its air rate is assumed
def test_the_default_rf_sensitivity_stays_the_datasheets_best_case_and_is_marked_assumed():
    from cafe.pm import credibility
    raw = yaml.safe_load((c.PLATFORMS / "radios.yaml").read_text())["radios"]
    leaf = raw["rfd900x"]["rx_sens_dbm"]
    assert leaf["assumed"] is True and leaf["value"] == -121.0 and leaf["unit"] == "dBm" and "air data rate" in leaf["why"] and "Replace with" in leaf["why"]
    # the models read the bare value, as for every wrapped number
    assert c._yaml("radios.yaml")["radios"]["rfd900x"]["rx_sens_dbm"] == -121.0
    assert raw["rfd900x_fast"]["rx_sens_dbm"] == -105.0                                                # the other radios are as they were
    item = next(i for i in credibility.assumed_inputs() if i["id"] == "radios.yaml:radios.rfd900x.rx_sens_dbm")
    assert item["kind"] == "assumed" and item["file"] == "platforms/radios.yaml"


# ---------------------------------------------------------------- M-11: a link position interpolated across 180 degrees
def _across_180(lon):
    from cafe.pm import stage1
    out = {"v": dict(t=np.array([0.0, 600.0, 1200.0]), lon=np.array(lon, float)[:, None], lat=np.zeros((3, 1)), depth=np.zeros((3, 1)), antenna_m=0.5)}
    mission = dict(ship=dict(id="ship", lon=-179.95, lat=0.0, antenna_height_m=10.0))
    t = np.array([0.0, 300.0, 600.0, 900.0, 1200.0])
    A, B = stage1._pos("v", out, mission, t), stage1._pos("ship", out, mission, t)
    return A, stage1._dist(A, B)[:, 0]


def test_a_link_position_between_records_either_side_of_180_degrees_is_between_them_not_at_zero():
    """Round 16, M-11: np.interp on the raw longitude gave 0.0 deg at the middle of 179.99 and -179.99 and a range to a ship at -179.95 of 20,009 km."""
    A, d = _across_180([179.99, -179.99, -179.97])
    # 0.06, 0.05, 0.04, 0.03 and 0.02 deg from the ship: the middle of the first two records is 5.56 km away
    assert d == pytest.approx([6672.0, 5560.0, 4448.0, 3336.0, 2224.0], abs=10.0)
    assert np.all((A[0] >= -180.0) & (A[0] < 180.0)) and np.all(np.abs(A[0]) > 179.9)


def test_a_link_position_without_a_crossing_is_what_it_was_and_a_missing_record_stays_missing():
    A, d = _across_180([10.0, 10.01, 10.02])
    assert A[0][:, 0] == pytest.approx([10.0, 10.005, 10.01, 10.015, 10.02], abs=1e-12)
    B, _ = _across_180([10.0, np.nan, 10.02])
    assert np.isnan(B[0][1:4, 0]).all() and B[0][0, 0] == 10.0


# ---------------------------------------------------------------- M-25: a speed factor or scale that is not a number is refused
def _usv(bias=-0.24, **pt):
    from cafe.pm.env.protocol import AnalyticEnv
    from cafe.pm.physics import usv
    return usv.USVSim(usv.load_platform(), 3, AnalyticEnv(wind=(-6.0, 0.0), swdown=0.0), (-165.0, -1.0), 0.0, dict(mode="station", station=(-165.0, 0.5)),
                      perturb=dict(vpp_bias=np.array([0.0, bias, 0.0]), **pt))


@pytest.mark.parametrize("bias", [np.nan, np.inf, -np.inf])
def test_a_usv_speed_factor_that_is_not_finite_is_refused_not_flown_to_a_nan_position(bias):
    with pytest.raises(ValueError, match="finite number above 0"):
        _usv(bias)


# ---------------------------------------------------------------- M-10: the USV's insolation is sampled, and its lowest state of charge is kept
def test_a_usv_with_less_sun_reaches_a_lower_state_of_charge_and_the_scale_must_be_a_positive_number():
    from cafe.pm.env.protocol import AnalyticEnv
    from cafe.pm.physics import usv
    P = usv.load_platform()
    even = P["hotel_w"] / (P["solar_eff"] * P["solar_area_m2"])                          # the insolation that exactly pays the hotel load
    mk = lambda sw, **pt: usv.USVSim(P, 3, AnalyticEnv(wind=(-6.0, 0.0), swdown=sw), (-165.0, -1.0), 0.0, dict(mode="station", station=(-165.0, 0.5)),
                                     perturb=dict(vpp_bias=np.full(3, -0.24), **pt))
    s = mk(even, solar_scale=np.array([0.5, 1.0, 1.5]))
    h = s.run(12 * 3600.0, 600.0)
    low = P["soc0"] - (P["hotel_w"] * 0.5) * 12 / P["battery_wh"]                            # half the sun: half the hotel load is unpaid for 12 h
    assert h["soc_min"][0] == pytest.approx(low, rel=1e-6) and h["soc_min"][1] == pytest.approx(P["soc0"]) and h["soc_min"][2] == pytest.approx(P["soc0"])
    n = mk(0.0)
    h = n.run(72 * 3600.0, 600.0)                                                            # no sun: the hotel load alone empties the pack (50 h from soc0)
    assert h["soc_min"].tolist() == [0.0] * 3 and n.fail["battery"].all() and h["soc_min"].shape == (3,)
    d = mk(even)
    assert d.run(3600.0, 600.0)["soc_min"].tolist() == pytest.approx([P["soc0"]] * 3)        # the default scale is 1
    for bad in (0.0, -1.0, np.nan, np.inf):
        with pytest.raises(ValueError, match="solar_scale must be finite and above 0"):
            mk(0.0, solar_scale=np.array([1.0, bad, 1.0]))


def test_the_solar_yield_prior_is_the_hourly_shortwave_error_of_the_assumptions_and_is_assumed():
    from cafe.pm.stats import sampling
    pri = sampling.load_perturbations()
    a = yaml.safe_load((config.ROOT / "config" / "assumptions.yaml").read_text())["env.sigma.swdown_frac"]
    e = pri["solar_yield_scale"]
    assert e["dist"] == "lognormal" and e["median"] == 1.0 and e["value"] == a["value"] == 0.20 and e["kind"] == "assumed" and "ASSUMED" in e["citation"]


# ---------------------------------------------------------------- M-29: the turbulence series must cover the longest flight, not the nominal one
def test_a_turbulence_series_shorter_than_the_longest_flight_is_refused_and_one_that_covers_it_is_not():
    from cafe.pm.env.protocol import AnalyticEnv
    from cafe.pm.physics import uas
    P = uas.load_platform()
    so = P["sortie"]
    assert uas.sortie_t_max(so) == so["duration_s"] * so["hard_stop_factor"] and so["hard_stop_factor"] > 1.0
    long_enough = int(np.ceil((uas.sortie_t_max(so) + 60.0) / uas.DT_ENV))
    nominal_only = int(np.ceil((so["duration_s"] + 60.0) / uas.DT_ENV))
    assert nominal_only < long_enough
    env, ship = AnalyticEnv(wind=(-6.0, 0.0)), (lambda t: np.zeros(2))
    # the old guard let this through: the hold at the last row from 1,260 s on
    with pytest.raises(ValueError, match="turbulence series covers"):
        uas.fly_sortie(env, ship, 0.0, M=2, turb=np.zeros((2, nominal_only, 3)))
    with pytest.raises(ValueError, match="turbulence series covers"):
        uas.fly_sortie(env, ship, 0.0, M=2, turb=np.zeros((2, long_enough - 1, 3)))
    uas._turbulence_covers(np.zeros((2, long_enough, 3)), uas.sortie_t_max(so))            # covers it: no error
    uas._turbulence_covers(None, uas.sortie_t_max(so))


# ---------------------------------------------------------------- M-28: the USV table cache is written whole, and a cut one is rebuilt
def test_a_cut_or_foreign_usv_table_cache_is_rebuilt_and_written_whole(tmp_path, monkeypatch):
    from cafe.pm.physics import usv
    P = usv.load_platform()
    built = []
    monkeypatch.setattr(usv, "_CACHE", {})
    monkeypatch.setattr(usv, "_build_polar", lambda P: built.append(1) or usv.Polar(np.arange(2.0), np.arange(3.0), np.ones((2, 3))))
    monkeypatch.setattr(usv, "_build_waves", lambda P: usv.WaveTab(np.arange(2.0), np.arange(3.0), np.arange(4.0), np.ones((2, 3, 4))))
    f = tmp_path / f"usv_tables_{usv._digest(P)}.npz"
    f.write_bytes(b"PK\x03\x04truncated")                                        # a file cut by a kill: BadZipFile at every later read, and nothing recovered
    polar, waves = usv.tables(P, tmp_path)
    assert len(built) == 1 and polar.f.shape == (2, 3) and waves.g.shape == (2, 3, 4) and list(tmp_path.iterdir()) == [f]      # rebuilt, no temporary left
    usv._CACHE.clear()
    # the file now read back is whole
    assert usv.tables(P, tmp_path)[1].g.shape == (2, 3, 4) and len(built) == 1
    usv._CACHE.clear()
    # a file of another kind: a key missing
    np.savez(f, other=np.zeros(1))
    usv.tables(P, tmp_path)
    assert len(built) == 2 and np.load(f)["pf"].shape == (2, 3)


# ---------------------------------------------------------------- M-22: six edits of round 15's fixes survived the tests that name them
class _NanSeaEnv:
    """Waves of 2 m that are NaN wherever the position is: what a gridded sea mask gives at no position."""
    def waves(self, lon, lat, t):
        from cafe.pm import Tagged
        return dict(Hs=Tagged(np.where(np.isfinite(lat) & np.isfinite(lon), 2.0, np.nan), "test", 0.0, "assumed"))


def test_m22_a_link_reads_no_sea_at_an_unknown_position_instead_of_the_nearest_one():
    """stage1._link_hs (row 834): an unknown position reads 0 and is no moment the link was required; without the `isfinite` guard the NaN sea there was
    FILLED from the member's neighbouring samples (counted in hs_filled) or, with no neighbour, OutsideData."""
    from cafe.pm import stage1
    n, M = 4, 2
    lon, lat = np.full((n, M), -165.0), np.zeros((n, M))
    lat[1, 1] = np.nan
    A = (lon, lat, np.full((n, M), 10.0), np.zeros((n, M)))
    tt = np.broadcast_to(np.arange(n, dtype=float)[:, None], (n, M))
    hs, filled = stage1._link_hs(_NanSeaEnv(), A, A, tt, "link x")
    assert filled == 0 and hs[0][1, 1] == 0.0 and (hs[0][np.isfinite(lat)] == 2.0).all()
    lat[:, 1] = np.nan                                                                    # a member with no position at all: still no OutsideData
    assert stage1._link_hs(_NanSeaEnv(), A, A, tt, "link x")[1] == 0


def test_m22_a_manifest_box_has_exactly_four_numbers():
    """orca.real_numbers (row 836): `len(v) == n` replaced by True accepted a box of three or five numbers, and so did every manifest shape that calls it."""
    from cafe.pm.env import orca, tao
    assert orca.real_numbers([1.0, 2.0, 3.0, 4.0], 4) and orca.real_numbers([1.0, 2.0, 3.0]) and not orca.real_numbers([], 1)
    assert not orca.real_numbers([1.0, 2.0, 3.0], 4) and not orca.real_numbers([1.0, 2.0, 3.0, 4.0, 5.0], 4) and not orca.real_numbers((1.0, 2.0, 3.0, 4.0), 4)
    good = dict(base="b", t0="2023-03-01", t1="2023-03-02", hours=24.0, box=[-170.0, -160.0, -5.0, 5.0])
    assert orca.manifest_shape(good)
    assert not orca.manifest_shape(dict(good, box=good["box"][:3])) and not orca.manifest_shape(dict(good, box=good["box"] + [0.0]))
    t = dict(t0=1.0, t1=2.0, box=[-170.0, -160.0, -5.0, 5.0], files={}, selected={}, positions={})
    assert tao.manifest_shape(t) and not tao.manifest_shape(dict(t, box=t["box"][:3])) and not tao.manifest_shape(dict(t, box=t["box"] + [0.0]))


BOX = dict(lon_min=-180.0, lon_max=-150.0, lat_min=-5.0, lat_max=5.0)                  # 30 deg wide, 10 high


@pytest.mark.parametrize("mod", [dict(dlon=30.0), dict(dlon=-30.0), dict(dlat=10.0), dict(dlat=-10.0), dict(duty=0.0), dict(duty=-0.5)])
def test_m22_a_move_as_wide_as_the_box_and_a_duty_of_zero_or_below_are_refused(mod):
    """whatif._numbers (rows 860, 861): `>=` as `>` let a move of exactly the box's width or height through (it lands where it began); `0.0 < duty` as
    `<=` let a duty of 0 through to a division by zero."""
    from cafe.pm import whatif
    with pytest.raises(whatif.Invalid):
        whatif._numbers("v", mod, BOX)
    assert whatif._numbers("v", dict(dlon=29.999, dlat=9.999, duty=1e-9), BOX) == (0.0, 29.999, 9.999, 1e-9)


class _QuadraticEnv:
    """A current of 0.05 + 2e-5 z^2 m/s north at every point: a mean over the dive band depends on how many depths are sampled."""
    def at(self, lat, lon, t, z):
        z = np.asarray(z, float)
        cur = np.stack([0.05 + 2e-5 * z * z, np.zeros(len(lat))], -1)
        return dict(current_ne=cur, wind_ne=cur, land=np.zeros(len(lat), bool))


def test_m22_the_glider_band_is_six_depths_whatever_the_profile():
    """cafe/reach.py: `np.linspace(top, bottom, 6)`: the existing profile is linear in depth, so 5 or 6 depths give one mean; a quadratic one does not."""
    from types import SimpleNamespace as NS
    from cafe import reach
    g = NS(kind="uuv", battery_wh=1e9, hotel_w=1.0, actuators=[NS(kind="buoy")], limits=dict(glide_speed_sim=0.3, glide_band=(10.0, 60.0)))
    want = float(np.mean(0.05 + 2e-5 * np.linspace(10.0, 60.0, 6) ** 2))
    assert want != pytest.approx(float(np.mean(0.05 + 2e-5 * np.linspace(10.0, 60.0, 5) ** 2)), rel=1e-6)
    assert reach.reach(g, _QuadraticEnv(), 5.0, -150.0, hours=3, n=11)["flow_max"] == pytest.approx(want, rel=1e-12)


def test_m22_a_sub_daily_period_starts_at_the_window_not_at_the_first_daily_slot():
    """stage1.launch_times (row 835): `first = slot` instead of walking back by whole periods: a period of 0.5 d launches at 06:00 and 18:00 on the first
    day, not from 18:00."""
    from cafe.pm import stage1
    t0 = config.utc("2023-03-01T00:00:00Z").timestamp()
    got = stage1.launch_times({"local_solar_time": "18:00", "every_days": 0.5}, 0.0, t0, t0 + 48 * 3600.0, 600.0)
    assert (got - t0).tolist() == [6 * 3600.0, 18 * 3600.0, 30 * 3600.0, 42 * 3600.0]


# ---------------------------------------------------------------- M-2: the what-if line says which wind model its baseline flew in
def test_the_what_if_line_of_a_uas_names_the_wind_model_and_the_reports_own_baseline(wi, capsys, monkeypatch):  # noqa: F811
    from cafe.pm import __main__ as cli, whatif
    uas = dict(base=dict(verdict="NO-GO", p_fail=0.969), method="Stage 1", why="no emulator", p_fail=1.0, lo=0.922, hi=1.0, verdict="NO-GO", n=32,
               wind_model=whatif.WIND_MODEL_2D, base_3d=dict(verdict="NO-GO", p_fail=0.953))
    plain = dict(base=dict(verdict="GO", p_fail=0.0), method="Stage 1", why="no emulator", p_fail=0.0, lo=0.0, hi=0.1, verdict="GO", n=32)
    monkeypatch.setattr(whatif, "answer", lambda *a, **k: dict(vehicles={"uas": uas, "usv": plain}, dropped=[], links_removed=[], unchanged={}))
    assert cli.main(whatif_args(wi, "--shift", "6h")) == 0
    out = capsys.readouterr().out.splitlines()
    i = next(k for k, line in enumerate(out) if line.startswith("uas: NO-GO (P(fail) 0.969) -> NO-GO (P(fail) 1.000)"))
    assert out[i + 1].startswith("  note: uas UAS what-if answers use the 10 m scaled profile")
    assert "The report's own baseline, flown in the 3-D wind, is NO-GO (P(fail) 0.953); " in out[i + 1]
    assert "the baseline shown above is the unchanged mission in the 10 m profile" in out[i + 1]
    assert not any("3-D" in line for line in out if line.startswith(("usv:", "  note: usv")))                  # a vehicle with no wind model gets no such line
    uas["base_3d"] = None                                                                                       # no finished run: the note alone
    cli.main(whatif_args(wi, "--shift", "6h"))
    assert "flown in the 3-D wind" not in capsys.readouterr().out
