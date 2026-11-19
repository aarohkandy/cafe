"""Round 20 merge step: the findings of the merge that no batch owned (review/round_20/handbacks and the lead's brief for the merge).

M2: `ingest-ocean` says a half-deleted `.dead.tmp` in `hycom.dead_note`'s words, the one wording (the pipeline's check says the same). M3: a NaN `gci`, which
`cfd.gci` writes where it has no index and which `cafe/_seed.py` rightly accepts, reads as untrusted (inf) in every reader, wherever it stands in the list
(Python's `max` with a NaN answers by the order, so a result with no index could read as a converged grid or give every member a NaN drag). M5: an absurd
modification time is "unknown date" in the advice of `hycom.leftover_note`, not an exception. M6: a P(fail) or a band that is not a probability, which
batch F made a ValueError in `stats.intervals` (it used to print NO-GO), reaches the command line as the message of a damaged emulator, and a count above
2**53 in a summary is the refusal of `credibility.check_counts`, not that ValueError. Each test fails on the tree at a3ac533 (the six batches merged) and
passes with the fix."""
import json
import pathlib
import types

import numpy as np
import pytest

from cafe import cfd, geom, hangar, mission, vehicle
from cafe.pm import __main__ as cli, config, credibility as cr, emulator as em_mod, report, vv
from cafe.pm.env import hycom
from tests.fixtures import pm_run
from tests.test_cli import wi, whatif_args  # noqa: F401  (wi is a fixture)
from tests.test_report import data_dir, set_link_fields  # noqa: F401  (data_dir is autouse)
from tests.test_round19_m import ingest, lab_mission  # noqa: F401  (ingest needs lab_mission's file)
from tests.test_round20_c import dead_dir

NAN, INF = float("nan"), float("inf")
REAL = pathlib.Path(__file__).parent / "fixtures" / "cfd_real"


# ---------------------------------------------------------------------------------------------------------------------------------------------------- M2

def test_m2_ingest_ocean_prints_the_wording_of_hycom_dead_note_and_no_other(monkeypatch, tmp_path, capsys):
    """Batch C wrote its own sentence for the same fact batch E's `dead_note` says for `pipeline._need`: now there is one."""
    out = tmp_path / "lab.zarr"
    out.mkdir()
    dead_dir(out, 0.5)
    lines = ingest(monkeypatch, tmp_path, capsys).splitlines()
    assert lines == ["note:" + hycom.dead_note(out)[1:] + ": this ingest does, once it has written the new store", f"ocean store: {out}"]     # round 21, M-11
    assert "safe to delete by hand" not in lines[0] and "`.dead.tmp` is beside the store" not in lines[0]            # batch C's own words are gone


# ---------------------------------------------------------------------------------------------------------------------------------------------------- M3

@pytest.mark.parametrize("bad", [NAN, INF, -INF, None, "0.1", True, [0.1], {}], ids=["nan", "inf", "-inf", "none", "text", "bool", "list", "dict"])
def test_m3_a_gci_that_is_not_a_finite_number_is_inf(bad):
    assert vv.gci_value(bad) == INF


@pytest.mark.parametrize("good", [0, 0.0, 3, 0.05, 1.5, np.float64(0.2)])
def test_m3_a_finite_gci_is_itself_as_a_float(good):
    assert vv.gci_value(good) == float(good) and type(vv.gci_value(good)) is float


@pytest.mark.parametrize("order", [(NAN, 0.05, 0.02), (0.05, NAN, 0.02), (0.05, 0.02, NAN), (NAN, NAN), (None, 0.1)])
def test_m3_the_worst_gci_is_inf_wherever_the_index_that_is_missing_stands(order):
    """Python's `max([nan, 0.1])` is nan and `max([0.1, nan])` is 0.1: the order decided whether a result with no index read as a converged grid."""
    assert vv.worst_gci(order) == INF and vv.worst_gci(iter(order)) == INF
    assert max([NAN, 0.05]) != max([0.05, NAN])                                       # the premise: what the plain max did


def test_m3_the_worst_of_finite_indices_is_the_largest_and_of_none_is_the_default():
    assert vv.worst_gci([0.05, 0.2, 0.1]) == 0.2 and vv.worst_gci([]) == 0.0 and vv.worst_gci([], default=7.0) == 7.0


def incidence(planes=("+y", "+z")):
    """The shape `cfd.characterize_incidence` returns, with arbitrary numbers (`hull_lift` reads the coarse forces only for the GCI, which the test fixes)."""
    rng = np.random.default_rng(0)
    labels = ["+x", *planes, *(f"x{p}{a:g}" for p in planes for a in (5.0, 10.0))]
    dirs = {lab: dict(force=list(rng.normal(size=3)), moment=list(rng.normal(size=3)), force_coarse=list(rng.normal(size=3)),
                      moment_coarse=list(rng.normal(size=3))) for lab in labels}
    return dict(rho=1025.0, speed=1.5, L=1.0, alphas=[5.0, 10.0], planes=list(planes), dirs=dirs)


@pytest.mark.parametrize("seen", [(NAN, 0.05), (0.05, NAN)], ids=["nan first", "nan last"])
def test_m3_hull_lift_returns_inf_when_one_plane_has_no_index_whichever_plane_it_is(monkeypatch, seen):
    """Before: nan when the plane with no index came first and 0.05 (a converged grid) when it came last."""
    it = iter(seen)
    monkeypatch.setattr(cfd, "gci", lambda *a, **k: next(it))
    _, g = vehicle.hull_lift(incidence(), np.zeros(3), np.zeros((3, 3)))
    assert g == INF


def test_m3_hull_lift_of_finite_indices_is_the_largest(monkeypatch):
    it = iter((0.05, 0.2))
    monkeypatch.setattr(cfd, "gci", lambda *a, **k: next(it))
    assert vehicle.hull_lift(incidence(), np.zeros(3), np.zeros((3, 3)))[1] == 0.2


@pytest.fixture(scope="module")
def torpedo():
    s = geom.SAMPLES["torpedo"]
    return s["kind"], s["make"](), s["spec"], json.loads((REAL / "torpedo.external.json").read_text())


@pytest.fixture(scope="module")
def wigley():
    s = geom.SAMPLES["wigley"]
    return s["kind"], s["make"](), s["spec"], json.loads((REAL / "wigley.surface.json").read_text())


def built(sample, **hangar_parts):
    kind, mesh, spec, _ = sample
    return vehicle.build(kind, mesh, spec, hangar_parts)


@pytest.mark.parametrize("at", [0, 3, 5])
def test_m3_a_direction_with_no_index_is_inf_in_the_drag_table_and_in_the_vehicles_spread(torpedo, at):
    """The real torpedo result with the `gci` of one direction NaN. Before: the table kept the NaN (the spread of the mission was NaN when it was the first
    direction, 0.1604 as if the grid had converged when it was any other)."""
    res = json.loads(json.dumps(torpedo[3]))
    d = list(res["dirs"])[at]
    res["dirs"][d]["gci"] = NAN
    v = built(torpedo, cfd=res)
    g = [c[3] for c in v.drag.values()]
    assert sum(x == INF for x in g) == 1 and all(np.isfinite(x) for x in g if x != INF)
    clean = built(torpedo, cfd=torpedo[3])
    assert mission.drag_sigma(clean) == pytest.approx(np.hypot(mission.SIG["drag_cfd"], max(c[3] for c in clean.drag.values())))      # unchanged
    assert mission.drag_sigma(v) == pytest.approx(max(mission.SIG["drag_est"], np.hypot(mission.SIG["drag_cfd"], max(x for x in g if x != INF))))


@pytest.mark.parametrize("at", [0, 1, 2])
def test_m3_a_speed_with_no_index_makes_the_resistance_gci_inf_and_the_spread_no_smaller_than_an_estimates(wigley, at):
    """Before: the NaN of the last speed was ignored, so the printed spread read as that of a converged grid, and of the first was NaN."""
    res = json.loads(json.dumps(wigley[3]))
    u = list(res["speeds"])[at]
    res["speeds"][u]["gci"] = NAN
    v = built(wigley, fs=res)
    assert v.limits["resistance_gci"] == INF and mission.drag_sigma(v) == mission.SIG["drag_est"]
    assert np.isfinite(built(wigley, fs=wigley[3]).limits["resistance_gci"])


def fake(resistance=None, drag=None, sources=None, **limits):
    return types.SimpleNamespace(resistance=resistance, drag={i: (0, 0, 0, g) for i, g in enumerate(drag or [])}, sources=sources or {}, limits=limits)


def test_m3_the_drag_spread_of_a_vehicle():
    """Finite: unchanged (the 10 % of the CFD with the largest GCI). Not finite: no smaller than an estimate's 30 %, and the largest finite GCI still counts."""
    h, est = mission.SIG["drag_cfd"], mission.SIG["drag_est"]
    cfd_ = dict(sources=dict(drag="cfd"))
    assert mission.drag_sigma(fake(drag=[0.05, 0.2], **cfd_)) == pytest.approx(np.hypot(h, 0.2))
    assert mission.drag_sigma(fake(drag=[0.05, 0.2], lift_gci=0.4, **cfd_)) == pytest.approx(np.hypot(h, 0.4))
    assert mission.drag_sigma(fake(drag=[0.05, INF], **cfd_)) == est
    assert mission.drag_sigma(fake(drag=[0.5, INF], **cfd_)) == pytest.approx(np.hypot(h, 0.5)) and np.hypot(h, 0.5) > est      # a wide finite one is kept
    assert mission.drag_sigma(fake(drag=[0.05], lift_gci=INF, **cfd_)) == est and mission.drag_sigma(fake(drag=[INF, INF], **cfd_)) == est
    assert mission.drag_sigma(fake(resistance=1, resistance_gci=0.2)) == pytest.approx(np.hypot(h, 0.2))
    assert mission.drag_sigma(fake(resistance=1, resistance_gci=INF)) == est and mission.drag_sigma(fake(resistance=1)) == pytest.approx(h)
    assert mission.drag_sigma(fake(drag=[0.9], sources=dict(drag="estimate"))) == est                                                 # no CFD: the estimate's


def test_m3_the_hangar_warns_of_a_grid_with_no_index_wherever_it_stands_and_says_so():
    """Before (`max` of the list): a NaN that came after a finite one was not seen, so no warning, and one that came first gave `nan > 0.3` False: none."""
    def result(*gcis):
        return dict(cfd=dict(dirs={f"d{i}": dict(gci=g) for i, g in enumerate(gcis)}))

    assert hangar.grid_warning({}) is None and hangar.grid_warning(result()) is None and hangar.grid_warning(result(0.05, 0.3)) is None
    assert "GCI up to 45%" in hangar.grid_warning(result(0.05, 0.45))
    for order in ((NAN, 0.05), (0.05, NAN), (0.05, None, 0.02), (INF,)):
        w = hangar.grid_warning(result(*order))
        assert w and "a direction has no GCI at all" in w and "worst" in w and "verdicts lean MARGINAL" in w and "inf" not in w
    fs = dict(fs=dict(speeds={"1.0": dict(gci=0.01), "1.5": dict(gci=NAN)}))
    assert "no GCI at all" in hangar.grid_warning(fs)
    assert "GCI up to 400%" in hangar.grid_warning(dict(cfd_aoa=dict(dirs={"x": dict(gci=4.0)}), fs=None))


# ---------------------------------------------------------------------------------------------------------------------------------------------------- M5

@pytest.mark.parametrize("t", [1e13, 1e18, -1e13, -1e18, INF, -INF, NAN], ids=["1e13", "1e18", "-1e13", "-1e18", "inf", "-inf", "nan"])
def test_m5_an_absurd_modification_time_is_an_unknown_date_in_the_advice_not_an_exception(monkeypatch, tmp_path, t):
    """Before: OverflowError, ValueError or OSError from `datetime.fromtimestamp` inside the text that exists to help after a failure."""
    store = tmp_path / "lab_x.zarr"
    aside = tmp_path / f"{hycom._aside_stem(store)}0123456789ab.old.tmp"
    aside.mkdir()
    monkeypatch.setattr(hycom, "_mtime", lambda d: t)
    note = hycom.leftover_note(store, True)
    assert f"{aside} (0.0 GB, newest, modified unknown date)" in note and f"`mv {aside} {store}` puts it back" in note


def test_m5_a_sane_time_still_prints_its_date_and_the_sort_is_still_by_time(tmp_path):
    import os
    store = tmp_path / "lab_x.zarr"
    stem = hycom._aside_stem(store)
    old, new = tmp_path / f"{stem}ffffffffffff.old.tmp", tmp_path / f"{stem}000000000000.old.tmp"
    for d, t in ((old, 1.9e9), (new, 2.0e9)):
        d.mkdir()
        os.utime(d, (t, t))
    note = hycom.leftover_note(store, True)
    assert "newest, modified 2033-05-18 03:33 UTC" in note and "older, modified 2030-03-17 17:46 UTC" in note and f"`mv {new} " in note
    assert hycom._date(0.0) == "1970-01-01 00:00 UTC" and hycom._date(1e13) == hycom._date(NAN) == "unknown date"


# ---------------------------------------------------------------------------------------------------------------------------------------------------- M6

def stub(p, lo, hi):
    """An emulator whose model answers `p` with the band (lo, hi) for every row, and that has already judged the mission near enough to the training set."""
    em = em_mod.Emulator.__new__(em_mod.Emulator)
    em.threshold, em.n_train, em.n_cal, em.features = 1.0, 10, 5, ["a"]
    em.distance = lambda x: 0.1                                                       # type: ignore[method-assign]
    em._dist = lambda x: np.zeros(len(x))                                             # type: ignore[method-assign]
    em.predict = lambda x, alpha=0.1: dict(p_fail=dict(value=np.full(len(np.atleast_2d(x)), p), lo=np.full(len(np.atleast_2d(x)), lo),    # type: ignore[method-assign]
                                                       hi=np.full(len(np.atleast_2d(x)), hi)))
    return em


def test_m6_the_emulators_answer_that_is_a_probability_is_judged_as_before():
    assert stub(0.05, 0.01, 0.09).query({"a": 0.0})["verdict"] == "GO" and stub(0.5, 0.4, 0.6).query({"a": 0.0})["verdict"] == "NO-GO"


@pytest.mark.parametrize("p, lo, hi", [(NAN, 0.1, 0.2), (1.5, 0.1, 0.2), (-0.1, 0.1, 0.2), (0.1, NAN, 0.2), (0.1, 0.1, 1.2), (INF, 0.0, 1.0)],
                         ids=["p nan", "p over 1", "p negative", "lo nan", "hi over 1", "p inf"])
def test_m6_an_emulator_answer_that_is_not_a_probability_is_a_config_error_naming_the_quantity(p, lo, hi):
    """Before (batch F): the bare ValueError of `intervals.verdict_band` ('need 0 <= p_fail <= 1'), a traceback at the command line."""
    with pytest.raises(config.ConfigError) as e:
        stub(p, lo, hi).query({"a": 0.0})
    text = str(e.value)
    assert text.startswith("the emulator's P(fail) is ") and "not a probability" in text and "need 0 <= " in text and "damaged" in text and "rerun" in text


def test_m6_the_flip_search_says_the_same_for_the_base_and_for_a_candidate():
    em = stub(0.3, 0.2, 0.4)
    assert em.flip_search({"a": 0.0}, {"a": (0.0, 1.0)}, steps=3, pair_steps=2)["base_verdict"] == "MARGINAL"
    with pytest.raises(config.ConfigError, match="the emulator's P"):
        stub(NAN, 0.2, 0.4).flip_search({"a": 0.0}, {"a": (0.0, 1.0)}, steps=3, pair_steps=2)
    cand = stub(0.3, 0.2, 0.4)
    cand.predict = lambda x, alpha=0.1: dict(p_fail=dict(value=np.full(len(x), 0.3 if len(x) == 1 else NAN), lo=np.full(len(x), 0.2), hi=np.full(len(x), 0.4)))
    with pytest.raises(config.ConfigError, match="the emulator's P"):
        cand.flip_search({"a": 0.0}, {"a": (0.0, 1.0)}, steps=3, pair_steps=2)


def test_m6_the_command_line_ends_a_what_if_on_a_damaged_emulator_with_error_and_exit_2_not_a_traceback(wi, capsys, monkeypatch):  # noqa: F811
    from cafe.pm import whatif
    monkeypatch.setattr(whatif, "answer", lambda *a, **k: stub(NAN, 0.1, 0.2).query({"a": 0.0}))
    assert cli.main(whatif_args(wi, "--shift", "6h")) == 2
    err = capsys.readouterr().err
    assert "\nerror: the emulator's P(fail) is nan" in "\n" + err and "Traceback" not in err


@pytest.mark.parametrize("n", [2 ** 53 + 1, 10 ** 30])
def test_m6_a_count_above_2_to_the_53_is_not_a_count_and_a_summary_with_one_is_refused_by_the_report_not_a_value_error(tmp_path, n):
    """Batch F made `intervals.verdict` refuse a count above 2**53 (a ValueError); a damaged summary holding one must reach `check_counts`' refusal first."""
    assert cr.counts_ok(0, 2 ** 53) and not cr.counts_ok(0, n) and not cr.counts_ok(n, n)
    with pytest.raises(config.ConfigError, match="is not a count .* n at most 9007199254740992"):
        cr.check_counts(0, n, "summary.links.x")
    run = tmp_path / "run"
    run.mkdir()
    m, plan = pm_run.make_run(run)
    p = run / "stage1b" / "summary.json"
    d = json.loads(p.read_text())
    e = d["summary"]["links"]["usv-uas-rf"]
    e["n"], e["k_fail"], e["verdict"]["n"], e["verdict"]["k_fail"] = n, 0, n, 0
    p.write_text(json.dumps(d))
    with pytest.raises(config.ConfigError, match=r"summary\.links\.usv-uas-rf: k_fail 0 of n \d+ members is not a count"):
        report.write(run, m, plan)
