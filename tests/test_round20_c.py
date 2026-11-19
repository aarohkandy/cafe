"""Round 20, batch C: the command line. One test (or a few) for each finding; each is to fail on the code of 8e22951 and pass with the fix
(review/round_20/handbacks/batch_c.md lists the runs). M-5 a `plan.json` with a size above 10**6 or a budget that is not a budget name is the "damaged or
incomplete" message, not a traceback, a what-if with no plan or a blame on `--budget`; M-6 the what-if line says "not distinguishable from the baseline" when
its interval holds the base P(fail), as the report's fix table does; M-8 (the `ingest-ocean` hunk) a half-deleted `.dead.tmp` beside the store is named with
its size."""
import pytest

from cafe.pm import __main__ as cli, budget, report, whatif
from cafe.pm.env import hycom
from tests.test_cli import wi, whatif_args  # noqa: F401  (wi is a fixture)
from tests.test_round16_report import data_dir  # noqa: F401  (autouse)
from tests.test_round17_a import edit_json
from tests.test_round19_m import ingest, lab_mission  # noqa: F401  (ingest needs lab_mission's file)

pytestmark = pytest.mark.usefixtures("emulator_speed_not_tested")


# ---- M-5: the sizes and the budget of a plan.json are checked where they are read -----------------------------------------------------------------------

@pytest.mark.parametrize("edit", [dict(batch=10**30), dict(n_max=10**30), dict(batch=10**6 + 1), dict(n_max=10**6 + 1, n_min=32),
                                  dict(budget=["quick"]), dict(budget=None), dict(budget=5), dict(budget="nonesuch"), dict(budget=True), dict(budget={})],
                         ids=["batch 1e30", "n_max 1e30", "batch 1e6+1", "n_max 1e6+1", "budget list", "budget null", "budget int", "budget unknown",
                              "budget bool", "budget object"])
def test_m5_a_plan_json_with_a_huge_size_or_no_budget_name_is_the_damaged_file_message_and_nothing_is_answered(wi, capsys, edit):  # noqa: F811
    """Before: an OverflowError, a what-if that started, a TypeError, a what-if with no plan, and a `--budget 5` blamed on a flag the user never gave."""
    edit_json(wi.run / "plan.json", lambda d: d.update(edit))
    assert cli.main(whatif_args(wi, "--shift", "6h")) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: ") and "damaged or incomplete (ValueError: plan.json has " in err and "Traceback" not in err
    assert "run it again (--fresh)" in err and "--budget" not in err and not wi.seen


def test_m5_the_size_message_keeps_its_words_and_names_the_bound_and_the_budget_message_the_names(wi, capsys):  # noqa: F811
    edit_json(wi.run / "plan.json", lambda d: d.update(batch=10**30))
    cli.main(whatif_args(wi, "--shift", "6h"))
    assert "plan.json has batch 1000000000000000000000000000000, n_min " in capsys.readouterr().err
    edit_json(wi.run / "plan.json", lambda d: d.update(batch=32, budget=5))
    cli.main(whatif_args(wi, "--shift", "6h"))
    assert f"plan.json has budget 5: one of {list(budget.BUDGET_S)} is needed" in capsys.readouterr().err


def test_m5_the_bounds_are_the_edge_not_below_it_and_every_budget_name_is_read(wi):  # noqa: F811
    """Round 21, M-8: the edge is the planner's table of that budget (it was 10**6, 2,000 times the largest plan: tests/test_round21_c.py), so the plan of each
    budget name is read as it was, with its own sizes, and one past its own table is refused."""
    assert max(budget.N_MAX.values()) < 10**6 and max(budget.BATCH.values()) < 10**6
    for name in budget.BUDGET_S:
        edit_json(wi.run / "plan.json",
                  lambda d, name=name: d.update(budget=name, batch=budget.BATCH[name], n_min=budget.N_MIN[name], n_max=budget.N_MAX[name]))
        wi.seen.clear()
        assert cli.main(whatif_args(wi, "--shift", "6h")) == 0 and wi.seen["plan"]["budget"] == name
        assert wi.seen["plan"]["n_max"] == budget.N_MAX[name] and wi.seen["plan"]["batch"] == budget.BATCH[name]
        edit_json(wi.run / "plan.json", lambda d, name=name: d.update(n_max=budget.N_MAX[name] + 1))
        assert cli.main(whatif_args(wi, "--shift", "6h")) == 2


def test_m5_a_sound_plan_whose_budget_differs_from_the_flag_is_still_the_flags_message(wi, capsys):  # noqa: F811
    """The plan is checked first, so the older mismatch message is reached only by a plan that is sound."""
    edit_json(wi.run / "plan.json", lambda d: d.update(budget="ci", batch=16, n_min=8, n_max=16))        # sound for ci (round 21: sizes within its tables)
    assert cli.main(whatif_args(wi, "--shift", "6h", "--budget", "quick")) == 2
    err = capsys.readouterr().err
    assert "--budget quick: the run" in err and "was made with --budget ci" in err and "damaged" not in err


# ---- M-6: the what-if line carries the report's flag for a candidate that is not distinguishable from the baseline --------------------------------------

def rows(monkeypatch, **vehicles):
    monkeypatch.setattr(whatif, "answer", lambda *a, **k: dict(vehicles=vehicles, dropped=[], links_removed=[]))


def row(base, p, lo, hi, method="Stage 1"):
    return dict(base=dict(verdict="MARGINAL", p_fail=base), method=method, why="x", p_fail=p, lo=lo, hi=hi, verdict="MARGINAL", n=32, distance=0.5,
                threshold=1.0)


def test_m6_a_candidate_whose_interval_holds_the_base_says_so_and_one_whose_interval_excludes_it_does_not(wi, capsys, monkeypatch):  # noqa: F811
    """C-5's case: a 36 s shift printed 0.234 -> 0.203 (0.133 to 0.297), which reads as a change."""
    rows(monkeypatch, holds=row(0.234, 0.203, 0.133, 0.297), above=row(0.234, 0.5, 0.4, 0.6), below=row(0.234, 0.05, 0.01, 0.1),
         emulated=row(0.234, 0.2, 0.1, 0.3, "EMULATED"), lo_edge=row(0.2, 0.3, 0.2, 0.4), hi_edge=row(0.4, 0.3, 0.2, 0.4))
    assert cli.main(whatif_args(wi, "--shift", "0.01h")) == 0
    out = {line.split(":")[0]: line for line in capsys.readouterr().out.splitlines() if "(P(fail)" in line}
    said = f"; {report.SAME_AS_BASELINE}"
    assert said.endswith("not distinguishable from the baseline (its interval contains the baseline's P(fail))")
    assert out["holds"].endswith("  [Stage 1, n = 32 (x)]" + said) and out["emulated"].endswith("limit 1.00]" + said)
    assert out["lo_edge"].endswith(said) and out["hi_edge"].endswith(said)                    # the interval's ends hold the base, as `report._fix` says
    assert not out["above"].endswith(said) and not out["below"].endswith(said) and "not distinguishable" not in out["above"] + out["below"]


def test_m6_a_vehicle_with_no_interval_gets_no_words(wi, capsys, monkeypatch):  # noqa: F811
    rows(monkeypatch, glider_eq=dict(base=dict(verdict="GO", p_fail=0.0), method="unchanged", p_fail=0.0, verdict="GO"))
    cli.main(whatif_args(wi, "--shift", "6h"))
    assert "not distinguishable" not in capsys.readouterr().out


# ---- M-8 (the ingest-ocean hunk): a half-deleted `.dead.tmp` beside the store is named with its size --------------------------------------------------

def dead_dir(out, gb=0.0):
    """The `.dead.tmp` name `write_store` gives an aside it is deleting, with a (sparse) file of `gb` GB in it."""
    d = hycom._aside_name(out).with_name(hycom._aside_name(out).name.replace(".old.tmp", ".dead.tmp"))
    d.mkdir()
    with open(d / "chunk", "wb") as f:
        f.truncate(int(gb * 1e9))
    return d


def test_m8_ingest_ocean_names_a_half_deleted_dead_tmp_beside_the_store_with_its_size(monkeypatch, tmp_path, capsys):
    out = tmp_path / "lab.zarr"
    out.mkdir()
    d = dead_dir(out, 2.5)
    text = ingest(monkeypatch, tmp_path, capsys)
    assert text.endswith(f"ocean store: {out}\n")                         # round 21, M-11: the note is asked, and printed, before the write
    assert (f"note: a half-deleted leftover of an earlier ingest that was killed while it deleted the old store is beside the store: {d} (2.5 GB): "
            in text)                                                       # `hycom.dead_note`'s wording, the one the pipeline's check says too (round 20, M2)
    assert f"safe to delete (`rm -r {d}`)" in text and "nothing reads it" in text and "still beside this one" not in text      # no whole aside: only this line


def test_m8_ingest_ocean_names_a_whole_aside_and_a_dead_one_each_in_its_own_line_and_nothing_for_another_stores(monkeypatch, tmp_path, capsys):
    out = tmp_path / "lab.zarr"
    out.mkdir()
    aside = hycom._aside_name(out)
    aside.mkdir()
    d = dead_dir(out)
    other = tmp_path / "other.zarr"
    other.mkdir()
    hycom._aside_name(other).mkdir()
    dead_dir(other)
    lines = ingest(monkeypatch, tmp_path, capsys).splitlines()
    assert len(lines) == 3 and f"beside the store: {d} (0.0 GB):" in lines[0] and lines[1] == f"ocean store: {out}"
    assert f"is still beside this one: {aside};" in lines[2]


def test_m8_ingest_ocean_says_only_the_store_when_nothing_is_beside_it(monkeypatch, tmp_path, capsys):
    out = tmp_path / "lab.zarr"
    out.mkdir()
    (tmp_path / "other.zarr").mkdir()
    dead_dir(tmp_path / "other.zarr")
    assert ingest(monkeypatch, tmp_path, capsys) == f"ocean store: {out}\n"
