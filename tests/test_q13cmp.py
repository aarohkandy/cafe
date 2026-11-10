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


def make(root, name, n_var, rows, killed=None, wall=1.0, cand=10):
    """A run directory with the files the comparison reads. `cand`: the UAS flip search's candidate count, which follows the code (DECISIONS 733); the
    `reason` text of a tried move quotes the rows of the training table, which follow the variants run (DECISIONS 754)."""
    run = root / name
    (run / "emulator").mkdir(parents=True)
    (run / "report").mkdir()
    (run / "emulator" / "design.json").write_text(json.dumps(dict(
        variants=[dict(variant=f"v{k}") for k in range(n_var)], planned_variants=6, killed=killed, rows_added=rows)))
    tried = [dict(change="launch the sorties 6 h later", p_fail=0.875, reason=f"{n_var + 1} uas/quad_uas/144h rows in the training table, 100 are needed")]
    (run / "emulator" / "flip.json").write_text(json.dumps(dict(vehicles=dict(uas=dict(candidates=cand, tried=tried)))))
    (run / "report" / "report.json").write_text(json.dumps(dict(
        run=name, emulator=dict(run_note=f"{n_var} variant runs"), vehicles=dict(uas=dict(fix=dict(candidates=cand, tried=tried))), seed=7,
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
    assert "[load-dependent] /rows_added" in out and "[load-dependent] /emulator/run_note" in out and "[load-dependent] /vehicles/uas/fix/tried/#/reason" in out
    assert "[load-dependent] /machine/timing/variants/runs" in out
    assert "/machine/timing/total   e.g." in out and "[load-dependent] /machine/timing/total" not in out        # a figure the count cannot move stays a mover
    assert "/run   e.g." in out and "[load-dependent] /run" not in out
    # not load-dependent: run, total; load-dependent: killed (2), variant, rows_added, run_note, runs, and the `reason` of a tried move (flip.json, report.json)
    assert "## total json leaves differing: 2 (and 8 load-dependent: the variant counts differ)" in out


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


def test_r14_q2_a_flip_candidate_count_that_differs_is_a_mover_and_only_reason_texts_follow_the_variants(tmp_path, capsys):
    """Round 14, P-R14Q2: q14 and q13la have 10 UAS flip candidates and q13 has 12 (DECISIONS 733: the same mission is listed once), whatever the number of
    variants run; the comparison tagged every `/fix/` node and every leaf of `emulator/flip.json` load-dependent when the counts differed, and hid it."""
    make(tmp_path, "slow", 5, 24, killed=dict(reason="killed: the stage share"), wall=2.0, cand=10)
    make(tmp_path, "fast", 6, 28, cand=12)
    out = run_main(tmp_path, capsys, "slow", "fast")
    assert "fast 6 of 6 run; COUNT DIFFERS" in out.splitlines()[0]
    assert "/vehicles/uas/fix/candidates   e.g." in out and "[load-dependent] /vehicles/uas/fix/candidates" not in out
    assert "/vehicles/uas/candidates   e.g." in out and "[load-dependent] /vehicles/uas/candidates" not in out                 # emulator/flip.json
    assert "[load-dependent] /vehicles/uas/tried/#/reason" in out and "[load-dependent] /vehicles/uas/fix/tried/#/reason" in out
    # movers: run, total, and the candidate count in flip.json and in report.json; load-dependent: killed (2), variant, rows_added, run_note, runs, 2 x reason
    assert "## total json leaves differing: 4 (and 8 load-dependent: the variant counts differ)" in out


@pytest.mark.parametrize("f, group, expect", [
    ("emulator/flip.json", "/vehicles/uas/candidates", False), ("emulator/flip.json", "/vehicles/uas/tried/#/change", False),
    ("emulator/flip.json", "/vehicles/uas/tried/#/p_fail", False), ("emulator/flip.json", "/vehicles/uas/tried/#/reason", True),
    ("report/report.json", "/vehicles/uas/fix/candidates", False), ("report/report.json", "/vehicles/uas/fix/tried/#/reason", True),
    ("report/report.json", "/vehicles/uas/fix/rows", True), ("report/report.json", "/vehicles/uas/fix/spent", True),
    ("emulator/design.json", "/anything", True), ("emulator/holdout.json", "/stale_rows", True), ("report/report.json", "/emulator/run_note", True),
    ("report/report.json", "/machine/timing/variants/runs", True), ("report/report.json", "/machine/timing/total", False)])
def test_r14_q2_only_the_figures_that_follow_the_variants_are_load_dependent(f, group, expect):
    assert q.load_dependent(f, group) is expect
