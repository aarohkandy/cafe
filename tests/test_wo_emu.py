"""Work order step 4, the emulator: (c) a resume under another `--emulator-table` reruns the emulator stage; (b) a UAS base row of the training table is
a 10 m profile row, as its variants' are; (a) `whatif` trains on the rows of the run's own code and honours the run's own gate. Each test failed on the
code of round 23 and passes with the change (review/workorder/handbacks/emu.md lists the jobs)."""
import json
import os
import pathlib

import pytest

from cafe.pm import __main__ as cli, pipeline, stage1, whatif
from cafe.pm.audit import STAGES
from tests.test_cli import wi, whatif_args  # noqa: F401  (wi is a fixture)
from tests.test_pipeline import (  # noqa: F401  (data, fake_stage1 and table are fixtures)
    GS, cheap_plan, data, fake_stage1, go, run_stage, seed_table, stub_stages, synthetic_ctx, table)
from tests.test_round16_report import data_dir  # noqa: F401  (autouse)
from tests.test_whatif import Env3D

pytestmark = pytest.mark.usefixtures("data", "emulator_speed_not_tested")


def test_c_a_resume_under_another_emulator_table_reruns_the_emulator_and_the_stages_after_it(tmp_path, monkeypatch):
    calls = []
    stub_stages(monkeypatch, calls)
    stub = pipeline.FUNCS["emulator"]

    def emulator(ctx, L):                                                          # what s_emulator records of its training table
        stub(ctx, L)
        L.input(ctx.path("emulator", "out.txt"), kind=pipeline.TABLE_INPUT, source=str(ctx.table))
    monkeypatch.setitem(pipeline.FUNCS, "emulator", emulator)
    run, after = tmp_path / "run", STAGES[STAGES.index("emulator"):]
    go(run, emulator_table=tmp_path / "a.parquet")
    assert calls == STAGES
    del calls[:]
    go(run, emulator_table=tmp_path / "a.parquet")
    assert calls == []                                                             # the same table: everything is up to date
    go(run, emulator_table=tmp_path / "b" / ".." / "b.parquet")
    assert calls == after                                                          # another table: the stage trains on a snapshot of it, so it runs again
    del calls[:]
    go(run, emulator_table=tmp_path / "x" / ".." / "b.parquet")
    assert calls == []                                                             # the same file under another spelling is the same table


def test_b_a_uas_base_row_is_made_in_the_10_m_profile_like_its_variants(tmp_path, table, fake_stage1, monkeypatch):  # noqa: F811
    env = Env3D()
    ctx = cheap_plan(synthetic_ctx(tmp_path, 48), 10.0)                           # no budget for variants: the rows of the run only
    ctx._env = env
    calls, real = [], stage1.run_batch

    def run_batch(mission, e, members, seed, pri, marg, scales=None):
        calls.append(([v["id"] for v in mission["vehicles"]], list(members), e.use_3d))
        b = real(mission, e, members, seed, pri, marg, scales)
        return dict(vehicles={v["id"]: b["vehicles"][v["id"]] for v in mission["vehicles"]})       # a solo mission has only its own vehicle
    monkeypatch.setattr(stage1, "run_batch", run_batch)
    d = run_stage(pipeline.s_emulator, ctx, "emulator")
    assert calls == [(["uas"], list(range(ctx.plan["batch"])), False)] and env.use_3d is True       # one UAS batch in the 10 m profile, the switch restored
    df = whatif.read_table(table)
    assert sorted(df["vehicle"]) == ["glider_2n", "glider_eq", "uas", "usv"] and set(df["variant"]) == {"base"}
    assert df[df["vehicle"] == "uas"].iloc[0]["n_members"] == ctx.plan["batch"] and df[df["vehicle"] == "usv"].iloc[0]["n_members"] == 48
    assert next(c for c in d["checks"] if c["name"] == "emulator_rows_appended")["ok"]


def digest_table(path, digest):
    whatif.write_table(whatif.read_table(path).assign(code_digest=digest), path)


def finished_emulator(run, **ledger):
    p = run / "checkpoints" / "emulator" / "ledger.json"
    p.write_text(json.dumps(dict(json.loads(p.read_text()), **ledger)))


def test_a_whatif_trains_on_the_rows_of_the_code_the_run_was_made_with(wi):  # noqa: F811
    path = wi.data / "emulator" / "train.parquet"
    seed_table(path, n=101)
    digest_table(path, "d" * 64)                                                  # rows of another checkout than this one
    assert pipeline.code_digest() != "d" * 64
    cli.main(whatif_args(wi, "--shift", "48h"))
    assert wi.seen["ems"][GS][0] is None and wi.seen["ems"][GS][1]["stale_rows"] == 101            # no run ledger of that code: as before
    finished_emulator(wi.run, code_digest="d" * 64)
    cli.main(whatif_args(wi, "--shift", "48h"))
    em, info = wi.seen["ems"][GS]
    assert em is not None and info["stale_rows"] == 0 and info["points"] >= whatif.MIN_ROWS
    finished_emulator(wi.run, ok=False)                                            # a failed emulator stage has no digest to take
    cli.main(whatif_args(wi, "--shift", "48h"))
    assert wi.seen["ems"][GS][0] is None


def test_a_whatif_keeps_the_scopes_the_run_did_not_use_in_stage_1_with_the_runs_reason(wi):  # noqa: F811
    seed_table(wi.data / "emulator" / "train.parquet", n=101)
    cli.main(whatif_args(wi, "--shift", "48h"))
    assert whatif.usable(wi.seen["ems"], GS) == (wi.seen["ems"][GS][0], None) and wi.seen["ems"][GS][0] is not None       # the table alone passes the gate
    why = f"the {GS} emulator missed BRIEF 2.7 acceptance (coverage), so Stage 1 answers"
    hold = wi.run / "emulator" / "holdout.json"
    hold.write_text(json.dumps(dict(glider_eq=dict(scope=GS, trained=True, used=False, unused_reason=why),
                                    glider_2n=dict(scope=GS, trained=True, used=False, unused_reason=why), uas=dict(scope="other", used=True))))
    cli.main(whatif_args(wi, "--shift", "48h"))
    assert whatif.usable(wi.seen["ems"], GS) == (None, why)                         # Stage 1 answers, with the run's own reason
    assert wi.seen["ems"][GS][1]["used"] is False and wi.seen["ems"][GS][1]["trained"] is True


def test_c_the_table_the_emulator_records_is_an_absolute_path(tmp_path, table, fake_stage1, monkeypatch):  # noqa: F811
    ctx = cheap_plan(synthetic_ctx(tmp_path, 48), 10.0)
    monkeypatch.chdir(tmp_path)
    ctx._table = pathlib.Path(os.path.relpath(table, tmp_path))                     # `--emulator-table` as a relative path
    d = run_stage(pipeline.s_emulator, ctx, "emulator")
    src = next(i["source"] for i in d["inputs"] if i.get("kind") == pipeline.TABLE_INPUT)
    assert src == str(table) and os.path.isabs(src)
    monkeypatch.chdir(tmp_path / "caf_data")                                        # a resume from another directory names the same table, relative to it
    ctx._table = pathlib.Path(os.path.relpath(table))
    assert str(ctx.table) != src and not pipeline._other_table(ctx, d)


def test_a_whatif_without_readable_run_files_answers_as_before(wi):  # noqa: F811
    seed_table(wi.data / "emulator" / "train.parquet", n=101)
    for text in ("[1, 2", json.dumps(dict(a=1, b="x"))):
        (wi.run / "emulator" / "holdout.json").write_text(text)
        cli.main(whatif_args(wi, "--shift", "48h"))
        assert wi.seen["ems"][GS][0] is not None                                    # no gate from a hold-out that cannot be read
    finished_emulator(wi.run, ok=True)
    (wi.run / "checkpoints" / "emulator" / "ledger.json").write_text("[1, 2")
    cli.main(whatif_args(wi, "--shift", "48h"))
    assert wi.seen["ems"][GS][0] is not None


def test_a_whatif_answers_with_its_own_fit_for_a_scope_the_run_did_not_train(wi):  # noqa: F811
    seed_table(wi.data / "emulator" / "train.parquet", n=101)
    (wi.run / "emulator" / "holdout.json").write_text(json.dumps(dict(glider_eq=dict(scope=GS, trained=False, used=False, unused_reason="few rows then"))))
    cli.main(whatif_args(wi, "--shift", "48h"))
    assert wi.seen["ems"][GS][0] is not None and wi.seen["ems"][GS][1].get("unused_reason") != "few rows then"
