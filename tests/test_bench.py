"""bench/throughput.py `stage1()`: the per-class cost model written to config/throughput.json, run against a temporary copy of that file."""
import json
import pathlib
import shutil

import pytest

from bench import throughput
from cafe.pm import par, pipeline, stage1
from cafe.pm.env import ocean as ocean_mod
from tests.fixtures.ci_env import make as ci_make

REAL = pathlib.Path(throughput.OUT)


@pytest.fixture
def bench(tmp_path, ci_env, monkeypatch):
    """stage1() pointed at a copy of throughput.json and at the session's synthetic tree (no new tree is generated, nothing outside tmp is written)."""
    out = tmp_path / "throughput.json"
    shutil.copy(REAL, out)
    monkeypatch.setattr(throughput, "OUT", out)
    monkeypatch.setattr("tempfile.mkdtemp", lambda prefix="": str(ci_env.data))
    monkeypatch.setattr(ci_make, "make", lambda d: None)
    monkeypatch.setenv("CAFE_DATA", str(ci_env.data))
    monkeypatch.setattr(pipeline, "DATA", ci_env.data)
    monkeypatch.setattr(ocean_mod, "DATA", ci_env.data)
    monkeypatch.setattr(throughput.os, "getloadavg", lambda: (0.5, 0.5, 0.5), raising=False)      # the box is shared: the quiet-machine guard is tested below
    return out


@pytest.fixture(autouse=True)
def memory_unknown(monkeypatch):
    """The bench plans the demo mission (a 9 GB environment) only to read its vehicle classes; a small container must not refuse that (M-6)."""
    monkeypatch.setattr(par, "memory_gb", lambda: None)


CI = "missions/ci_fixture.yaml"


def fake_batches(monkeypatch, wall):
    """run_batch replaced by one that reports `wall[(size, vehicle)]` seconds per vehicle; -> the sizes it was asked for."""
    asked = []

    def run_batch(mission, env, members, seed, pri, marg, scales=None):
        asked.append((len(members), seed))
        return {"vehicles": {vid: {"wall_s": wall[(len(members), vid)]} for vid in ("glider_eq", "glider_1n", "glider_2n", "usv", "uas")
                                      if (len(members), vid) in wall}}
    monkeypatch.setattr(stage1, "run_batch", run_batch)
    return asked


def test_stage1_fits_a_plus_b_times_members_per_vehicle_and_keeps_the_costliest_of_a_class(bench, monkeypatch, capsys):
    wall = {(8, "glider_eq"): 10.0, (32, "glider_eq"): 34.0,                     # b = 1.0 s/member, a = 2.0 s
            (8, "glider_1n"): 20.0, (32, "glider_1n"): 20.0 + 24 * 0.5,          # b = 0.5, a = 16.0: dearer per batch, cheaper per member
            (8, "usv"): 6.0, (32, "usv"): 30.0,                                   # b = 1.0, a = -2 -> 0
            (8, "uas"): 40.0, (32, "uas"): 30.0}                                  # b < 0 -> 0, a = the 8-member time
    asked = fake_batches(monkeypatch, wall)
    throughput.stage1(mission=CI)
    days = 1.5
    out = json.loads(bench.read_text())["stage1"]
    # the warm-up, then each size twice
    assert asked == [(2, 20230301), (8, 20230301), (32, 20230301), (8, 20230301), (32, 20230301)] and set(out) == {"glider", "usv", "uas"}
    # each is the max over the class
    assert out["glider"]["s_per_batch_day"] == pytest.approx(16.0 / days) and out["glider"]["s_per_member_day"] == pytest.approx(1.0 / days)
    assert out["usv"]["s_per_batch_day"] == 0.0 and out["usv"]["s_per_member_day"] == pytest.approx(1.0 / days)
    assert out["uas"]["s_per_batch_day"] == pytest.approx(40.0 / days) and out["uas"]["s_per_member_day"] == 0.0
    assert json.loads(capsys.readouterr().out) == {"stage1": out}


def timed_batches(monkeypatch, extra):
    """run_batch replaced by one whose glider costs 10 s + 0.5 s per member plus `extra[k]` on its k-th call (0 = the warm-up); -> the batch sizes asked."""
    n = []

    def run_batch(mission, env, members, seed, pri, marg, scales=None):
        k = len(n)
        n.append(len(members))
        return {"vehicles": {"glider_eq": {"wall_s": 10.0 + 0.5 * len(members) + extra.get(k, 0.0)}, "glider_1n": {"wall_s": 1.0}, "usv": {"wall_s": 1.0},
                             "uas": {"wall_s": 1.0}}}
    monkeypatch.setattr(stage1, "run_batch", run_batch)
    return n


def test_a_one_time_cost_on_the_first_call_is_not_folded_into_the_batch_cost(bench, monkeypatch):
    """Round 4 M-26: the batch of 8 was the first call in the process, so the JIT compile (10 s here) became the glider's per-batch cost; the warm-up
    batch takes it now."""
    n = timed_batches(monkeypatch, {0: 10.0})
    throughput.stage1(mission=CI)
    g = json.loads(bench.read_text())["stage1"]["glider"]
    assert n == [2, 8, 32, 8, 32] and g["s_per_batch_day"] == pytest.approx(10.0 / 1.5) and g["s_per_member_day"] == pytest.approx(0.5 / 1.5)  # a = 10, b = 0.5
    assert g["slope_resolved"] is True and "after a warm-up batch" in g["note"]


def test_the_faster_of_two_timings_of_a_size_is_kept(bench, monkeypatch):
    """A slow first timing of a size (a stall, a cold cache) is dropped: calls 1 (8 members) and 2 (32) are 30 s slow, their repeats are clean."""
    timed_batches(monkeypatch, {1: 30.0, 2: 30.0})
    throughput.stage1(mission=CI)
    g = json.loads(bench.read_text())["stage1"]["glider"]
    assert g["s_per_batch_day"] == pytest.approx(10.0 / 1.5) and g["s_per_member_day"] == pytest.approx(0.5 / 1.5)


def test_a_flat_pair_stores_a_zero_slope_and_says_it_was_not_resolved(bench, monkeypatch):
    """Round 4 M-26: a slope clipped to 0 used to look like a measurement; a batch of 32 that is not slower than 8 gives 0 with `slope_resolved: false`."""
    fake_batches(monkeypatch, {(s, v): 7.0 for s in (8, 32) for v in ("glider_eq", "glider_1n", "usv", "uas")})
    throughput.stage1(mission=CI)
    out = json.loads(bench.read_text())["stage1"]
    assert all(e["s_per_member_day"] == 0.0 and e["slope_resolved"] is False and e["s_per_batch_day"] == pytest.approx(7.0 / 1.5) for e in out.values())


def test_stage1_labels_every_class_entry_and_writes_the_machine_block(bench, monkeypatch, capsys):
    fake_batches(monkeypatch, {(s, v): float(s) for s in (8, 32) for v in ("glider_eq", "glider_1n", "usv", "uas")})
    throughput.stage1(mission=CI)
    data = json.loads(bench.read_text())
    for e in data["stage1"].values():
        assert e["sizes"] == [8, 32] and e["mission"] == CI and e["mission_name"] == "ci_fixture" and e["mission_days"] == 1.5
        assert e["load_1min_after"] == 0.5 and e["note"].startswith("wall time of stage1.run_batch")
        assert e["cpus"] == data["machine"]["cpus"]
        assert e["host"] == throughput.platform.node() and len(e["measured"]) == 10 and e["load_1min"] >= 0.0
    m = data["machine"]
    assert m["id"] == throughput.platform.node() and m["cpus"] >= 1 and m["cpu"] == throughput._cpu() and m["measured"] == data["stage1"]["glider"]["measured"]
    printed = json.loads(capsys.readouterr().out)
    assert printed == {"stage1": data["stage1"]}


def test_stage1_replaces_only_its_own_entries_in_the_file(bench, monkeypatch):
    before = json.loads(bench.read_text())
    before["openfoam-pimpleFoam-les"]["marker"] = "kept"
    before["stage1"] = {"old": {"s_per_batch_day": 1.0}}
    bench.write_text(json.dumps(before))
    fake_batches(monkeypatch, {(s, v): 1.0 for s in (8, 32) for v in ("glider_eq", "glider_1n", "usv", "uas")})
    throughput.stage1(mission=CI)
    after = json.loads(bench.read_text())
    assert set(after["stage1"]) == {"glider", "usv", "uas"} and after["openfoam-pimpleFoam-les"]["marker"] == "kept"
    assert {k: v for k, v in after.items() if k not in ("stage1", "machine")} == {k: v for k, v in before.items() if k not in ("stage1", "machine")}


def test_stage1_creates_the_file_when_there_is_none(bench, monkeypatch):
    bench.unlink()
    fake_batches(monkeypatch, {(s, v): 2.0 * s for s in (8, 32) for v in ("glider_eq", "glider_1n", "usv", "uas")})
    throughput.stage1(sizes=(8, 32), mission=CI)
    assert set(json.loads(bench.read_text())) == {"stage1", "machine"}


def test_stage1_without_getloadavg_records_no_load(bench, monkeypatch):
    monkeypatch.delattr(throughput.os, "getloadavg")
    fake_batches(monkeypatch, {(s, v): 1.0 for s in (8, 32) for v in ("glider_eq", "glider_1n", "usv", "uas")})
    throughput.stage1(mission=CI)
    assert all(e["load_1min"] is None for e in json.loads(bench.read_text())["stage1"].values())


def test_the_numbers_stage1_writes_are_the_ones_the_planner_reads(bench, monkeypatch):
    from cafe.pm import budget
    fake_batches(monkeypatch, {(8, "glider_eq"): 10.0, (32, "glider_eq"): 34.0, (8, "glider_1n"): 1.0, (32, "glider_1n"): 1.0,
                               (8, "usv"): 4.0, (32, "usv"): 4.0, (8, "uas"): 40.0, (32, "uas"): 40.0})
    throughput.stage1(mission=CI)
    thr = budget.throughput(bench)
    cost, source = budget.member_cost(thr, "glider")
    assert cost == pytest.approx((2.0 / 1.5, 1.0 / 1.5)) and source.startswith("measured (") and "load" in source


def test_cpu_name_falls_back_to_the_platform_without_proc_cpuinfo(monkeypatch):
    def refuse(*a, **k):
        raise OSError("no /proc")
    monkeypatch.setattr(throughput, "open", refuse, raising=False)
    assert throughput._cpu() == throughput.platform.processor()
    monkeypatch.setattr(throughput, "open", lambda *a, **k: iter(["vendor_id: x\n", "flags: y\n"]), raising=False)
    assert throughput._cpu() == throughput.platform.processor()
    monkeypatch.setattr(throughput, "open", lambda *a, **k: iter(["vendor_id: x\n", "model name\t: Example CPU 9000\n"]), raising=False)
    assert throughput._cpu() == "Example CPU 9000"


def test_save_merges_a_solver_entry_into_the_file(tmp_path, monkeypatch, capsys):
    out = tmp_path / "t.json"
    out.write_text(json.dumps({"a": 1}))
    monkeypatch.setattr(throughput, "OUT", out)
    throughput.save("b", {"x": 2})
    assert json.loads(out.read_text()) == {"a": 1, "b": {"x": 2}} and json.loads(capsys.readouterr().out) == {"b": {"x": 2}}
    out.unlink()
    throughput.save("c", {"y": 3})
    assert json.loads(out.read_text()) == {"c": {"y": 3}}


def test_stage1_refuses_to_write_a_rate_measured_on_a_busy_machine(bench, monkeypatch):
    asked = fake_batches(monkeypatch, {(s, v): 1.0 for s in (8, 32) for v in ("glider_eq", "glider_1n", "usv", "uas")})
    before = bench.read_text()
    monkeypatch.setattr(throughput.os, "getloadavg", lambda: (33.0, 30.0, 20.0))
    with pytest.raises(SystemExit, match=r"load 33\.0 on \d+ CPUs is above"):
        throughput.stage1(mission=CI)
    assert asked == [] and bench.read_text() == before


def test_stage1_defaults_to_the_demo_mission_and_needs_its_environment_cache(bench, monkeypatch, tmp_path):
    assert throughput.DEMO == "missions/tepex_c_demo.yaml"
    fake_batches(monkeypatch, {(s, v): 1.0 for s in (8, 32) for v in ("glider_eq", "glider_1n", "usv", "uas")})
    monkeypatch.setenv("CAFE_DATA", str(tmp_path / "nodata"))
    with pytest.raises(SystemExit, match="no environment cache at .*tepex_c_demo.*fetch"):
        throughput.stage1()


def test_stage1_on_the_demo_mission_records_it_and_its_days(bench, monkeypatch, tmp_path):
    data = tmp_path / "data"
    (data / "cache" / "tepex_c_demo").mkdir(parents=True)
    monkeypatch.setenv("CAFE_DATA", str(data))
    monkeypatch.setattr(pipeline, "DATA", data)
    monkeypatch.setattr(pipeline.Context, "env", None)                       # run_batch is faked: no environment is read
    fake_batches(monkeypatch, {(s, v): 6.0 * s for s in (8, 32) for v in ("glider_eq", "glider_2n", "usv", "uas")})
    throughput.stage1()
    e = json.loads(bench.read_text())["stage1"]["glider"]
    assert e["mission"] == "missions/tepex_c_demo.yaml" and e["mission_name"] == "tepex_c_demo" and e["mission_days"] == 6.0
    assert e["s_per_member_day"] == pytest.approx(1.0)


def test_stage1_stores_the_sortie_minutes_the_uas_batch_flew_so_the_planner_can_scale_its_cost(bench, monkeypatch):
    """Round 5 M-5: the CI fixture's quadrotor flies 20 min on each of two days; only the UAS entry carries `sortie_min`."""
    fake_batches(monkeypatch, {(s, v): float(s) for s in (8, 32) for v in ("glider_eq", "glider_1n", "usv", "uas")})
    throughput.stage1(mission=CI)
    out = json.loads(bench.read_text())["stage1"]
    assert out["uas"]["sortie_min"] == 40.0 and "sortie_min" not in out["glider"] and "sortie_min" not in out["usv"]
    from cafe.pm import budget
    assert budget.bench_sortie_rate(out["uas"]) == pytest.approx(40.0 / 1.5)
