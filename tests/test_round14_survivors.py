"""Round 14, M-5 and M-42: one assertion for each one-edit mutant that the tests of rounds 13 and 14's reviewers' lists let survive. Each test names the
mutant it kills; a mutant was applied to a throwaway copy and the test was seen to fail, then to pass without it (handback A lists the runs).

The tests only pin; no production behavior is added here. They sit in one file so that the batches of round 14 never edit the same test file."""
import datetime as dt
import platform
import types

import numpy as np
import pytest

import cafe.receipts as cr
from cafe.pm import audit, credibility as cred, whatif
from cafe.pm.env import environment as envm
from cafe.pm.stage3 import wallmodel as wm
from cafe.pm.stats import sampling
from tests.fixtures import pm_run
from tests.test_credibility import factors
from tests.test_platform_required import LOADERS, copy_of
from tests.test_whatif import ENV, plan_for, two_uas


# ---- M-5 mutant 1: whatif.py `changed[v["id"]] = dict(mod, shift_h=0.0)` -> `dict(mod)` (row 752)

def test_r14_m5_a_uas_that_only_follows_the_ship_is_asked_for_the_move_and_not_the_launch_shift(monkeypatch):
    """The ship is one, so `uas_b` flies from the new point; the 6 h later that was asked of `uas` is not its own."""
    m = whatif.apply(two_uas(), drop=["usv", "glider_1n", "glider_eq"])
    seen = []
    real = whatif.apply
    monkeypatch.setattr(whatif, "apply", lambda mission, mods=None, drop=(): seen.append(mods) or real(mission, mods, drop))
    base = {v: dict(verdict="GO", p_fail=0.0) for v in ("uas", "uas_b")}
    whatif.answer(m, dict(shift_h=6.0, dlon=0.1), base, {}, ENV, {}, plan_for(m), None, None, only=["uas"])
    asked = [s for s in seen if s and "uas_b" in s]
    assert len(asked) == 1 and asked[0]["uas"]["shift_h"] == 6.0 and asked[0]["uas_b"]["shift_h"] == 0.0 and asked[0]["uas_b"]["dlon"] == 0.1


# ---- M-5 mutant 2: sampling.py, the fixed-setting branch without `and e["mean"] > 0` (row 746)

@pytest.mark.parametrize("mean", [0.0, -1.0])
def test_r14_m5_a_fixed_setting_with_a_mean_of_zero_or_below_is_refused(mean):
    with pytest.raises(ValueError, match=r"perturbation 'other_setting': the fixed setting \(mean\) is .*must be finite and > 0"):
        sampling.check_entry("other_setting", dict(dist="fixed", mean=mean, value=0.0))
    sampling.check_entry("other_setting", dict(dist="fixed", mean=1e-3, value=0.0))


# ---- M-5 mutant 3: acceptance.py `os.W_OK | os.X_OK` -> `os.W_OK` is M-2 again. After M-2 `_probe(golden)` is what tries the search permission and the
# ---- X_OK is gone, so the mutant no longer exists; the case it stood for (a directory that can be written and not searched) is
# ---- tests/test_acceptance.py::test_r14_m2_a_directory_that_can_be_written_but_not_searched_refuses_a_golden_in_it.


# ---- M-5 mutant 4: audit.py `_same_place` with `Path.resolve()` where it has `real()` (row 713)

def test_r14_m5_same_place_follows_a_symlink_loop_to_false_and_does_not_raise(tmp_path):
    loop = tmp_path / "loop"
    loop.symlink_to(loop)                                                       # a link to itself
    good = tmp_path / "run"
    (good / "report").mkdir(parents=True)
    host = dict(host=platform.node())
    assert audit._same_place(good, dict(machine=host, outputs=[dict(path=str(good / "report" / "r.out"))])) is True
    assert audit._same_place(good, dict(machine=host, outputs=[dict(path=str(loop / "report" / "r.out"))])) is False       # the recorded place is a loop
    assert audit._same_place(loop, dict(machine=host, outputs=[dict(path=str(good / "report" / "r.out"))])) is False       # the run directory is


# ---- M-5 mutant 5: whatif.py describe, the tolerance of "rounded up to whole days" (row 746 sibling)

def test_r14_m5_a_period_that_is_whole_to_float_rounding_is_not_said_to_be_rounded_up():
    v = dict(whatif.vehicle(two_uas(), "uas"))
    v["sorties"] = dict(v["sorties"], every_days=7)
    assert 7 / 0.07 != 100.0 and abs(7 / 0.07 - 100.0) < 1e-9                  # the quotient is 100.00000000000001
    assert whatif.describe(dict(duty=0.07), v) == "fly sorties every 100 d instead of 7"


# ---- M-5 mutant 6: environment._stamp without OSError (platform-bound: `fromtimestamp` raises OSError on some systems for a time out of range)

def test_r14_m5_a_time_the_platform_refuses_with_an_oserror_is_printed_as_the_number(monkeypatch):
    def refuse(t, tz=None):
        raise OSError(75, "Value too large for defined data type")
    monkeypatch.setattr(envm, "dt", types.SimpleNamespace(datetime=types.SimpleNamespace(fromtimestamp=refuse), timezone=dt.timezone))
    assert envm._stamp(12.0) == "12 s"


# ---- M-5 mutant 7: credibility._ms_management, `has_commit(sha)` -> `sha not in (None, "none")` (row 716)

@pytest.mark.parametrize("sha", ["abc", ""])
def test_r14_m5_a_ledger_whose_git_sha_names_no_commit_is_management_level_one(tmp_path, monkeypatch, sha):
    monkeypatch.setenv("CAFE_DATA", str(tmp_path / "data"))
    run = tmp_path / "run"
    run.mkdir()
    pm_run.make_run(run, git=sha)
    f = factors(run)["ms_management"]
    assert f["level"] == 1 and "lacks a git sha" in f["missing"][0]


# ---- M-5 mutant 8: credibility._row without `D is not None` (both places)

def test_r14_m5_a_row_with_a_simulation_and_no_reference_has_no_error_and_no_verdict():
    for u in (None, (0.1, 0.1, 0.1)):
        r = cred._row("a", "c", "s", 1.0, None, u, "")
        assert r["status"] == "run" and r["E"] is None and r["validated"] is None and r["u_val"] is None


# ---- M-42: P11, W31, W29. (P4 and P21 were refuted by the verifier: tests/test_usv.py:914 and :1214 already kill them.)

def test_r14_m42_a_nested_list_is_no_list_of_numbers(tmp_path):
    """P11: `list3` without `np.ndim(a) == 1` accepted [[a, b, c]], three numbers in the wrong shape."""
    path = copy_of(tmp_path, "quad_uas", lambda r: r["airframe"]["inertia_kgm2"].update(value=[[0.0025, 0.0021, 0.0043]]))
    with pytest.raises(ValueError, match=r"airframe\.inertia_kgm2: .* must be a finite number above 0"):
        LOADERS["quad_uas"].load_platform(path)


def _stub_plate(**over):
    base = dict(cf=0.0040, ittc=0.0040, re=1e6, yfrac=0.95, force=np.ones(10), utau=0.002, mach_max=0.05, err=0.0, re_a=1e5)
    return dict(base, **over)


def _stub_channel():
    return dict(tau_w=1e-5, tau_target=1e-5, cf=0.0051, cf_dean=0.0052, re_b=4e4, yplus_m=200.0, ym_over_h=0.2, bb_tangential_frac=0.0, err=0.02,
                balance_err=0.0)


@pytest.mark.parametrize("yfrac, ok", [(0.95, True), (0.9, True), (0.7, False), (0.2, False)])
def test_r14_m42_the_share_of_wall_cells_in_the_log_layer_must_be_at_least_nine_tenths(monkeypatch, tmp_path, yfrac, ok):
    """W31: the gate 0.9 -> 0.5 survived: the stub default 0.95 passes at both and 0.2 fails at both."""
    monkeypatch.setattr(wm, "SLOW_DIR", tmp_path)
    monkeypatch.setattr(cr, "OUT", [])
    rows = wm.receipts(_stub_plate(yfrac=yfrac), _stub_channel())
    share = [r for r in rows if "share of wall cells" in r["claim"]]
    assert len(share) == 1 and share[0]["ok"] is ok


def test_r14_m42_the_plate_nose_is_a_half_ellipse():
    """W29: sqrt -> linear in the nose profile survived (the test counted only the tail and the middle). Cells in a column of the nose of a plate of
    half-thickness 2 cells and a nose of 8: h = 2 sqrt(1 - dx^2) with dx = (x0 + nose - x) / nose; cell centres at |y - 20| = 0.5, 1.5, ..."""
    m = wm.plate_mask((60, 40, 3), 10, 40, 20.0, 2.0, 8)
    cells = [int(m[i, :, 0].sum()) for i in range(10, 20)]
    assert cells == [2, 2, 2, 4, 4, 4, 4, 4, 4, 4]                           # x = 10.5 .. 19.5: h = 0.70, 1.17, 1.45, 1.65, 1.80, 1.90, 1.96, 2.0, 2, 2
