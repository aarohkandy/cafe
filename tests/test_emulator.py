"""Tests for cafe.pm.emulator."""
import contextlib
import pathlib
import sys
import threading
import time

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, strategies as st

from cafe.pm import emulator as E
from cafe.pm.stats import intervals as I


@pytest.fixture(scope="module")
def fitted(tmp_path_factory):
    df = E.synthetic_table(500, 3)
    em = E.Emulator(E.FEATURES, E.TARGETS, path=tmp_path_factory.mktemp("em") / "train.parquet", seed=3)
    em.fit(df, holdout=0.2)
    return em, df


def test_the_emulators_seed_reaches_smt_in_both_the_single_and_the_multi_fidelity_fit(tmp_path):
    """SMT draws the random starts of its hyper-parameter search from its own `seed` option (None: a different draw every call, and on a table
    where a start other than the first wins, a different fit): the Emulator's seed must reach it, or two same-seed runs of the pipeline can
    disagree in every emulated number. Same seed twice gives the same predictions; the option is what makes that a guarantee."""
    df = E.synthetic_table(160, 3)
    ems = []
    for name in ("a", "b"):
        em = E.Emulator(E.FEATURES, E.TARGETS, path=tmp_path / f"{name}.parquet", seed=5)
        em.fit(df, holdout=0.2)
        ems.append(em)
    a, b = ems
    assert all(m.options["seed"] == 5 for m in a.models.values()) and a.holdout == b.holdout
    x = df.iloc[:20][E.FEATURES]
    pa, pb = a.predict(x), b.predict(x)
    assert all(np.array_equal(pa[t][k], pb[t][k]) for t in E.TARGETS for k in ("value", "lo", "hi", "std"))
    mf = E.Emulator(["a", "b"], ["p_fail"], path=tmp_path / "mf.parquet", seed=7)
    mf.fit(_two_fidelity(8))
    assert mf.multi_fidelity and mf.models["p_fail"].options["seed"] == 7


# ---- acceptance (BRIEF 2.7) ----------------------------------------------------------------------------------------
def test_holdout_rmse_and_coverage(fitted):
    em, df = fitted
    h = em.holdout
    assert h["n_test"] == 100 and h["n_train"] == 400 and h["nominal"] == 0.9
    assert h["rmse"]["p_fail"] <= 0.05
    assert abs(h["coverage"]["p_fail"] - 0.90) <= 0.05
    assert all(abs(c - 0.9) <= 0.1 for c in h["coverage"].values())
    # the emulator beats "predict the training mean" by a wide margin
    assert h["rmse"]["p_fail"] < 0.5 * df.p_fail.std()


def test_query_under_10_ms_and_format(fitted):
    em, df = fitted
    x = df.iloc[0][E.FEATURES]
    em.query(x)
    best = []
    for _ in range(5):                       # the fastest of 5 rounds of 30 times the code, not the load (one round read 14.9 ms beside 6 test workers)
        t0 = time.perf_counter()
        for _ in range(30):
            r = em.query(x)
        best.append((time.perf_counter() - t0) / 30)
    assert min(best) < 0.010
    assert r["status"] == "ok" and r["badge"] == "EMULATED" and r["verdict"] in ("GO", "MARGINAL", "NO-GO")
    pf = r["targets"]["p_fail"]
    assert 0 <= pf["lo"] <= pf["value"] <= pf["hi"] <= 1 and set(r["targets"]) == set(E.TARGETS)
    assert r["verdict"] == I.verdict_from_p(pf["value"]) and r["n_train"] == 500
    wide = em.query(x, alpha=0.01)["targets"]["p_fail"]
    assert wide["hi"] - wide["lo"] > pf["hi"] - pf["lo"]


def test_query_input_forms_agree(fitted):
    em, df = fitted
    row = df.iloc[5]
    a = em.query(row[E.FEATURES])["targets"]["p_fail"]["value"]
    assert a == em.query(row[E.FEATURES].to_dict())["targets"]["p_fail"]["value"]
    assert a == em.query(row[E.FEATURES].to_numpy(float))["targets"]["p_fail"]["value"]
    assert a == em.query(df.iloc[[5]])["targets"]["p_fail"]["value"]


def test_out_of_range_returns_no_number(fitted):
    em, df = fitted
    far = df.iloc[0][E.FEATURES].copy()
    far["wind_mean"] = 40.0
    r = em.query(far)
    assert r["status"] == "out_of_range" and r["distance"] > r["threshold"] and "targets" not in r and "verdict" not in r
    assert em.distance(df.iloc[0][E.FEATURES]) == 0.0
    # threshold is the 99th percentile of leave-one-out NN distances, so ~1 % of training rows exceed it
    z = (df[E.FEATURES].to_numpy() - em.mu) / em.sd
    d = np.sort(np.linalg.norm(z[:, None] - z[None], axis=2), axis=1)[:, 1]
    assert abs(np.mean(d > em.threshold) - 0.01) < 0.01


def test_conformal_coverage_holds_on_fresh_draws(fitted):
    em, _ = fitted
    s = em.score(E.synthetic_table(400, 99))
    assert abs(s["coverage"]["p_fail"] - 0.9) < 0.06 and s["n_test"] == 400


def test_exact_zero_and_one_targets_are_covered_on_the_calibration_scale_not_missed_on_the_raw_p_scale(tmp_path):
    """Round 4 M-3. Stage-1 P(fail) is k / 32, so about a quarter of the rows are exactly 0 or 1; the intervals are conformal on the clipped logit, where
    those rows are the clip and can be inside, but a sigmoid interval never reaches 0 or 1, so on the raw P scale they are always misses and a calibrated
    emulator read 0.7 against 0.9. `coverage` is the calibration-scale number (what the gate uses), `coverage_raw_p` the other. Five seeds: with 30
    calibration rows one seed's realised coverage scatters by about 0.05 (seed 3 here: 0.96), so the band is 0.85 to 0.97 each and 0.03 on the mean."""
    cov, raw = [], []
    for seed in range(5):
        df = E.synthetic_table(550, seed, members=32)
        em = E.Emulator(E.FEATURES, ["p_fail", "t_fail_h"], path=tmp_path / f"{seed}.csv", seed=seed)
        em.fit(df.iloc[:150])
        test = df.iloc[150:]
        s = em.score(test)
        assert s["n_test"] == 400 and test.p_fail.isin([0.0, 1.0]).mean() > 0.15                  # the exact 0 and 1 rows are in the n
        assert set(s["coverage_raw_p"]) == {"p_fail"} and set(s["coverage"]) == {"p_fail", "t_fail_h"}
        cov.append(s["coverage"]["p_fail"])
        raw.append(s["coverage_raw_p"]["p_fail"])
        assert 0.85 <= cov[-1] <= 0.97 and raw[-1] < cov[-1] - 0.1
    assert abs(np.mean(cov) - 0.9) <= 0.03 and np.mean(raw) < 0.8                           # the gate number passes (limit 0.05), the old one would not


def test_the_predicted_bounds_are_exposed_on_the_model_scale_and_map_back_to_the_probability_bounds():
    em = E.Emulator(["a"], ["p_fail", "t"], path="x.csv")
    df = pd.DataFrame(dict(a=np.linspace(0, 1, 40), p_fail=np.clip(np.linspace(0, 1.2, 40) - 0.1, 0, 1), t=np.linspace(0, 5, 40)))
    em.fit(df)
    p = em.predict(df.iloc[:5][["a"]])
    assert np.allclose(E._sigmoid(p["p_fail"]["lo_z"]), p["p_fail"]["lo"]) and np.allclose(E._sigmoid(p["p_fail"]["hi_z"]), p["p_fail"]["hi"])
    assert np.array_equal(p["t"]["lo_z"], p["t"]["lo"])                                       # a non-probability target: the same scale


def test_receipts_pass_and_fail_when_calibration_is_wrong(monkeypatch):
    from cafe import receipts as R

    R.OUT.clear()
    rs = E.receipts()
    assert len(rs) == 5 and all(r["ok"] for r in rs)
    real = E._conformal_q
    monkeypatch.setattr(E, "_conformal_q", lambda s, a: 0.1 * real(s, a))       # miscalibrated: intervals far too narrow
    R.OUT.clear()
    bad = E.receipts()
    assert [r["claim"] for r in bad if not r["ok"]] == ["conformal coverage at 90 % nominal, P(fail) (20 % held out)"]
    R.OUT.clear()


# ---- conformal and transforms --------------------------------------------------------------------------------------
@given(st.lists(st.floats(0, 100, allow_nan=False), min_size=1, max_size=200), st.floats(0.01, 0.5))
def test_conformal_q_guarantee_and_monotone(scores, alpha):
    s = np.array(scores)
    q = E._conformal_q(s, alpha)
    if np.isfinite(q):
        assert np.mean(s <= q) >= (1 - alpha) * len(s) / (len(s) + 1) + 1e-12 or np.mean(s <= q) >= 1 - alpha
        assert E._conformal_q(s, alpha / 2) >= q
    else:
        assert np.ceil((len(s) + 1) * (1 - alpha)) > len(s)


def test_conformal_q_values():
    assert E._conformal_q(np.arange(1.0, 10.0), 0.2) == 8.0          # ceil(10*0.8) = 8th smallest
    assert E._conformal_q(np.arange(1.0, 10.0), 0.05) == np.inf and E._conformal_q(np.array([]), 0.1) == np.inf


@given(st.floats(0, 1))
def test_logit_roundtrip_stays_in_unit_interval(p):
    z = E._logit(np.array([p]), 1e-3)
    back = E._sigmoid(z)[0]
    assert 1e-3 - 1e-12 <= back <= 1 - 1e-3 + 1e-12
    if 1e-3 < p < 1 - 1e-3:
        assert abs(back - p) < 1e-9


def test_probability_targets_are_logit_scaled_others_are_not():
    em = E.Emulator(["a"], ["p_fail", "m"], path="x.csv")
    assert em._tf("m", np.array([2.0]))[0] == 2.0 and em._tf("p_fail", np.array([0.5]))[0] == 0.0
    assert em._inv("m", np.array([2.0]))[0] == 2.0 and em._inv("p_fail", np.array([0.0]))[0] == 0.5
    assert E.Emulator(["a"], ["q"], path="x.csv").prob == []
    assert E.Emulator(["a"], ["q"], prob_targets=["q"], path="x.csv").prob == ["q"]


# ---- storage -------------------------------------------------------------------------------------------------------
def test_store_path_falls_back_to_csv_without_pyarrow(monkeypatch, tmp_path):
    monkeypatch.setattr(E.importlib.util, "find_spec", lambda name: None)
    p, fmt = E.store_path(tmp_path / "train.parquet")
    assert p.suffix == ".csv" and "pyarrow" in fmt
    assert E.store_path(tmp_path / "t.csv") == (tmp_path / "t.csv", "csv")
    monkeypatch.setattr(E.importlib.util, "find_spec", lambda name: object())
    assert E.store_path(tmp_path / "train.parquet") == (tmp_path / "train.parquet", "parquet")


def test_append_roundtrip_exact_and_validates(tmp_path):
    em = E.Emulator(["a", "b"], ["p_fail"], path=tmp_path / "emulator" / "train.csv")
    em.append(dict(a=0.1 + 0.2, b=1 / 3, p_fail=0.123456789012345))
    em.append(dict(a=2.0, b=3.0, p_fail=0.5, fidelity=1))
    t = em.table()
    assert len(t) == 2 and t.a[0] == 0.1 + 0.2 and t.b[0] == 1 / 3 and t.p_fail[0] == 0.123456789012345
    with pytest.raises(KeyError):
        em.append(dict(a=1.0))
    assert not list((tmp_path / "emulator").glob("*.tmp"))


def test_parquet_path_is_used_when_pyarrow_is_present(monkeypatch, tmp_path):
    """pyarrow is not in the image; stand in for its reader/writer to prove the .parquet branch is wired."""
    seen = []
    monkeypatch.setattr(E.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(pd.DataFrame, "to_parquet", lambda self, p: (seen.append("w"), self.to_csv(p, index=False))[0])
    monkeypatch.setattr(pd, "read_parquet", lambda p: (seen.append("r"), pd.read_csv(p))[1])
    em = E.Emulator(["a"], ["p_fail"], path=tmp_path / "train.parquet")
    em.append(dict(a=1.0, p_fail=0.2))
    em.append(dict(a=2.0, p_fail=0.3))
    assert em.store_format == "parquet" and len(em.table()) == 2 and seen.count("w") == 2 and "r" in seen


@pytest.mark.parametrize("name,content", [("train.parquet", b"this is not a table"), ("train.parquet", b""), ("train.csv", b"")],
                         ids=["parquet garbage", "parquet zero bytes", "csv zero bytes"])  # csv garbage is a one-line header: an empty table
def test_an_unreadable_training_table_is_a_config_error_naming_the_file_not_an_empty_table(tmp_path, name, content):
    """Round 4 M-23: the pyarrow/pandas error named nothing and told nobody what to do; the file is not treated as empty (the next write would
    replace its rows silently)."""
    from cafe.pm.config import ConfigError
    f = tmp_path / name
    f.write_bytes(content)
    with pytest.raises(ConfigError, match=rf"training table {f} cannot be read \(\w+\); move it aside \(rows in it are lost\)"):
        E.read_table(f)
    assert f.read_bytes() == content


def test_a_truncated_parquet_table_is_a_config_error_too(tmp_path):
    from cafe.pm.config import ConfigError
    f = tmp_path / "t.parquet"
    pd.DataFrame(dict(a=np.arange(50.0), p_fail=np.linspace(0, 1, 50))).to_parquet(f)
    f.write_bytes(f.read_bytes()[:-60])
    with pytest.raises(ConfigError, match="cannot be read"):
        E.read_table(f)
    with pytest.raises(FileNotFoundError):                                                          # a missing file is the caller's business, as before
        E.read_table(tmp_path / "none.parquet")


def test_fit_reads_stored_table(tmp_path):
    df = E.synthetic_table(60, 1)
    em = E.Emulator(E.FEATURES, E.TARGETS, path=tmp_path / "t.csv")
    for _, r in df.iterrows():
        em.append(r.to_dict())
    em.fit()
    assert em.n_train + em.n_cal == 60 and em.query(df.iloc[0][E.FEATURES])["status"] == "ok"


# ---- fidelity, high dimension, small data --------------------------------------------------------------------------
def _two_fidelity(n_hi):
    rng = np.random.default_rng(0)
    hi = lambda x: 1 / (1 + np.exp(-(3 * x[:, 0] - 1.5 + x[:, 1])))                  # noqa: E731
    lo = lambda x: 1 / (1 + np.exp(-(2.4 * x[:, 0] - 1.2 + 0.8 * x[:, 1] + 0.2)))    # noqa: E731
    x = rng.random((80, 2))
    xh = rng.random((n_hi, 2))
    return pd.DataFrame(dict(a=np.r_[x[:, 0], xh[:, 0]], b=np.r_[x[:, 1], xh[:, 1]], p_fail=np.r_[lo(x), hi(xh)],
                             fidelity=np.r_[np.zeros(80), np.ones(n_hi)]))


def test_cokriging_only_with_three_high_fidelity_rows(tmp_path):
    two = E.Emulator(["a", "b"], ["p_fail"], path=tmp_path / "x.csv")
    two.fit(_two_fidelity(2))
    assert not two.multi_fidelity and two.n_train + two.n_cal == 82            # fidelity ignored: all rows, one level
    mf = E.Emulator(["a", "b"], ["p_fail"], path=tmp_path / "x.csv")
    df = _two_fidelity(8)
    mf.fit(df)
    assert mf.multi_fidelity and mf.ledger({"a": 0.5, "b": 0.5})["multi_fidelity"]
    test = _two_fidelity(40).iloc[80:]
    s = mf.score(test)
    assert s["rmse"]["p_fail"] < 0.15
    # without the low-fidelity rows the same 8 high-fidelity rows alone do worse
    only = E.Emulator(["a", "b"], ["p_fail"], path=tmp_path / "x.csv")
    only.fit(df[df.fidelity == 1])
    assert only.score(test)["rmse"]["p_fail"] > s["rmse"]["p_fail"]
    # all-ones fidelity column and 3-row boundary
    e3 = E.Emulator(["a", "b"], ["p_fail"], path=tmp_path / "x.csv")
    e3.fit(_two_fidelity(3))
    assert e3.multi_fidelity and e3.n_cal == 0


def test_high_dimensional_features_use_kpls(tmp_path):
    rng = np.random.default_rng(0)
    f = [f"f{i}" for i in range(12)]
    df = pd.DataFrame(rng.random((70, 12)), columns=f)
    df["m"] = 2 * df.f0 - df.f1 + 0.01 * rng.standard_normal(70)
    em = E.Emulator(f, ["m"], path=tmp_path / "x.csv")
    em.fit(df)
    assert type(em.models["m"]).__name__ == "KPLS" and em.score(df.iloc[:10])["rmse"]["m"] < 0.5


def test_tiny_calibration_set_gives_trivial_but_valid_intervals(tmp_path):
    em = E.Emulator(E.FEATURES, ["p_fail", "t_fail_h"], path=tmp_path / "x.csv")
    em.fit(E.synthetic_table(12, 0))
    assert em.n_cal == 2
    r = em.predict(E.synthetic_table(3, 1)[E.FEATURES])
    assert (r["p_fail"]["lo"] == 0).all() and (r["p_fail"]["hi"] == 1).all() and np.isinf(r["t_fail_h"]["hi"]).all()
    em2 = E.Emulator(E.FEATURES, ["p_fail"], path=tmp_path / "x.csv")
    em2.fit(E.synthetic_table(2, 0))
    assert em2.n_cal == 0 and em2.n_train == 2


# ---- active learning, flip search, ledger --------------------------------------------------------------------------
def test_next_candidate_is_the_least_known(fitted):
    em, df = fitted
    near = df.iloc[[3, 4]][E.FEATURES].reset_index(drop=True)
    far = near.iloc[[0]].copy()
    far["wind_mean"] = 12.0
    far["hs_max"] = 6.0
    cands = pd.concat([near, far], ignore_index=True)
    i, row = em.next_candidate(cands)
    assert i == 2 and row["wind_mean"] == 12.0


def test_flip_search_finds_the_cheapest_verdict_change(fitted):
    em, df = fitted
    x = df.iloc[np.abs(em.predict(df[E.FEATURES])["p_fail"]["value"] - 0.30).argmin()][E.FEATURES].to_dict()  # the row nearest P = 0.30 (it was the lowest P)
    bounds = {"duty_cycle": (0.2, 1.0), "lon_shift_deg": (-1.0, 1.0), "deploy_shift_h": (-12.0, 12.0)}
    r = em.flip_search(x, bounds)
    assert r["found"] and r["verdict"] != r["base_verdict"]
    moved = dict(x, **{k: x[k] + v for k, v in r["change"].items()})
    assert I.verdict_from_p(em.predict(moved)["p_fail"]["value"][0]) == r["verdict"]
    assert all(bounds[k][0] - 1e-9 <= moved[k] <= bounds[k][1] + 1e-9 for k in bounds)
    # nothing on a coarse single-parameter scan is cheaper
    for k, (lo, hi) in bounds.items():
        for v in np.linspace(lo, hi, 21):
            c = dict(x, **{k: v})
            if abs(v - x[k]) / (hi - lo) < r["cost"] - 1e-9 and em.distance(c) <= em.threshold:
                assert I.verdict_from_p(em.predict(c)["p_fail"]["value"][0]) == r["base_verdict"]


def test_flip_search_reports_when_nothing_flips(fitted):
    em, df = fitted
    x = df.iloc[0][E.FEATURES].to_dict()
    r = em.flip_search(x, {"duty_cycle": (x["duty_cycle"], x["duty_cycle"])})
    assert not r["found"] and r["base_verdict"] in ("GO", "MARGINAL", "NO-GO")


def test_ledger_entry(fitted):
    em, df = fitted
    L = em.ledger(df.iloc[0][E.FEATURES])
    assert L["n_train"] == 500 and L["holdout"]["rmse"]["p_fail"] <= 0.05 and not L["out_of_range"]
    assert L["store_format"] in ("parquet", "csv (pyarrow not installed)")


# ---------------------------------------------------------------------------------------------------------------- review round 1 (M-8)

def test_the_holdout_splits_by_feature_point_so_replicates_never_straddle_it(tmp_path, monkeypatch):
    """M-8: a random row split put copies of one point on both sides of the hold-out, so RMSE and coverage were scored on points the model had trained on."""
    base = E.synthetic_table(40, 1)
    df = pd.concat([base.assign(p_fail=np.clip(base.p_fail + d, 0, 1)) for d in (0.0, 0.01, -0.01)], ignore_index=True)       # three replicates of each point
    em = E.Emulator(E.FEATURES, E.TARGETS, path=tmp_path / "t.parquet", seed=1)
    seen = {}
    real_fit, real_score = E.Emulator.fit, E.Emulator.score
    monkeypatch.setattr(E.Emulator, "fit", lambda self, d, *a, **k: (seen.setdefault("train", d), real_fit(self, d, *a, **k))[1])
    monkeypatch.setattr(E.Emulator, "score", lambda self, d, *a, **k: (seen.setdefault("test", d), real_score(self, d, *a, **k))[1])
    h = em.holdout_report(df)

    def points(d):
        return set(map(tuple, d[E.FEATURES].round(9).to_numpy()))
    assert not points(seen["train"]) & points(seen["test"]) and len(points(seen["test"])) == 8 and len(seen["test"]) == 24
    assert h["n_test"] == 24 and len(seen["train"]) == 96 and h["n_train"] == 96 and len(points(seen["train"])) == 32


def test_a_holdout_of_one_feature_point_is_refused(tmp_path):
    em = E.Emulator(E.FEATURES, E.TARGETS, path=tmp_path / "t.parquet")
    with pytest.raises(ValueError, match="at least two distinct feature points, the table has 1"):
        em.holdout_report(pd.concat([E.synthetic_table(1, 1)] * 5, ignore_index=True))


def test_the_holdout_split_is_reproducible(tmp_path):
    df = E.synthetic_table(60, 2)
    a = E.Emulator(E.FEATURES, E.TARGETS, path=tmp_path / "a.parquet", seed=4).holdout_report(df)
    b = E.Emulator(E.FEATURES, E.TARGETS, path=tmp_path / "b.parquet", seed=4).holdout_report(df)
    assert a == b and a["n_test"] == 12


def test_holdout_report_scores_the_held_out_points_against_fresh_draws_and_stops_at_three(tmp_path):
    """Round 3 M-4: `fresh(row)` re-estimates P(fail) at a held-out row on members no training row used; the emulator trained without that point is scored
    against it. A row `fresh` cannot re-run (None) is skipped, and at most FRESH_POINTS are used."""
    df = E.synthetic_table(160, 3)
    asked = []

    def fresh(row):
        asked.append(row["wind_mean"])
        return None if len(asked) == 1 else (0.5, 64)
    em = E.Emulator(E.FEATURES, E.TARGETS, path=tmp_path / "a.parquet", seed=3)
    h = em.holdout_report(df, fresh=fresh)
    f = h["fresh"]
    assert f["points"] == E.FRESH_POINTS == 3 and len(asked) == 4 and len(set(asked)) == 4 and f["n_members"] == 64 and f["p_fresh"] == [0.5] * 3
    assert len(f["p_emulated"]) == 3 and f["rmse"] == pytest.approx(float(np.sqrt(np.mean((np.array(f["p_emulated"]) - 0.5) ** 2))))
    assert "fresh" not in em.holdout_report(df)                                                  # no callback, no key: the old report
    assert "fresh" not in em.holdout_report(df, fresh=lambda row: None)                          # nothing could be re-run
    em.fit(df, holdout=0.2, fresh=fresh)
    assert em.holdout is not None and em.holdout["fresh"]["points"] == 3                         # fit keeps it for the ledger


def test_write_table_uses_a_temporary_of_its_own_and_leaves_none_behind_when_it_fails(tmp_path, monkeypatch):
    """M-6: every writer renamed the one fixed `train.parquet.tmp`, so two writers raced on it and a failed write left it behind."""
    t = tmp_path / "train.parquet"
    seen = []
    real = E.os.replace
    monkeypatch.setattr(E.os, "replace", lambda a, b: (seen.append(pathlib.Path(a).name), real(a, b)))
    E.write_table(pd.DataFrame(dict(key=["a"], x=[1.0])), t)
    E.write_table(pd.DataFrame(dict(key=["a", "b"], x=[1.0, 2.0])), t)
    assert len(set(seen)) == 2 and "train.parquet.tmp" not in seen and all(n.startswith("train.parquet.") and n.endswith(".tmp") for n in seen)
    assert list(tmp_path.iterdir()) == [t] and len(E.read_table(t)) == 2

    def half(self, name, *a, **k):
        pathlib.Path(name).write_bytes(b"PAR1 half a file")
        raise OSError("disk full")
    monkeypatch.setattr(pd.DataFrame, "to_parquet", half)
    with pytest.raises(OSError, match="disk full"):
        E.write_table(pd.DataFrame(dict(key=["c"], x=[3.0])), t)
    assert list(tmp_path.iterdir()) == [t]                                                  # no half-written temporary; the old table is whole
    monkeypatch.undo()
    assert len(E.read_table(t)) == 2


def test_the_table_lock_makes_a_second_holder_wait_and_is_skipped_without_fcntl(tmp_path, monkeypatch):
    t = tmp_path / "sub" / "train.parquet"
    got = []
    def second():
        with E.locked(t):
            got.append(time.time())
    with E.locked(t):
        th = threading.Thread(target=second)
        th.start()
        time.sleep(0.3)
        assert got == []                                                                    # queued behind the first holder
        released = time.time()
    th.join(10)
    assert got and got[0] >= released and (tmp_path / "sub" / "train.parquet.lock").exists()
    monkeypatch.setitem(sys.modules, "fcntl", None)                                         # `import fcntl` raises ImportError
    with E.locked(t):
        pass


# ---------------------------------------------------------------------------------------------------------------- review round 7: M-6, M-25, M-47

def test_the_range_threshold_ignores_replicate_rows(tmp_path):
    """Round 7 M-25: a row with an exact duplicate has nearest-neighbour distance 0; with replicates of every row the 99 % quantile was 0 and the guard
    refused every query."""
    once = E.synthetic_table(120, 1)
    a = E.Emulator(E.FEATURES, E.TARGETS, path=tmp_path / "a.parquet", seed=2)
    a.fit(once)
    b = E.Emulator(E.FEATURES, E.TARGETS, path=tmp_path / "b.parquet", seed=2)
    b.fit(pd.concat([once] * 5, ignore_index=True))
    assert a.threshold > 0 and b.threshold == pytest.approx(a.threshold, rel=1e-6)
    fresh = E.synthetic_table(1000, 99)
    refused = [float(np.mean(m._dist(m._x(fresh[E.FEATURES])) > m.threshold)) for m in (a, b)]
    assert refused[1] == pytest.approx(refused[0], abs=0.02) and refused[1] < 0.5                  # 1.0 before: every query refused


def test_the_holdout_splits_on_the_point_columns_so_replicates_with_other_noise_columns_stay_together(tmp_path, monkeypatch):
    """Round 7 M-6: replicates of one mission differ in the environment medians of their member draws and were split by the hold-out as distinct points."""
    base = E.synthetic_table(40, 1)
    rng = np.random.default_rng(3)
    df = pd.concat([base.assign(wind_mean=base.wind_mean + 0.01 * rng.normal(size=len(base)), hs_max=base.hs_max + 0.01 * rng.normal(size=len(base)))
                    for _ in range(3)], ignore_index=True)
    cols = ["deploy_shift_h", "lon_shift_deg", "duty_cycle", "battery_wh"]
    em = E.Emulator(E.FEATURES, E.TARGETS, path=tmp_path / "t.parquet", seed=1, point_cols=cols)
    seen = {}
    real_fit, real_score = E.Emulator.fit, E.Emulator.score
    monkeypatch.setattr(E.Emulator, "fit", lambda self, d, *a, **k: (seen.setdefault("train", d), real_fit(self, d, *a, **k))[1])
    monkeypatch.setattr(E.Emulator, "score", lambda self, d, *a, **k: (seen.setdefault("test", d), real_score(self, d, *a, **k))[1])
    h = em.holdout_report(df)

    def points(d):
        return set(map(tuple, d[cols].round(9).to_numpy()))
    assert not points(seen["train"]) & points(seen["test"]) and len(points(seen["test"])) == 8 and h["n_test"] == 24 and h["n_train"] == 96


def test_append_holds_the_table_lock_once(tmp_path, monkeypatch):
    """Round 7 M-47: replacing `with locked(self.path):` by a null context left every test green (row 313)."""
    entered = []

    @contextlib.contextmanager
    def locked(p):
        entered.append(p)
        yield
    monkeypatch.setattr(E, "locked", locked)
    em = E.Emulator(["x"], ["y"], path=tmp_path / "t.parquet")
    em.append(dict(x=1.0, y=2.0))
    assert entered == [tmp_path / "t.parquet"]


def test_threads_appending_to_one_table_lose_none(tmp_path):
    """Round 7 M-47: two read-modify-writes of the table at once keep only the later one unless `append` holds the lock (flock: POSIX)."""
    import fcntl  # noqa: F401  (without it `locked` is no lock and this test has nothing to show)
    em = E.Emulator(["x"], ["y"], path=tmp_path / "t.parquet")
    errs = []

    def add(tag):
        try:
            for i in range(5):
                em.append(dict(x=float(i), y=0.0, key=f"{tag}{i}", pad="p" * 300_000))
        except BaseException as e:                                                              # a thread's failure must fail the test, not vanish
            errs.append(e)
    ts = [threading.Thread(target=add, args=(t,)) for t in "abcd"]
    [t.start() for t in ts]
    [t.join(300) for t in ts]
    assert errs == [] and sorted(E.read_table(tmp_path / "t.parquet")["key"]) == sorted(f"{t}{i}" for t in "abcd" for i in range(5))
