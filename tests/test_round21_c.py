"""Round 21, batch C: the command line and the app. One test (or a few) for each finding; each is to fail on the code of 7599881 and pass with the fix
(review/round_21/handbacks/batch_c.md lists the runs). M-8 the bound of a `plan.json` is the planner's own tables, so every plan the planner writes for every
budget name is read and nothing a hand edit can write is bigger than a plan can be; M-11 `ingest-ocean` asks for a half-deleted `.dead.tmp` before the write
that deletes it; M-12 a hangar result with a direction that has no GCI is a JSON the app can send (null, never NaN); M-5 (`hangar.grid_warning` only) the
warning reads its limit from `vv.GCI_TRUSTED`, a missing `gci` key is no index, and the sentence no longer says the verdicts lean MARGINAL."""
import json
import pathlib
import shutil

import numpy as np
import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from hypothesis import given, settings, strategies as st

from cafe import _site_data, app as capp, hangar
from cafe.pm import __main__ as cli, budget, vv
from cafe.pm.env import hycom
from tests.test_budget import CLASSES, MISSION, thr
from tests.test_cli import wi, whatif_args  # noqa: F401  (wi is a fixture)
from tests.test_round16_report import data_dir  # noqa: F401  (autouse)
from tests.test_round17_a import edit_json
from tests.test_round19_m import ingest, lab_mission  # noqa: F401  (ingest needs lab_mission's file)
from tests.test_round20_c import dead_dir

pytestmark = pytest.mark.usefixtures("emulator_speed_not_tested")
NAN, INF = float("nan"), float("inf")
NAMES = list(budget.BUDGET_S)


# ---- M-8: plan.json is bounded by the planner's own tables ------------------------------------------------------------------------------------------------

def planned(name, batch_day, member_day):
    """The plan the planner writes for `name` at those measured costs, as plan.json holds it (a JSON round trip)."""
    return json.loads(json.dumps(budget.plan(name, 0, MISSION, thr=thr(batch_day, member_day), vehicle_classes=CLASSES), default=str))


def sizes(name, **kw):
    """The largest plan the planner can write for `name`, with `kw` changed."""
    return dict(budget=name, batch=budget.BATCH[name], n_min=budget.N_MIN[name], n_max=budget.N_MAX[name]) | kw


@pytest.mark.parametrize("name", NAMES)
def test_m8_the_planners_largest_plan_for_each_budget_name_is_a_plan_the_planner_writes_and_is_accepted(name):
    """Cheap members give the table's own numbers (so the bound below is the edge of what exists, not a looser number), and a dear one a shrunk batch."""
    p = planned(name, 0.01, 0.001)
    assert (p["batch"], p["n_min"], p["n_max"]) == (budget.BATCH[name], min(budget.N_MIN[name], budget.N_MAX[name]), budget.N_MAX[name])
    cli._plan_sizes(p)
    cli._plan_sizes(sizes(name))
    cli._plan_sizes(sizes(name, batch=1, n_min=1, n_max=1))                                # the smallest plan: one member
    cli._plan_sizes(sizes(name, batch=2, n_min=1, n_max=2))


@settings(max_examples=60, deadline=None)
@given(st.sampled_from(NAMES), st.floats(0.0, 5e3), st.floats(0.0, 50.0))
def test_m8_every_plan_the_planner_can_write_for_any_budget_name_and_any_cost_is_accepted(name, batch_day, member_day):
    """Before and after: no plan the planner makes is refused (a table change that broke this fails here)."""
    try:
        p = planned(name, batch_day, member_day)
    except budget.PlanError:
        return
    cli._plan_sizes(p)
    assert 1 <= p["batch"] <= min(budget.BATCH[name], p["n_max"]) and 1 <= p["n_min"] <= p["n_max"] <= budget.N_MAX[name]


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("bad", [dict(batch=lambda n: budget.BATCH[n] + 1), dict(n_max=lambda n: budget.N_MAX[n] + 1),
                                 dict(n_min=lambda n: budget.N_MAX[n] + 1), dict(batch=lambda n: 3, n_min=lambda n: 1, n_max=lambda n: 2),
                                 dict(batch=lambda n: 0), dict(n_min=lambda n: 0), dict(batch=lambda n: -1), dict(n_max=lambda n: 0, n_min=lambda n: 0),
                                 dict(batch=lambda n: 10**6, n_max=lambda n: 10**6), dict(batch=lambda n: 10**400), dict(n_max=lambda n: 10**400),
                                 dict(batch=lambda n: True), dict(n_min=lambda n: 1.0), dict(n_max=lambda n: str(budget.N_MAX[n])), dict(batch=lambda n: None)],
                         ids=["batch above its table by 1", "n_max above its table by 1", "n_min above its table", "batch above n_max", "batch 0", "n_min 0",
                              "batch -1", "n_max 0", "10**6", "batch 10**400", "n_max 10**400", "bool", "float", "text", "null"])
def test_m8_a_size_a_plan_cannot_have_is_refused_for_every_budget_name_and_names_the_limits(name, bad):
    plan = sizes(name, **{k: f(name) for k, f in bad.items()})
    with pytest.raises(ValueError) as e:
        cli._plan_sizes(plan)
    text = str(e.value)
    assert text.startswith("plan.json has batch ") and f"for budget {name}" in text
    assert f"n_max at most {budget.N_MAX[name]}" in text and f"at most {budget.BATCH[name]} and not above n_max" in text


def test_m8_the_budget_name_is_still_read_first_and_a_bool_or_list_is_no_name():
    for name in (["quick"], None, 5, "nonesuch", True, {}):
        with pytest.raises(ValueError, match="plan.json has budget "):
            cli._plan_sizes(sizes("quick", budget=name))


@pytest.mark.parametrize("edit", [dict(batch=1000), dict(batch=1000, n_max=64), dict(n_max=65), dict(batch=33), dict(batch=10**6, n_min=1, n_max=10**6)],
                         ids=["batch 1000, n_max 64", "batch 1000", "n_max 65", "batch 33", "batch 10**6"])
def test_m8_a_what_if_on_a_plan_json_past_the_tables_is_the_damaged_file_message_and_runs_nothing(wi, capsys, edit):  # noqa: F811
    """D's case: `batch` 1000000 took a what-if to 26 GB in 100 s; C's: `batch` 1000 with `n_max` 64 was accepted. The fixture's plan is a real `quick` one."""
    edit_json(wi.run / "plan.json", lambda d: d.update(edit))
    assert cli.main(whatif_args(wi, "--shift", "6h")) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: ") and "damaged or incomplete (ValueError: plan.json has batch " in err and "Traceback" not in err
    assert "n_max at most 64" in err and "at most 32 and not above n_max" in err and "for budget quick" in err and "run it again (--fresh)" in err
    assert not wi.seen


def test_m8_the_plan_the_planner_wrote_into_the_run_is_read_untouched_and_so_is_its_table_edge(wi):  # noqa: F811
    assert cli.main(whatif_args(wi, "--shift", "6h")) == 0
    for name in NAMES:
        edit_json(wi.run / "plan.json", lambda d, name=name: d.update(sizes(name)))
        wi.seen.clear()
        assert cli.main(whatif_args(wi, "--shift", "6h")) == 0 and wi.seen["plan"]["budget"] == name
        assert (wi.seen["plan"]["batch"], wi.seen["plan"]["n_max"]) == (budget.BATCH[name], budget.N_MAX[name])


# What a hand edit of each field of plan.json can do. `batch`, `n_min`, `n_max` and `budget` are the only fields a what-if reads from the file (`_whatif` copies
# those three into the machine's own plan and uses the name); every other field is read for display by `report --run` (`budget.describe`, `report._machine`,
# `report._timing`, `report._stage3`) or by `acceptance` (`les`), as numbers that are printed or divided, never as a count of anything to build.
SIZE_FIELDS = {"batch", "n_min", "n_max"}
NAME_FIELD = {"budget"}
DISPLAY_FIELDS = {"budget_s", "gpus", "days", "stage1_s", "stage1_share_s", "workers", "workers_by_cpu", "workers_by_memory", "mem_gb", "env_gb",
                  "stage1_s_basis", "tasks", "sitl_members", "member_cost", "les", "refit_iterations", "notes", "certify_possible", "shares",
                  "vehicle_classes", "vehicle_scopes",
                  "seed_override", "refit_iterations_max", "stage3", "emulator"}                  # the last four: added by `pipeline.Context._make_plan`


@pytest.mark.parametrize("name", NAMES)
def test_m8_every_field_the_planner_writes_is_classified_so_a_new_one_has_to_be_looked_at(name):
    keys = set(planned(name, 0.01, 0.001))
    unclassified = sorted(keys - SIZE_FIELDS - NAME_FIELD - DISPLAY_FIELDS)
    assert not unclassified, f"a field of plan.json that no one has classified: {unclassified}"
    assert SIZE_FIELDS | NAME_FIELD <= keys


def test_m8_no_field_but_the_three_sizes_and_the_name_reaches_what_a_what_if_runs(wi):  # noqa: F811
    """Every other field set to 10**9 (or a list of them): the what-if still answers and runs on the machine's own plan, not the file's number."""
    mine = json.loads((wi.run / "plan.json").read_text())
    huge = {k: 10**9 for k in DISPLAY_FIELDS if k in mine and type(mine[k]) in (int, float)}
    assert {"budget_s", "days", "workers", "sitl_members", "refit_iterations"} <= set(huge)
    edit_json(wi.run / "plan.json", lambda d: d.update(huge))
    assert cli.main(whatif_args(wi, "--shift", "6h")) == 0
    assert all(wi.seen["plan"][k] != 10**9 for k in huge if k in wi.seen["plan"])
    assert {k: wi.seen["plan"][k] for k in SIZE_FIELDS} == {k: mine[k] for k in SIZE_FIELDS}


# ---- M-11: ingest-ocean asks for the half-deleted `.dead.tmp` before the write that deletes it ------------------------------------------------------------

def sweeping_write(monkeypatch, seen):
    """A stand-in for `ingest_lab_hycom` that does what `write_store` ends with (`for q in dead(out): rmtree(q)`), and a `dead_note` that records whether the
    `.dead.tmp` was there when the note was asked."""
    real_note = hycom.dead_note

    def write(path, box, out, *a):
        seen["at_write"] = bool(hycom.dead(out))
        for q in hycom.dead(out):
            shutil.rmtree(q, ignore_errors=True)
        return pathlib.Path(out)

    def note(path):
        seen.setdefault("at_note", []).append(bool(hycom.dead(path)))
        return real_note(path)
    monkeypatch.setattr(hycom, "ingest_lab_hycom", write)
    monkeypatch.setattr(hycom, "dead_note", note)


def test_m11_the_dead_tmp_is_named_while_it_is_there_and_the_note_says_this_ingest_deletes_it(monkeypatch, tmp_path, capsys):
    """Before: the note was asked after the write, which had deleted every `.dead.tmp`, so the command printed only 'ocean store: ...'."""
    out = tmp_path / "lab.zarr"
    out.mkdir()
    d = dead_dir(out, 1.5)
    seen: dict = {}
    sweeping_write(monkeypatch, seen)
    assert cli.main(["ingest-ocean", "--mission", lab_mission(tmp_path, out), "--path", "/lab/hycom"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert seen["at_note"] == [True] and seen["at_write"] is True and not d.exists()      # asked first, deleted by the write
    assert len(lines) == 2 and lines[1] == f"ocean store: {out}"
    assert lines[0].startswith("note: a half-deleted leftover of an earlier ingest that was killed while it deleted the old store is beside the store: ")
    assert f"{d} (1.5 GB)" in lines[0] and f"safe to delete (`rm -r {d}`)" in lines[0] and "nothing reads it" in lines[0]
    assert lines[0].endswith("the next ingest that writes the store deletes it too: this ingest does, once it has written the new store")


def test_m11_with_nothing_beside_the_store_no_note_is_printed_and_the_asides_note_still_follows_the_store_line(monkeypatch, tmp_path, capsys):
    out = tmp_path / "lab.zarr"
    out.mkdir()
    seen: dict = {}
    sweeping_write(monkeypatch, seen)
    assert cli.main(["ingest-ocean", "--mission", lab_mission(tmp_path, out), "--path", "/lab/hycom"]) == 0
    assert capsys.readouterr().out == f"ocean store: {out}\n" and seen["at_note"] == [False]
    aside = hycom._aside_name(out)
    aside.mkdir()
    dead_dir(out)
    assert cli.main(["ingest-ocean", "--mission", lab_mission(tmp_path, out), "--path", "/lab/hycom"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert [x.split(":")[0] for x in lines] == ["note", "ocean store", "note"] and "half-deleted" in lines[0] and f"still beside this one: {aside};" in lines[2]


def test_m11_a_store_whose_directory_does_not_exist_yet_has_nothing_beside_it_and_the_note_is_not_an_error(monkeypatch, tmp_path, capsys):
    """The note is asked before the write, which is what makes the store's parent: `dead` must not fail on a directory that is not there."""
    out = tmp_path / "new" / "lab.zarr"
    seen: dict = {}
    sweeping_write(monkeypatch, seen)
    assert cli.main(["ingest-ocean", "--mission", lab_mission(tmp_path, out), "--path", "/lab/hycom"]) == 0
    assert capsys.readouterr().out == f"ocean store: {out}\n" and seen["at_note"] == [False]


# ---- M-12: a hangar result with a direction that has no index is a JSON the app can send --------------------------------------------------------------------

def result_with(gci):
    dirs = {"+x": dict(force=[1.0, 0.0, 0.0], gci=gci), "+y": dict(force=[0.0, 1.0, 0.0], gci=0.05)}
    return dict(kind="uuv", hangar=dict(cfd=dict(rho=1025.0, speed=1.5, dirs=dirs),
                                        fs=dict(speeds={"1.0": dict(resistance=3.0, gci=gci)})))


@pytest.mark.parametrize("bad", [NAN, INF, -INF, np.float64("nan"), np.float32("nan"), np.float64("inf")],
                         ids=["nan", "inf", "-inf", "np nan", "np32 nan", "np inf"])
def test_m12_the_hangar_writes_a_direction_with_no_index_as_null_and_the_file_is_strict_json(tmp_path, bad):
    """Before: the bare token `NaN`, which `json.dumps` writes and no strict parser (the browser's, Starlette's) reads."""
    hangar._write_result(tmp_path, result_with(bad))
    text = (tmp_path / "result.json").read_text()
    assert "NaN" not in text and "Infinity" not in text
    back = json.loads(text, parse_constant=lambda c: pytest.fail(c))
    assert back["hangar"]["cfd"]["dirs"]["+x"]["gci"] is None and back["hangar"]["fs"]["speeds"]["1.0"]["gci"] is None
    assert back["hangar"]["cfd"]["dirs"]["+y"]["gci"] == 0.05                                  # a finite index is itself


def test_m12_an_array_with_a_nan_item_and_every_finite_result_are_written_as_they_were(tmp_path):
    res = dict(kind="uuv", warnings=["w"], a=np.array([1.0, NAN, 3.0]), n=np.int64(4), b=np.bool_(True), f=np.float32(0.5), t=(1, 2), s=np.float64(2.5))
    hangar._write_result(tmp_path, res)
    assert json.loads((tmp_path / "result.json").read_text()) == dict(kind="uuv", warnings=["w"], a=[1.0, None, 3.0], n=4, b=True, f=0.5, t=[1, 2], s=2.5)
    ok = dict(kind="usv", x=np.array([1.5, 2.5]), y=dict(z=[1, 2.5, None, "text"]))
    hangar._write_result(tmp_path, ok)
    assert (tmp_path / "result.json").read_text() == json.dumps(ok, default=hangar._j)         # byte for byte what the writer wrote before


def hangar_design(tmp_path, monkeypatch, text):
    monkeypatch.setattr(capp, "DESIGNS", tmp_path)
    d = tmp_path / "d1"
    d.mkdir()
    (d / "spec.json").write_text(json.dumps(dict(name="d1", kind="uuv")))
    (d / "status.json").write_text(json.dumps(dict(state="done", step="ready", progress=1.0)))
    (d / "result.json").write_text(text)
    return d


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_m12_the_design_endpoint_sends_a_stored_nan_as_null_with_the_status_200_body_the_encoder_accepts(tmp_path, monkeypatch, token):
    """The file as an older hangar wrote it (a bare token). Before: `get_design` returned the NaN and the response encoder raised ValueError."""
    text = '{"kind": "uuv", "hangar": {"cfd": {"dirs": {"+x": {"force": [1.0, 0.0, 0.0], "gci": %s}}}}}' % token
    hangar_design(tmp_path, monkeypatch, text)
    out = capp.get_design("d1")
    assert out["result"]["hangar"]["cfd"]["dirs"]["+x"]["gci"] is None
    body = JSONResponse(jsonable_encoder(out)).body                                           # what FastAPI does with the return value
    assert json.loads(body)["result"]["hangar"]["cfd"]["dirs"]["+x"]["gci"] is None


def test_m12_a_result_the_hangar_wrote_now_goes_through_the_endpoint_and_the_listing(tmp_path, monkeypatch):
    d = hangar_design(tmp_path, monkeypatch, "{}")
    hangar._write_result(d, dict(kind="uuv", estimates=dict(cruise=1.2, vmax=NAN), hangar=result_with(NAN)["hangar"]))
    out = capp.get_design("d1")
    assert out["result"]["hangar"]["cfd"]["dirs"]["+x"]["gci"] is None and out["result"]["hangar"]["cfd"]["dirs"]["+y"]["gci"] == 0.05
    JSONResponse(jsonable_encoder(out))
    assert capp.list_designs()[0]["vmax"] is None and capp.list_designs()[0]["errors"] is None            # the listing: a null, not "damaged"
    assert (d / "result.json").read_text().count("null") >= 3


def test_m12_the_files_the_app_reads_that_are_clean_read_as_they_were(tmp_path):
    p = tmp_path / "a.json"
    p.write_text('{"a": [1, 2.5, null, "NaN"], "b": {"c": true}}')
    assert capp._read(p) == {"a": [1, 2.5, None, "NaN"], "b": {"c": True}}                      # the STRING "NaN" is not the token
    assert capp._read(tmp_path / "nope.json", {}) == {} and capp._read(p.with_name("b.json")) is None
    p.write_text("{not json")
    assert capp._read(p, 7) == 7


def test_m12_hull_json_gets_null_for_a_direction_with_no_index_and_the_rounded_number_for_the_rest():
    """Before: `round(nan, 4)`, a NaN token in a file the site's JavaScript parses; a missing key was a KeyError."""
    t = _site_data.gci_table({"+x": dict(gci=0.020512), "+y": dict(gci=NAN), "+z": dict(gci=INF), "-x": {}, "-y": dict(gci=None), "-z": dict(gci="0.1"),
                              "x+y5": dict(gci=0), "x+y10": dict(gci=np.float64(0.1049999))})
    assert t == {"+x": 0.0205, "+y": None, "+z": None, "-x": None, "-y": None, "-z": None, "x+y5": 0.0, "x+y10": 0.105}
    assert "NaN" not in json.dumps(t, allow_nan=False)


# ---- M-5 (hangar.grid_warning): the limit is vv.GCI_TRUSTED, a missing key is no index, the sentence is the right way round ------------------------------

@pytest.fixture
def trusted(monkeypatch):
    """`vv.GCI_TRUSTED` is batch D's (the contract name); the value is the one `grid_warning` always had. Set here so that this file also passes on this
    branch alone (raising=False: the name is absent until the merge); after the merge it is set to its own value."""
    monkeypatch.setattr(vv, "GCI_TRUSTED", 0.3, raising=False)
    return 0.3


def cfd_result(*gcis):
    return dict(cfd=dict(dirs={f"d{i}": ({} if g is None else dict(gci=g)) for i, g in enumerate(gcis)}))


def test_m5_the_warning_reads_its_limit_from_the_one_constant_not_a_literal(trusted, monkeypatch):
    """Before: 0.3 was a literal in `grid_warning`, so a moved constant moved `drag_sigma` and not the sentence that says what `drag_sigma` did."""
    assert hangar.grid_warning(cfd_result(trusted)) is None and hangar.grid_warning(cfd_result(0.05, trusted)) is None             # at the limit: trusted
    assert "GCI up to 30%" in hangar.grid_warning(cfd_result(float(np.nextafter(trusted, 1.0))))                                  # just past it
    monkeypatch.setattr(vv, "GCI_TRUSTED", 0.5)
    assert hangar.grid_warning(cfd_result(0.4)) is None and hangar.grid_warning(cfd_result(0.5)) is None
    assert "GCI up to 51%" in hangar.grid_warning(cfd_result(0.51))
    monkeypatch.setattr(vv, "GCI_TRUSTED", 0.1)
    assert "GCI up to 20%" in hangar.grid_warning(cfd_result(0.05, 0.2))


@pytest.mark.parametrize("res", [cfd_result(None), cfd_result(0.05, None), cfd_result(None, 0.05), dict(fs=dict(speeds={"1.0": {}, "1.5": dict(gci=0.01)})),
                                 dict(cfd_aoa=dict(dirs={"x": {}}), fs=None)], ids=["only", "last", "first", "fs speed", "cfd_aoa"])
def test_m5_a_direction_with_no_gci_key_is_no_index_not_a_converged_grid(trusted, res):
    """Before: `r.get('gci', 0.0)` read a missing key as a perfect grid and printed nothing."""
    w = hangar.grid_warning(res)
    assert w and "a direction has no GCI at all" in w


@pytest.mark.parametrize("bad", [True, "0.1", [0.1], {}, -INF], ids=["bool", "text", "list", "dict", "-inf"])
def test_m5_a_gci_that_is_not_a_number_is_no_index_in_the_warning_as_it_is_in_the_readers(trusted, bad):
    assert "a direction has no GCI at all" in hangar.grid_warning(cfd_result(0.05, bad))


def test_m5_the_sentence_says_what_the_mission_does_and_no_longer_that_verdicts_lean_marginal(trusted):
    """A GCI of 1.5 gives a drag spread 5 to 10 times a no-index one, and most sampled drags below nominal: 'lean MARGINAL' was the other way round."""
    w = hangar.grid_warning(cfd_result(1.5))
    assert w.startswith("CFD grid study not converged: the coarse and fine meshes disagree (GCI up to 150%), "
                        "so the grid index cannot stand for the drag uncertainty: ")
    assert "the mission takes the spread of an estimate instead" in w and "not decided by the CFD" in w
    assert "lean MARGINAL" not in w and w.endswith("would narrow it")
    assert "GCI up to inf" not in hangar.grid_warning(cfd_result(NAN)) and "inf" not in hangar.grid_warning(cfd_result(INF))


def test_m5_nothing_to_say_for_no_study_or_a_converged_one(trusted):
    assert hangar.grid_warning({}) is None and hangar.grid_warning(dict(cfd=None, cfd_aoa=None, fs=None)) is None and hangar.grid_warning(cfd_result()) is None
    assert hangar.grid_warning(dict(cfd=cfd_result(0.0, 0.125)["cfd"], fs=dict(speeds={"1.0": dict(gci=0.0276)}))) is None
