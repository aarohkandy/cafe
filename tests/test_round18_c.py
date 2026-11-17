"""Round 18, batch C: the sensitivity ranks the quantity of the dominant failure mode over the columns that move it (M-4), and the tests of round 16's UAS
sortie length (M-16: A-2)."""
import copy
import warnings

import numpy as np
import pytest

from cafe.pm import credibility, stage1
from cafe.pm.env.protocol import AnalyticEnv
from cafe.pm.physics import glider, uas
from cafe.pm.stats import sampling
from tests.test_stage1 import LK, MISSION, merged, uas_inputs

NAMES = list(stage1.priors_for(MISSION)[1])
TESTS_SENTENCE = "one in twenty unrelated outcomes would also clear it"


def _modes(r, **modes):
    """Give the synthetic vehicle result `r` these failure modes (name -> (n,) bool) and no others: its first times are 100 s for every member."""
    r["fail"] = {k: np.asarray(v, bool) for k, v in modes.items()}
    r["first"] = {k: np.where(v, 100.0, np.nan) for k, v in modes.items()}


def _col(res, name):
    return res["U"][:, NAMES.index(name)].copy()


# ---------------------------------------------------------------- M-4: what a vehicle's "most sensitive to" ranks and which columns can act on it
def test_r18_m4_a_usv_that_runs_out_of_charge_ranks_its_charge_and_the_solar_yield_not_the_cross_track_error():
    """Reviewer B's case: every failure is `battery`; the old line ranked the cross-track error and named usv_vpp_bias (S1 0.997), a column that cannot
    change a charge by the failure's own mechanism. Now the lowest state of charge is ranked, over the columns that move it, solar_yield_scale first."""
    res = merged({"usv": 0.0})
    u = res["vehicles"]["usv"]
    u["margin"], u["margin_name"] = _col(res, "usv_vpp_bias"), "maximum cross-track error"                 # the steering prior alone sets the cross-track error
    u["energy_margin"] = 0.2 + 0.6 * _col(res, "solar_yield_scale")                                         # the insolation harvested alone sets the charge
    _modes(u, battery=u["energy_margin"] < 0.35)
    e = stage1.summarize(res, NAMES, MISSION, 73)["vehicles"]["usv"]["sensitivity"]
    assert e["case"] == "ranked" and e["param"] == "solar_yield_scale" and e["quantity"] == "lowest state of charge (fraction of the pack)"
    assert "for the lowest state of charge" in e["text"] and set(e["S1"]) == set(stage1.FORCING) | {"usv_vpp_bias", "solar_yield_scale"}
    _modes(u, swept_off_track=u["margin"] < 0.3)                                                           # the cross-track error is what failed: unchanged
    e = stage1.summarize(res, NAMES, MISSION, 73)["vehicles"]["usv"]["sensitivity"]
    assert e["param"] == "usv_vpp_bias" and e["quantity"] == "maximum cross-track error" and "solar_yield_scale" not in e["S1"]


def test_r18_m4_a_mode_with_no_quantity_of_its_own_ranks_the_failure_indicator_over_every_column_of_the_class():
    res = merged({"usv": 0.0})
    u = res["vehicles"]["usv"]
    u["margin"], u["margin_name"] = _col(res, "usv_vpp_bias"), "maximum cross-track error"
    u["energy_margin"], u["energy_margin_name"] = _col(res, "solar_yield_scale"), "lowest state of charge"
    _modes(u, becalmed=_col(res, "wind_speed_bias") < 0.4)
    e = stage1.summarize(res, NAMES, MISSION, 73)["vehicles"]["usv"]["sensitivity"]
    assert e["quantity"] == "failure indicator" and e["case"] == "ranked" and e["param"] == "wind_speed_bias"
    assert set(e["S1"]) == set(stage1.FORCING) | {"usv_vpp_bias", "solar_yield_scale"}
    assert dict(stage1.RANKED) == {("glider", "station_lost"): "margin", ("glider", "battery"): "battery_margin", ("usv", "swept_off_track"): "margin",
                                   ("usv", "battery"): "energy_margin", ("uas", "battery_reserve"): "margin", ("uas", "profile_incomplete"): "profile_margin"}


def test_r18_m4_a_glider_that_runs_out_of_battery_ranks_its_energy_over_the_two_columns_that_move_it():
    res = merged({"glider_eq": 0.0})
    g = res["vehicles"]["glider_eq"]
    g["margin"], g["margin_name"] = _col(res, "wind_speed_bias"), "maximum distance from the station"       # a station glider's margin is its distance
    g["battery_margin"], g["battery_margin_name"] = _col(res, "battery_capacity_scale"), "battery energy margin"
    _modes(g, battery=g["battery_margin"] < 0.3)
    e = stage1.summarize(res, NAMES, MISSION, 73)["vehicles"]["glider_eq"]["sensitivity"]
    assert e["case"] == "ranked" and e["param"] == "battery_capacity_scale" and e["quantity"] == "battery energy margin"
    assert set(e["S1"]) == {"glider_speed_scale", "battery_capacity_scale"}                                  # not the wind and the current
    _modes(g, station_lost=g["margin"] < 0.3)
    e = stage1.summarize(res, NAMES, MISSION, 73)["vehicles"]["glider_eq"]["sensitivity"]
    assert e["param"] == "wind_speed_bias" and e["quantity"] == "maximum distance from the station" and "battery_capacity_scale" not in e["S1"]


def test_r18_m4_a_result_that_does_not_hold_the_quantity_ranks_the_failure_indicator():
    """A res.pkl made before this round has no `battery_margin` for a glider (its `margin` is the distance on a station task): the fallback is the indicator
    over the class's columns, never the distance under the name of a battery failure."""
    res = merged({"glider_eq": 0.0})
    g = res["vehicles"]["glider_eq"]
    g["margin"], g["margin_name"] = _col(res, "wind_speed_bias"), "maximum distance from the station"
    _modes(g, battery=_col(res, "battery_capacity_scale") < 0.3)
    e = stage1.summarize(res, NAMES, MISSION, 73)["vehicles"]["glider_eq"]["sensitivity"]
    assert e["quantity"] == "failure indicator" and e["param"] == "battery_capacity_scale" and len(e["S1"]) == 6
    g["battery_margin"] = np.where(np.arange(24) < 12, np.nan, 0.5)                                          # fewer than 16 finite values: the same
    e = stage1.summarize(res, NAMES, MISSION, 73)["vehicles"]["glider_eq"]["sensitivity"]
    assert e["quantity"] == "failure indicator" and set(e["S1"]) == set(stage1.SENS_ACTS["glider"])
    u = merged({"usv": 0.0})["vehicles"]["usv"]                                                              # a USV result without the name: the default
    assert stage1._ranked(dict(u, energy_margin=np.arange(24.0)), "battery")[2] == stage1.QUANTITY["energy_margin"]


def test_r18_m4_without_a_failure_the_entry_keeps_the_margin_label_and_a_station_glider_keeps_its_battery_beside_the_distance():
    res = merged({})
    s = stage1.summarize(res, NAMES, MISSION, 73)["vehicles"]["usv"]["sensitivity"]
    assert s["case"] == "all_pass" and s["quantity"] == "failure indicator"                                  # no margin stored: unchanged from round 17
    u = res["vehicles"]["usv"]
    u["margin"], u["margin_name"] = np.arange(24.0), "maximum cross-track error"
    assert stage1.summarize(res, NAMES, MISSION, 73)["vehicles"]["usv"]["sensitivity"]["quantity"] == "maximum cross-track error"
    v = next(x for x in MISSION["vehicles"] if x["id"] == "glider_eq")
    t0 = stage1.utc(v["deploy"]["time"]).timestamp()
    X = dict(glider_speed_scale=np.ones(2), battery_capacity_scale=np.array([1.0, 0.5]))
    r = stage1._run_glider(v, glider.load_platform("seaglider"), AnalyticEnv(wind=(-5.0, 0.0), current=(0.1, 0.0)), 2, X, t0, t0 + 6 * 3600.0)
    assert r["margin_name"] == "maximum distance from the station" and r["margin"][0] == r["margin"][1]      # the battery does not move the distance
    assert r["battery_margin_name"] == "battery energy margin" and r["battery_margin"][1] < r["battery_margin"][0] < 1.0
    b = dict(U=np.zeros((2, 3)), X={"a": np.zeros(2)}, vehicles={"glider_eq": dict(r, wall_s=1.0, **{"class": "glider"})}, links={})
    j = stage1.merge([b, b])["vehicles"]["glider_eq"]                                                       # merge keeps the new key and its name
    assert j["battery_margin"].shape == (4,) and j["battery_margin_name"] == "battery energy margin" and j["margin_name"] == r["margin_name"]


def test_r18_m4_an_iridium_link_that_no_column_acts_on_is_not_ranked_and_is_not_counted_as_a_test():
    res = merged({"usv": 0.5, "uas": 0.5, "glider_eq": 0.5}, {lid: 0.25 for lid in LK})
    s = stage1.summarize(res, NAMES, MISSION, 73)
    iri = s["links"]["usv-shore-iridium"]["sensitivity"]
    assert LK["usv-shore-iridium"]["when"] == "always" and iri["case"] == "no_acting_input" and iri["S1"] == {} and iri["param"] is None
    assert iri["noise_floor"] is None and iri["text"].startswith("No sampled input can act on the fraction of the required moments the link worked")
    tests = [e["sensitivity"] for k in ("vehicles", "links") for e in s[k].values() if e["sensitivity"]["noise_floor"] is not None]
    assert iri not in tests and all(f"the report makes {len(tests)} such test" in t["text"] for t in tests if t["case"] == "ranked")
    e = stage1._sensitivity(NAMES, res["U"], np.arange(24) < 8, set(), np.linspace(0.0, 1.0, 24), "q")           # the entry itself, with nothing to rank
    assert e["case"] == "no_acting_input" and e["quantity"] == "q" and e["S1"] == {}
    assert stage1._sensitivity(NAMES, res["U"], np.zeros(24, bool), set(), None, "q")["case"] == "all_pass"      # a link that never failed says so first


def test_r18_m4_a_link_feels_the_track_of_its_ends_and_its_own_columns_only():
    cls = dict(glider_eq="glider", usv="usv", uas="uas", glider_1n="glider")
    lk = dict(a="usv", b="shore", kind="iridium", when="surfacing")
    assert stage1.link_acts(lk, cls) == set()                                                                # a USV never surfaces in the sense of a pattern
    assert stage1.link_acts(dict(lk, a="glider_eq"), cls) == {"glider_speed_scale"}                          # the glider's surfacing pattern
    assert stage1.link_acts(dict(lk, a="uas", when="uas_airborne"), cls) == {"wind_speed_bias"}
    assert stage1.link_acts(dict(lk, when="always"), cls) == set() == stage1.link_acts(dict(lk, a="glider_eq", when="always"), cls)
    rf = dict(a="usv", b="uas", kind="rf", when="uas_airborne")
    assert stage1.link_acts(rf, cls) == set(stage1.FORCING) | {"usv_vpp_bias", "bulk_stress_scale"}
    assert stage1.link_acts(dict(rf, a="glider_eq", b="ship", kind="acoustic"), cls) == set(stage1.ACTING[("glider", "margin")])
    assert stage1.link_acts(dict(rf, a="glider_eq", b="ship"), cls) == set(stage1.ACTING[("glider", "margin")]) | {"hs_scale"}
    assert stage1.link_acts(dict(rf, a="glider_eq", b="glider_1n"), cls) == set(stage1.ACTING[("glider", "margin")]) | {"hs_scale"}      # two gliders


def test_r18_m4_the_used_by_counts_of_the_credibility_page_still_read_acts_not_the_sensitivity_table():
    assert credibility.CLASS_PRIORS == {"glider_speed_scale": "glider", "battery_capacity_scale": "glider|uas", "usv_vpp_bias": "usv",
                                        "solar_yield_scale": "usv", "bulk_stress_scale": "uas", "usv_vpp_bias_brief": "usv"}
    assert stage1.ACTS == dict(glider=("glider_speed_scale", "battery_capacity_scale"), usv=("usv_vpp_bias", "solar_yield_scale"),
                               uas=("bulk_stress_scale", "battery_capacity_scale"))


def test_r18_m4_hs_can_end_a_uas_sortie_through_its_link_which_is_why_it_is_listed_beside_what_the_probe_moved(monkeypatch):
    """`UNSEEN`: with the shipped RFD900x the UAS link has 35 dB or more of margin at any range a sortie reaches, so hs_scale never moves a UAS quantity in
    the probe; a radio 35 dB weaker (what a platform may name) does flip the lost-link hook with Hs, so the column is not inert by construction."""
    v, P, mission, t0, T, _ = uas_inputs()
    P, origin, ts = stage1._uas_setup(v, P, mission, t0, T)
    real = stage1._uas_radio
    d = np.arange(300.0, 40000.0, 25.0)
    rel = np.stack([d, np.zeros_like(d), np.full_like(d, 100.0)], 1)

    def lost(hs):
        return stage1._uas_links(AnalyticEnv(hs=hs), mission, origin, ts[:1], P, d.size)[0](float(ts[0]) + 600.0, rel)
    assert (lost(0.1) == lost(6.0)).all()                                                                    # the shipped radio: Hs decides nothing
    monkeypatch.setattr(stage1, "_uas_radio", lambda plat: dict(real(plat), tx_dbm=real(plat)["tx_dbm"] - 35.0))
    assert (lost(0.1) != lost(6.0)).any()
    assert "hs_scale" in stage1.ACTING[("uas", "margin")] and "hs_scale" in stage1.ACTING[("uas", "profile_margin")]


# ---------------------------------------------------------------- M-4: the table is what moves the quantity (every column alone, the real simulators)
M2, SEED = 2, 11


def _sub(vid, hours):
    end = np.datetime64("2023-03-01T18:00") + np.timedelta64(hours, "h")
    return dict(MISSION, vehicles=[v for v in MISSION["vehicles"] if v["id"] == vid], links=[],
                window=dict(start="2023-03-01T18:00:00Z", end=f"{end}:00Z"))


def _quantities(out):
    q = {}
    for r in out["vehicles"].values():
        for k in ("margin", "energy_margin", "battery_margin", "profile_margin"):
            if k in r:
                q[k] = np.asarray(r[k], float)
    return q


def _moved(run, names, spec, center, quantities):
    """{column: set of the quantities (keys of `quantities(run(X))`) that moved} for each column alone at its 5 % and 95 % quantile (member 0 and 1)."""
    base = quantities(run(center))
    out = {}
    for j in names:
        X = dict(center, **{j: np.array([spec[j].ppf(p) for p in (0.05, 0.95)], float)})
        got = quantities(run(X))
        out[j] = {k for k in base if not np.allclose(base[k], got[k], rtol=0, atol=1e-9, equal_nan=True)}
    return out


QS, M_WIDE, ROTATIONS = (0.05, 0.25, 0.5, 0.75, 0.95), 5, (0, 2)
MOVE = 1e-6  # a quantity differs by more than this: the column acts; below it the difference is 1e-7 and less (measured on the demo)


def _moved_wide(run, names, spec, base, quantities):
    """The wider probe of the round 18 addendum (DECISIONS 992): {column: quantities it moved by more than MOVE}. `base` holds the draws of M_WIDE members, EACH
    WITH ITS OWN other draws (a Latin hypercube, not the medians). A column is set alone to the 5, 25, 50, 75 and 95 % quantiles, member k at quantile
    QS[(k + r) % 5] for each rotation r in ROTATIONS: every quantile at two members' other draws. Member by member against the base batch (the same members and
    batch size, so the per-batch random streams are the same)."""
    ref = quantities(run(base))
    out = {j: set() for j in names}
    for j in names:
        for r in ROTATIONS:
            col = np.array([spec[j].ppf(QS[(k + r) % len(QS)]) for k in range(M_WIDE)], float)
            got = quantities(run(dict(base, **{j: col})))
            out[j] |= {k for k in ref if not np.allclose(ref[k], got[k], rtol=0, atol=MOVE, equal_nan=True)}
    return out


PROBES = [("glider_eq", 12, dict(margin=("glider", "margin"), battery_margin=("glider", "battery_margin"))),
          ("glider_1n", 12, dict(margin=("glider", "battery_margin"), battery_margin=("glider", "battery_margin"))),     # a drift one's margin is its battery
          ("usv", 12, dict(margin=("usv", "margin"), energy_margin=("usv", "energy_margin"))),
          ("uas", 9, dict(margin=("uas", "margin"), profile_margin=("uas", "profile_margin")))]


@pytest.mark.parametrize("vid,hours,keys", PROBES, ids=[p[0] for p in PROBES])
def test_r18_m4_the_acting_table_is_the_set_of_columns_that_move_each_quantity(vid, hours, keys, ci_full):
    """Every sampled column alone over its 5, 25, 50, 75 and 95 % quantiles at several members' other draws (`_moved_wide`), through the real `run_batch` on the
    CI environment (the gridded one: the insolation varies in it, so the USV's charge feels what moves its track): what moved a quantity is inside its row of
    `ACTING`, and the row, less `UNSEEN` and `DEMO_ONLY` (the demo's environment moves a Slocum's battery by the current columns, this fixture's does not:
    tests/test_round18_x.py holds those against the demo record), is what moved."""
    mission = _sub(vid, hours)
    pri, marg = stage1.priors_for(MISSION)
    spec = {k: sampling.marginal(m) for k, m in marg.items()}
    _, base = sampling.lhs(M_WIDE, marg, np.random.SeedSequence([SEED, 0]))      # no antithetic pairs: five members, five different other draws
    moved = _moved_wide(lambda X: stage1.run_batch(mission, ci_full, list(range(M_WIDE)), SEED, pri, marg, X=X), list(marg), spec, base, _quantities)
    for key, row in keys.items():
        got = {j for j, ks in moved.items() if key in ks}
        want = set(stage1.ACTING[row]) - set(stage1.UNSEEN.get(row, ()))
        assert got <= want, (vid, key, sorted(got - want))
        assert got == want - set(stage1.DEMO_ONLY.get(row, ())), (vid, key, sorted(got ^ want))


def test_r18_m4_every_column_that_moves_a_link_is_one_the_link_table_lists(monkeypatch):
    """The links of the CI mission and three more (an Iridium link on a surfacing glider, an RF link and an acoustic link on a vehicle each): the outcome
    quantities (the fraction, the moments required, the summed margin) that a column moves are in `link_acts`; the Iridium link `when: always`: by none."""
    links = MISSION["links"] + [
        dict(id="g-shore-iridium", a="glider_1n", b="shore", kind="iridium", when="surfacing", required_fraction=0.9),
        dict(id="g-ship-rf", a="glider_eq", b="ship", kind="rf", radio="rfd900x", when="surfacing", required_fraction=0.9),
        dict(id="usv-ship-acoustic", a="usv", b="ship", kind="acoustic", modem="benthos_atm960_mf", when="always", required_fraction=0.9)]
    mission = dict(MISSION, links=links, window=dict(start="2023-03-01T18:00:00Z", end="2023-03-02T03:00:00Z"))
    pri, marg = stage1.priors_for(MISSION)
    spec = {k: sampling.marginal(m) for k, m in marg.items()}
    center = {k: np.full(M2, float(spec[k].ppf(0.5))) for k in marg}
    env = AnalyticEnv(wind=(-6.0, 2.0), current=(0.15, -0.1), hs=2.0)

    def quantities(out):
        q = {}
        for lid, r in out["links"].items():
            q[f"{lid}|frac"], q[f"{lid}|need"] = np.asarray(r["frac"], float), np.asarray(r["need_count"], float)
            q[f"{lid}|margin"] = np.nansum(np.asarray(r["margin_db"], float), 0)
        return q

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        moved = _moved(lambda X: stage1.run_batch(mission, env, [0, 1], SEED, pri, marg, X=X), list(marg), spec, center, quantities)
    classes = dict(glider_eq="glider", glider_1n="glider", usv="usv", uas="uas")
    seen = set()
    for lk in links:
        acts = stage1.link_acts(lk, classes)
        got = {j for j, ks in moved.items() if any(k.startswith(lk["id"] + "|") for k in ks)}
        seen |= got
        assert got <= acts, (lk["id"], sorted(got - acts))
    assert {j for j, ks in moved.items() if any(k.startswith("usv-shore-iridium|") for k in ks)} == set() == stage1.link_acts(LK["usv-shore-iridium"], classes)
    assert {"wind_speed_bias", "glider_speed_scale"} <= seen                                                 # the probe does move links: not an empty check


# ---------------------------------------------------------------- M-16 (A-2): the sortie length is `sortie_t_max`, at three of its five sites
def _sortie_setup():
    v, P, mission, t0, T, X = uas_inputs()
    P2, origin, ts = stage1._uas_setup(v, P, mission, t0, T)
    return v, P, P2, mission, t0, T, X, origin, ts


def test_r18_a2_a_launch_whose_hard_stop_does_not_fit_before_the_end_of_the_window_is_dropped():
    """stage1.py `_uas_setup` -> `launch_times(..., uas.sortie_t_max(so))`: with `duration_s` instead, a 20 min sortie that may fly 32 min was launched 25 min
    before the window's end, and its flight ran past the window."""
    v, P, P2, mission, t0, T, X, origin, ts = _sortie_setup()
    so = P2["sortie"]
    first = float(ts[0])
    assert so["duration_s"] < 1500.0 < uas.sortie_t_max(so)
    assert stage1._uas_setup(v, P, mission, t0, first + 1500.0)[2].size == 0                                 # the nominal sortie fits, the hard stop does not
    assert stage1._uas_setup(v, P, mission, t0, first + uas.sortie_t_max(so) + 1.0)[2].tolist() == [first]
    r = stage1._run_uas(v, P, AnalyticEnv(), 2, X, t0, first + 1500.0, mission, 1, [0, 1])
    assert r["sorties"] == [] and r["fail"]["no_sortie_flown"].all()


class _AskedForWaves(AnalyticEnv):
    """AnalyticEnv that records the latest time its waves were asked for."""
    latest = -np.inf

    def waves(self, lon, lat, t):
        self.latest = max(self.latest, float(np.max(t)))
        return super().waves(lon, lat, t)


def test_r18_a2_the_wave_height_at_the_ship_is_read_over_the_whole_flight_to_the_hard_stop_and_its_margin():
    """stage1.py `_uas_links`: `tg = t0 + arange(0, sortie_t_max + 61, 30)`; with `duration_s` the Hs grid ended 11 min before the hard stop and held its last
    value over the end of a long flight."""
    v, P, P2, mission, t0, T, X, origin, ts = _sortie_setup()
    env = _AskedForWaves()
    stage1._uas_links(env, mission, origin, ts[:1], P2, 2)
    assert env.latest - float(ts[0]) >= uas.sortie_t_max(P2["sortie"]) + 60.0 - 30.0
    assert env.latest - float(ts[0]) > P2["sortie"]["duration_s"] + 61.0 + 30.0


def test_r18_a2_the_fine_grid_of_a_flown_sortie_runs_to_the_hard_stop():
    """stage1.py `_run_uas`: `tf = tl + arange(0, sortie_t_max + 1, FINE_S)` (the 30 s grid the links are judged on)."""
    v, P, P2, mission, t0, T, X, origin, ts = _sortie_setup()
    r = stage1._run_uas(v, P, AnalyticEnv(), 2, X, t0, T, mission, 1, [0, 1])
    assert r["fine"]["t"].max() - float(ts[0]) == pytest.approx(uas.sortie_t_max(P2["sortie"]), abs=stage1.FINE_S)
    assert r["fine"]["t"].max() - float(ts[0]) > P2["sortie"]["duration_s"] + stage1.FINE_S


def test_r18_a2_a_flight_that_is_not_home_at_the_nominal_duration_flies_on_to_the_hard_stop():
    """physics/uas.py `fly_sortie` -> `simulate(t_max=sortie_t_max(so))`: with `duration_s` the run stopped at the nominal duration, member still up."""
    P = copy.deepcopy(uas.load_platform("quad_uas"))
    P["sortie"]["duration_s"] = 100.0
    r = uas.fly_sortie(AnalyticEnv(wind=(0.0, 0.0)), uas.steaming(), 0.0, M=1, origin=(-165.0, 0.0), plat=P)
    end = float(r["track"]["t"][-1])
    assert end > 100.0 + 1.0 and end <= uas.sortie_t_max(P["sortie"]) + 1.0
    assert uas.sortie_t_max(P["sortie"]) == pytest.approx(100.0 * P["sortie"]["hard_stop_factor"])
