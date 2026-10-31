"""cafe.pm.budget: the plan adapts to the measured machine, shrinks when the measured member cost is high, and refuses oversized nests."""
import json

import pytest

from cafe.pm import budget
from cafe.pm.budget import PlanError

MISSION = dict(window=dict(start="2023-03-01T12:00:00Z", end="2023-03-07T12:00:00Z"))          # 6 days
CLASSES = dict(glider_eq="glider", usv="usv", uas="uas")


def thr(batch=None, member=None, **extra):
    """A throughput.json with measured stage-1 costs per mission day: s per batch (environment calls) and s per member."""
    t = {}
    if batch is not None:
        t["stage1"] = {c: dict(s_per_batch_day=batch, s_per_member_day=member, measured="2026-10-29", host="az_serv", load_1min=19.5)
                       for c in ("glider", "usv", "uas")}
    t.update(extra)
    return t


def test_cheap_batches_get_the_full_ensemble_and_certify():
    p = budget.plan("quick", 0, MISSION, thr=thr(0.01, 0.001), vehicle_classes=CLASSES)
    assert p["n_max"] == budget.N_MAX["quick"] == 64 and p["n_min"] == 32 and p["certify_possible"] is False and p["notes"] == []
    big = budget.plan("overnight", 0, MISSION, thr=thr(0.01, 0.001), vehicle_classes=CLASSES)
    assert big["n_max"] == 512 and big["certify_possible"] and big["n_min"] == 73 and big["sitl_members"] == 8 and big["refit_iterations"] == 2


def test_a_high_measured_batch_cost_shrinks_the_ensemble_to_whole_batches_and_says_so():
    cheap = budget.plan("4h", 0, MISSION, thr=thr(1.0, 0.05), vehicle_classes=CLASSES)
    dear = budget.plan("4h", 0, MISSION, thr=thr(100.0, 0.05), vehicle_classes=CLASSES)
    assert cheap["n_max"] == 256 and dear["n_max"] < cheap["n_max"]
    per_batch, per_member = 3 * 100.0 * 6, 3 * 0.05 * 6                              # s per batch of environment calls, s per member (3 vehicles, 6 days)
    n_batches = int(budget.SHARE["stage1"] * budget.BUDGET_S["4h"] // (per_batch + budget.BATCH["4h"] * per_member))
    assert n_batches == 3 and dear["n_max"] == 3 * budget.BATCH["4h"] == 192 and dear["n_max"] % dear["batch"] == 0
    assert any("ensemble capped at 192 members" in n and "1800 s per batch of 64" in n and "0.90 s per member" in n for n in dear["notes"])
    quick = budget.plan("quick", 0, MISSION, thr=thr(20.0, 0.01), vehicle_classes=CLASSES)
    assert quick["n_max"] == quick["batch"] == 32 and quick["n_min"] == 32 and any("ensemble capped at 32 members" in n for n in quick["notes"])


def test_the_member_cost_matters_too_but_far_less_than_the_batch_cost():
    base = budget.plan("4h", 0, MISSION, thr=thr(100.0, 0.05), vehicle_classes=CLASSES)["n_max"]
    members_dear = budget.plan("4h", 0, MISSION, thr=thr(100.0, 3.0), vehicle_classes=CLASSES)["n_max"]
    batches_dear = budget.plan("4h", 0, MISSION, thr=thr(200.0, 0.05), vehicle_classes=CLASSES)["n_max"]
    assert batches_dear < base and members_dear < base


def test_the_ensemble_never_falls_below_one_batch_and_batch_never_exceeds_it():
    p = budget.plan("4h", 0, MISSION, thr=thr(1e6, 1e3), vehicle_classes=CLASSES)
    assert p["n_max"] == budget.BATCH["4h"] and p["batch"] == budget.BATCH["4h"] and p["n_min"] == p["n_max"]     # n_min is capped at what fits
    absurd = budget.plan("ci", 0, MISSION, thr=thr(1e4, 1e4), vehicle_classes=CLASSES)
    assert absurd["n_max"] == budget.BATCH["ci"] == 16 and absurd["n_min"] == min(budget.N_MIN["ci"], 16) and absurd["refit_iterations"] == 0


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
    r, backend, src = budget.lbm_rate({"xlb-jax-cpu": dict(per_device=3e6, measured="d", device="cpu")}, 0)
    assert (r, backend) == (3e6, "xlb-jax-cpu") and src.startswith("measured")
    r, _, src = budget.lbm_rate({"jax-lbm-d3q19-cpu": dict(per_device=2e6, measured="d")}, 0)
    assert r == 2e6 and "cpu" in src
    r, backend, src = budget.lbm_rate({}, 0)
    assert (r, backend) == (5e6, "xlb-jax-cpu") and "NOT MEASURED" in src
    r, backend, src = budget.lbm_rate({"xlb-warp-gpu": dict(per_device=1e10, measured="d", device="H100")}, 2)
    assert (r, backend) == (2e10, "xlb-warp") and "H100" in src
    r, _, src = budget.lbm_rate({}, 1)
    assert r == pytest.approx(0.95 * 20.8e9) and "projected" in src


def test_cpu_plan_is_labelled_as_the_fallback_and_gpu_plan_sizes_the_nest_cap():
    cpu = budget.plan("overnight", 0, MISSION, thr={}, vehicle_classes=CLASSES)
    assert cpu["les"]["cpu_fallback"] is True and cpu["les"]["label"].startswith("CPU fallback") and "max_cells" not in cpu["les"]
    gpu = budget.plan("4h", 1, MISSION, thr={}, gpu_mem_gb=48.0, vehicle_classes=CLASSES)
    assert gpu["les"]["cpu_fallback"] is False and gpu["les"]["label"] == "GPU LES windows" and gpu["les"]["gpu_mem_gb"] == 48.0
    assert gpu["les"]["max_cells"] == int(0.85 * 48e9 / 55.0)
    assert gpu["les"]["cell_steps_per_window"] > cpu["les"]["cell_steps_per_window"]
    assert "max_cells" not in budget.plan("4h", 1, MISSION, thr={}, vehicle_classes=CLASSES)["les"]


def test_no_vehicles_is_a_valid_empty_plan():
    p = budget.plan("quick", 0, MISSION, thr={})
    assert p["member_cost"] == {} and p["n_max"] == budget.N_MAX["quick"]


def test_default_throughput_is_the_repo_file_and_a_missing_file_is_empty(tmp_path):
    assert budget.throughput(tmp_path / "none.json") == {}
    f = tmp_path / "t.json"
    f.write_text(json.dumps({"stage1": {}}))
    assert budget.throughput(f) == {"stage1": {}}
    assert budget.plan("ci", 0, MISSION, vehicle_classes=CLASSES)["budget_s"] == 600


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
    p = budget.plan("quick", 0, MISSION, thr=thr(20.0, 0.01), vehicle_classes=CLASSES)
    w = budget.wall_estimate(p)
    assert p["n_max"] == p["batch"] == 32
    assert w["stage1"] == pytest.approx((1 * 3 * 20.0 + 32 * 3 * 0.01) * 6)                     # whole batches of environment calls + the per-member part
    assert w["stage3"] == pytest.approx(p["les"]["cell_steps_per_window"] * 1 * 3 / p["les"]["rate"])
    big = budget.plan("4h", 0, MISSION, thr=thr(100.0, 0.05), vehicle_classes=CLASSES)
    assert budget.wall_estimate(big)["stage1"] == pytest.approx((3 * 3 * 100.0 + 192 * 3 * 0.05) * 6)
    assert budget.wall_estimate(big)["stage1"] <= budget.SHARE["stage1"] * budget.BUDGET_S["4h"]
    text = budget.describe(p)
    assert "budget quick (20 min), 0 GPU(s), 6.00 mission days" in text and "cannot certify" in text
    assert "ensemble capped at 32 members" in text and "stage 3: 1 window(s)/vehicle on xlb-jax-cpu" in text
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
    p = budget.plan("quick", 0, MISSION, thr=thr(1.0, 0.01), vehicle_classes=CLASSES)            # quick: 1200 s, stage-3 share 360 s
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
