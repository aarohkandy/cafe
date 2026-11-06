"""cafe.pm.budget: the plan adapts to the measured machine, shrinks when the measured member cost is high, and refuses oversized nests."""
import json
import math
import pathlib
import re

import pytest
from hypothesis import given, settings, strategies as st

from cafe.pm import budget, config, par, stage1
from cafe.pm.budget import PlanError

MISSION = dict(window=dict(start="2023-03-01T12:00:00Z", end="2023-03-07T12:00:00Z"))          # 6 days
CLASSES = dict(glider_eq="glider", usv="usv", uas="uas")
GPU = 1                                                         # a GPU plan never skips a LES window: its shares are the SHARE table


def thr(batch=None, member=None, **extra):
    """A throughput.json with measured stage-1 costs per mission day: s per batch (environment calls) and s per member."""
    t = {}
    if batch is not None:
        t["stage1"] = {c: dict(s_per_batch_day=batch, s_per_member_day=member, measured="2026-10-29", host="az_serv", load_1min=19.5)
                       for c in ("glider", "usv", "uas")}
    t.update(extra)
    return t


def test_cheap_batches_get_the_full_ensemble_and_certify():
    p = budget.plan("quick", GPU, MISSION, thr=thr(0.01, 0.001), vehicle_classes=CLASSES)
    assert p["n_max"] == budget.N_MAX["quick"] == 64 and p["n_min"] == 32 and p["certify_possible"] is False
    assert [n for n in p["notes"] if "ensemble" in n or "batch" in n] == []
    big = budget.plan("overnight", GPU, MISSION, thr=thr(0.01, 0.001), vehicle_classes=CLASSES)
    assert big["n_max"] == 512 and big["certify_possible"] and big["n_min"] == 73 and big["sitl_members"] == 0 and big["refit_iterations"] == 2


def test_a_high_measured_batch_cost_shrinks_the_ensemble_to_whole_batches_and_says_so():
    cheap = budget.plan("4h", GPU, MISSION, thr=thr(1.0, 0.05), vehicle_classes=CLASSES)
    dear = budget.plan("4h", GPU, MISSION, thr=thr(100.0, 0.05), vehicle_classes=CLASSES)
    assert cheap["n_max"] == 256 and dear["n_max"] < cheap["n_max"]
    per_batch, per_member = 3 * 100.0 * 6, 3 * 0.05 * 6                              # s per batch of environment calls, s per member (3 vehicles, 6 days)
    n_batches = int(budget.SHARE["stage1"] * budget.BUDGET_S["4h"] // (per_batch + budget.BATCH["4h"] * per_member))
    assert n_batches == 3 and dear["n_max"] == 3 * budget.BATCH["4h"] == 192 and dear["n_max"] % dear["batch"] == 0
    assert any("ensemble capped at 192 members" in n and "1800 s per batch of 64" in n and "0.90 s per member" in n for n in dear["notes"])
    quick = budget.plan("quick", GPU, MISSION, thr=thr(20.0, 0.01), vehicle_classes=CLASSES)
    assert quick["n_max"] == quick["batch"] == 32 and quick["n_min"] == 32 and any("ensemble capped at 32 members" in n for n in quick["notes"])


def test_the_member_cost_matters_too_but_far_less_than_the_batch_cost():
    base = budget.plan("4h", 0, MISSION, thr=thr(100.0, 0.05), vehicle_classes=CLASSES)["n_max"]
    members_dear = budget.plan("4h", 0, MISSION, thr=thr(100.0, 3.0), vehicle_classes=CLASSES)["n_max"]
    batches_dear = budget.plan("4h", 0, MISSION, thr=thr(200.0, 0.05), vehicle_classes=CLASSES)["n_max"]
    assert batches_dear < base and members_dear < base


def test_a_batch_that_does_not_fit_the_share_is_halved_to_the_largest_that_does_and_the_plan_says_so():
    p = budget.plan("quick", GPU, MISSION, thr=thr(27.0, 0.1), vehicle_classes=CLASSES)             # 486 s per batch + 1.8 s per member; share 540 s
    assert 486.0 + 32 * 1.8 > p["stage1_share_s"] == 540.0 and 486.0 + 16 * 1.8 <= 540.0
    assert p["batch"] == p["n_max"] == 16 and p["stage1_s"] == pytest.approx(486.0 + 16 * 1.8) and p["stage1_s"] <= p["stage1_share_s"]
    assert any("batch shrunk from 32 to 16 members" in n and "540 s" in n for n in p["notes"])
    assert p["n_min"] == 16 and p["certify_possible"] is False


def test_when_not_even_the_smallest_batch_fits_the_plan_refuses_and_names_the_shortfall():
    with pytest.raises(PlanError, match=r"--budget 4h: stage 1 needs 18072000 s for even one batch of 4 members .* share of the 14400 s budget is 6480 s: "
                                        r"short by 18065520 s"):
        budget.plan("4h", GPU, MISSION, thr=thr(1e6, 1e3), vehicle_classes=CLASSES)
    with pytest.raises(PlanError, match="short by"):
        budget.plan("ci", GPU, MISSION, thr=thr(1e4, 1e4), vehicle_classes=CLASSES)


@settings(max_examples=60, deadline=None)
@given(st.sampled_from(list(budget.BUDGET_S)), st.floats(0.0, 5e3), st.floats(0.0, 50.0))
def test_the_plan_never_predicts_more_stage_1_time_than_its_share(name, batch_day, member_day):
    try:
        p = budget.plan(name, 0, MISSION, thr=thr(batch_day, member_day), vehicle_classes=CLASSES)
    except PlanError:
        return
    assert p["stage1_s"] <= p["stage1_share_s"] * (1 + 1e-9) and p["n_max"] % p["batch"] == 0 and p["batch"] >= budget.MIN_BATCH


def test_a_stage_1_rate_measured_under_load_or_on_another_mission_is_warned_about_in_the_plan():
    t = thr(1.0, 0.05)
    for e in t["stage1"].values():
        e.update(cpus=8, load_1min=32.85, mission="missions/ci_fixture.yaml")
    named = dict(MISSION, name="tepex_c_demo")
    notes = budget.plan("quick", 0, named, thr=t, vehicle_classes=CLASSES)["notes"]
    assert any("measured at load 32.9 on 8 CPUs (above 2)" in n for n in notes)
    assert any("measured on mission 'ci_fixture', not 'tepex_c_demo'" in n for n in notes)
    assert len([n for n in notes if "load" in n]) == 1                                         # one line for the three classes
    for e in t["stage1"].values():
        e.update(load_1min=1.5, mission_name="tepex_c_demo")
    assert not [n for n in budget.plan("quick", 0, named, thr=t, vehicle_classes=CLASSES)["notes"] if "measured" in n]
    for e in t["stage1"].values():
        e.update(load_1min=2.5)
    assert any("load 2.5" in n for n in budget.plan("quick", 0, named, thr=t, vehicle_classes=CLASSES)["notes"])


def test_the_shipped_stage_1_measurement_was_made_on_a_quiet_box():
    """DECISIONS 272: re-measured at 1-min load 1.4 (the 2026-10-29 file, at 32.9, was flagged as contended; the test above keeps that path tested)."""
    notes = budget.plan("quick", 0, dict(MISSION, name="tepex_c_demo"), vehicle_classes=CLASSES)["notes"]
    assert not any("measured at load" in n for n in notes)


def test_the_plan_says_when_the_emulator_cannot_train_at_this_budget():
    dear = budget.plan("quick", GPU, MISSION, thr=thr(26.0, 0.1), vehicle_classes=CLASSES)
    em = budget.emulator_plan(dear)
    assert not em["trains"] and em["variants_refit"] == em["variants_no_refit"] == 0 and em["note"] in dear["notes"]
    assert "cannot train at this budget" in em["note"] and "0 of 6 variants" in em["note"]
    cheap = budget.plan("quick", GPU, MISSION, thr=thr(0.01, 0.001), vehicle_classes=CLASSES)          # 6 variants + the base: 7 points of the 100
    ec = budget.emulator_plan(cheap)
    assert not ec["trains"] and ec["variants_no_refit"] == 6 and ec["note"] in cheap["notes"]
    assert ec["points_per_scope"] == {"glider/?/144h": 7, "uas/?/144h": 7, "usv/?/144h": 7}
    assert "this budget gives 7 distinct points per emulator scope (vehicle class, platform, window length) in one run" in ec["note"]
    assert "100 are needed" in ec["note"]
    assert "will not train from this run alone" in ec["note"]


def test_a_long_budget_sizes_the_variants_to_reach_the_minimum_points_when_the_share_allows():
    assert budget.EMULATOR_MIN_POINTS == 100
    big = budget.plan("overnight", GPU, MISSION, thr=thr(0.01, 0.001), vehicle_classes=CLASSES)
    e = budget.emulator_plan(big)
    need = math.ceil(100 * budget.EMULATOR_POINTS_MARGIN) - 1                                # 1 vehicle per class: (variants + 1) points
    assert e["max_variants"] == need == 119 and e["variants_no_refit"] == 119 and e["trains"] and e["points_per_scope"]["usv/?/144h"] == 120
    assert not any("emulator" in n for n in big["notes"])
    gs = "glider/seaglider/144h"
    two = budget.emulator_plan(dict(big, vehicle_scopes=dict(g1=gs, g2=gs)))                     # two vehicles per scope: half as many variants
    assert two["max_variants"] == 59 and two["points_per_scope"] == {gs: 120}
    old = budget.emulator_plan(dict(big, vehicle_scopes=None, vehicle_classes=dict(g1="glider", g2="glider")))           # a plan made before scopes: per class
    assert old["max_variants"] == 59 and old["points_per_scope"] == dict(glider=120)
    dear = budget.plan("overnight", GPU, MISSION, thr=thr(60.0, 0.1), vehicle_classes=CLASSES)          # a variant costs more than the share holds 119 of
    d = budget.emulator_plan(dear)
    assert 0 < d["variants_no_refit"] < 119 and not d["trains"] and d["note"] in dear["notes"]
    assert f"{d['variants_no_refit'] + 1} distinct points" in d["note"]
    assert budget.emulator_plan(dict(big, member_cost={}))["trains"] is False                         # nothing priced: no variants, one point


def test_the_emulator_plan_counts_points_per_scope_so_two_platforms_of_one_class_do_not_add_up():
    """Round 10 M-1: the plan counted per class, so the demo's seaglider and Slocum counted as 2 points per variant; an emulator is trained on one platform
    and one window length only, so each has 1."""
    demo = config.load_mission(budget.ROOT / "missions" / "tepex_c_demo.yaml")
    p = budget.plan("quick", GPU, demo, thr=thr(0.01, 0.001), vehicle_classes=stage1._classes(demo))
    assert p["vehicle_scopes"] == {"glider_eq": "glider/seaglider/144h", "glider_2n": "glider/slocum/144h", "usv": "usv/saildrone_explorer/144h",
                                   "uas": "uas/quad_uas/144h"}
    e = budget.emulator_plan(p)
    assert e["points_per_scope"] == dict.fromkeys(sorted(set(p["vehicle_scopes"].values())), 7) and e["variants_no_refit"] == 6
    long = config.load_mission(budget.ROOT / "missions" / "tepex_c_demo.yaml")
    long["window"]["end"] = "2023-03-09T12:00:00Z"
    assert budget.emulator_scope(long, "glider_eq", "glider") == "glider/seaglider/192h" != budget.emulator_scope(demo, "glider_eq", "glider")


def test_an_unresolved_slope_is_said_in_the_source_and_costs_a_batch_the_same_whatever_its_size():
    """Round 4 M-26: the bench stores `slope_resolved: false` with a 0 slope; the planner then charges per batch only, and its source line says so."""
    thr = {"stage1": {"usv": dict(s_per_batch_day=12.0, s_per_member_day=0.0, slope_resolved=False, measured="2026-11-01", host="h", load_1min=0.5),
                      "uas": dict(s_per_batch_day=12.0, s_per_member_day=0.1, slope_resolved=True, measured="2026-11-01", host="h", load_1min=0.5),
                      "glider": dict(s_per_batch_day=12.0, s_per_member_day=0.0, measured="2026-10-29", host="h", load_1min=0.5)}}
    (b, m), src = budget.member_cost(thr, "usv")
    assert (b, m) == (12.0, 0.0) and src.endswith("a batch costs the same whatever its size") and "did not resolve a per-member slope" in src
    assert "slope" not in budget.member_cost(thr, "uas")[1] and "slope" not in budget.member_cost(thr, "glider")[1]  # resolved, or an older file
    plan = dict(batch=8, days=2.0, member_cost={"usv": dict(s_per_batch_day=12.0, s_per_member_day=0.0, source=src)})
    assert budget.batch_cost_s(plan) == 24.0 == budget.batch_cost_s(dict(plan, batch=64))


def test_unmeasured_classes_use_the_labelled_fallback():
    assert budget.member_cost({}, "uas") == (budget.FALLBACK_COST["uas"], "NOT MEASURED on this machine (run `make bench`): planner fallback")
    (b, m), src = budget.member_cost(thr(7.0, 0.2), "usv")
    assert (b, m) == (7.0, 0.2) and src == "measured (2026-10-29, az_serv, load 19.5)"
    p = budget.plan("quick", 0, MISSION, thr={}, vehicle_classes=CLASSES)
    assert p["member_cost"]["uas"] == dict(s_per_batch_day=20.0, s_per_member_day=0.3, source=budget.member_cost({}, "uas")[1])
    assert all("NOT MEASURED" in v["source"] for v in p["member_cost"].values())
    m = budget.plan("quick", 0, MISSION, thr=thr(1.0, 0.2), vehicle_classes=CLASSES)
    assert all(v["source"].startswith("measured (2026-10-29, az_serv") for v in m["member_cost"].values())


def test_bad_arguments_are_refused():
    with pytest.raises(PlanError, match=r"--budget 'weekend': choose one of \['ci', 'quick', '4h', 'overnight'\]"):
        budget.plan("weekend", 0, MISSION, thr={})
    with pytest.raises(PlanError, match="--gpus must be >= 0"):
        budget.plan("quick", -1, MISSION, thr={})


def test_lbm_rate_cpu_gpu_measured_and_projected():
    r, backend, src = budget.lbm_rate({"jax-lbm-d3q19-cpu": dict(per_device=3e6, measured="d", device="cpu")}, 0)
    assert (r, backend) == (3e6, "native-jax-cpu") and src.startswith("measured")
    r, backend, src = budget.lbm_rate({}, 0)
    assert (r, backend) == (5e6, "native-jax-cpu") and "NOT MEASURED" in src
    r, backend, src = budget.lbm_rate({"jax-lbm-d3q19-gpu": dict(per_device=1e10, measured="d", device="H100")}, 2)
    assert (r, backend) == (2e10, "native-jax-gpu") and "H100" in src and src.startswith("measured")
    old = {"xlb-warp-gpu": dict(per_device=1e10, measured="d", device="H100")}                                   # the old, never-written key is ignored
    assert budget.lbm_rate(old, 2)[2].startswith("projected")
    import inspect, pathlib
    bench = (pathlib.Path(__file__).resolve().parents[1] / "bench" / "throughput.py").read_text()
    assert 'save(f"jax-lbm-d3q19-{device}"' in bench and "jax-lbm-d3q19-gpu" in inspect.getsource(budget.lbm_rate)   # bench writes what the planner reads
    r, _, src = budget.lbm_rate({}, 1)
    assert r == pytest.approx(0.95 * 20.8e9) and "projected" in src


def test_cpu_plan_is_labelled_as_the_fallback_and_gpu_plan_sizes_the_nest_cap():
    cpu = budget.plan("overnight", 0, MISSION, thr={}, vehicle_classes=CLASSES)
    assert cpu["les"]["cpu_fallback"] is True and cpu["les"]["label"].startswith("CPU fallback") and "max_cells" not in cpu["les"]
    assert cpu["les"]["backend"] == "native-jax-cpu" and "XLB" not in cpu["les"]["label"] and "blended" not in cpu["les"]["label"]
    assert "no LES coefficients exist on this machine" in cpu["les"]["label"] and "pooled window coefficient" not in cpu["les"]["label"]
    gpu = budget.plan("4h", 1, MISSION, thr={}, gpu_mem_gb=48.0, vehicle_classes=CLASSES)
    assert gpu["les"]["cpu_fallback"] is False and gpu["les"]["label"] == "GPU LES windows" and gpu["les"]["gpu_mem_gb"] == 48.0
    assert gpu["les"]["max_cells"] == int(0.85 * 48e9 / 300.0)                    # the native nest's 300 B/cell (round 7 M-13; 55 is FluidX3D's FP16 layout)
    assert gpu["les"]["cell_steps_per_window"] > cpu["les"]["cell_steps_per_window"]
    assert "max_cells" not in budget.plan("4h", 1, MISSION, thr={}, vehicle_classes=CLASSES)["les"]


# ---------------------------------------------------------------------------------------------------------------- M-8: windows a CPU cannot reach

def test_a_cpu_plan_skips_every_les_window_that_cannot_reach_the_physical_viscosity_and_gives_the_slices_to_stage_1(monkeypatch):
    monkeypatch.setenv("CAFE_NPROC", "6")                                                       # (the free-surface price depends on the cores)
    for name in ("quick", "4h"):                                                                  # (overnight keeps the seconds its free-surface case fits)
        p = budget.plan(name, 0, MISSION, thr=thr(0.01, 0.001), vehicle_classes=CLASSES)
        w = p["les"]["windows"]
        assert set(w) == {"glider_eq/body", "usv/hull", "usv/wing", "uas/body"}
        assert not any(x["runs"] or x["reachable"] for x in w.values()) and all(x["need_cell_updates"] > 100 * x["afford_cell_updates"] for x in w.values())
        assert all(x["skip_reason"].startswith("not run: the physical lattice viscosity") and "went to stage 1" in x["skip_reason"] for x in w.values())
        B = budget.BUDGET_S[name]
        assert p["shares"]["stage3"] == 0.0 and p["shares"]["stage1"] == pytest.approx(budget.SHARE["stage1"] + budget.SHARE["stage3"])   # no FS case fits
        assert p["stage1_share_s"] == pytest.approx(0.75 * B) and p["shares"]["emulator"] == budget.SHARE["emulator"]
        assert any(n.startswith("stage 3: no LES coefficients exist on this machine: 4 of 4 window part(s) are not run") for n in p["notes"])
    gpu = budget.plan("overnight", 1, MISSION, thr=thr(0.01, 0.001), vehicle_classes=CLASSES)                  # the GPU path is unchanged
    assert all(x["runs"] and x["skip_reason"] is None for x in gpu["les"]["windows"].values()) and gpu["shares"] == budget.SHARE
    assert not any("no LES coefficients" in n for n in gpu["notes"])


def test_the_skipped_share_raises_the_ensemble_and_the_plan_is_deterministic(monkeypatch):
    monkeypatch.setenv("CAFE_NPROC", "6")
    kw = dict(thr=thr(20.0, 0.01), vehicle_classes=CLASSES)
    cpu, gpu = budget.plan("quick", 0, MISSION, **kw), budget.plan("quick", 1, MISSION, **kw)
    assert gpu["n_max"] == 32 and cpu["n_max"] == 64 and cpu["stage1_share_s"] > gpu["stage1_share_s"]
    assert budget.plan("quick", 0, MISSION, **kw) == cpu


def test_ci_keeps_one_window_as_a_smoke_path_and_the_others_give_their_slices_up():
    p = budget.plan("ci", 0, MISSION, thr={}, vehicle_classes=CLASSES)
    w = p["les"]["windows"]
    assert [k for k, x in w.items() if x["runs"]] == ["glider_eq/body"] and w["glider_eq/body"]["smoke"] and not w["glider_eq/body"]["reachable"]
    assert w["glider_eq/body"]["skip_reason"] is None and all(not x["smoke"] and x["skip_reason"] for k, x in w.items() if k != "glider_eq/body")
    assert p["shares"]["stage3"] == pytest.approx(budget.SHARE["stage3"] / 4)                                  # one of four parts keeps its slice
    s = budget.stage3_plan(p, CLASSES, a3())
    assert s["les_parts"] == 1 and s["slice_s"] == pytest.approx(budget.SHARE["stage3"] * 600 / 4) and s["runs"]   # = four parts' slice
    assert s["les"]["reachable"] is False and "sub-grid and refit stay uncalibrated" in s["les"]["note"]


def test_the_free_surface_cases_keep_the_share_they_fit_when_the_les_slices_go_to_stage_1(monkeypatch):
    monkeypatch.setenv("CAFE_NPROC", "6")
    p = budget.plan("overnight", 0, MISSION, thr={}, vehicle_classes=CLASSES)
    fs = budget.stage3_plan(p, CLASSES, a3())["fs"]
    assert fs["fit"] == 1 and p["shares"]["stage3"] * 36000 == pytest.approx(fs["need_s"])   # the case that fits keeps its seconds
    assert p["shares"]["stage1"] == pytest.approx(budget.SHARE["stage1"] + budget.SHARE["stage3"] - fs["need_s"] / 36000)
    assert budget.stage3_plan(p, CLASSES, a3())["les_parts"] == 0
    q = budget.plan("quick", 0, MISSION, thr={}, vehicle_classes=CLASSES)
    assert budget.stage3_plan(q, CLASSES, a3())["fs"]["fit"] == 0 and q["shares"]["stage3"] == 0.0     # nothing fits the quick share: all of it goes to stage 1
    no_usv = budget.plan("quick", 0, MISSION, thr={}, vehicle_classes=dict(g="glider"))
    assert no_usv["shares"]["stage3"] == 0.0 and no_usv["les"]["windows"]["g/body"]["runs"] is False


def test_no_free_surface_case_is_priced_when_the_fluidx3d_plugin_runs_it(monkeypatch):
    from cafe.pm.stage3 import fluidx3d
    monkeypatch.setattr(fluidx3d, "available", lambda cfg: (True, "plugin"))
    assert budget.fs_plan(CLASSES, 1, a3(), 360.0) is None
    assert budget.plan("quick", 0, MISSION, thr={}, vehicle_classes=CLASSES)["shares"]["stage3"] == 0.0     # nothing to hold: the whole share goes to stage 1


def test_the_planner_refuses_a_nest_over_85_percent_of_the_gpu_memory_and_says_what_to_reduce():
    p = budget.plan("overnight", 1, MISSION, thr={}, vehicle_classes=CLASSES, gpu_mem_gb=96.0)
    assert budget.stage3_plan(p, CLASSES, a3())["les"]["windows"] == p["les"]["windows"]          # fits: the plan goes through
    tiny = budget.plan("overnight", 1, MISSION, thr={}, vehicle_classes=CLASSES, gpu_mem_gb=0.5)
    with pytest.raises(PlanError, match=r"nest needs .* GB > 85% of 0.5 GB: coarsen each axis by"):
        budget.stage3_plan(tiny, CLASSES, a3())
    cpu = budget.plan("overnight", 0, MISSION, thr={}, vehicle_classes=CLASSES, gpu_mem_gb=0.5)     # no GPU: no memory to guard
    budget.stage3_plan(cpu, CLASSES, a3())


def test_les_need_is_the_box_at_the_dx_that_reaches_the_floor_run_for_the_shortest_acceptable_time():
    a = a3(nu_lat_floor=1e-4, box_bodies=[3.0, 1.0, 1.0], min_flow_throughs=2.0)
    n = budget.les_need(0.25, 2.0, "water", a)
    dx = 1.19e-6 * 0.04 / (0.25 * 1e-4)
    assert n["dx"] == pytest.approx(dx) and n["cells"] == math.ceil(6.0 / dx) * math.ceil(2.0 / dx) ** 2
    assert n["steps"] == math.ceil(2.0 * math.ceil(6.0 / dx) / 0.04) and n["cell_steps"] == pytest.approx(n["cells"] * n["steps"])
    assert budget.les_need(0.25, 2.0, "water", dict(a, nu_lat_floor=2e-4))["cell_steps"] == pytest.approx(16 * n["cell_steps"], rel=0.01)   # 2x floor: dx/2


def test_no_vehicles_is_a_valid_empty_plan():
    p = budget.plan("quick", 0, MISSION, thr={})
    assert p["member_cost"] == {} and p["n_max"] == budget.N_MAX["quick"]


def test_default_throughput_is_the_repo_file_and_a_missing_file_is_empty(tmp_path):
    assert budget.throughput(tmp_path / "none.json") == {}
    f = tmp_path / "t.json"
    f.write_text(json.dumps({"stage1": {}}))
    assert budget.throughput(f) == {"stage1": {}}
    day_and_a_half = dict(window=dict(start="2023-03-01T12:00:00Z", end="2023-03-03T00:00:00Z"))
    assert budget.plan("ci", 0, day_and_a_half, vehicle_classes=CLASSES)["budget_s"] == 600


def test_memory_guard_passes_a_fitting_nest_and_refuses_an_oversized_one_with_advice():
    assert budget.memory_guard(100e6, 55.0, 24.0) == pytest.approx(5.5)
    with pytest.raises(PlanError) as e:
        budget.memory_guard(1e9, 55.0, 24.0)                                   # 55 GB on a 24 GB device
    msg = str(e.value)
    f = (0.85 * 24.0 / 55.0) ** (1 / 3)
    assert "nest needs 55.0 GB > 85% of 24.0 GB" in msg and f"coarsen each axis by {1 / f:.2f}x" in msg
    # round 7 M-13: 55 B/cell is FluidX3D's FP16 layout, which the native nest cannot use; the advice names the figure the guard was given
    assert "halve the box" in msg and "the native nest needs 55 B/cell" in msg and "FP16" not in msg
    assert budget.memory_guard(0.85 * 24.0 * 1e9 / 55.0 * 0.9999, 55.0, 24.0) == pytest.approx(0.85 * 24.0, rel=1e-3)


def test_following_the_advice_makes_the_nest_fit():
    cells, bpc, mem = 1e9, 55.0, 24.0
    with pytest.raises(PlanError):
        budget.memory_guard(cells, bpc, mem)
    f = (0.85 * mem / (cells * bpc / 1e9)) ** (1 / 3)
    assert budget.memory_guard(cells * f ** 3 * 0.999, bpc, mem) < 0.85 * mem


def test_wall_estimate_and_describe():
    p = budget.plan("quick", 0, MISSION, thr=thr(20.0, 0.01), vehicle_classes=CLASSES)          # the CPU's skipped LES share is stage 1's: two batches fit
    w = budget.wall_estimate(p)
    assert p["n_max"] == 64 and p["batch"] == 32
    assert w["stage1"] == pytest.approx((2 * 3 * 20.0 + 64 * 3 * 0.01) * 6)                     # whole batches of environment calls + the per-member part
    assert w["stage3"] == pytest.approx(p["les"]["cell_steps_per_window"] * 1 * 3 / p["les"]["rate"])
    big = budget.plan("4h", GPU, MISSION, thr=thr(100.0, 0.05), vehicle_classes=CLASSES)
    assert budget.wall_estimate(big)["stage1"] == pytest.approx((3 * 3 * 100.0 + 192 * 3 * 0.05) * 6)
    assert budget.wall_estimate(big)["stage1"] <= budget.SHARE["stage1"] * budget.BUDGET_S["4h"]
    text = budget.describe(p)
    assert "budget quick (20 min), 0 GPU(s), 6.00 mission days" in text and "cannot certify" in text
    assert "stage 3: 1 window(s)/vehicle on native-jax-cpu" in text and "no LES coefficients exist on this machine" in text
    assert "glider_eq: 20 s/batch/day + 0.01 s/member/day, measured" in text
    assert "can certify" in budget.describe(budget.plan("overnight", 0, MISSION, thr=thr(0.01, 0.001), vehicle_classes=CLASSES))
    assert budget.wall_estimate(budget.plan("ci", 0, MISSION, thr={}))["stage1"] == 0.0


def test_emulator_share_adds_stage_1b_only_when_no_vehicle_was_refit():
    p = budget.plan("quick", 0, MISSION, thr={}, vehicle_classes=CLASSES)
    base = budget.emulator_share_s(p)
    assert base == pytest.approx(p["budget_s"] * p["shares"]["emulator"]) and base > 0
    assert budget.emulator_share_s(p, stage1b_free=True) == pytest.approx(p["budget_s"] * (p["shares"]["emulator"] + p["shares"]["stage1b"]))
    assert budget.emulator_share_s(p, True) > base


def test_batch_cost_is_per_environment_call_plus_per_member_for_the_named_vehicles_and_days():
    p = budget.plan("quick", 0, MISSION, thr=thr(20.0, 0.01), vehicle_classes=CLASSES)
    assert p["batch"] == 32
    per_vehicle = 20.0 + 32 * 0.01
    assert budget.batch_cost_s(p) == pytest.approx(3 * per_vehicle * 6)
    assert budget.batch_cost_s(p, vids=["glider_eq"]) == pytest.approx(per_vehicle * 6)
    assert budget.batch_cost_s(p, vids=["usv", "uas"], days=1.5) == pytest.approx(2 * per_vehicle * 1.5)
    assert budget.batch_cost_s(p, vids=[]) == 0.0


# ---------------------------------------------------------------------------------------------------------------- sizes that stage 3 and the emulator use

def a3(**over):
    """stage3 assumptions with the numbers the formulas below are checked against."""
    a = budget.stage3_assumptions()
    a.update(over)
    return a


def test_stage3_cell_steps_are_the_share_less_compile_and_fea_over_the_margin_at_the_plan_rate():
    p = budget.plan("quick", 1, MISSION, thr=thr(1.0, 0.01), vehicle_classes=CLASSES)            # quick: 1200 s, stage-3 share 360 s (GPU: no window skipped)
    a = a3(compile_s_guess=10.0, fea_reserve_frac=0.25, les_margin=1.5, min_window_s=6.0, fea_min_s=8.0)
    s = budget.stage3_plan(p, CLASSES, a)
    share = 0.30 * 1200.0
    parts = 1 + 2 + 1                                                                              # glider body, usv hull + wing, uas body (K = 1 each)
    assert s["share_s"] == pytest.approx(share) and s["les_parts"] == parts and s["slice_s"] == pytest.approx(share / parts)
    sl, rate = share / parts, p["les"]["rate"]
    assert s["cell_steps_per_part"]["glider"] == pytest.approx(rate * (sl - 0.25 * sl - 10.0) / 1.5)         # only the glider carries the FEA reserve
    assert s["cell_steps_per_part"]["usv"] == s["cell_steps_per_part"]["uas"] == pytest.approx(rate * (sl - 10.0) / 1.5)
    assert s["runs"] and s["fea"]["runs"] and s["fea"]["reserve_s"] == pytest.approx(0.25 * sl)
    assert s["fs"]["cases"] == 1 and s["fs"]["fit"] == int(min(1, share // s["fs"]["need_s"])) and s["fs"]["need_s"] == pytest.approx(
        s["fs"]["estimate"]["total_s"] * a["fs.margin"])
    # the answer is a function of the plan and the assumptions: the same twice, and a slower assumed compile only ever shrinks it
    assert budget.stage3_plan(p, CLASSES, a) == s
    slow = budget.stage3_plan(p, CLASSES, a3(compile_s_guess=20.0))
    assert all(slow["cell_steps_per_part"][c] < s["cell_steps_per_part"][c] for c in s["cell_steps_per_part"])


def test_stage3_plan_says_when_the_slice_is_too_small_to_run_and_when_the_fea_is_planned_out():
    p = budget.plan("ci", 0, MISSION, thr=thr(1.0, 0.01), vehicle_classes=CLASSES)               # 180 s over 4 parts: 45 s each
    assert budget.stage3_plan(p, CLASSES, a3(min_window_s=6.0))["runs"]
    small = budget.stage3_plan(p, CLASSES, a3(min_window_s=60.0))
    assert not small["runs"] and small["slice_s"] == pytest.approx(45.0)
    assert budget.stage3_plan(p, CLASSES, a3(fea_reserve_frac=0.25, fea_min_s=8.0))["fea"]["runs"]                  # 11.25 s of reserve
    assert not budget.stage3_plan(p, CLASSES, a3(fea_reserve_frac=0.25, fea_min_s=12.0))["fea"]["runs"]
    tiny = budget.stage3_plan(p, CLASSES, a3(compile_s_guess=1e6))                               # the compile alone spends the slice: zero cell-steps
    assert set(tiny["cell_steps_per_part"].values()) == {0.0}


def test_stage3_plan_counts_free_surface_cases_that_fit_the_share_in_queue_order(monkeypatch):
    monkeypatch.setenv("CAFE_NPROC", "6")
    a = a3()
    need = budget.stage3_plan(budget.plan("overnight", 0, MISSION, thr={}, vehicle_classes=CLASSES), CLASSES, a)["fs"]["need_s"]
    p = budget.plan("quick", 0, MISSION, thr={}, vehicle_classes=CLASSES)
    p["les"]["windows_per_vehicle"] = 3
    for share, fit in ((0.99 * need, 0), (1.01 * need, 1), (2.5 * need, 2), (10 * need, 3)):         # three USV windows queue behind each other
        p["shares"], p["budget_s"] = dict(p["shares"], stage3=1.0), share
        assert budget.stage3_plan(p, CLASSES, a)["fs"]["fit"] == fit and budget.stage3_plan(p, CLASSES, a)["fs"]["cases"] == 3
    assert budget.stage3_plan(p, dict(glider_eq="glider"), a)["fs"] is None                           # no USV, no free-surface case


def test_a_plan_without_a_wall_clock_budget_shares_the_cell_steps_between_the_parts_of_a_vehicle():
    p = dict(les=dict(cell_steps_per_window=8e6, windows_per_vehicle=1))
    s = budget.stage3_plan(p, dict(g="glider", u="usv"), a3())
    assert s["share_s"] is None and s["runs"] and s["fea"]["runs"] and s["cell_steps_per_part"] == dict(glider=8e6, usv=4e6)
    assert s["fs"]["fit"] == 1 and s["fs"]["share_s"] is None


def test_the_emulator_plan_is_variants_that_fit_the_train_fraction_of_the_share_at_the_planners_cost():
    p = budget.plan("quick", 0, MISSION, thr=thr(20.0, 0.01), vehicle_classes=CLASSES)
    e = budget.emulator_plan(p)
    est = budget.batch_cost_s(p)
    assert e["variant_s"] == pytest.approx(est) and "planner" in e["variant_s_source"] and e["train_fraction"] == budget.TRAIN_FRAC
    assert e["share_s"] == dict(refit=budget.emulator_share_s(p), no_refit=budget.emulator_share_s(p, True))
    assert e["variants_refit"] == min(budget.EMULATOR_VARIANTS["quick"], int(budget.TRAIN_FRAC * e["share_s"]["refit"] // est))
    assert e["variants_no_refit"] >= e["variants_refit"] and e["max_variants"] == budget.EMULATOR_VARIANTS["quick"]
    cheap = dict(p, member_cost={v: dict(c, s_per_batch_day=0.001, s_per_member_day=0.0) for v, c in p["member_cost"].items()})
    assert budget.emulator_plan(cheap)["variants_refit"] == budget.EMULATOR_VARIANTS["quick"]                  # capped by the budget name
    free = dict(p, member_cost={})
    assert budget.emulator_plan(free)["variants_refit"] == 0 == budget.emulator_plan(free)["variants_no_refit"]    # nothing to price: none


def test_stage3_assumptions_carry_the_assumed_refit_floors_from_the_yaml_only():
    a = budget.stage3_assumptions()
    assert a["refit.between_window_frac"] == 0.10 and a["refit.discretisation_frac"] == 0.05 and not hasattr(budget, "STAGE3_DEFAULTS")
    from cafe.pm.config import assumptions
    for k in ("stage3.refit.between_window_frac", "stage3.refit.discretisation_frac"):
        e = assumptions()[k]
        assert e["why"].startswith("ASSUMED") and e["replace_with"] and e["unit"] == "-"


def test_workers_cost_a_batch_its_longest_task_and_fit_more_batches_in_the_share():
    """With 8 workers a batch of the demo mission is its longest task (a whole glider; the UAS splits into its 6 sorties), so the quick share
    holds the full 64 members (both batches at once) where one worker fits one batch of 32; one worker plans exactly as before (the sum of the vehicles)."""
    m = config.load_mission(config.ROOT / "missions" / "tepex_c_demo.yaml")
    cls = stage1._classes(m)
    one = budget.plan("quick", 0, m, thr=thr(20.0, 0.01), vehicle_classes=cls, workers=1)
    eight = budget.plan("quick", 0, m, thr=thr(20.0, 0.01), vehicle_classes=cls, workers=8)
    v = (20.0 + 32 * 0.01) * 6                                              # one vehicle's batch of 32 over the 6 days
    assert budget.batch_cost_s(one) == pytest.approx(len(cls) * v) and one["n_max"] == 32 and one["workers"] == 1
    assert eight["tasks"] == {"glider_eq": 1, "glider_2n": 1, "usv": 1, "uas": 6}
    assert budget.batch_cost_s(eight) == pytest.approx(v) and budget.batch_cost_s(eight, ["uas"]) == pytest.approx(v / 6)
    assert eight["n_max"] == 64 and budget.batches_at_once(eight) == 2 and eight["stage1_s"] == pytest.approx(v)    # both batches in one wave


# ---------------------------------------------------------------------------------------------------------------- round 5: M-5, M-6, M-13

def demo(every_days=1, duration_min=20):
    """The demo mission with the UAS flying a sortie every `every_days` days of `duration_min` minutes, and its vehicle classes."""
    m = config.load_mission(config.ROOT / "missions" / "tepex_c_demo.yaml")
    so = next(v for v in m["vehicles"] if v["id"] == "uas")["sorties"]
    so.update(every_days=every_days, duration_min=duration_min)
    return m, stage1._classes(m)


def uas_cost(every_days=1, duration_min=20, **kw):
    m, c = demo(every_days, duration_min)
    p = budget.plan("quick", 0, m, vehicle_classes=c, workers=6, **kw)
    return p, p["member_cost"]["uas"]


def test_the_uas_cost_follows_the_sortie_minutes_the_mission_flies_and_the_demos_is_untouched():
    """M-5: 119 sorties in six days cost the same 4.62 s per batch-day as 6, and `--budget` was not held. The benchmark flew 6 x 20 = 120 sortie-minutes."""
    thr = budget.throughput()["stage1"]["uas"]
    base, mc = uas_cost()
    assert mc["s_per_batch_day"] == thr["s_per_batch_day"] and mc["s_per_member_day"] == thr["s_per_member_day"] and "sortie" not in mc["source"]
    many, mm = uas_cost(every_days=0.05)
    assert many["tasks"]["uas"] == 119 and mm["s_per_batch_day"] == pytest.approx(thr["s_per_batch_day"] * 119 / 6)
    assert mm["s_per_member_day"] == pytest.approx(thr["s_per_member_day"] * 119 / 6) and "x19.8 for 2380 sortie-minutes in 6 days" in mm["source"]
    long, ml = uas_cost(duration_min=120)
    assert long["tasks"]["uas"] == 6 and ml["s_per_batch_day"] == pytest.approx(thr["s_per_batch_day"] * 6)
    assert many["stage1_s"] > 1.3 * base["stage1_s"] and long["stage1_s"] > base["stage1_s"]                    # was 52.7 s in all three
    assert long["member_cost"]["glider_eq"] == base["member_cost"]["glider_eq"] and long["member_cost"]["usv"] == base["member_cost"]["usv"]


def test_the_sortie_scale_is_per_day_so_a_longer_window_of_the_same_sorties_is_not_scaled_twice():
    m, c = demo()
    m["window"]["end"] = "2023-03-13T12:00:00Z"                                                                  # 12 days of the benchmark's one sortie a day
    p = budget.plan("4h", 0, m, vehicle_classes=c, workers=6)
    assert p["days"] == 12.0 and p["member_cost"]["uas"]["s_per_batch_day"] == budget.throughput()["stage1"]["uas"]["s_per_batch_day"]


def test_a_mission_whose_sorties_alone_outrun_the_stage_1_share_is_refused_with_the_shortfall():
    m, c = demo(every_days=0.05, duration_min=120)                                       # 119 sorties of 2 h: 119 times the benchmark's UAS work
    ok, _ = demo()
    budget.plan("quick", 0, ok, vehicle_classes=c, workers=1)
    with pytest.raises(PlanError, match=r"stage 1 needs \d+ s for even one batch of 4 members .* short by \d+ s"):
        budget.plan("quick", 0, m, vehicle_classes=c, workers=1)


def test_the_benchmark_sortie_rate_is_stored_or_read_from_the_mission_it_names():
    assert budget.bench_sortie_rate(dict(sortie_min=120.0, mission_days=6.0)) == 20.0
    assert budget.bench_sortie_rate(budget.throughput()["stage1"]["uas"]) == 20.0                                # the stored file names the demo
    assert budget.bench_sortie_rate(dict(mission="missions/no_such.yaml", mission_days=6.0)) is None
    m, c = demo()
    t = {"stage1": {k: dict(v, mission="missions/no_such.yaml") for k, v in budget.throughput()["stage1"].items()}}
    assert any("not scaled by sortie-minutes" in n for n in budget.plan("quick", 0, m, thr=t, vehicle_classes=c, workers=6)["notes"])


def test_the_memory_caps_the_workers_and_the_plan_records_which_limit_set_them(monkeypatch):
    """M-6: 16 GB less the demo's 9 GB environment holds 7 workers of 0.9 GB, not 8; `describe` says memory capped them."""
    monkeypatch.delenv("CAFE_WORKERS")
    monkeypatch.setattr(par, "workers", lambda: 8)
    MISSION, CLASSES = demo()
    p = budget.plan("quick", 0, MISSION, vehicle_classes=CLASSES, mem_gb=16.0, env_gb=9.0)
    assert (p["workers_by_cpu"], p["workers_by_memory"], p["workers"]) == (8, 7, 7) and p["mem_gb"] == 16.0 and p["env_gb"] == 9.0
    assert "capped from 8 by memory (16 GB less 9 GB environment, 0.9 GB each)" in budget.describe(p)
    roomy = budget.plan("quick", 0, MISSION, vehicle_classes=CLASSES, mem_gb=28.0, env_gb=9.0)
    assert (roomy["workers_by_cpu"], roomy["workers_by_memory"], roomy["workers"]) == (8, 21, 8) and "capped" not in budget.describe(roomy)
    unknown = budget.plan("quick", 0, MISSION, vehicle_classes=CLASSES)
    assert (unknown["workers_by_cpu"], unknown["workers_by_memory"], unknown["workers"]) == (8, None, 8) and unknown["mem_gb"] is None
    assert budget.plan("quick", 0, MISSION, vehicle_classes=CLASSES, mem_gb=16.0)["env_gb"] == 9.0               # the default is 1.5 GB per window day


def test_an_explicit_worker_count_is_honoured_and_the_plan_prints_the_memory_it_needs(monkeypatch):
    monkeypatch.setenv("CAFE_WORKERS", "1")
    MISSION, CLASSES = demo()
    one = budget.plan("quick", 0, MISSION, vehicle_classes=CLASSES, mem_gb=16.0, env_gb=9.0)
    assert (one["workers_by_cpu"], one["workers_by_memory"], one["workers"]) == (1, 7, 1) and not [n for n in one["notes"] if "kernel" in n]
    plain = budget.plan("quick", 0, MISSION, vehicle_classes=CLASSES)
    assert {k: v for k, v in one.items() if k not in ("mem_gb", "env_gb", "workers_by_memory")} == {k: v for k, v in plain.items() if k not in
                                                                                                 ("mem_gb", "env_gb", "workers_by_memory")}
    eight = budget.plan("quick", 0, MISSION, vehicle_classes=CLASSES, mem_gb=16.0, env_gb=9.0, workers=8)
    assert eight["workers"] == 8 and any("8 worker(s) were asked for and need about 16 GB (9 GB environment + 0.9 GB each); 16 GB is available" in n
                                         for n in eight["notes"])


def test_a_window_whose_environment_leaves_no_room_for_one_worker_is_refused_naming_the_memory():
    m = dict(MISSION, window=dict(start="2023-03-01T12:00:00Z", end="2023-03-31T12:00:00Z"))                     # 30 days: 45 GB of environment
    with pytest.raises(PlanError, match=r"stage 1 needs about 45 GB for the environment of a 30-day window and 0.9 GB per worker, and 28 GB is available"):
        budget.plan("4h", 0, m, vehicle_classes=CLASSES, mem_gb=28.0)
    assert budget.plan("4h", 0, m, vehicle_classes=CLASSES, mem_gb=64.0)["workers_by_memory"] == 21
    with pytest.raises(PlanError, match="9 GB for the environment of a 6-day window"):
        budget.plan("quick", 0, MISSION, vehicle_classes=CLASSES, mem_gb=9.5)


def test_the_environment_is_1_5_gb_a_day_or_the_stores_on_disk_when_they_are_larger(tmp_path):
    m = dict(MISSION)
    assert budget.env_gb(m) == 9.0 and budget.env_gb(m, tmp_path / "nowhere") == 9.0
    (tmp_path / "derived.zarr" / "c").mkdir(parents=True)
    (tmp_path / "derived.zarr" / "c" / "0").write_bytes(b"x" * 1000)
    (tmp_path / "other").write_bytes(b"x" * 10 ** 6)                                                              # not a store
    assert budget.env_gb(m, tmp_path) == 9.0
    big = tmp_path / "big.zarr"
    big.mkdir()
    with open(big / "0", "wb") as f:
        f.truncate(12 * 10 ** 9)                                                                                  # a sparse 12 GB file
    assert budget.env_gb(m, tmp_path) == pytest.approx(12.0, abs=0.01)


def test_describe_and_plan_call_the_stage_1_time_a_lower_bound_and_say_what_it_leaves_out():
    m, c = demo()
    p = budget.plan("quick", GPU, m, thr=thr(1.0, 0.05), vehicle_classes=c, workers=4)
    assert p["stage1_s_basis"].startswith("critical path: the longest task or the work over the workers")
    assert "lower bound" in p["stage1_s_basis"] and "serial part" in p["stage1_s_basis"] and "start-up" in p["stage1_s_basis"]
    line = budget.describe(p).splitlines()[1]
    assert f"about {p['stage1_s']:.0f} s (a lower bound, not a schedule: plan.json stage1_s_basis) on 4 worker(s)" in line


def test_the_free_surface_price_follows_the_machines_cores(monkeypatch):
    """M-22: `fs_plan` priced 6 cores whatever the machine had."""
    monkeypatch.setenv("CAFE_NPROC", "x")
    monkeypatch.delenv("CAFE_NPROC")
    monkeypatch.setenv("CAFE_WORKERS", "1")
    one = budget.fs_plan(CLASSES, 1, a3(), 1e9)
    monkeypatch.setenv("CAFE_WORKERS", "16")
    six = budget.fs_plan(CLASSES, 1, a3(), 1e9)
    assert one["estimate"]["cores"] == 1 and six["estimate"]["cores"] == 6 and one["need_s"] > 2.0 * six["need_s"]
    monkeypatch.setenv("CAFE_NPROC", "4")
    assert budget.fs_plan(CLASSES, 1, a3(), 1e9)["estimate"]["cores"] == 4


def test_the_plan_charges_no_sitl_member_because_no_stage_flies_one():
    """Round 6 M-3: 4h printed 4 SITL members and overnight 8; stage 1 and the pipeline never call `fly_sitl`, so the number must be 0 until one does."""
    for name in budget.BUDGET_S:
        assert budget.plan(name, GPU, MISSION, thr=thr(0.01, 0.001), vehicle_classes=CLASSES)["sitl_members"] == 0
    import pathlib
    for f in ("stage1.py", "pipeline.py"):
        assert "fly_sitl" not in (pathlib.Path(budget.__file__).parent / f).read_text()          # a stage that flies SITL must make the count non-zero


DEMO_BOX = dict(MISSION, name="m", box=dict(lon_min=165.0, lon_max=-165.0, lat_min=-5.0, lat_max=5.0, pad_deg=2.0),
                 environment=dict(ocean=dict(source="gofs31")))


def test_the_environment_grows_with_the_area_of_the_padded_box_and_the_demo_stays_9_gb():
    """M-2: `env_gb` took only the window's days, so a box 90 times the demo's area was planned at the demo's 9.0 GB."""
    assert budget.padded_area_deg2(DEMO_BOX) == 14 * 34                                                          # 165 to -165 wraps: 30 deg + 2 x 2
    assert budget.env_gb(DEMO_BOX) == 9.0 and budget.env_model_gb(DEMO_BOX) == 9.0                               # the one measured point, to the digit
    big = dict(DEMO_BOX, box=dict(lon_min=-180.0, lon_max=179.9, lat_min=-60.0, lat_max=60.0, pad_deg=2.0))
    assert budget.env_gb(big) == pytest.approx(9.0 * 360 * 124 / (14 * 34), rel=1e-12) and budget.env_gb(big) > 80 * 9.0
    long = dict(DEMO_BOX, window=dict(start="2023-03-01T12:00:00Z", end="2023-03-13T12:00:00Z"))
    assert budget.env_gb(long) == pytest.approx(18.0)                                                            # linear in the days too
    with pytest.raises(PlanError, match="about 844 GB for the environment"):
        budget.plan("quick", 0, big, vehicle_classes=CLASSES, mem_gb=64.0)                                       # was planned at 9 GB and passed
    assert budget.plan("quick", 0, DEMO_BOX, vehicle_classes=CLASSES, mem_gb=28.0)["env_gb"] == 9.0


def test_every_zarr_store_below_the_cache_and_the_ocean_store_count_toward_the_floor(tmp_path, monkeypatch):
    """M-2: the disk floor summed `cache/*.zarr` only (derived.zarr, 218 MB); the big stores are cache/orca/*.zarr and DATA/ocean/gofs_<m>.zarr."""
    cache = tmp_path / "cache" / "m"
    (cache / "orca" / "wrf.zarr").mkdir(parents=True)
    with open(cache / "orca" / "wrf.zarr" / "0", "wb") as f:
        f.truncate(12 * 10 ** 9)                                                                                 # a sparse 12 GB file
    assert budget.env_gb(DEMO_BOX, cache) == pytest.approx(12.0, abs=0.01)                                       # 9.0 before: orca/ was not looked at
    from cafe.pm.env import ocean
    monkeypatch.setattr(ocean, "DATA", tmp_path)
    (tmp_path / "ocean" / "gofs_m.zarr").mkdir(parents=True)
    with open(tmp_path / "ocean" / "gofs_m.zarr" / "0", "wb") as f:
        f.truncate(5 * 10 ** 9)
    assert budget.env_gb(DEMO_BOX, cache) == pytest.approx(17.0, abs=0.01)                                       # the orca store plus the ocean store
    lab = dict(DEMO_BOX, environment=dict(ocean=dict(source="lab_hycom")))                                       # no path: validate's error, not a crash here
    assert budget.env_gb(lab, cache) == pytest.approx(12.0, abs=0.01)
    assert budget.env_gb({k: v for k, v in DEMO_BOX.items() if k != "environment"}, cache) == pytest.approx(12.0, abs=0.01)


def test_a_mission_without_a_box_is_planned_on_the_demos_box():
    assert budget.env_gb(MISSION) == 9.0 and budget.padded_area_deg2(MISSION) == 14 * 34


def test_r7_m1_planning_the_budget_does_not_replace_the_missions_verdict_cut_offs(monkeypatch):
    from cafe.pm.stats import intervals
    m, c = demo()
    for name in ("P_FAIL_GO", "P_FAIL_NOGO", "LO_SUCCESS_GO"):
        monkeypatch.setattr(intervals, name, getattr(intervals, name))
    intervals.set_thresholds(0.8, 0.5)                                                  # the user's mission: verdict {go: 0.8, nogo: 0.5}
    budget.plan("quick", 0, m, vehicle_classes=c, workers=6)
    assert (intervals.P_FAIL_GO, intervals.P_FAIL_NOGO) == (pytest.approx(0.2), 0.5)


def test_the_refusal_of_a_long_window_says_its_memory_figure_is_the_models_and_not_a_measurement():
    """Round 7 M-38: 45 GB for 30 days is a linear extrapolation of one 6-day point; the refusal read like a measurement."""
    m = dict(MISSION, window=dict(start="2023-03-01T12:00:00Z", end="2023-03-31T12:00:00Z"))
    with pytest.raises(PlanError) as e:
        budget.plan("4h", 0, m, vehicle_classes=CLASSES, mem_gb=28.0)
    assert "The 45 GB is the model's figure (linear from one measured 6-day point), not a measurement: " in str(e.value)
    assert "measure the peak memory of a longer window before relying on it" in str(e.value)


def test_the_worker_memory_comment_carries_no_date_it_cannot_have_and_names_what_is_missing():
    """Round 7 M-46: the comment dated the measurement 2026-11-05, after the commit that carries it; no script or output behind it is in the repository."""
    src = pathlib.Path(budget.__file__).read_text()
    i = src.index("WORKER_GB = 0.9")
    comment = src[src.rindex("\n\n", 0, i):i]
    assert "0.81 to 0.84 GB measured in round 5 by B's mem.py (the date is not recorded;" in comment and "not in the repository" in comment
    assert not re.search(r"\d{4}-\d{2}-\d{2}", comment)


def test_the_nest_cap_and_the_memory_guard_use_the_native_kernels_300_bytes_per_cell():
    """Round 7 M-13: the planner used FluidX3D's 55 B/cell, 5.5 x too lenient for the native nest (300 B/cell: 182 measured + masks + Bouzidi q)."""
    assert budget.LES_BYTES_PER_CELL == 300.0
    gpu = budget.plan("4h", 1, MISSION, thr={}, gpu_mem_gb=24.0, vehicle_classes=CLASSES)
    assert gpu["les"]["max_cells"] == int(0.85 * 24e9 / 300.0)
    with pytest.raises(PlanError, match="nest needs"):
        budget.memory_guard(gpu["les"]["max_cells"] * 1.01, budget.LES_BYTES_PER_CELL, 24.0)
    assert budget.memory_guard(gpu["les"]["max_cells"], budget.LES_BYTES_PER_CELL, 24.0) <= 0.85 * 24.0


def test_r8_l0_a_damaged_throughput_file_is_a_config_error_naming_it_not_a_traceback(tmp_path):
    """`throughput` was a bare json.loads: a truncated file raised JSONDecodeError and the valid JSON `[]` came back as a list where callers use a dict."""
    f = tmp_path / "t.json"
    for bad in ('{"stage1": {"uas":', "", "[]", "3"):
        f.write_text(bad)
        with pytest.raises(config.ConfigError, match=rf"{re.escape(str(f))}: not a JSON object .*make bench"):
            budget.throughput(f)
    f.write_text("{}")
    assert budget.throughput(f) == {}


# ---------------------------------------------------------------------------------------------------------------- round 9, batch A

@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), -5.0, 0.0])
@pytest.mark.parametrize("gpus", [0, 1])
def test_r9_m11_a_device_memory_that_is_not_a_positive_number_is_refused_whatever_the_gpu_count(bad, gpus):
    with pytest.raises(PlanError, match=r"--gpu-mem-gb .*: the device memory must be a positive number of GB"):
        budget.plan("quick", gpus, MISSION, thr={}, vehicle_classes=CLASSES, gpu_mem_gb=bad)
    assert budget.plan("quick", 1, MISSION, thr={}, vehicle_classes=CLASSES, gpu_mem_gb=0.001)["les"]["max_cells"] >= 0          # small is not zero


def test_r9_m9_the_bench_machine_is_compared_with_the_host_by_cpu_count_and_model():
    t = {"machine": dict(id="homebase", cpu="AMD EPYC 9V45", cpus=8, measured="2026-11-01")}
    same = dict(cpus=8, cpu="AMD EPYC 9V45")
    assert budget.machine_warning(t, same) is None and budget.machine_warning({}, same) is None            # no machine block: nothing to compare
    w = budget.machine_warning(t, dict(cpus=32, cpu="AMD EPYC 9V45"))
    assert w == ("throughput.json was measured on homebase (8 CPUs, AMD EPYC 9V45, 2026-11-01); here it is 32 CPUs, not 8. The stage-1 costs and LES rates "
                 "in the plan are that machine's: run `make bench` here to measure this one")
    assert "here it is CPU model Intel, not AMD EPYC 9V45." in budget.machine_warning(t, dict(cpus=8, cpu="Intel"))
    assert "here it is 32 CPUs, not 8; CPU model Intel, not AMD EPYC 9V45." in budget.machine_warning(t, dict(cpus=32, cpu="Intel"))
    assert budget.machine_warning(t, dict(cpus=8)) is None and budget.machine_warning(t, dict(cpus=8, cpu="")) is None      # a model the host does not give
    assert budget.machine_warning(t, dict(cpus=16)) is not None


@pytest.mark.parametrize("machine", [[1], "homebase", 8, 1.5, True, [], {}, None])
def test_r9_m9_a_machine_block_that_is_not_a_mapping_is_nothing_to_compare_and_not_a_traceback(machine):
    """A hand-edited throughput.json: `"machine": "homebase"` or a list reached `.get` and ended `plan` and `run` in an AttributeError."""
    assert budget.machine_warning({"machine": machine}, dict(cpus=8, cpu="Intel")) is None


@pytest.mark.parametrize("block", [dict(cpus="8"), dict(cpus=8.0), dict(cpus=True), dict(cpus=0), dict(cpus=[8]), dict(cpu=5), dict(cpu=["AMD"]),
                                   dict(cpus=None, cpu=None)])
def test_r9_m9_a_cpu_count_or_model_of_the_wrong_type_is_not_compared_and_not_printed_as_a_difference(block):
    """`{"cpus": "8"}` against a host of 8 CPUs used to say 'here it is 8 CPUs, not 8'."""
    assert budget.machine_warning({"machine": dict(id="homebase", **block)}, dict(cpus=8, cpu="Intel")) is None


def test_r9_m9_a_good_field_is_still_compared_beside_a_bad_one():
    w = budget.machine_warning({"machine": dict(id="homebase", cpus="eight", cpu="AMD")}, dict(cpus=8, cpu="Intel"))
    assert w is not None and "CPU model Intel, not AMD" in w and "CPUs, not" not in w


def test_r9_m9_the_warning_is_never_in_the_plan_so_the_same_seed_on_two_machines_plans_and_reports_alike():
    """The plan's notes and describe() are in plan.json and in report.json (`machine.notes`, `machine.describe`), which acceptance compares between runs of one
    seed; a machine-dependent sentence there would differ between burst and orca (DECISIONS 290)."""
    t = thr(0.01, 0.001)
    t["machine"] = dict(id="elsewhere", cpu="Nobody CPU", cpus=os_cpus() + 1, measured="2026-11-01")
    assert budget.machine_warning(t) is not None
    p = budget.plan("quick", 0, MISSION, thr=t, vehicle_classes=CLASSES)
    assert "throughput.json was measured" not in json.dumps(p) and "throughput.json was measured" not in budget.describe(p)
    assert budget.plan("quick", 0, MISSION, thr=t, vehicle_classes=CLASSES) == budget.plan("quick", 0, MISSION, thr=thr(0.01, 0.001), vehicle_classes=CLASSES)


def os_cpus():
    import os
    return os.cpu_count() or 1


def test_r9_m9_a_cpu_limited_container_on_the_benchmarked_box_is_not_warned(monkeypatch):
    """The bench records `os.cpu_count()` and the /proc/cpuinfo model; docker --cpus, the affinity mask and CAFE_WORKERS change `par.workers()` only."""
    t = {"machine": dict(id="here", cpu=budget.cpu_model(), cpus=os_cpus(), measured="2026-11-01")}
    assert budget.machine_warning(t) is None
    monkeypatch.setattr(par, "workers", lambda: 1)
    monkeypatch.setattr(par, "_cgroup_cpus", lambda root="": 1)
    monkeypatch.setenv("CAFE_WORKERS", "1")
    assert budget.machine_warning(t) is None


def test_r9_m9_the_cpu_model_is_the_first_model_name_of_proc_cpuinfo_else_the_processor(monkeypatch, tmp_path):
    info = tmp_path / "cpuinfo"
    info.write_text("processor\t: 0\nmodel name\t: Fancy CPU @ 3 GHz\nmodel name\t: second\n")
    monkeypatch.setattr(budget, "open", lambda f, *a, **k: open(info, *a, **k), raising=False)                  # the module's own `open`
    assert budget.cpu_model() == "Fancy CPU @ 3 GHz"
    info.write_text("processor\t: 0\n")                                                                          # an arm board names no model
    monkeypatch.setattr(budget.platform, "processor", lambda: "aarch64")
    assert budget.cpu_model() == "aarch64"
    monkeypatch.setattr(budget, "open", lambda f, *a, **k: open(tmp_path / "gone", *a, **k), raising=False)
    assert budget.cpu_model() == "aarch64"


def test_r9_m20_equal_box_longitudes_are_a_strip_with_no_width_in_the_budget_as_in_the_config():
    flat = dict(DEMO_BOX, box=dict(lon_min=-165.0, lon_max=-165.0, lat_min=-5.0, lat_max=5.0, pad_deg=2.0))
    assert budget.padded_area_deg2(flat) == 4 * 14                      # 0 + 2 x 2 deg wide, not the full circle it was read as


# ---------------------------------------------------------------------------------------------------------------- round 9, batch L1

def test_l1_the_machine_warning_compares_each_entry_with_its_own_cpus_and_model_not_only_the_machine_block():
    """The `machine` block is only what the last `stage1` bench wrote: a stage-1 bench on burst after the lbm and stage-1 entries of homebase left the block
    saying burst, and the warning on burst was None while the plan used homebase's rates."""
    burst = dict(cpus=4, cpu="AMD EPYC")
    t = {"machine": dict(id="burst", cpu="AMD EPYC", cpus=4, measured="2026-11-05"),
         "jax-lbm-d3q19-cpu": dict(host="homebase", cpus=8, cpu="AMD EPYC", measured="2026-10-28"),
         "openfoam-pimpleFoam-les": dict(host="6700c448c4f7", cpu="Intel Xeon", measured="2026-10-28"),
         "stage1": {"glider": dict(host="burst", cpus=4, measured="2026-11-05"), "usv": dict(host="homebase", cpus=8, measured="2026-11-01")}}
    w = budget.machine_warning(t, burst)
    assert w is not None and w.startswith("entries measured on another machine: ")
    assert "jax-lbm-d3q19-cpu (8 CPUs, AMD EPYC, 2026-10-28)" in w and "openfoam-pimpleFoam-les (? CPUs, Intel Xeon, 2026-10-28)" in w
    assert "stage1/usv (8 CPUs, ?, 2026-11-01)" in w and "glider" not in w and "here it is 4 CPUs, AMD EPYC. The stage-1 costs" in w
    assert budget.machine_warning(t, dict(cpus=8, cpu="AMD EPYC")) is not None                 # on homebase: the burst block and glider entry differ
    ok = {"machine": t["machine"], "stage1": {"glider": t["stage1"]["glider"]}, "jax-lbm-d3q19-cpu": dict(cpus=4, cpu="AMD EPYC")}
    assert budget.machine_warning(ok, burst) is None


def test_l1_an_entry_that_differs_as_the_machine_block_does_is_not_said_twice_and_a_bad_entry_is_not_compared():
    t = {"machine": dict(id="homebase", cpu="AMD", cpus=8, measured="2026-11-01"), "stage1": {"glider": dict(cpus=8), "usv": dict(cpus="eight")},
         "x": [1], "jax-lbm-d3q19-cpu": dict(cpus=8, cpu="AMD"), "y": dict(cpu=5, cpus=True)}
    w = budget.machine_warning(t, dict(cpus=4, cpu="AMD"))
    assert w == ("throughput.json was measured on homebase (8 CPUs, AMD, 2026-11-01); here it is 4 CPUs, not 8. The stage-1 costs and LES rates in the plan "
                 "are that machine's: run `make bench` here to measure this one")
    t["jax-lbm-d3q19-cpu"] = dict(cpus=16, cpu="AMD")
    assert "entries also measured on another machine: jax-lbm-d3q19-cpu (16 CPUs, AMD, ?)" in budget.machine_warning(t, dict(cpus=4, cpu="AMD"))
    assert budget.machine_warning({"stage1": "x", "machine": "y"}, dict(cpus=4, cpu="AMD")) is None
