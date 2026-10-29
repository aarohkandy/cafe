import copy

import numpy as np
import pytest
from hypothesis import given, strategies as st

from cafe.pm import Tagged
from cafe.pm.env import subgrid as sg

CFG = sg.load_config()
HOUR = np.arange(0, 12 * 3600.0, 3600.0)


@pytest.fixture(scope="module")
def recs():
    return sg.receipts()


def broken(**over):
    c = copy.deepcopy(CFG)
    for path, v in over.items():
        d = c
        *ks, last = path.split(".")
        for k in ks:
            d = d[k]
        d[last] = v
    return c


def collect(fn):
    from cafe import receipts as R
    n0 = len(R.OUT)
    fn()
    return R.OUT[n0:]


def failing(monkeypatch, name, fn, which):
    monkeypatch.setattr(sg, name, fn)
    return [r["claim"] for r in collect(which) if r["ok"] is False]


# ---------------------------------------------------------------- receipts and the ways they must fail

def test_receipts_pass(recs):
    assert len(recs) >= 25
    assert not [r["claim"] for r in recs if r["ok"] is False]


def test_receipt_fails_when_amplitude_is_wrong(monkeypatch):
    orig = sg._unit_box

    def bad(*a):
        st_, sig = orig(*a)
        return st_, sig * 1.5

    assert any("sigma_u" in c for c in failing(monkeypatch, "_unit_box", bad, sg._turbulence_receipts))


def test_receipt_fails_when_sde_drops_the_gradient_term(monkeypatch):
    orig = sg.ocean_sde_step
    drop = lambda x, K, gradK, dt, rng, u=None: orig(x, K, 0 * np.asarray(gradK), dt, rng, u)       # noqa: E731
    assert any("with dK/dx drift" in x for x in failing(monkeypatch, "ocean_sde_step", drop, sg._ocean_receipts))


def test_receipt_fails_when_sde_drift_has_wrong_sign(monkeypatch):
    orig = sg.ocean_sde_step
    flip = lambda x, K, gradK, dt, rng, u=None: orig(x, K, -np.asarray(gradK), dt, rng, u)          # noqa: E731
    assert any("with dK/dx drift" in x for x in failing(monkeypatch, "ocean_sde_step", flip, sg._ocean_receipts))


def test_receipt_fails_when_rain_lens_ignores_wind(monkeypatch):
    cfg = broken(**{"rain_lens.wind_absent_above_ms": 30.0})
    assert any("9 m/s" in c for c in failing(monkeypatch, "load_config", lambda path=None: cfg, sg._lens_receipts))


def test_receipt_fails_when_windage_fraction_is_ten_times_too_big(monkeypatch):
    cfg = broken(**{"ocean.windage.fraction_min": 0.18, "ocean.windage.fraction_max": 0.23})
    assert any("windage" in x for x in failing(monkeypatch, "load_config", lambda path=None: cfg, sg._surface_receipts))


def test_receipt_fails_when_diurnal_jet_is_not_scaled_by_warm_layer_dT(monkeypatch):
    cfg = broken(**{"ocean.diurnal_jet.u_min": 0.5, "ocean.diurnal_jet.u_max": 0.9})
    assert any("diurnal jet" in x for x in failing(monkeypatch, "load_config", lambda path=None: cfg, sg._surface_receipts))


def test_receipt_fails_when_front_temperature_criterion_is_missed(monkeypatch):
    weak = lambda tau, rise, dur: 0.5 * np.where((tau >= 0) & (tau <= dur), 1.0, 0.0)               # noqa: E731
    assert any("Wills" in c for c in failing(monkeypatch, "_shape", weak, sg._gust_receipts))


# ---------------------------------------------------------------- config, calibration provenance

def test_config_cites_everything_and_reports_the_calibration_run():
    for k in ("turbulence", "stability", "gust_front", "ocean", "rain_lens"):
        assert len(CFG[k]["citation"]) > 100
    assert CFG["calibration"]["source_run"] is None and CFG["calibration"]["sigma_u_over_ustar"] == 2.5
    assert "no Stage-3 LES run" in sg.calibration_note(CFG)
    c = broken(**{"calibration.source_run": "run_2023mar_les_07"})
    assert "run_2023mar_les_07" in sg.calibration_note(c)
    assert "run_2023mar_les_07" in sg.turbulence(1, 0.3, -200.0, 10.0, 6.0, 20.0, 1.0, cfg=c).source


def test_assumptions_are_complete():
    import yaml
    a = yaml.safe_load(open(sg._CFG_DIR / "assumptions.yaml"))
    for k, v in a.items():
        assert set(v) == {"value", "unit", "why", "replace_with"}, k
    assert sg.assumption("subgrid.gust_front.lambda_max_per_h") > 0


# ---------------------------------------------------------------- turbulence

def test_mann_length_rules():
    assert np.isclose(sg.mann_length(10.0, np.inf), 0.8 * 0.7 * 10.0)
    assert np.isclose(sg.mann_length(100.0, np.inf), 0.8 * 42.0)               # Lambda1 capped at 42 m
    assert sg.mann_length(10.0, -50.0) > sg.mann_length(10.0, np.inf) > sg.mann_length(10.0, 50.0)
    lo, hi = sg.assumption("subgrid.stability_ratio_clip")
    assert np.isclose(sg.mann_length(10.0, 0.01), lo * 5.6) and np.isclose(sg.mann_length(10.0, -0.01), hi * 5.6)
    assert np.isclose(sg.mann_length(10.0, np.inf, broken(**{"calibration.length_scale_factor": 2.0})), 11.2)


@given(z=st.floats(0.5, 100.0), zeta=st.floats(-5.0, 5.0).filter(lambda x: abs(x) > 1e-3))
def test_mann_length_is_ordered_by_stability(z, zeta):
    L_of = lambda zt: sg.mann_length(z, z / zt if zt else np.inf)                  # noqa: E731
    neutral, L = L_of(0.0), L_of(zeta)
    assert L > 0 and ((L <= neutral * (1 + 1e-12)) if zeta > 0 else (L >= neutral * (1 - 1e-12)))
    assert L_of(zeta - 0.5) >= L * (1 - 1e-12)                                      # more unstable -> longer


def test_turbulence_shape_tag_reproducibility_and_scaling():
    a = sg.turbulence(7, 0.3, -300.0, 10.0, 6.0, 60.0, 0.5)
    b = sg.turbulence(7, 0.3, -300.0, 10.0, 6.0, 60.0, 0.5)
    c = sg.turbulence(8, 0.3, -300.0, 10.0, 6.0, 60.0, 0.5)
    d = sg.turbulence(7, 0.6, -300.0, 10.0, 6.0, 60.0, 0.5)
    assert isinstance(a, Tagged) and a.kind == "modelled" and a.value.shape == (121, 3) and "Mann" in a.source
    assert np.array_equal(a.value, b.value) and not np.allclose(a.value, c.value)
    assert np.allclose(d.value, 2 * a.value)                                     # amplitude is linear in u*
    assert np.all(np.isfinite(a.value))


def test_turbulence_components_and_correlation_sign():
    x = sg.turbulence(3, 0.3, -300.0, 10.0, 6.0, 3000.0, 0.5).value
    assert x[:, 0].std() > x[:, 1].std() > x[:, 2].std() > 0                    # sigma_u > sigma_v > sigma_w
    assert np.corrcoef(x[:, 0], x[:, 2])[0, 1] < 0                              # shear: u'w' < 0 (momentum flux downward)


def test_turbulence_members_pooling_and_limits():
    m = sg.turbulence_members(5, 4, np.array([0.2, 0.3, 0.4, 0.5]), -200.0, 10.0, 6.0, 100.0, 0.5, n_boxes=2)
    assert m.value.shape == (4, 201, 3) and m.uncertainty.shape == (4, 1, 1)
    assert not np.allclose(m.value[0], m.value[2])                               # same box, different segment
    with pytest.raises(ValueError, match="raise n_boxes"):
        sg.turbulence_members(5, 10_000, 0.3, -200.0, 10.0, 6.0, 100.0, 0.5, n_boxes=1)
    with pytest.raises(ValueError, match="shorten"):
        sg.turbulence_members(5, 1, 0.3, -200.0, 10.0, 6.0, 1e6, 0.5)


def test_gust_enu_directions():
    g = np.array([1.0, 0.0, 0.5])                                                # 1 m/s along the wind, 0.5 up
    assert np.allclose(sg.gust_enu(g, 0.0), [0.0, -1.0, 0.5])                    # wind from north blows toward south
    assert np.allclose(sg.gust_enu(g, 270.0), [1.0, 0.0, 0.5])                   # wind from west blows toward east
    cross = sg.gust_enu(np.array([0.0, 1.0, 0.0]), 270.0)                        # cross-wind points left of the flow: north
    assert np.allclose(cross, [0.0, 1.0, 0.0])


@given(u=st.floats(-5, 5), v=st.floats(-5, 5), w=st.floats(-5, 5), d=st.floats(0, 360))
def test_gust_enu_preserves_norm_and_vertical(u, v, w, d):
    out = sg.gust_enu(np.array([u, v, w]), d)
    assert np.isclose(np.linalg.norm(out), np.linalg.norm([u, v, w]), atol=1e-9) and out[2] == w


# ---------------------------------------------------------------- gust fronts

def test_rain_rate_from_accum():
    r = sg.rain_rate_from_accum(np.array([0.0, 1.0, 3.0, 3.0, 0.5]), np.arange(5) * 3600.0)
    assert np.allclose(r, [1.0, 1.0, 2.0, 0.0, 0.0])                           # last: accumulator reset clipped
    assert sg.rain_rate_from_accum(np.array([[0.0, 2.0], [0.0, 0.0]]), np.array([0.0, 1800.0]))[0, 0] == 4.0


def test_theta_e_values_and_monotonicity():
    assert 345 < float(sg.theta_e(300.15, 0.018, 101000.0)) < 360                # warm-pool surface air
    assert sg.theta_e(300.0, 0.020, 101000.0) > sg.theta_e(300.0, 0.015, 101000.0)
    assert sg.theta_e(302.0, 0.018, 101000.0) > sg.theta_e(300.0, 0.018, 101000.0)


def test_gust_rate_depends_on_rain_and_instability():
    assert sg.gust_rate(0.0) == sg.assumption("subgrid.gust_front.lambda_bg_per_h")
    assert sg.gust_rate(5.0) > sg.gust_rate(0.5) > sg.gust_rate(0.0)
    r = sg.gust_rate
    assert r(5.0, 330.0) == r(0.0) < r(5.0, 340.0) < r(5.0, 360.0) == r(5.0)


def test_gust_fronts_reproducible_and_inside_ranges():
    rain = np.full(HOUR.size, 4.0)
    a = sg.gust_fronts(11, rain, HOUR, 50)
    b = sg.gust_fronts(11, rain, HOUR, 50)
    assert all(np.array_equal(x, y) for x, y in zip(a[:5], b[:5], strict=True)) and a.n_members == 50 and a.member.size > 0
    gs = CFG["calibration"]["gust_stats"]
    sp = np.hypot(a.dU[:, 0], a.dU[:, 1])
    assert sp.min() >= gs["dU_min"] and sp.max() <= gs["dU_max"] and np.all(a.dT == gs["dT"]) and np.all(a.dT < 0)
    assert a.duration.min() >= gs["duration_min_s"] and a.duration.max() <= gs["duration_max_s"]
    assert a.start.min() >= HOUR[0] and a.start.max() < HOUR[-1] + 3600.0


def test_gust_fronts_follow_the_mean_wind_direction():
    ev = sg.gust_fronts(12, np.full(HOUR.size, 5.0), HOUR, 200, wind_to_deg=np.full(HOUR.size, 90.0))
    ang = np.degrees(np.arctan2(ev.dU[:, 0], ev.dU[:, 1]))                      # compass direction toward
    off = (ang - 90.0 + 180.0) % 360.0 - 180.0                                  # wrapped offset from the mean wind
    assert abs(np.mean(off)) < 5.0 and 30.0 < np.std(off) < 60.0
    dry = sg.gust_fronts(12, np.zeros(HOUR.size), HOUR, 20, theta_e_K=np.full(HOUR.size, 330.0))
    assert dry.member.size <= 3


def test_gust_perturbation_shape_in_time_and_members():
    ev = sg.Events(np.array([0, 2]), np.array([100.0, 100.0]), np.array([1200.0, 600.0]), np.array([[6.0, 0.0], [0.0, -4.0]]),
                   np.array([-1.5, -1.5]), 3)
    t = np.array([[0.0, 100.0, 550.0, 700.0, 1300.0, 1400.0]])
    dU, dT = sg.gust_perturbation(ev, t)
    assert dU.kind == dT.kind == "modelled" and dU.value.shape == (3, 1, 6, 2) and dT.value.shape == (3, 1, 6)
    assert np.allclose(dU.value[0, 0, 0], 0) and np.allclose(dU.value[0, 0, 1], 0)                  # before / at onset
    assert np.allclose(dU.value[0, 0, 2], [6.0, 0.0])                                               # peak 450 s after onset
    assert 0 < dU.value[0, 0, 3, 0] < 6.0 and np.allclose(dU.value[0, 0, 4:], 0)                    # ends at 1300 s
    assert np.allclose(dT.value[0, 0, 2], -1.5 * 450 / 600) and np.allclose(dT.value[2, 0, 3], -1.5 * (600 - 600) / 1)
    assert np.allclose(dU.value[1], 0) and np.allclose(dT.value[1], 0)                              # member 1 has no events
    assert dU.value[2, 0, 2, 1] < 0                                                                  # southward member 2


def test_gust_perturbation_without_events():
    ev = sg.gust_fronts(1, np.zeros(3), HOUR[:3], 4, theta_e_K=np.full(3, 300.0))
    ev0 = ev._replace(member=ev.member[:0], start=ev.start[:0], duration=ev.duration[:0], dU=ev.dU[:0], dT=ev.dT[:0])
    dU, dT = sg.gust_perturbation(ev0, np.array([1.0, 2.0]))
    assert dU.value.shape == (4, 2, 2) and not dU.value.any() and not dT.value.any()


@given(tau=st.floats(-100, 3000), rise=st.floats(30, 900), dur=st.floats(600, 1800))
def test_triangle_shape_bounds(tau, rise, dur):
    s = float(sg._shape(tau, rise, dur))
    assert 0.0 <= s <= 1.0 + 1e-12
    if tau < 0 or tau > dur:
        assert s == 0.0


# ---------------------------------------------------------------- ocean

def test_sde_step_deterministic_part_and_noise_scale():
    rng = np.random.default_rng(0)
    x = np.zeros((200000, 2))
    out = sg.ocean_sde_step(x, np.full(200000, 2.0), np.tile([0.01, -0.02], (200000, 1)), 10.0, rng, u=np.array([0.1, 0.0]))
    assert np.allclose(out.mean(0), [1.1, -0.2], atol=0.05)                      # (u + gradK) dt
    assert np.allclose(out.std(0), np.sqrt(2 * 2.0 * 10.0), rtol=0.01)           # sqrt(2 K dt)
    out2 = sg.ocean_sde_step(x[:1000], np.tile([1.0, 4.0], (1000, 1)), np.zeros((1000, 2)), 1.0, np.random.default_rng(1))
    assert out2[:, 1].std() > 1.7 * out2[:, 0].std()                             # anisotropic K: y twice as wide
    assert np.array_equal(sg.ocean_sde_step(x[:5], np.zeros(5), np.ones((5, 2)), 2.0, rng), np.full((5, 2), 2.0))


def test_okubo_diffusivity():
    k8 = float(sg.okubo_K(8000.0))
    assert 3.0 < k8 < 15.0 and sg.okubo_K(1e4) > sg.okubo_K(1e3)
    assert np.isclose(float(sg.okubo_K(100.0)), 0.0103 * 1e4**1.15 * 1e-4)


def test_windage_magnitude_per_member_and_tag():
    w = sg.windage(1, np.tile([[3.0, 4.0]], (300, 1))[:, None, :] * np.ones((1, 2, 1)))
    assert isinstance(w, Tagged) and w.kind == "modelled" and w.value.shape == (300, 2, 2)
    frac = np.hypot(w.value[..., 0], w.value[..., 1]) / 5.0
    assert frac.min() >= 0.018 and frac.max() <= 0.023 and np.allclose(frac[:, 0], frac[:, 1])
    assert np.allclose(w.value[..., 0] / w.value[..., 1], 0.75)                  # along the wind


def test_diurnal_jet_scaling_and_direction():
    w10 = np.tile([[0.0, -6.0]], (200, 1))                                       # wind toward the south
    j = sg.diurnal_jet(2, np.full(200, 1.5), w10)
    full = sg.diurnal_jet(2, np.full(200, 6.0), w10)
    assert j.kind == "modelled"
    assert np.allclose(full.value[:, 1], -np.hypot(*full.value.T)) and np.allclose(full.value[:, 0], 0)
    assert np.allclose(j.value, full.value * 0.5)                                # dT 1.5 of dT_ref 3
    assert 0.1 <= np.hypot(*full.value.T).min() and np.hypot(*full.value.T).max() <= 0.3
    assert not sg.diurnal_jet(2, np.full(3, 3.0), np.zeros((3, 2))).value.any()  # no wind, no downwind direction


# ---------------------------------------------------------------- rain lens

def test_rain_lens_wind_rain_time_and_depth_dependence():
    ds = lambda *a, **k: float(sg.rain_lens(*a, **k)["dS"].value)               # noqa: E731
    assert np.isclose(ds(10.0, 2.0, 0.0), 0.5, rtol=1e-3)
    assert ds(10.0, 2.0, 0.0) > ds(10.0, 6.5, 0.0) > ds(10.0, 7.9, 0.0) > 0 and ds(10.0, 8.0, 0.0) == 0 == ds(10.0, 15.0, 0.0)
    assert ds(0.5, 2.0, 0.0) == 0 and 0 < ds(3.0, 2.0, 0.0) < ds(5.0, 2.0, 0.0)
    assert ds(10.0, 2.0, 3600.0) < ds(10.0, 2.0, 0.0) and np.isclose(ds(10.0, 2.0, 7200.0), 0.5 * np.exp(-1), rtol=1e-3)
    assert ds(10.0, 7.0, 3600.0) < ds(10.0, 3.0, 3600.0)                         # stronger wind erodes it faster
    assert ds(10.0, 2.0, 0.0, z=-0.2) > 0.45 and ds(10.0, 2.0, 0.0, z=-2.0) < 0.01 and ds(10.0, 2.0, 0.0, z=1.0) == 0
    r = sg.rain_lens(10.0, 2.0, 0.0)
    assert r["dS"].kind == r["dT"].kind == "modelled" and r["dT"].value < 0 and r["size_km"] == 7.0
    assert sg.rain_lens(np.array([0.0, 10.0]), np.array([2.0, 2.0]), 0.0)["dS"].value.shape == (2,)


def test_rain_lens_switch():
    off = sg.rain_lens(10.0, 2.0, 0.0, cfg=broken(**{"rain_lens.enabled": False}))
    assert float(off["dS"].value) == 0 and float(off["dT"].value) == 0
