"""bench/throughput.py `stage1()`: the per-class cost model written to config/throughput.json, run against a temporary copy of that file."""
import json
import pathlib
import shutil

import pytest

from bench import throughput
from cafe.pm import pipeline, stage1
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
    return out


def fake_batches(monkeypatch, wall):
    """run_batch replaced by one that reports `wall[(size, vehicle)]` seconds per vehicle; -> the sizes it was asked for."""
    asked = []

    def run_batch(mission, env, members, seed, pri, marg, scales=None):
        asked.append((len(members), seed))
        return {"vehicles": {vid: {"wall_s": wall[(len(members), vid)]} for vid in ("glider_eq", "glider_1n", "usv", "uas")}}
    monkeypatch.setattr(stage1, "run_batch", run_batch)
    return asked


def test_stage1_fits_a_plus_b_times_members_per_vehicle_and_keeps_the_costliest_of_a_class(bench, monkeypatch, capsys):
    wall = {(8, "glider_eq"): 10.0, (32, "glider_eq"): 34.0,                     # b = 1.0 s/member, a = 2.0 s
            (8, "glider_1n"): 20.0, (32, "glider_1n"): 20.0 + 24 * 0.5,          # b = 0.5, a = 16.0: dearer per batch, cheaper per member
            (8, "usv"): 6.0, (32, "usv"): 30.0,                                   # b = 1.0, a = -2 -> 0
            (8, "uas"): 40.0, (32, "uas"): 30.0}                                  # b < 0 -> 0, a = the 8-member time
    asked = fake_batches(monkeypatch, wall)
    throughput.stage1()
    days = 1.5
    out = json.loads(bench.read_text())["stage1"]
    assert asked == [(8, 20230301), (32, 20230301)] and set(out) == {"glider", "usv", "uas"}
    # each is the max over the class
    assert out["glider"]["s_per_batch_day"] == pytest.approx(16.0 / days) and out["glider"]["s_per_member_day"] == pytest.approx(1.0 / days)
    assert out["usv"]["s_per_batch_day"] == 0.0 and out["usv"]["s_per_member_day"] == pytest.approx(1.0 / days)
    assert out["uas"]["s_per_batch_day"] == pytest.approx(40.0 / days) and out["uas"]["s_per_member_day"] == 0.0
    assert json.loads(capsys.readouterr().out) == {"stage1": out}


def test_stage1_labels_every_class_entry_and_writes_the_machine_block(bench, monkeypatch, capsys):
    fake_batches(monkeypatch, {(s, v): float(s) for s in (8, 32) for v in ("glider_eq", "glider_1n", "usv", "uas")})
    throughput.stage1()
    data = json.loads(bench.read_text())
    for e in data["stage1"].values():
        assert e["sizes"] == [8, 32] and e["mission"] == "missions/ci_fixture.yaml" and e["note"].startswith("wall time of stage1.run_batch")
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
    throughput.stage1()
    after = json.loads(bench.read_text())
    assert set(after["stage1"]) == {"glider", "usv", "uas"} and after["openfoam-pimpleFoam-les"]["marker"] == "kept"
    assert {k: v for k, v in after.items() if k not in ("stage1", "machine")} == {k: v for k, v in before.items() if k not in ("stage1", "machine")}


def test_stage1_creates_the_file_when_there_is_none(bench, monkeypatch):
    bench.unlink()
    fake_batches(monkeypatch, {(s, v): 2.0 * s for s in (8, 32) for v in ("glider_eq", "glider_1n", "usv", "uas")})
    throughput.stage1(sizes=(8, 32))
    assert set(json.loads(bench.read_text())) == {"stage1", "machine"}


def test_stage1_without_getloadavg_records_no_load(bench, monkeypatch):
    monkeypatch.delattr(throughput.os, "getloadavg")
    fake_batches(monkeypatch, {(s, v): 1.0 for s in (8, 32) for v in ("glider_eq", "glider_1n", "usv", "uas")})
    throughput.stage1()
    assert all(e["load_1min"] is None for e in json.loads(bench.read_text())["stage1"].values())


def test_the_numbers_stage1_writes_are_the_ones_the_planner_reads(bench, monkeypatch):
    from cafe.pm import budget
    fake_batches(monkeypatch, {(8, "glider_eq"): 10.0, (32, "glider_eq"): 34.0, (8, "glider_1n"): 1.0, (32, "glider_1n"): 1.0,
                               (8, "usv"): 4.0, (32, "usv"): 4.0, (8, "uas"): 40.0, (32, "uas"): 40.0})
    throughput.stage1()
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
