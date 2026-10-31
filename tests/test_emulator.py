"""Tests for cafe.pm.emulator."""
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
    t0 = time.perf_counter()
    for _ in range(30):
        r = em.query(x)
    assert (time.perf_counter() - t0) / 30 < 0.010
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
