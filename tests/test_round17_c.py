"""Round 17, batch C: the sensitivity's acting columns (M-8) and the tests of round 16's USV and UAS fixes that no test pinned (M-19: A-3, A-5, A-6)."""
import sys
import types

import numpy as np
import pytest

from cafe.pm import stage1
from cafe.pm.env.protocol import AnalyticEnv
from cafe.pm.physics import glider, uas, usv
from tests.test_stage1 import LK, MISSION, merged, uas_inputs


# ---------------------------------------------------------------- M-8: the sensitivity ranks only the columns the class's simulator reads
GLIDER = {"wind_speed_bias", "wind_direction_bias", "current_speed_scale", "current_direction_bias", "glider_speed_scale", "battery_capacity_scale"}
USV = set(stage1.FORCING) | {"usv_vpp_bias", "solar_yield_scale"}          # round 18, M-4: the solar yield moves the battery flag, so the indicator too
UAS = {"wind_speed_bias", "wind_direction_bias", "hs_scale", "bulk_stress_scale", "battery_capacity_scale"}


def _summary():
    res = merged({"usv": 0.5, "uas": 0.5, "glider_eq": 0.5}, {lid: 0.25 for lid in LK})
    names = list(stage1.priors_for(MISSION)[1])
    return res, names, stage1.summarize(res, names, MISSION, 73)


def test_r17_m8_each_vehicle_and_link_ranks_only_the_columns_its_simulator_reads():
    _, _, s = _summary()
    v = {vid: set(s["vehicles"][vid]["sensitivity"]["S1"]) for vid in ("glider_eq", "usv", "uas")}
    assert v == dict(glider_eq=GLIDER, usv=USV, uas=UAS)          # no wave column for the glider, no current or Tp for the UAS, no solar yield for the USV
    kinds = {lid: lk["kind"] for lid, lk in LK.items()}
    assert set(kinds.values()) == {"rf", "acoustic", "iridium"}
    # round 18, M-4: the columns that move an end's track (not its battery or its insolation); an RF link also reads Hs; an Iridium link `when: always` has none
    want = {"rf": set(stage1.FORCING) | {"usv_vpp_bias", "bulk_stress_scale", "battery_capacity_scale"},   # round 19, M-5: the UAS end's battery
            "acoustic": GLIDER - {"battery_capacity_scale"}, "iridium": set()}
    for lid, kind in kinds.items():
        assert set(s["links"][lid]["sensitivity"]["S1"]) == want[kind], lid


def test_r17_m8_an_rf_link_reads_hs_whatever_the_classes_at_its_ends():
    res, names, _ = _summary()
    glider_rf = dict(MISSION, links=[dict(LK["usv-uas-rf"], id="g-ship-rf", a="glider_eq", b="ship")])
    res["links"] = {"g-ship-rf": res["links"]["usv-uas-rf"]}
    got = stage1.summarize(res, names, glider_rf, 73)["links"]["g-ship-rf"]["sensitivity"]["S1"]
    assert set(got) == (GLIDER - {"battery_capacity_scale"}) | {"hs_scale"} and "tp_bias" not in got


def test_r17_m8_a_column_the_uas_cannot_feel_cannot_head_its_list():
    res, names, _ = _summary()
    j = names.index("current_direction_bias")
    u = res["vehicles"]["uas"]
    u["margin"] = res["U"][:, j].copy()                                                            # a margin that is a function of the inert column alone
    u["margin_name"] = "battery reserve margin"
    u["fail"], u["first"] = dict(battery_reserve=u["fail"]["mode_a"]), dict(battery_reserve=u["first"]["mode_a"])      # round 18, M-4: the battery failed
    e = stage1.summarize(res, names, MISSION, 73)["vehicles"]["uas"]["sensitivity"]
    assert "current_direction_bias" not in e["S1"] and e["param"] != "current_direction_bias" and e["quantity"] == "battery reserve margin"


class _Waves(dict):
    def __init__(self, read, w):
        super().__init__(w)
        self.read = read

    def __getitem__(self, k):
        self.read.add(k)
        return super().__getitem__(k)


class _Recording:
    """AnalyticEnv that records which fields a simulator reads: 'wind', 'current' and the wave keys."""

    def __init__(self, **kw):
        self._env, self.read = AnalyticEnv(**kw), set()

    def wind(self, *a):
        self.read.add("wind")
        return self._env.wind(*a)

    def current(self, *a):
        self.read.add("current")
        return self._env.current(*a)

    def waves(self, *a):
        return _Waves(self.read, self._env.waves(*a))

    def __getattr__(self, name):
        if name in ("_env", "read"):
            raise AttributeError(name)
        return getattr(self._env, name)


def _read_columns(read):
    cols = set()
    for field, names in (("wind", ("wind_speed_bias", "wind_direction_bias")), ("current", ("current_speed_scale", "current_direction_bias"))):
        cols |= set(names) if field in read else set()
    return cols | ({"hs_scale"} if "Hs" in read else set()) | ({"tp_bias"} if read & {"Tp", "Tm", "stokes0"} else set())


def _flown(cls):
    """The forcing columns the real simulator of `cls` reads, from the fields it asks the environment for."""
    env = _Recording(wind=(-5.0, 0.0), current=(0.1, 0.1))
    ones = {k: np.ones(2) for k in ("glider_speed_scale", "battery_capacity_scale", "usv_vpp_bias", "solar_yield_scale", "bulk_stress_scale")}
    if cls == "uas":
        v, P, mission, t0, T, X = uas_inputs()
        stage1._run_uas(v, P, env, 2, X, t0, T, mission, 1, [0, 1])
    else:
        v = next(x for x in MISSION["vehicles"] if x["id"] == ("glider_eq" if cls == "glider" else "usv"))
        t0 = stage1.utc(v["deploy"]["time"]).timestamp()
        if cls == "glider":
            stage1._run_glider(v, glider.load_platform("seaglider"), env, 2, ones, t0, t0 + 24 * 3600.0, windage=np.array([0.02, 0.02]))
        else:
            stage1._run_usv(v, usv.load_platform("saildrone_explorer"), env, 2, ones, t0, t0 + 2 * 3600.0)
    return _read_columns(env.read)


@pytest.mark.parametrize("cls", ["glider", "usv", "uas"])
def test_r17_m8_the_acting_table_is_what_the_simulator_reads_of_the_forcing(cls):
    """The table is a second copy of what `_run_glider`, `_run_usv` and `_run_uas` read; this holds the two together (round 16, M-29's trap)."""
    assert set(stage1.SENS_ACTS[cls]) & set(stage1.FORCING) == _flown(cls)
    acts, own = set(stage1.SENS_ACTS[cls]), set(stage1.ACTS[cls])
    assert acts <= set(stage1.FORCING) | own and own - acts <= {"solar_yield_scale"}                # the only prior left out is the USV's solar yield


def test_r17_m8_the_usv_margin_does_not_move_with_the_solar_yield_only_its_charge_does():
    P = usv.load_platform("saildrone_explorer")
    even = P["hotel_w"] / (P["solar_eff"] * P["solar_area_m2"])
    v = next(x for x in MISSION["vehicles"] if x["id"] == "usv")
    t0 = stage1.utc(v["deploy"]["time"]).timestamp()
    X = dict(usv_vpp_bias=np.full(2, -0.24), solar_yield_scale=np.array([0.5, 2.0]))
    r = stage1._run_usv(v, P, AnalyticEnv(wind=(-6.0, 0.0), swdown=even), 2, X, t0, t0 + 6 * 3600.0)
    assert r["margin"][0] == r["margin"][1] > 0.0 and r["energy_margin"][0] < r["energy_margin"][1]
    assert "solar_yield_scale" not in stage1.ACTING[("usv", "margin")] and "solar_yield_scale" in stage1.ACTING[("usv", "energy_margin")]   # round 18, M-4


# ---------------------------------------------------------------- M-19 (A-6): soc_min is the lowest state of charge, from the start value
def test_r17_a6_soc_min_is_the_lowest_state_of_charge_and_starts_at_the_platform_start_value():
    P = dict(usv.load_platform(), soc0=0.8)
    even = P["hotel_w"] / (P["solar_eff"] * P["solar_area_m2"])
    sim = usv.USVSim(P, 3, AnalyticEnv(wind=(-6.0, 0.0), swdown=2.0 * even), (-165.0, -1.0), 0.0, dict(mode="station", station=(-165.0, 0.5)),
                     perturb=dict(vpp_bias=np.full(3, -0.24)))
    assert sim.soc_min.tolist() == [0.8] * 3
    h = sim.run(6 * 3600.0, 600.0)
    last = sim.soc_wh / P["battery_wh"]
    assert (last > 0.9).all() and h["soc_min"].tolist() == [0.8] * 3          # the pack gained: the lowest is where it started, not the last state


# ---------------------------------------------------------------- M-19 (A-3): the USV table cache is written through a temporary
def test_r17_a3_a_cut_write_of_the_usv_table_cache_leaves_no_file_at_its_name(tmp_path, monkeypatch):
    monkeypatch.setattr(usv, "_CACHE", {})
    real = np.savez

    def cut(fh, **kw):
        real(fh, **kw)
        raise OSError("the disk was pulled")

    monkeypatch.setattr(usv.np, "savez", cut)
    P = usv.load_platform()
    with pytest.raises(OSError, match="pulled"):
        usv.tables(P, cache_dir=tmp_path)
    assert list(tmp_path.glob("usv_tables_*.npz")) == []                                          # a cut write is no cache file


# ---------------------------------------------------------------- M-19 (A-5): fly_sitl refuses a short turbulence series before it flies
@pytest.fixture
def sitl_stub(tmp_path, monkeypatch):
    """A SITL directory with a file named arducopter (never run) and a stand-in `pymavlink`: fly_sitl reaches its first statement after the imports."""
    from cafe import emulator
    (tmp_path / "arducopter").write_text("")
    monkeypatch.setattr(emulator, "SITL_DIR", tmp_path)
    mod = types.ModuleType("pymavlink")
    mod.mavutil = types.ModuleType("pymavlink.mavutil")                                           # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pymavlink", mod)
    monkeypatch.setitem(sys.modules, "pymavlink.mavutil", mod.mavutil)                            # type: ignore[attr-defined]


def test_r17_a5_fly_sitl_refuses_a_series_shorter_than_the_longest_flight_before_anything_else(sitl_stub):
    P = uas.load_platform()
    so = P["sortie"]
    nominal = int(np.ceil((so["duration_s"] + 60.0) / uas.DT_ENV))                                # covers the nominal sortie, not the hard stop
    assert nominal < int(np.ceil((uas.sortie_t_max(so) + 60.0) / uas.DT_ENV))
    ship = lambda t: np.zeros(2)
    with pytest.raises(ValueError, match="turbulence series covers"):
        uas.fly_sitl(AnalyticEnv(), ship, 0.0, turb=np.zeros((1, nominal, 3)))
    longer = int(np.ceil((uas.sortie_t_max(so) + 60.0) / uas.DT_ENV))
    with pytest.raises(ValueError, match="turbulence series covers"):                             # a caller's longer max_s is the length that is asked for
        uas.fly_sitl(AnalyticEnv(), ship, 0.0, turb=np.zeros((1, longer, 3)), max_s=3.0 * uas.sortie_t_max(so))
