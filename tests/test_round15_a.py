"""Round 15, batch A: one test (or a few) for each finding fixed there. Each test names its finding; a fix was removed from a throwaway worktree and the test
was seen to fail, then to pass with it (handbacks/r15_handback_A.md lists the runs). The tests of M-1 and M-3 that extend a file of the earlier rounds live
here too, so that the batches of this round never edit one test file."""
import errno
import math
import os
import pathlib
import re
import shutil
import stat
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
import pytest

from cafe import atomic, hangar
from cafe.pm import config, emulator as E, stage1, whatif
from cafe.pm.env import environment as envm, hycom, orca, tao
from cafe.pm.stats import intervals as I, sensitivity as SE
from tests.test_stage1 import LK, MISSION, _split_sea, rf_scene
from tests.test_tao import _tao_manifest
from tests.test_whatif import CI, DEMO, ENV, GL, GSC, PRI, STORM, TRACK, plan_for, storm_em  # noqa: F401  (storm_em is a fixture)

pytestmark = pytest.mark.usefixtures("emulator_speed_not_tested")


# ---- the atomic writer (security review of cafe/atomic.py; M-6) ----------------------------------------------------------------------------------------

@pytest.fixture
def umask():
    """Set the process umask for a test and put it back."""
    old = os.umask(0o022)

    def set_(m):
        os.umask(m)
    yield set_
    os.umask(old)


def test_a_temporary_is_never_readable_more_widely_than_the_file_it_becomes(tmp_path, monkeypatch, umask):
    """The temporary was made with the umask's mode (0o644) and given the target's mode (0o600) only after the write: a 0o600 file's new content was readable by
    the group and others for as long as the write took. Every moment at which the code calls something on the temporary (the mode change, the replace) it is
    no wider than the file it replaces."""
    umask(0o022)
    f = tmp_path / "secret.json"
    f.write_text("old")
    f.chmod(0o600)
    seen = []
    mode = lambda p: stat.S_IMODE(os.stat(p).st_mode)                                                                  # noqa: E731
    real_replace, real_fchmod, real_chmod = os.replace, os.fchmod, os.chmod
    monkeypatch.setattr(os, "replace", lambda a, b: (seen.append(mode(a)), real_replace(a, b))[1])
    monkeypatch.setattr(os, "fchmod", lambda fd, m: (seen.append(stat.S_IMODE(os.fstat(fd).st_mode)), real_fchmod(fd, m))[1])
    monkeypatch.setattr(os, "chmod", lambda p, m, **k: (seen.append(mode(p)), real_chmod(p, m, **k))[1])
    real_copymode = shutil.copymode
    monkeypatch.setattr(shutil, "copymode", lambda s, d: (seen.append(mode(d)), real_copymode(s, d))[1])
    atomic.write_text(f, "new")
    assert seen and all(m & ~0o600 == 0 for m in seen), [oct(m) for m in seen]
    assert f.read_text() == "new" and mode(f) == 0o600


@pytest.mark.parametrize("old_mode, mask, new_mode", [(0o600, 0o022, 0o600), (0o664, 0o077, 0o664), (0o666, 0o022, 0o666), (0o444, 0o022, 0o444)])
def test_an_existing_file_keeps_its_mode_and_a_new_one_gets_the_umasks(tmp_path, umask, old_mode, mask, new_mode):
    """The final mode is the one it always was: the replaced file's, or `0o666 & ~umask` for a new file."""
    umask(mask)
    f = tmp_path / "f.json"
    f.write_text("1")
    f.chmod(old_mode)
    atomic.write_text(f, "2")
    assert stat.S_IMODE(f.stat().st_mode) == new_mode and f.read_text() == "2"
    g = tmp_path / "new.json"
    atomic.write_text(g, "3")
    assert stat.S_IMODE(g.stat().st_mode) == 0o666 & ~mask


def test_a_symbolic_link_at_the_target_is_refused_unless_the_caller_follows_it(tmp_path):
    """`cafe.atomic.write_text` followed a link, so a planted `status.json -> ~/.profile` made the job write there. Default: refused, with nothing written and
    nothing left behind; `follow_symlinks=True` (the pipeline's writers of a path a person names) replaces the file the link points to and keeps the link."""
    real, link = tmp_path / "real.json", tmp_path / "status.json"
    real.write_text("keep")
    link.symlink_to(real)
    for write in (lambda: atomic.write_text(link, "x"), lambda: atomic.write_json(link, {"a": 1})):
        with pytest.raises(OSError, match="symbolic link") as e:
            write()
        assert e.value.errno == errno.ELOOP
        assert real.read_text() == "keep" and link.is_symlink() and sorted(p.name for p in tmp_path.iterdir()) == ["real.json", "status.json"]
    atomic.write_text(link, "followed", follow_symlinks=True)
    assert link.is_symlink() and real.read_text() == "followed"
    config.write_text(link, "by config")                                                                               # the pipeline's writers follow
    config.write_json(link, {"b": 2})
    assert link.is_symlink() and real.read_text() == '{"b": 2}'
    dangling = tmp_path / "dangling.json"
    dangling.symlink_to(tmp_path / "nowhere.json")
    with pytest.raises(OSError, match="symbolic link"):
        atomic.write_text(dangling, "x")
    assert not (tmp_path / "nowhere.json").exists()


def test_a_link_planted_at_the_temporarys_name_after_the_create_is_not_written_through(tmp_path, monkeypatch):
    """The temporary was made with O_EXCL and then written by name (`Path.write_text` opens again, following links and truncating): a link put at its name
    between the two made the write land in the victim file. The text goes through the descriptor of the file we created."""
    victim = tmp_path / "victim.txt"
    victim.write_text("VICTIM-ORIGINAL")
    real_open = os.open

    def swapping(path, *a, **k):
        fd = real_open(path, *a, **k)
        if str(path).endswith(".tmp"):
            os.unlink(path)
            os.symlink(victim, path)
        return fd
    monkeypatch.setattr(os, "open", swapping)
    atomic.write_text(tmp_path / "status.json", "JOB-DATA")
    monkeypatch.undo()
    assert victim.read_text() == "VICTIM-ORIGINAL"


def test_the_apps_job_files_refuse_a_symbolic_link_and_the_jobs_other_writes_still_work(tmp_path):
    """`hangar.Job.status` (the app, the worker and the emulator job write their files the same way) got the default."""
    job = hangar.Job(tmp_path)
    job.status("running", step="mesh", progress=0.5)
    assert '"mesh"' in (tmp_path / "status.json").read_text()
    other = tmp_path / "elsewhere.json"
    other.write_text("{}")
    (tmp_path / "status.json").unlink()
    (tmp_path / "status.json").symlink_to(other)
    with pytest.raises(OSError, match="symbolic link"):
        job.status("running", step="bem", progress=0.6)
    assert other.read_text() == "{}"


def _longest_name(d):
    return next(k for k in range(255, 10, -1) if _plain_write_works(d / ("z" * k)))


def _plain_write_works(p):
    try:
        p.write_text("x")
    except OSError:
        return False
    p.unlink()
    return True


def test_a_temporary_fits_where_the_final_name_fits(tmp_path):
    """The temporary was `<name>.<pid>.<8 hex>.tmp`, up to 21 characters longer than the name: a final name of 235 to 255 characters raised OSError 63 where
    a plain write works. Now it is 17 characters whatever the name is."""
    n = _longest_name(tmp_path)                                                           # the longest name this file system takes (255 where the limit is 255)
    assert n >= 40
    name = "a" * (n - 5) + ".json"
    atomic.write_text(tmp_path / name, "[1]")
    assert (tmp_path / name).read_text() == "[1]" and [p.name for p in tmp_path.iterdir()] == [name]
    longest = tmp_path / ("b" * n)
    atomic.write_text(longest, "[2]")
    assert longest.read_text() == "[2]"
    t = atomic.tmp_name(longest)
    assert len(t.name) == 17 and t.name.endswith(".tmp") and t.parent == tmp_path and atomic.tmp_name(longest) != t


def test_the_emulator_table_is_written_through_a_temporary_that_fits_too(tmp_path):
    """`emulator.write_table` copied the 21-character suffix: its own band of names that fail."""
    t = tmp_path / ("c" * (_longest_name(tmp_path) - 4) + ".csv")
    E.write_table(pd.DataFrame(dict(key=["a"], x=[1.0])), t)
    assert [p.name for p in tmp_path.iterdir()] == [t.name] and len(E.read_table(t)) == 1


# ---- M-1: one verdict rule for a prediction with a band -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("go, nogo", [(0.9, 0.6), (0.95, 0.5), (0.8, 0.3)])
def test_m1_verdict_band_is_verdict_for_the_band_that_k_of_n_gives(go, nogo):
    """`verdict_band(k / n, *interval(k, n, 0.90))` is `verdict(k, n)` for every k at n up to 60, at the demo's thresholds and at others."""
    I.set_thresholds(go, nogo)
    try:
        for n in range(1, 61):
            for k in range(n + 1):
                lo, hi, _ = I.interval(k, n, 0.90)
                assert I.verdict_band(k / n, lo, hi) == I.verdict(k, n)["verdict"], (go, nogo, k, n)
    finally:
        I.set_thresholds(0.9, 0.6)


def test_m1_a_wide_band_is_not_go_and_a_point_at_the_cut_off_agrees_with_stage_1():
    """0.09 with the band 0.00 to 0.40 was GO by `verdict_from_p`; `verdict` needs the upper end at 0.25 or below."""
    assert I.verdict_band(0.09, 0.0, 0.40) == "MARGINAL" and I.verdict_from_p(0.09) == "GO"
    assert I.verdict_band(0.10, 0.0, 0.35) == I.verdict(1, 10)["verdict"] == "MARGINAL"
    assert I.verdict_band(0.05, 0.0, 0.25) == "GO" and I.verdict_band(0.05, 0.0, 0.2501) == "MARGINAL"
    assert I.verdict_band(0.10, 0.0, 0.10) == "GO" and I.verdict_band(0.1001, 0.0, 0.11) == "MARGINAL"
    assert I.verdict_band(0.4, 0.3, 0.5) == "MARGINAL" and I.verdict_band(0.4001, 0.3, 0.5) == "NO-GO"
    assert I.verdict_band(0.0, 0.0, 1.0) == "MARGINAL"                                  # an infinite conformal band (too few calibration rows) is never GO


def test_m1_band_in_asks_for_every_verdict_the_band_can_take():
    want = lambda lo, hi, *w: I.band_in(lo, hi, w)                                                                      # noqa: E731
    assert want(0.02, 0.09, "GO") and not want(0.0, 0.2, "GO") and want(0.12, 0.35, "MARGINAL") and not want(0.0, 0.2, "MARGINAL")
    assert want(0.0, 0.35, "GO", "MARGINAL") and not want(0.0, 0.45, "GO", "MARGINAL")
    assert not want(0.0, 1.0, "GO", "NO-GO"), "a band across the whole range takes MARGINAL values as well"
    assert want(0.5, 0.9, "NO-GO") and not want(0.3, 0.9, "NO-GO")


@pytest.fixture(scope="module")
def small_emulator(tmp_path_factory):
    df = E.synthetic_table(160, 3)
    em = E.Emulator(E.FEATURES, E.TARGETS, path=tmp_path_factory.mktemp("em") / "train.parquet", seed=3)
    em.fit(df, holdout=0.2)
    return em, df


def test_m1_query_reads_the_verdict_off_the_band_not_the_point(small_emulator, monkeypatch):
    """With the conformal band widened to the whole range, a low predicted P(fail) is not GO; with the fitted band it is what the band says."""
    em, df = small_emulator
    p = em.predict(df[E.FEATURES])["p_fail"]["value"]
    x = df.iloc[int(np.argmin(p))][E.FEATURES].to_dict()
    q = em.query(x)["targets"]["p_fail"]
    assert q["value"] <= 0.1 and em.query(x)["verdict"] == I.verdict_band(q["value"], q["lo"], q["hi"])
    monkeypatch.setitem(em.scores, "p_fail", em.scores["p_fail"] * 1e6)
    wide = em.query(x)
    assert wide["targets"]["p_fail"]["value"] <= 0.1 and wide["targets"]["p_fail"]["hi"] > 0.9
    assert wide["verdict"] == "MARGINAL" and I.verdict_from_p(wide["targets"]["p_fail"]["value"]) == "GO"      # the point alone said GO


def test_m1_the_emulators_flip_search_needs_the_whole_band_in_the_new_verdict(small_emulator, monkeypatch):
    """`flip_search` took the cheapest of the candidates by the point estimate alone. With every band as wide as the range no candidate is shown to flip."""
    em, df = small_emulator
    x = df.iloc[np.abs(em.predict(df[E.FEATURES])["p_fail"]["value"] - 0.30).argmin()][E.FEATURES].to_dict()
    bounds = {"duty_cycle": (0.2, 1.0), "lon_shift_deg": (-1.0, 1.0), "deploy_shift_h": (-12.0, 12.0)}
    narrow = em.flip_search(x, bounds)
    assert narrow["compared"] > 0 and narrow["base_verdict"] in ("GO", "MARGINAL", "NO-GO")
    if narrow["found"]:                                                                  # whatever it found, its band is wholly in the other verdicts
        moved = dict(x, **{k: x[k] + v for k, v in narrow["change"].items()})
        pc = em.predict(pd.DataFrame([moved])[E.FEATURES])["p_fail"]
        assert I.band_in(float(pc["lo"][0]), float(pc["hi"][0]), [v for v in ("GO", "MARGINAL", "NO-GO") if v != narrow["base_verdict"]])
    monkeypatch.setitem(em.scores, "p_fail", em.scores["p_fail"] * 1e6)
    wide = em.flip_search(x, bounds)
    assert not wide["found"] and wide["base_verdict"] == "MARGINAL" and wide["compared"] == narrow["compared"]
    assert "not_shown" in wide and wide["not_shown"]["verdict"] != wide["base_verdict"] and wide["not_shown"]["hi"] > 0.9


def test_m1_the_whatif_flip_search_reports_a_wide_band_winner_as_not_shown(storm_em, monkeypatch):  # noqa: F811
    """Before: the cheapest emulated candidate whose point is GO won with band 0 to 1. Now it is `not_shown`, `found` is False, the log line says so and
    gives how many candidates were compared. Stage 1 is not run (a budget of 0), so nothing else answers."""
    em, _ = storm_em
    monkeypatch.setitem(em.scores, "p_fail", em.scores["p_fail"] * 1e6)
    log = []
    flips, spent = whatif.flip_search(STORM, {GL: dict(verdict="NO-GO", p_fail=0.9)}, {GL: TRACK}, ENV, {GSC: (em, {})}, plan_for(STORM), *PRI,
                                      None, 5, 0.0, log.append)
    f = flips[GL]
    assert spent == 0.0 and not f["found"] and f["best"] is None and f["evaluated"] >= 1
    assert f["not_shown"]["method"] == "EMULATED" and f["not_shown"]["verdict"] in ("GO", "MARGINAL") and f["not_shown"]["shown"] is False
    assert all(t["shown"] is False for t in f["tried"] if t["method"] == "EMULATED" and t["verdict"] in ("GO", "MARGINAL"))
    assert f"among the {f['evaluated']} evaluated" in log[0] and "not shown:" in log[0] and f["not_shown"]["change"] in log[0]


def test_m1_the_whatif_flip_search_with_the_fitted_band_still_finds_the_flip_and_says_of_how_many(storm_em):  # noqa: F811
    em, _ = storm_em
    log = []
    flips, _ = whatif.flip_search(STORM, {GL: dict(verdict="NO-GO", p_fail=0.9)}, {GL: TRACK}, ENV, {GSC: (em, {})}, plan_for(STORM), *PRI,
                                  None, 5, 100.0, log.append)
    f = flips[GL]
    assert f["found"] and f["not_shown"] is None and f["best"]["shown"] is True and I.band_in(f["best"]["lo"], f["best"]["hi"], ("GO", "MARGINAL"))
    assert f"the cheapest of {f['evaluated']} evaluated" in log[0]
    assert whatif.emulate(em, {})["status"] == "no_track"


# ---- M-3: an RF link takes the worse margin of its two ends' Hs ---------------------------------------------------------------------------------------

def test_m3_an_rf_link_takes_the_worse_margin_of_the_two_ends_not_the_larger_hs():
    """A rougher sea fills the interference nulls: the larger Hs gave the better margin where the nulls are (by up to 20 dB) and the worse one at the peaks.
    The USV (north of 0.005 deg, Hs 3 m) and the ship (Hs 0.2 m) are 0.8 to 15 km apart, antennas 15 m and 60 m: the margin is, sample by sample, the
    worse of the margins in the two seas, in either naming."""
    out, air = rf_scene(M=1, bad_samples=(0,))
    n = out["usv"]["lat"].shape[0]
    out["usv"]["lat"][:, 0] = np.linspace(0.8, 15.0, n) / 111.195
    out["usv"]["antenna_m"] = 15.0
    out["uas"]["alt"][:] = 59.9                                                          # plus the UAS antenna's 0.1 m: 60 m
    lk = LK["usv-uas-rf"]
    run = lambda env, a="usv", b="uas": stage1.evaluate_link(dict(lk, a=a, b=b), out, MISSION, env, 1, 3, [0])["margin_db"]            # noqa: E731
    fwd, rev = run(_split_sea((0.2, 6.0), (3.0, 6.0), 1)), run(_split_sea((0.2, 6.0), (3.0, 6.0), 1), "uas", "usv")
    rough, calm = run(_split_sea((3.0, 6.0), (3.0, 6.0), 1)), run(_split_sea((0.2, 6.0), (0.2, 6.0), 1))
    ok = np.isfinite(calm) & np.isfinite(rough)
    assert ok.sum() > 50 and np.allclose(fwd, rev, atol=1e-9, equal_nan=True)                  # (swapped antenna heights differ by float dust, not by a dB)
    assert np.array_equal(fwd, np.minimum(rough, calm), equal_nan=True)
    assert (calm < rough - 1.0)[ok].any() and (rough < calm - 1.0)[ok].any(), "neither sea is the worse one everywhere, so no one Hs is 'the conservative one'"
    assert (rough - fwd)[ok].max() > 5.0, "the larger Hs, which the link used before, is optimistic by more than 5 dB at some sample"


# ---- M-4: a sortie period that is not a whole number of days ---------------------------------------------------------------------------------------------

def _mission_file(tmp_path, every):
    d = config.yaml.safe_load((config.ROOT / "missions" / "tepex_c_demo.yaml").read_text())
    uas = next(v for v in d["vehicles"] if "sorties" in v)
    uas["sorties"]["every_days"] = every
    p = tmp_path / "m.yaml"
    p.write_text(config.yaml.safe_dump(d))
    return p


def test_m4_every_days_of_a_day_and_a_half_warns_that_the_hour_drifts(tmp_path):
    with pytest.warns(UserWarning, match=r"every_days: 1\.5 d is not a whole number of days, so local_solar_time 14:00 holds for the first launch only; "
                                         r"the launches fall at local solar times 14:00, 02:00, 14:00, 02:00$"):
        config.load_mission(_mission_file(tmp_path, 1.5), set_verdict=False)


def test_m4_whole_days_and_sub_daily_periods_do_not_warn(tmp_path, recwarn):
    for every in (1, 2.0, 0.7, 0.5):
        config.load_mission(_mission_file(tmp_path, every), set_verdict=False)
    assert not [w for w in recwarn if "whole number of days" in str(w.message)]


# ---- M-5: manifests and attributes -------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, True])
def test_m5_real_numbers_and_the_manifest_shapes_refuse_nan_infinity_and_bool(bad):
    assert orca.real_numbers([1.0, 2], 2) and not orca.real_numbers([bad, 1.0], 2)
    assert not orca.real_numbers([bad]) and orca.real_numbers([]) and not orca.real_numbers([10 ** 400])
    good = dict(base="b", t0="a", t1="c", hours=3, box=[1.0, 2.0, 3.0, 4.0], hours3d=["h"])
    assert orca.manifest_shape(good) and not orca.manifest_shape(dict(good, hours=bad)) and not orca.manifest_shape(dict(good, box=[bad, 2.0, 3.0, 4.0]))
    parts = dict(parts={"p.nc": dict(sha256="x", dataset="d", server="s")}, dataset="d", box=[1.0, 2.0, 3.0, 4.0])
    assert hycom.manifest_shape(parts, whole=True) and not hycom.manifest_shape(dict(parts, box=[1.0, bad, 3.0, 4.0]), whole=True)
    man = _tao_manifest()
    assert tao.manifest_shape(man) is True and tao.manifest_shape(dict(man, t0=bad)) is False
    assert tao.manifest_shape(dict(man, box=[1.0, 2.0, bad, 4.0])) is False


def test_m5_a_boolean_attribute_is_not_a_grid_spacing_or_an_sst_update():
    """`float(True)` is 1.0: DX true read '0.001 km' and SST_UPDATE true 'updated during the run'."""
    assert envm._wrf_notes({"DX": True, "SST_UPDATE": 0}) == ("grid spacing (DX) not recorded", "frozen: SST_UPDATE=0 (start date not recorded)")
    assert envm._wrf_notes({"DX": 12000, "SST_UPDATE": True}) == ("12 km", "SST_UPDATE not recorded")
    assert envm._wrf_notes({"DX": np.bool_(True), "SST_UPDATE": np.bool_(True)}) == ("grid spacing (DX) not recorded", "SST_UPDATE not recorded")
    assert envm._wrf_notes({"DX": 12000, "SST_UPDATE": 1}) == ("12 km", "updated during the run: SST_UPDATE=1")


# ---- M-28 to M-31: what-if changes -------------------------------------------------------------------------------------------------------------------

def test_m28_changes_that_cancel_are_refused_and_a_dropped_vehicle_is_dropped_once():
    for ops in (dict(shift_h=0.0), dict(shift_h=6.0 + -6.0), dict(dlon=1.0 + -1.0, dlat=0.0), dict()):
        with pytest.raises(whatif.Invalid, match="the changes cancel: nothing changes"):
            whatif.answer(CI, ops, {}, {}, None, {}, {}, None, None)
    with pytest.raises(whatif.Invalid, match="the changes cancel"):
        whatif.answer(CI, dict(shift_h=0.0, drop=[]), {}, {}, None, {}, {}, None, None)
    r = whatif.answer(CI, dict(drop=["usv", "usv"]), {}, {}, ENV, {}, plan_for(CI), None, None)
    assert r["dropped"] == ["usv"]
    r = whatif.answer(CI, dict(shift_h=24.0), {}, {}, ENV, {}, plan_for(CI), None, None, only=["uas"])       # a whole-day shift is an answer, not a refusal
    assert r["vehicles"] == {} and set(r["unchanged"]) == {"uas"}


@pytest.mark.parametrize("dlon", [1e300, 355.0, 360.0, 721.0, -355.0])
def test_m29_a_move_as_wide_as_the_box_is_refused_whatever_it_wraps_to(dlon):
    """`_wrap` works modulo 360: 355 deg east was accepted as 5 deg west, 1e300 as 10 deg west, 360 as no move at all."""
    for mission, vid in ((DEMO, "glider_eq"), (CI, "uas"), (DEMO, "uas")):
        with pytest.raises(whatif.Invalid, match=re.escape(f"{vid}: a move of {dlon:+g} deg lon, +0 deg lat is not smaller than the mission box")):
            whatif.apply(mission, {vid: dict(dlon=dlon)})
    with pytest.raises(whatif.Invalid, match="not smaller than the mission box"):
        whatif.answer(DEMO, dict(dlon=dlon), {}, {}, None, {}, {}, None, None)


def test_m29_a_move_smaller_than_the_box_is_unchanged_and_a_huge_dlat_is_refused():
    old = whatif.vehicle(DEMO, "glider_eq")["deploy"]["lon"]
    assert whatif.vehicle(whatif.apply(DEMO, {"glider_eq": dict(dlon=-0.5)}), "glider_eq")["deploy"]["lon"] == pytest.approx(float(whatif._wrap(old - 0.5)))
    with pytest.raises(whatif.Invalid, match="not smaller than the mission box"):
        whatif.apply(DEMO, {"usv": dict(dlat=1e300)})
    with pytest.raises(whatif.Invalid, match="not smaller than the mission box"):
        whatif.apply(DEMO, {"usv": dict(dlat=10.0)})                                          # the demo box is 10 deg high


@pytest.mark.parametrize("duty", [10.0, 1.0001, 1000.0])
def test_m30_a_duty_above_one_is_refused(duty):
    """A duty of 10 gave a glider a dive of 9500 m; 1000 gave a UAS a sortie every 0.001 d."""
    for vid in ("glider_eq", "uas"):
        with pytest.raises(whatif.Invalid, match="a duty above 0 and at most 1"):
            whatif.apply(DEMO, {vid: dict(duty=duty)})


def test_m30_a_duty_that_takes_the_dive_below_the_platforms_minimum_is_refused():
    """`apply` did not run the checks `load_mission` makes of the mission it builds: a glider's dive of 9.5 m (min_dive_m 30) or 9.5e-298 m."""
    for duty in (0.01, 1e-300):
        with pytest.raises(whatif.Invalid, match=r"glider_eq: duty .* gives a mission the loader would refuse: glider_eq/task/dive_depth_m: "
                                                 r".* min_dive_m 30 m to rating_m 1000 m"):
            whatif.apply(DEMO, {"glider_eq": dict(duty=duty)})
    assert whatif.vehicle(whatif.apply(DEMO, {"glider_eq": dict(duty=0.05)}), "glider_eq")["task"]["dive_depth_m"] == pytest.approx(47.5)
    assert whatif.vehicle(whatif.apply(DEMO, {"uas": dict(duty=1e-300)}), "uas")["sorties"]["every_days"] > 1e299            # a UAS period only gets longer


def test_m30_the_design_drops_a_duty_that_cannot_be_applied_before_it_drops_the_whole_change():
    """`_fits_all` shrank shift and move and kept the duty, so a duty the dive limit refuses sent the whole change to zero."""
    got = whatif._fits(CI, GL, dict(shift_h=4.0, dlon=0.0, dlat=0.0, duty=0.01))
    assert got == dict(shift_h=4.0, dlon=0.0, dlat=0.0, duty=1.0)
    assert whatif._fits(CI, GL, dict(shift_h=4.0, dlon=0.0, dlat=0.0, duty=0.5)) == dict(shift_h=4.0, dlon=0.0, dlat=0.0, duty=0.5)


def test_m30_the_flip_candidates_are_still_the_ones_the_demo_had():
    """The duty candidates (0.75 and 0.5) take the demo's dives to 712.5 and 475 m and the Slocum's to 375 and 250 m: none is refused."""
    assert len(whatif.candidates(DEMO, "glider_eq")) == len(whatif.candidates(DEMO, "glider_2n"))
    assert {c["change"] for c in whatif.candidates(DEMO, "glider_eq")} >= {"dive 25 % shallower (950 m to 712.5 m)", "dive 50 % shallower (950 m to 475 m)"}


def test_m31_a_launch_shift_that_only_rounds_to_whole_days_says_what_is_tested():
    """0.001 h, 24.001 h and 23.999 h were refused as 'a whole number of days'; the test is at the minute (launch times are HH:MM)."""
    for h in (0.001, 24.001, 23.999, -0.004):
        with pytest.raises(whatif.Invalid, match=r"uas: launching .* h later rounds to a whole number of days at the one-minute resolution of launch "
                                                 r"times \(HH:MM\), the same launch time of day"):
            whatif.apply(CI, {"uas": dict(shift_h=h)})
    with pytest.raises(whatif.Invalid, match=r"uas: launching \+24 h later is a whole number of days, the same launch time of day"):
        whatif.apply(CI, {"uas": dict(shift_h=24.0)})
    assert whatif.vehicle(whatif.apply(CI, {"uas": dict(shift_h=0.01)}), "uas")["sorties"]["local_solar_time"] == "14:01"
    r = whatif.answer(CI, dict(shift_h=24.001), {}, {}, ENV, {}, plan_for(CI), None, None, only=["uas"])
    assert r["unchanged"]["uas"] == ("launching +24.001 h later keeps the same launch time of day: nothing changes "
                                     "(it rounds to a whole number of days at the one-minute resolution of launch times (HH:MM))")
    r = whatif.answer(CI, dict(shift_h=24.0), {}, {}, ENV, {}, plan_for(CI), None, None, only=["uas"])
    assert r["unchanged"]["uas"] == "launching +24 h later keeps the same launch time of day: nothing changes"


# ---- M-37: domain edges ----------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("n", [4, 5, 8, 15])
def test_m37_first_order_refuses_fewer_than_the_least_number_of_members(n):
    """n = 4 was a ZeroDivisionError and n = 5 gave S1 = 1.0 for independent noise."""
    rng = np.random.default_rng(1)
    with pytest.raises(ValueError, match=rf"at least {SE.SENS_MIN_N} members, got {n}"):
        SE.first_order(rng.random((n, 2)), rng.random(n))
    with pytest.raises(ValueError, match="at least 16 members"):
        SE.noise_floor(rng.random((n, 2)), rng.random(n), perms=3)
    assert SE.first_order(rng.random((16, 2)), rng.random(16)).shape == (2,)
    assert stage1.SENS_MIN_N is SE.SENS_MIN_N == 16


def test_m37_first_order_refuses_harmonics_that_make_lambda_one_or_more():
    rng = np.random.default_rng(2)
    x, y = rng.random((16, 1)), rng.random(16)
    for m in (8, 9, 100):
        with pytest.raises(ValueError, match=rf"{m} harmonics need more than {2 * m} members"):
            SE.first_order(x, y, m)
    assert SE.first_order(x, y, 7).shape == (1,) and SE.first_order(rng.random((8, 1)), rng.random(8), 2, False).shape == (1,)


def test_m37_the_interval_functions_refuse_what_interval_refuses():
    for f, args in ((I.wilson, (5, 3)), (I.wilson, (0, 0)), (I.wilson, (-1, 3)), (I.agresti_coull, (1, 0)), (I.agresti_coull, (4, 3)),
                    (I.newcombe_diff, (1, 0, 1, 2)), (I.newcombe_diff, (1, 2, 3, 2)), (I.interval, (5, 3))):
        with pytest.raises(ValueError, match="need 0 <= k <= n and n >= 1"):
            f(*args)
    for f, kw in ((I.wilson, dict(conf=1.0)), (I.wilson, dict(conf=0.0)), (I.agresti_coull, dict(conf=1.5))):
        with pytest.raises(ValueError, match="need 0 < conf < 1"):
            f(1, 4, **kw)
    with pytest.raises(ValueError, match="need n >= 1"):
        I.rule_of_three(0)
    for f, kw in ((I.n_certify, dict(level=0.0)), (I.n_certify, dict(level=1.0)), (I.n_certify, dict(conf=1.0)), (I.n_certify_one_sided, dict(conf=1.0)),
                  (I.n_certify_one_sided, dict(level=0.0)), (I.n_certify_one_sided, dict(level=1.0)), (I.n_certify_one_sided, dict(conf=0.0))):
        with pytest.raises(ValueError, match="need 0 < level < 1 and 0 < conf < 1"):
            f(**kw)
    assert I.n_certify() == 73 and I.n_certify_one_sided() == 59 and I.wilson(0, 73)[1] < 0.05 and I.rule_of_three(60) == 0.05


def test_m37_shares_main_answers_a_bad_command_line_with_usage_and_exit_2(tmp_path, capsys):
    from cafe.pm import shares
    root = tmp_path / "repo"
    (root / "tests").mkdir(parents=True)
    for name in ("test_a.py", "test_b.py"):
        (root / "tests" / name).write_text("def test_x():\n    pass\n")
    out = tmp_path / "out"
    good = tmp_path / "ok.xml"
    ET.ElementTree(ET.fromstring('<testsuites><testsuite><testcase classname="tests.test_a" name="test_x" time="1.0"/></testsuite></testsuites>')).write(good)
    cut = tmp_path / "cut.xml"
    cut.write_text('<testsuites><testsuite><testcase classname="tests.test_a" name="te')
    assert shares.main(["2", str(out), str(good)], root) == 0
    for argv in (["0", str(out)], ["²", str(out)], ["٣", str(out)], ["x", str(out)], ["2"], []):
        assert shares.main(argv, root) == 2
    capsys.readouterr()
    assert shares.main(["2", str(out), str(cut)], root) == 2 and "error:" in capsys.readouterr().err                   # a truncated junit file
    assert shares.main(["2", str(out), str(tmp_path / "missing.xml")], root) == 2 and "error:" in capsys.readouterr().err
    assert shares.main(["3", str(out), str(good)], root) == 2 and "3 shares for 2 test files" in capsys.readouterr().err
    assert pathlib.Path(out / "s1.args").exists()
    a_file = tmp_path / "a_file"
    a_file.write_text("x")
    assert shares.main(["2", str(a_file), str(good)], root) == 2 and "error:" in capsys.readouterr().err               # an output path that is a file
    assert shares.main(["2", str(a_file / "below"), str(good)], root) == 2 and "error:" in capsys.readouterr().err
