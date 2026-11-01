"""cafe.pm.budget: the plan adapts to the measured machine, shrinks when the measured member cost is high, and refuses oversized nests."""
import json
import math

import pytest
from hypothesis import given, settings, strategies as st

from cafe.pm import budget
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
    assert big["n_max"] == 512 and big["certify_possible"] and big["n_min"] == 73 and big["sitl_members"] == 8 and big["refit_iterations"] == 2


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


def test_the_shipped_stage_1_measurement_is_flagged_as_contended():
    notes = budget.plan("quick", 0, dict(MISSION, name="tepex_c_demo"), vehicle_classes=CLASSES)["notes"]
    assert any("measured at load" in n for n in notes)


def test_the_plan_says_when_the_emulator_cannot_train_at_this_budget():
    dear = budget.plan("quick", GPU, MISSION, thr=thr(26.0, 0.1), vehicle_classes=CLASSES)
    em = budget.emulator_plan(dear)
    assert not em["trains"] and em["variants_refit"] == em["variants_no_refit"] == 0 and em["note"] in dear["notes"]
    assert "cannot train at this budget" in em["note"] and "0 of 6 variants" in em["note"]
    cheap = budget.plan("quick", GPU, MISSION, thr=thr(0.01, 0.001), vehicle_classes=CLASSES)          # 6 variants + the base: 7 points of the 100
    ec = budget.emulator_plan(cheap)
    assert not ec["trains"] and ec["variants_no_refit"] == 6 and ec["points_per_class"] == dict(glider=7, uas=7, usv=7) and ec["note"] in cheap["notes"]
    assert "this budget gives 7 distinct points per vehicle class in one run" in ec["note"] and "100 are needed" in ec["note"]
    assert "will not train from this run alone" in ec["note"]


def test_a_long_budget_sizes_the_variants_to_reach_the_minimum_points_when_the_share_allows():
    assert budget.EMULATOR_MIN_POINTS == 100
    big = budget.plan("overnight", GPU, MISSION, thr=thr(0.01, 0.001), vehicle_classes=CLASSES)
    e = budget.emulator_plan(big)
    need = math.ceil(100 * budget.EMULATOR_POINTS_MARGIN) - 1                                # 1 vehicle per class: (variants + 1) points
    assert e["max_variants"] == need == 119 and e["variants_no_refit"] == 119 and e["trains"] and e["points_per_class"]["usv"] == 120
    assert not any("emulator" in n for n in big["notes"])
    two = budget.emulator_plan(dict(big, vehicle_classes=dict(g1="glider", g2="glider")))             # two vehicles per class: half as many variants
    assert two["max_variants"] == 59 and two["points_per_class"] == dict(glider=120)
    dear = budget.plan("overnight", GPU, MISSION, thr=thr(60.0, 0.1), vehicle_classes=CLASSES)          # a variant costs more than the share holds 119 of
    d = budget.emulator_plan(dear)
    assert 0 < d["variants_no_refit"] < 119 and not d["trains"] and d["note"] in dear["notes"]
    assert f"{d['variants_no_refit'] + 1} distinct points" in d["note"]
    assert budget.emulator_plan(dict(big, member_cost={}))["trains"] is False                         # nothing priced: no variants, one point


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
    assert gpu["les"]["max_cells"] == int(0.85 * 48e9 / 55.0)
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
    assert "halve the box" in msg and "FP16 storage (55 B/cell)" in msg
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
