"""cafe.pm.receipts: the table, the exit codes, the broken wave-direction configuration, and the direction convention setting."""
import json
import math
import pathlib
import re

import numpy as np
import pytest
import yaml

from cafe import receipts as R
from cafe.pm import __main__ as cli, receipts as pr
from cafe.pm.env import conventions as cv

BROKEN = pr.ROOT / "tests" / "fixtures" / "broken" / "wave_direction.yaml"


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    """Each test sees an empty cafe.receipts.OUT and no overlay, whatever ran before."""
    monkeypatch.setattr(R, "OUT", [])
    monkeypatch.delenv(cv.OVERLAY_ENV, raising=False)


def passing():
    R.receipt("G", "close", 1.001, 1.0, 0.01, "m", "src")


def failing():
    R.receipt("G", "far", 2.0, 1.0, 0.01, "m", "src")


def jobs_of(*fns):
    return lambda slow=False: list(fns)


# ------------------------------------------------------------------ normalising rows


def test_default_log_prints_and_flushes(capsys):
    pr._say("progress")
    assert capsys.readouterr().out == "progress\n"


def test_num_drops_non_finite():
    assert pr._num(1) == 1.0 and pr._num(None) is None and pr._num(float("inf")) is None and pr._num(float("nan")) is None


def test_the_three_record_kinds_become_rows():
    R.receipt("Grp", "rel claim", 1.02, 1.0, 0.05, "m", "the source")
    R.receipt("Grp", "abs claim", 3.0, 1.0, 0.5, "s", "x", rel=False)
    R.bracket("Grp", "in a bracket", 5.0, 4.0, 8.0, "kg", "y")
    R.bracket("Grp", "out of a bracket", 9.0, 4.0, 8.0, "kg", "y")
    R.context("Grp", "for orientation", 7.0, 6.0, "N", "z")
    rows = [pr._row("mod", d, {}) for d in R.OUT]
    assert [r["kind"] for r in rows] == ["pass", "fail", "pass", "fail", "context"]
    assert [r["ok"] for r in rows] == [True, False, True, False, None]
    keys = {"id", "module", "name", "value", "reference", "tolerance", "unit", "ok", "kind", "source", "note"}
    assert all(set(r) == keys and r["module"] == "mod" for r in rows)
    assert rows[0]["name"] == "Grp: rel claim" and rows[0]["reference"] == 1.0 and rows[0]["tolerance"] == 0.05
    assert rows[0]["unit"] == "m" and rows[0]["source"] == "the source" and rows[0]["note"].startswith("relative tolerance, error ")
    assert rows[1]["note"].startswith("absolute tolerance, error 2")
    assert rows[2]["reference"] == 6.0 and rows[2]["tolerance"] == 2.0 and rows[2]["note"] == "bracket [4, 8]"
    assert rows[4]["tolerance"] is None and rows[4]["reference"] == 6.0 and "context" in rows[4]["note"]
    json.dumps(rows, allow_nan=False)


def test_non_finite_values_stay_failing_and_keep_the_json_strict():
    R.bracket("Grp", "never", float("inf"), 0.0, 1.0, "m", "s")
    R.bracket("Grp", "nan", float("nan"), 0.0, 1.0, "m", "s")
    rows = [pr._row("mod", d, {}) for d in R.OUT]
    assert [r["kind"] for r in rows] == ["fail", "fail"] and rows[0]["value"] is None and "value inf" in rows[0]["note"] and "value nan" in rows[1]["note"]
    json.dumps(rows, allow_nan=False)


def test_ids_are_unique_slugs_even_for_repeated_claims():
    seen = {}
    ids = [pr._row("m", dict(group="A b", claim="same claim!", value=1.0, reference=1.0, tol=1.0, rel=False, error=0.0, ok=True), seen)["id"] for _ in range(3)]
    assert ids == ["m/a-b-same-claim", "m/a-b-same-claim-2", "m/a-b-same-claim-3"]
    long = pr._ident("m", "x" * 300, {})
    assert len(long) == len("m/") + 72


def test_extra_rows_fail_unless_they_are_context_and_may_carry_an_explicit_id():
    f, c = pr._extra_row("mod", "mod raised KeyError", True, "'x'", {}), pr._extra_row("mod", "mod note", False, "n", {}, ident="mod:custom")
    assert (f["kind"], f["ok"], f["id"]) == ("fail", False, "mod/mod-raised-keyerror") and (c["kind"], c["ok"], c["id"]) == ("context", None, "mod:custom")
    assert f["value"] is None and c["source"] == "cafe.pm.receipts"


# ------------------------------------------------------------------ collect, summary, run


def orientation():
    R.context("G", "for orientation", 1.0, 1.0)


def raising():
    passing()
    raise KeyError("boom")


def silent():
    return None


def noted():
    return "DTMB 5415: no hydro.json; no receipts emitted"


def test_collect_normalises_failures_exceptions_and_silence_and_hides_nothing(monkeypatch):
    monkeypatch.setattr(pr, "jobs", jobs_of(("a", passing), ("b", failing), ("c", raising), ("d", silent), ("e", noted)))
    logs = []
    rows = pr.collect(log=logs.append)
    by = {}
    for r in rows:
        by.setdefault(r["module"], []).append(r["kind"])
    assert by == {"a": ["pass"], "b": ["fail"], "c": ["fail", "pass"], "d": ["fail"], "e": ["fail"]}          # a required check that records nothing fails
    boom = next(r for r in rows if r["kind"] == "fail" and r["module"] == "c")
    assert boom["name"] == "c raised KeyError" and boom["note"] == "'boom'" and boom["ok"] is False
    assert next(r for r in rows if r["module"] == "e")["name"].startswith("DTMB 5415: no hydro.json")
    assert next(r for r in rows if r["module"] == "d")["name"] == "d recorded no receipts" and next(r for r in rows if r["module"] == "e")["ok"] is False
    assert logs[0] == "  a ..." and len(logs) == 10 and "records" in logs[1]


def test_collect_only_filters_by_substring_and_prints_nothing_from_receipts(monkeypatch, capsys):
    monkeypatch.setattr(pr, "jobs", jobs_of(("pm.env.waves", passing), ("pm.emulator", failing)))
    rows = pr.collect(only=["emul"], log=lambda s: None)
    assert [r["module"] for r in rows] == ["pm.emulator"] and capsys.readouterr().out == ""
    assert pr.collect(only=["waves", "emul"], log=lambda s: None)[0]["module"] == "pm.env.waves"


def test_summary_counts_and_lists_every_failure():
    R.receipt("G", "a", 1.0, 1.0, 0.1)
    R.bracket("G", "bad one", 9.0, 0.0, 1.0, "u", "s")
    R.context("G", "ctx", 1.0, 1.0)
    counts, text = pr.summary([pr._row("m", d, {}) for d in R.OUT])
    assert counts == {"pass": 1, "fail": 1, "context": 1} and text.startswith("1 pass, 1 fail, 1 context (3 rows)")
    assert text.count("\nFAIL ") == 1 and "G: bad one: value 9.0 u (bracket [0, 1])" in text


def test_run_passing_writes_the_table_and_exits_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(pr, "jobs", jobs_of(("a", passing)))
    out = tmp_path / "t" / "r.json"
    logs = []
    rows, code = pr.run(out=out, log=logs.append)
    assert code == 0 and json.loads(out.read_text()) == rows and rows[0]["kind"] == "pass"
    assert any(s.startswith("1 pass, 0 fail") for s in logs) and f"table: {out}" in logs


def test_run_exits_non_zero_on_any_failed_row_and_context_rows_do_not_count(tmp_path, monkeypatch):
    monkeypatch.setattr(pr, "jobs", jobs_of(("a", passing), ("b", failing)))
    rows, code = pr.run(out=tmp_path / "r.json", log=lambda s: None)
    assert code == 1 and sorted(r["kind"] for r in rows) == ["fail", "pass"]
    monkeypatch.setattr(pr, "jobs", jobs_of(("a", passing), ("d", orientation)))
    assert pr.run(out=tmp_path / "r.json", log=lambda s: None)[1] == 0


def test_default_table_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(pr, "ROOT", tmp_path)
    monkeypatch.setattr(pr, "jobs", jobs_of(("a", failing)))
    pr.run(log=lambda s: None)
    pr.run(broken=BROKEN, log=lambda s: None)
    assert (tmp_path / "runs" / "receipts.json").exists() and (tmp_path / "runs" / "receipts_broken.json").exists()


def test_broken_run_applies_the_overlay_only_while_running_and_inverts_the_exit_code(tmp_path, monkeypatch):
    seen = []

    def probe():
        seen.append((cv.wave_direction_convention(), cv.math_rad_to_compass_to(0.0)))
        failing()
    monkeypatch.setattr(pr, "jobs", jobs_of(("a", probe)))
    logs = []
    _, code = pr.run(broken=BROKEN, out=tmp_path / "b.json", log=logs.append)
    assert code == 0 and seen == [("compass_from", 180.0)] and cv.OVERLAY_ENV not in __import__("os").environ
    assert any("waves.direction_convention = compass_from" in s for s in logs) and any("failed 1 receipts, as required" in s for s in logs)
    monkeypatch.setattr(pr, "jobs", jobs_of(("a", passing)))
    logs.clear()
    _, code = pr.run(broken=BROKEN, out=tmp_path / "b.json", log=logs.append)
    assert code == 1 and any("NO receipt" in s for s in logs)


def test_broken_run_restores_a_previous_overlay_and_a_missing_file_is_an_error(tmp_path, monkeypatch):
    other = tmp_path / "o.yaml"
    other.write_text("waves: {direction_convention: umwm}\n")
    monkeypatch.setenv(cv.OVERLAY_ENV, str(other))
    monkeypatch.setattr(pr, "jobs", jobs_of(("a", failing)))
    pr.run(broken=BROKEN, out=tmp_path / "b.json", log=lambda s: None)
    assert __import__("os").environ[cv.OVERLAY_ENV] == str(other)
    with pytest.raises(FileNotFoundError, match="no/such.yaml: no such file"):
        pr.run(broken="no/such.yaml", log=lambda s: None)


# ------------------------------------------------------------------ the convention setting and the wave-direction receipts


def test_default_convention_is_umwm_and_the_broken_yaml_selects_the_other(tmp_path, monkeypatch):
    assert cv.wave_direction_convention() == "umwm" and float(cv.math_rad_to_compass_to(0.0)) == 90.0 and float(cv.compass_to_to_math_rad(90.0)) == 0.0
    monkeypatch.setenv(cv.OVERLAY_ENV, str(BROKEN))
    assert cv.wave_direction_convention() == "compass_from"
    assert float(cv.math_rad_to_compass_to(0.0)) == 180.0 and float(cv.math_rad_to_compass_to(np.pi / 2)) == 270.0
    assert float(cv.compass_to_to_math_rad(270.0)) == pytest.approx(np.pi / 2)


def test_overlay_without_the_setting_or_empty_means_umwm_and_a_bad_value_is_refused(tmp_path, monkeypatch):
    for text in ("", "other: 1\n", "waves: {}\n", "waves:\n"):
        p = tmp_path / f"o{len(text)}.yaml"
        p.write_text(text)
        monkeypatch.setenv(cv.OVERLAY_ENV, str(p))
        assert cv.wave_direction_convention() == "umwm"
    bad = tmp_path / "bad.yaml"
    bad.write_text("waves: {direction_convention: north_up}\n")
    monkeypatch.setenv(cv.OVERLAY_ENV, str(bad))
    with pytest.raises(ValueError, match=r"direction_convention is 'north_up', expected one of \('umwm', 'compass_from'\)"):
        cv.wave_direction_convention()


def test_the_broken_yaml_is_what_the_docs_say():
    d = yaml.safe_load(BROKEN.read_text())
    assert d == {"waves": {"direction_convention": "compass_from"}}


def test_synthetic_cache_follows_the_stated_trade_wind(tmp_path):
    import xarray as xr
    root = pr.synthetic_cache(tmp_path)
    w, u = xr.open_zarr(root / "orca" / "wrf.zarr"), xr.open_zarr(root / "orca" / "umwm.zarr")
    east, north = float(w.U10[0, 0, 0]), float(w.V10[0, 0, 0])
    assert math.hypot(east, north) == pytest.approx(pr.SYNTH_MS) and east < 0 and north < 0                 # blowing toward the south-west quadrant
    assert math.degrees(math.atan2(-east, -north)) % 360 == pytest.approx(pr.SYNTH_FROM_DEG)                # ... from 75 degrees
    wdir = float(u.wdir[0, 0, 0])
    assert (math.cos(wdir), math.sin(wdir)) == pytest.approx((east / pr.SYNTH_MS, north / pr.SYNTH_MS))
    assert float(u.mwd[0, 0, 0]) - wdir == pytest.approx(math.radians(10)) and float(u.dwd[0, 0, 0]) - wdir == pytest.approx(math.radians(20))
    s = xr.open_zarr(root / "orca" / "umwmspec.zarr")
    assert s.F.dims == ("time", "point", "th", "f") and int((s.F[0, 0] > 0).any("f").sum()) == 1


def test_stokes_native_is_independent_of_the_conventions_module(monkeypatch):
    f = 0.0313 * 1.12246 ** np.arange(37)
    th = -np.pi + (np.arange(32) + 0.5) * 2 * np.pi / 32
    k = (2 * np.pi * f) ** 2 / 9.81
    F = np.zeros((32, 37))
    F[3] = 1e-3 * k ** -4.0                                                    # one bin: theta = th[3], toward the south-west
    east, north = pr._stokes_native(F, k, f, th)
    assert math.atan2(north, east) == pytest.approx(th[3]) and east < 0 and north < 0
    monkeypatch.setenv(cv.OVERLAY_ENV, str(BROKEN))
    assert pr._stokes_native(F, k, f, th) == pytest.approx((east, north))


def test_dang_wraps():
    assert pr._dang(350.0, 10.0) == 20.0 and pr._dang(10.0, 350.0) == 20.0 and pr._dang(0.0, 180.0) == 180.0 and pr._dang(90.0, 90.0) == 0.0


def direction_rows():
    R.OUT.clear()
    pr.wave_direction_receipts()
    return [pr._row("d", d, {}) for d in R.OUT]


def test_direction_receipts_pass_with_the_default_convention_and_fail_under_the_broken_one(tmp_path, monkeypatch):
    monkeypatch.setenv("CAFE_DATA", str(tmp_path))
    ok = direction_rows()
    synth = [r for r in ok if "synthetic" in r["name"]]
    assert len(synth) == 6 and [r["kind"] for r in synth] == ["pass"] * 5 + ["context"]
    assert any("no mission cache with restart spectra" in r["name"] and r["kind"] == "context" for r in ok)
    monkeypatch.setenv(cv.OVERLAY_ENV, str(BROKEN))
    bad = [r for r in direction_rows() if "synthetic" in r["name"]]
    assert [r["kind"] for r in bad] == ["fail", "fail", "fail", "pass", "fail", "context"]          # the speed ratio does not depend on direction
    assert all(r["value"] > 100 for r in bad if r["kind"] == "fail")


def test_direction_receipts_also_run_on_a_mission_cache_when_there_is_one(tmp_path, monkeypatch):
    pr.synthetic_cache(tmp_path / "cache" / "m1")
    monkeypatch.setenv("CAFE_DATA", str(tmp_path))
    rows = direction_rows()
    assert len([r for r in rows if "cache m1" in r["name"]]) == 6 and not any("no mission cache" in r["name"] for r in rows)
    assert all(r["kind"] != "fail" for r in rows)


def test_each_direction_receipt_catches_its_own_error(tmp_path, monkeypatch):
    """Break the Stokes drift's north sign: the two Stokes receipts fail, the ones that never touch it still pass."""
    from cafe.pm.env import waves
    pr.synthetic_cache(tmp_path / "c")
    real = waves.stokes_profile
    monkeypatch.setattr(waves, "stokes_profile", lambda E, f, th, z: real(E, f, th, z) * np.array([1.0, -1.0]))     # north sign flipped
    R.OUT.clear()
    pr._direction_receipts("mirrored", tmp_path / "c")
    rows = [pr._row("d", d, {}) for d in R.OUT]
    assert [r["kind"] for r in rows[:2]] == ["pass", "pass"] and rows[2]["kind"] == "fail" and rows[4]["kind"] == "fail"


# ------------------------------------------------------------------ which receipts run


def test_every_receipts_function_in_cafe_pm_is_registered():
    root = pr.ROOT / "cafe" / "pm"
    have = {"pm." + ".".join(p.relative_to(root).with_suffix("").parts) for p in root.rglob("*.py") if re.search(r"^def receipts\(", p.read_text(), re.M)}
    assert len(have) >= 15
    names = [n for n, _ in pr.jobs(True)]
    assert have <= set(names) and len(names) == len(set(names))
    assert names[0] == "app" and "pm.env.wave_direction" in names


def test_slow_groups_are_always_listed_and_slow_swaps_in_the_reruns(monkeypatch):
    monkeypatch.setattr(pr, "_call", lambda mod, fn="receipts", **kw: (mod, fn, kw))
    fast, slow = dict(pr.jobs(False)), dict(pr.jobs(True))
    assert list(fast) == list(slow) and {"app.fea", "pm.physics.uas.slow", "pm.emulator"} <= set(fast)
    assert fast["pm.physics.uas"] == ("cafe.pm.physics.uas", "receipts", dict(sitl=False, sortie=False)) == slow["pm.physics.uas"]
    assert slow["pm.stage3.nest"] is pr._nest_sphere and slow["pm.stage3.wallmodel"] is pr._plate
    assert fast["pm.stage3.nest"][0] == "cafe.pm.stage3.nest" and fast["pm.stage3.wallmodel"][0] == "cafe.pm.stage3.wallmodel"


def test_stored_data_directories_are_passed_only_when_they_exist(tmp_path, monkeypatch):
    monkeypatch.setenv("CAFE_DATA", str(tmp_path))
    monkeypatch.setattr(pr, "_call", lambda mod, fn="receipts", **kw: kw)
    j = dict(pr.jobs())
    assert j["pm.env.tao"] == {"out_dir": None} and j["pm.env.bathy"] == {"cache": None}
    (tmp_path / "tao").mkdir()
    (tmp_path / "bathy").mkdir()
    (tmp_path / "bathy" / "gebco2026_tepex_c.npz").write_bytes(b"")
    j = dict(pr.jobs())
    assert j["pm.env.tao"] == {"out_dir": tmp_path / "tao"} and j["pm.env.bathy"] == {"cache": tmp_path / "bathy" / "gebco2026_tepex_c.npz"}


def test_call_resolves_the_module_function_lazily():
    assert pr._call("builtins", "dict", a=1)() == {"a": 1}


def test_app_receipts_run_in_the_order_of_cafe_receipts_main_without_fea(monkeypatch, tmp_path):
    order = []
    for n in ("geometry_receipts", "env_receipts", "weather_receipts", "dynamics_receipts", "hull_lift_algebra_receipts", "ocean_receipts", "bem_receipts",
              "fleet_receipts"):
        monkeypatch.setattr(R, n, lambda n=n: order.append(n))
    monkeypatch.setattr(R, "fea_receipts", lambda: order.append("fea"))
    monkeypatch.setattr(R, "cfd_receipts", lambda r: order.append("cfd") or R.receipt("CFD", "stored", 1.0, 1.0, 0.1))
    monkeypatch.setattr(R, "crosscheck_receipts", lambda r: order.append("cross"))
    pr._app(tmp_path)
    assert order == ["geometry_receipts", "env_receipts", "weather_receipts", "dynamics_receipts", "hull_lift_algebra_receipts", "ocean_receipts",
                     "bem_receipts", "fleet_receipts", "cfd", "cross"]
    assert R.OUT[0]["group"] == "CFD" and R.OUT[0].get("kind") != "context"
    assert R.OUT[1]["group"] == "Emulator" and R.OUT[1]["kind"] == "context" and "the SITL cross-check" in R.OUT[1]["claim"]


def test_absent_optional_cfd_results_are_a_context_row_not_silence(monkeypatch, tmp_path):
    for n in ("geometry_receipts", "env_receipts", "weather_receipts", "dynamics_receipts", "hull_lift_algebra_receipts", "ocean_receipts", "bem_receipts",
              "fleet_receipts"):
        monkeypatch.setattr(R, n, lambda: None)
    monkeypatch.setattr(R, "cfd_receipts", lambda r: None)
    monkeypatch.setattr(R, "crosscheck_receipts", lambda r: None)
    pr._app(tmp_path)
    assert [(d["group"], d["kind"]) for d in R.OUT] == [("CFD", "context"), ("Emulator", "context")]


def test_the_app_job_reads_its_stored_runs_from_the_env_var(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(pr, "_app", lambda r: seen.append(r))
    monkeypatch.setenv("CAFE_APP_RUNS", str(tmp_path))
    dict(pr.jobs())["app"]()
    monkeypatch.delenv("CAFE_APP_RUNS")
    dict(pr.jobs())["app"]()
    assert seen == [tmp_path, pathlib.Path("/work/runs")]


def test_fea_job_calls_the_apps_fea_receipts(monkeypatch):
    monkeypatch.setattr(R, "fea_receipts", lambda: R.context("FEA", "called", 1.0, 1.0))
    pr._fea()
    assert R.OUT[0]["group"] == "FEA"


def test_plate_job_pops_the_force_field_before_the_receipts_read_it(monkeypatch):
    from cafe.pm.stage3 import wallmodel
    got = {}
    monkeypatch.setattr(wallmodel, "flat_plate", lambda **kw: dict(kw, force=1, cf=0.1))
    monkeypatch.setattr(wallmodel, "receipts", lambda plate=None: got.setdefault("plate", plate) or "done")
    assert pr._plate() == dict(wallmodel.PLATE_SLOW, cf=0.1) and "force" not in got["plate"]


def test_nest_sphere_job_uses_a_scratch_directory_and_restores_the_stored_one(monkeypatch):
    from cafe.pm.stage3 import nest
    stored, calls = nest.SLOW_DIR, []
    monkeypatch.setattr(nest, "main", lambda argv: calls.append((argv, nest.SLOW_DIR)))
    monkeypatch.setattr(nest, "receipts", lambda: calls.append(("receipts", nest.SLOW_DIR)) or ["r"])
    assert pr._nest_sphere() == ["r"]
    assert calls[0][0] == ["slow", "100", "16", "14", "8", "8"] and calls[0][1] != stored and calls[1][1] == calls[0][1] and nest.SLOW_DIR == stored

    def boom():
        raise RuntimeError("kernel failed")
    monkeypatch.setattr(nest, "receipts", boom)
    with pytest.raises(RuntimeError):
        pr._nest_sphere()
    assert nest.SLOW_DIR == stored


# ------------------------------------------------------------------ slow groups: stored, fresh, stale, missing


CURRENT = "digest-of-this-code"


@pytest.fixture
def slowenv(tmp_path, monkeypatch):
    monkeypatch.setenv("CAFE_DATA", str(tmp_path))
    monkeypatch.setattr(pr, "code_digest", lambda scope: f"{CURRENT}-{scope}")
    return tmp_path


def run_group(monkeypatch, group, slow, runner=passing, **kw):
    monkeypatch.setattr(pr, "jobs", lambda s=False: [(group, pr.slow_group(group, 7, "pm", runner, slow, **kw))])
    return pr.collect(log=lambda s: None)


def test_a_slow_group_with_no_stored_result_is_a_fail_with_the_command(slowenv, monkeypatch):
    rows = run_group(monkeypatch, "pm.emulator", slow=False)
    assert len(rows) == 1 and rows[0]["id"] == "pm.emulator:not_run" and rows[0]["ok"] is False and rows[0]["kind"] == "fail"
    assert rows[0]["note"].startswith("not run on this code: `python -m cafe.pm receipts --slow --only pm.emulator` (≈7 min)")
    assert "no stored result at" in rows[0]["note"] and "pipeline.code_digest()" in rows[0]["note"] and R.OUT == []


def test_slow_stores_the_rows_with_provenance_and_a_fresh_default_run_reads_them_back_as_a_pass(slowenv, monkeypatch):
    rows = run_group(monkeypatch, "pm.emulator", slow=True)
    assert [r["kind"] for r in rows] == ["pass"]
    rec = json.loads((slowenv / "receipts" / "pm.emulator.json").read_text())
    assert rec["group"] == "pm.emulator" and rec["code_digest"] == f"{CURRENT}-pm" and rec["scope"] == "pm" and rec["rows"][0]["claim"] == "close"
    assert {"git_sha", "date", "host", "seconds"} <= set(rec) and rec["date"].endswith("+00:00") and not list((slowenv / "receipts").glob("*.tmp"))
    R.OUT.clear()
    back = run_group(monkeypatch, "pm.emulator", slow=False)
    assert [r["kind"] for r in back] == ["pass"] and back[0]["ok"] is True and "[stored " in back[0]["source"] and rec["host"] in back[0]["source"]
    assert back[0]["value"] == rows[0]["value"] and all(r["id"] != "pm.emulator:not_run" for r in back)


def test_a_stored_result_from_different_code_is_a_fail(slowenv, monkeypatch):
    run_group(monkeypatch, "pm.emulator", slow=True)
    R.OUT.clear()
    monkeypatch.setattr(pr, "code_digest", lambda scope: "somebody-edited-the-tree")
    rows = run_group(monkeypatch, "pm.emulator", slow=False)
    assert [(r["id"], r["kind"]) for r in rows] == [("pm.emulator:not_run", "fail")]
    assert "was made by different code" in rows[0]["note"] and "(≈7 min)" in rows[0]["note"] and R.OUT == []


def test_a_stored_fail_stays_a_fail(slowenv, monkeypatch):
    rows = run_group(monkeypatch, "pm.emulator", slow=True, runner=failing)
    assert [r["kind"] for r in rows] == ["fail"]
    R.OUT.clear()
    back = run_group(monkeypatch, "pm.emulator", slow=False)
    assert [(r["kind"], r["ok"]) for r in back] == [("fail", False)] and back[0]["id"] != "pm.emulator:not_run"
    assert pr.summary(back)[0]["fail"] == 1


def test_slow_keeps_only_the_rows_the_group_owns(slowenv, monkeypatch):
    def both():
        passing()
        R.receipt("Keep", "owned", 1.0, 1.0, 0.1)
    rows = run_group(monkeypatch, "pm.physics.uas.slow", slow=True, runner=both, keep=lambda d: d["group"] == "Keep")
    assert [r["name"] for r in rows] == ["Keep: owned"]
    assert [d["claim"] for d in json.loads((slowenv / "receipts" / "pm.physics.uas.slow.json").read_text())["rows"]] == ["owned"]


def test_a_failing_slow_run_stores_nothing(slowenv, monkeypatch):
    rows = run_group(monkeypatch, "pm.emulator", slow=True, runner=raising)
    assert any(r["name"] == "pm.emulator raised KeyError" and r["kind"] == "fail" for r in rows) and not (slowenv / "receipts").exists()


def test_default_run_exits_non_zero_while_a_required_group_is_not_run(slowenv, monkeypatch):
    def jobs_with(slow):
        return lambda s=False: [("a", passing), ("g", pr.slow_group("g", 3, "pm", passing, slow))]
    monkeypatch.setattr(pr, "jobs", jobs_with(False))
    rows, code = pr.run(out=slowenv / "t.json", log=lambda s: None)
    assert code == 1 and sorted(r["kind"] for r in rows) == ["fail", "pass"]
    monkeypatch.setattr(pr, "jobs", jobs_with(True))
    assert pr.run(slow=True, out=slowenv / "t.json", log=lambda s: None)[1] == 0
    monkeypatch.setattr(pr, "jobs", jobs_with(False))
    assert pr.run(out=slowenv / "t.json", log=lambda s: None)[1] == 0


def test_the_digests_follow_the_files(tmp_path):
    from cafe.pm import pipeline
    assert pr.code_digest("pm") == pipeline.code_digest()
    pr_root = pr.ROOT
    try:
        pr.ROOT = tmp_path
        (tmp_path / "cafe" / "sub").mkdir(parents=True)
        (tmp_path / "cafe" / "fea.py").write_text("a = 1\n")
        (tmp_path / "cafe" / "sub" / "x.py").write_text("b = 1\n")
        d1 = pr.code_digest("app")
        (tmp_path / "cafe" / "sub" / "x.py").write_text("b = 2\n")
        assert pr.code_digest("app") == d1                                       # only the app's top-level modules count
        (tmp_path / "cafe" / "fea.py").write_text("a = 2\n")
        assert pr.code_digest("app") != d1 and len(d1) == 64
    finally:
        pr.ROOT = pr_root


# ------------------------------------------------------------------ end to end and the command line


def test_make_broken_semantics_on_the_real_wave_receipts(tmp_path, monkeypatch):
    """The exit code `make broken` returns: 0 exactly when the wrong wave-direction convention fails a receipt through the real code."""
    monkeypatch.setenv("CAFE_DATA", str(tmp_path))
    only = ["pm.env.waves", "wave_direction"]
    rows, code = pr.run(only=only, out=tmp_path / "ok.json", log=lambda s: None)
    assert code == 0 and not [r for r in rows if r["kind"] == "fail"], [r["name"] for r in rows if r["kind"] == "fail"]
    R.OUT.clear()
    rows, code = pr.run(only=only, broken=BROKEN, out=tmp_path / "bad.json", log=lambda s: None)
    failed = {r["id"].split("/")[0] for r in rows if r["kind"] == "fail"}
    assert code == 0 and failed == {"pm.env.waves", "pm.env.wave_direction"} and cv.OVERLAY_ENV not in __import__("os").environ
    assert sum(r["kind"] == "fail" for r in rows) >= 6


def test_cli_receipts_passes_its_flags_and_returns_the_exit_code(monkeypatch, capsys):
    got = []
    monkeypatch.setattr(pr, "run", lambda *a: got.append(a) or ([], 7))
    assert cli.main(["receipts"]) == 7 and got[-1] == (False, None, None, None)
    assert cli.main(["receipts", "--slow", "--only", "a,b", "--broken", "x.yaml", "--json", "o.json"]) == 7
    assert got[-1] == (True, ["a", "b"], "x.yaml", "o.json")
