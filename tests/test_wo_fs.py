"""Work order hull_fs measurement: the pure parts of review/workorder/fs_probe.py (a measurement script, loaded by path)."""
import importlib.util
import pathlib

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fs_probe", ROOT / "review/workorder/fs_probe.py")
assert spec is not None and spec.loader is not None
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_the_out_directory_must_be_a_probe_directory_of_the_runs_folder():
    probe.check_out(pathlib.Path("/data/runs/fs_probe_f4"))
    for bad in ("/data/runs/on1", "/tmp/fs_probe_x", "/data/runs/x/fs_probe_f4", "/data/runs"):
        with pytest.raises(SystemExit):
            probe.check_out(pathlib.Path(bad))


def test_block_means_and_the_last_two_blocks():
    s = np.concatenate([np.full(1000, 20.0), np.full(1000, 22.0)])
    assert probe.block_means(s, 250) == [20.0] * 4 + [22.0] * 4
    assert probe.block_means(np.arange(300.0), 250) == [124.5]                  # a 50-value tail is dropped, a 125-value one kept
    assert probe.block_means(np.arange(375.0), 250)[-1] == pytest.approx(312.0)
    b = probe.last_blocks(s, 1000)
    assert b["last"] == 22.0 and b["previous"] == 20.0 and b["drift"] == pytest.approx(2 / 22)
    assert probe.last_blocks(s[:1999], 1000)["drift"] is None


def test_settled_at_finds_the_first_multiple_of_250_where_the_rule_holds():
    n = np.arange(1, 4001)
    R = 24.0 + 40.0 * np.exp(-n / 400.0)                                         # decays to 24 N
    at = probe.settled_at(R, 0.5 * R, 0.5 * R)
    assert at is not None and 1000 < at <= 4000 and at % 250 == 0
    assert probe.settled_at(R[:1200], 0.5 * R[:1200], 0.5 * R[:1200]) is None   # still falling
    flat = np.full(2000, 24.0)
    assert probe.settled_at(flat, 0.5 * flat, 0.5 * flat) == 1000               # never before MIN_ITERS
    noisy = 24.0 * (1 + 0.1 * (np.arange(2000) % 2))                            # scatter 5 %
    assert probe.settled_at(noisy, 0.5 * noisy, 0.5 * noisy) is None


def test_courant_numbers_of_an_interfoam_log():
    log = ("Courant Number mean: 0.01 max: 0.5\nInterface Courant Number mean: 0 max: 0.2\nFlow time scale min/max = 0.01, 5\n"
           "Courant Number mean: 0.02 max: 0.4\nInterface Courant Number mean: 0 max: 0.3\nFlow time scale min/max = 0.02, 6\n")
    c = probe.courant(log)
    assert c["Courant Number"] == dict(mean_max=0.02, max_max=0.5, last_max=0.4)
    assert c["Interface Courant Number"]["max_max"] == 0.3
    assert c["flow time scale [s]"] == dict(min_min=0.01, max_max=6.0, last_min=0.02, last_max=6.0)
    assert probe.courant("nothing here") == {}


def test_a_history_is_read_once_per_iteration_and_summarized(tmp_path):
    d = tmp_path / "postProcessing/forces/00000000"
    d.mkdir(parents=True)
    rows = ["# Time total_x total_y total_z pressure_x pressure_y pressure_z viscous_x viscous_y viscous_z"]
    for i in list(range(1, 1001)) + list(range(1000, 1201)):                       # a restart repeats iteration 1000
        rows.append(f"{i} (-5 0 100) (-3 0 100) (-2 0 0)")
    (d / "force.dat").write_text("\n".join(rows) + "\n")
    (d / "moment.dat").write_text("\n".join(rows) + "\n")
    h = probe.history(tmp_path)
    assert len(h["it"]) == 1200 and h["it"][-1] == 1200
    assert h["total"][0] == 10.0 and h["fz"][0] == 200.0 and h["viscous"][0] == 4.0
    s = probe.summarize(h)
    assert s["resistance_tail20_mean_n"] == 10.0 and s["scatter_tail20"] == 0.0 and s["tail20_rows"] == 240
    assert s["block_means_n"] == [10.0] * 5 and s["settled_at_iteration"] == 1000
