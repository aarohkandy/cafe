"""review/round_13/q13cmp.py, the run-to-run comparison: it names the number of emulator variants each run ran and keeps the figures that move with that
number apart from the ones that cannot (round 13 look-ahead L2: a slower machine killed the variant loop one variant earlier, 190 leaves moved with no code
cause, and the comparison listed them as movers)."""
import importlib.util
import json
import pathlib

import pytest

SPEC = importlib.util.spec_from_file_location("q13cmp", pathlib.Path(__file__).parents[1] / "review" / "round_13" / "q13cmp.py")
q = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(q)


def make(root, name, n_var, rows, killed=None, wall=1.0):
    run = root / name
    (run / "emulator").mkdir(parents=True)
    (run / "report").mkdir()
    (run / "emulator" / "design.json").write_text(json.dumps(dict(
        variants=[dict(variant=f"v{k}") for k in range(n_var)], planned_variants=6, killed=killed, rows_added=rows)))
    (run / "report" / "report.json").write_text(json.dumps(dict(
        run=name, emulator=dict(run_note=f"{n_var} variant runs"), vehicles=dict(uas=dict(fix=dict(candidates=2 * n_var))), seed=7,
        machine=dict(timing=dict(variants=dict(runs=n_var), total=wall)))))
    return run


def run_main(tmp_path, capsys, a, b):
    q.main(a, b, root=tmp_path)
    return capsys.readouterr().out


def test_r13_l2_the_comparison_names_the_variant_counts_and_lists_what_follows_them_apart(tmp_path, capsys):
    kill = "killed: the variant runs spent the emulator stage's whole wall-clock share (240 s) before variant v5 of 6"
    make(tmp_path, "slow", 5, 24, killed=dict(reason=kill), wall=2.0)
    make(tmp_path, "fast", 6, 28)
    out = run_main(tmp_path, capsys, "slow", "fast")
    first = out.splitlines()[0]
    assert first.startswith("## variants run: slow 5 of 6 run (killed: the variant runs spent") and "fast 6 of 6 run; COUNT DIFFERS" in first
    assert "[load-dependent] /rows_added" in out and "[load-dependent] /emulator/run_note" in out and "[load-dependent] /vehicles/uas/fix/candidates" in out
    assert "[load-dependent] /machine/timing/variants/runs" in out
    assert "/machine/timing/total   e.g." in out and "[load-dependent] /machine/timing/total" not in out        # a figure the count cannot move stays a mover
    assert "/run   e.g." in out and "[load-dependent] /run" not in out
    # not load-dependent: run, total; load-dependent: killed (2), variant, rows_added, run_note, candidates, runs
    assert "## total json leaves differing: 2 (and 7 load-dependent: the variant counts differ)" in out


def test_r13_l2_runs_with_the_same_variant_count_list_every_leaf_as_before(tmp_path, capsys):
    make(tmp_path, "a", 6, 28)
    make(tmp_path, "b", 6, 30, wall=3.0)
    out = run_main(tmp_path, capsys, "a", "b")
    assert "same count" in out.splitlines()[0] and "load-dependent" not in out.split("\n", 1)[1]
    assert "## total json leaves differing: 3\n" in out + "\n"                                               # rows_added, total, run


@pytest.mark.parametrize("n", [0, 1])
def test_r13_l2_a_run_with_no_design_file_is_named_and_not_a_traceback(tmp_path, capsys, n):
    make(tmp_path, "a", 6, 28)
    (tmp_path / "b" / "report").mkdir(parents=True)
    if n:
        (tmp_path / "b" / "emulator").mkdir()
    assert q.variants_run(tmp_path / "b") is None
    line = q.variant_line("a", "b", q.variants_run(tmp_path / "a"), None)  # was "same count": its emulator figures are not comparable
    assert "b no emulator/design.json; COUNT DIFFERS" in line and "one run has no emulator/design.json" in line


def test_r13_merge_one_run_without_a_design_file_differs_and_two_without_one_do_not_and_a_killed_state_counts():
    six, five_killed = (6, 6, None), (5, 6, "killed: the stage share")
    assert q.counts_differ(None, six) and q.counts_differ(six, None) and not q.counts_differ(None, None)
    assert q.counts_differ(six, five_killed) and not q.counts_differ(six, (6, 6, None))
    assert q.counts_differ(six, (6, 6, "killed after the last variant"))                  # the same number, one of them killed
    assert "same count" in q.variant_line("a", "b", None, None)


def test_r13_merge_the_comparison_of_a_run_with_no_design_file_sets_the_emulator_leaves_apart_as_load_dependent(tmp_path, capsys):
    make(tmp_path, "old", 6, 28)
    (tmp_path / "old" / "emulator" / "design.json").unlink()
    make(tmp_path, "new", 5, 30)
    out = run_main(tmp_path, capsys, "old", "new")
    assert "old no emulator/design.json; new 5 of 6 run; COUNT DIFFERS" in out.splitlines()[0]
    assert "[load-dependent] /emulator/run_note" in out
