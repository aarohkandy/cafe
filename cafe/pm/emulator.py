"""Mission emulator: feature vector -> P(fail), time-to-fail, margins, with conformal intervals and a range guard.

Model: SMT Kriging (Gaussian-process regression) per target. Chosen over scikit-learn's GaussianProcessRegressor because
SMT is also what provides the Kennedy-O'Hagan co-kriging (MFK) the brief asks for once >= 3 high-fidelity rows exist, so one
library covers both paths; query cost is ~0.3 ms per target at a few hundred rows. Probability targets are modelled on the
logit scale (clipped to [eps, 1 - eps]) and mapped back, so predictions stay in (0, 1).
Intervals: normalized split-conformal prediction (Lei et al. 2018, JASA 113; Vovk et al. 2005): score = |y - mu| / sigma_GP
on a calibration set the GP never saw, interval = mu +- q sigma_GP with q the ceil((n+1)(1-alpha))-th smallest score. Marginal
coverage >= 1 - alpha holds for exchangeable rows whatever the GP does; on the logit scale it carries over to P through
the monotone sigmoid.
Range guard: nearest-neighbour distance in z-scored feature space against the 99th percentile of leave-one-out
nearest-neighbour distances of the training rows; beyond it `query` returns status "out_of_range" and no number.
Multi-fidelity: Kennedy & O'Hagan (2000, Biometrika 87) via SMT MFK (Le Gratiet 2014). SMT documents nested designs; non-nested
rows run but the high-fidelity rows are then not guaranteed to be reproduced exactly.
Storage: emulator/train.parquet needs pyarrow; when it is missing the same table is kept as emulator/train.csv
(`store_format` says which) and read back with round-trip float parsing.
"""
from __future__ import annotations

import importlib.util
import itertools
import pathlib
import time
from typing import Any

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from .stats import intervals

NN_QUANTILE = 0.99


def _conformal_q(scores: np.ndarray, alpha: float) -> float:
    """ceil((n+1)(1-alpha))-th smallest calibration score; inf when the set is too small for that level."""
    n = len(scores)
    k = int(np.ceil((n + 1) * (1 - alpha)))
    return float("inf") if k > n else float(np.partition(scores, k - 1)[k - 1])


def _logit(p: np.ndarray, eps: float) -> np.ndarray:
    p = np.clip(p, eps, 1 - eps)
    return np.log(p / (1 - p))


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-z))


def store_path(path: str | pathlib.Path) -> tuple[pathlib.Path, str]:
    """(file actually used, format): .parquet when pyarrow is installed, else the sibling .csv."""
    path = pathlib.Path(path)
    if path.suffix == ".parquet" and importlib.util.find_spec("pyarrow") is None:
        return path.with_suffix(".csv"), "csv (pyarrow not installed)"
    return path, path.suffix.lstrip(".")


def read_table(path: pathlib.Path) -> pd.DataFrame:
    return pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path, float_precision="round_trip")


def write_table(df: pd.DataFrame, path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    df.to_parquet(tmp) if path.suffix == ".parquet" else df.to_csv(tmp, index=False)
    tmp.replace(path)


class Emulator:
    def __init__(self, features: list[str], targets: list[str], path: str | pathlib.Path = "emulator/train.parquet",
                 prob_targets: list[str] | None = None, eps: float = 1e-3, noise: float = 1e-2, seed: int = 0):
        """`prob_targets` (default: "p_fail" if it is a target) are logit-transformed; `noise` is the GP nugget on the
        normalized scale (the targets are Monte-Carlo estimates, not exact)."""
        self.features, self.targets = list(features), list(targets)
        self.prob = [t for t in (prob_targets if prob_targets is not None else ["p_fail"]) if t in self.targets]
        self.path, self.store_format = store_path(path)
        self.eps, self.noise, self.seed = eps, noise, seed
        self.models: dict[str, Any] = {}
        self.holdout: dict[str, Any] | None = None
        self.multi_fidelity, self.n_train, self.n_cal, self.threshold = False, 0, 0, float("inf")

    # ---- data -------------------------------------------------------------------------------------------------
    def table(self) -> pd.DataFrame:
        return read_table(self.path)

    def append(self, row: dict[str, Any]) -> None:
        """Add one Stage-1 result (all features and targets, optional "fidelity": 0 = L1 ensemble, 1 = L3-refit)."""
        miss = [c for c in self.features + self.targets if c not in row]
        if miss:
            raise KeyError(f"row lacks {miss}")
        new = pd.DataFrame([row])
        write_table(pd.concat([self.table(), new], ignore_index=True) if self.path.exists() else new, self.path)

    def _x(self, x: Any) -> np.ndarray:
        """dict / Series / DataFrame / array -> (m, d) float array in feature order."""
        if isinstance(x, dict):
            x = pd.DataFrame([x])
        if isinstance(x, (pd.DataFrame, pd.Series)):
            x = (x.to_frame().T if isinstance(x, pd.Series) else x)[self.features].to_numpy()
        return np.atleast_2d(np.asarray(x, float))

    def _tf(self, t: str, y: np.ndarray) -> np.ndarray:
        return _logit(y, self.eps) if t in self.prob else np.asarray(y, float)

    def _inv(self, t: str, z: np.ndarray) -> np.ndarray:
        return _sigmoid(z) if t in self.prob else z

    # ---- fit --------------------------------------------------------------------------------------------------
    def _krig(self, x: np.ndarray, y: np.ndarray, levels: list[tuple[np.ndarray, np.ndarray]] | None) -> Any:
        from smt.applications import MFK
        from smt.surrogate_models import KPLS, KRG

        d = x.shape[1]
        m: Any
        if levels:
            m = MFK(print_global=False, theta0=[1.0] * d, n_start=3)
            m.set_training_values(levels[0][0], levels[0][1], name=0)
            m.set_training_values(levels[1][0], levels[1][1])
        else:
            kw = dict(print_global=False, noise0=[self.noise], n_start=3, hyper_opt="Cobyla")
            m = KPLS(n_comp=3, theta0=[1.0] * 3, **kw) if d > 10 else KRG(theta0=[1.0] * d, **kw)
            m.set_training_values(x, y)
        m.train()
        return m

    def fit(self, df: pd.DataFrame | None = None, cal_frac: float = 0.2, holdout: float = 0.0) -> None:
        """Train on `df` (default: the stored table). Co-kriging is used only with >= 3 rows of fidelity 1 and >= 1 of 0.

        `holdout` > 0 first runs `holdout_report` on that fraction and keeps it in `self.holdout` for the ledger.
        """
        df = self.table() if df is None else df
        if holdout:
            self.holdout = self.holdout_report(df, holdout)
        x_all = self._x(df[self.features])
        fid = df["fidelity"].to_numpy() if "fidelity" in df else np.ones(len(df))
        self.multi_fidelity = bool((fid == 1).sum() >= 3 and (fid == 0).sum() >= 1)
        prim = np.flatnonzero(fid == 1) if self.multi_fidelity else np.arange(len(df))
        low = np.flatnonzero(fid == 0) if self.multi_fidelity else np.empty(0, int)
        rng = np.random.default_rng(self.seed)
        perm = rng.permutation(prim)
        n_cal = min(int(round(cal_frac * len(prim))), len(prim) - (3 if self.multi_fidelity else 2))
        cal, tr = perm[:max(n_cal, 0)], perm[max(n_cal, 0):]
        self.mu, self.sd = x_all.mean(0), np.where(x_all.std(0) > 0, x_all.std(0), 1.0)
        z = (x_all - self.mu) / self.sd
        self._tree = cKDTree(z)
        nn = self._tree.query(z, k=2)[0][:, 1]
        self.threshold = float(np.quantile(nn, NN_QUANTILE))
        self.n_train, self.n_cal = len(tr) + len(low), len(cal)
        self.models, self.scores, self.ysd = {}, {}, {}
        for t in self.targets:
            y = self._tf(t, df[t].to_numpy())
            lv = [(x_all[low], y[low]), (x_all[tr], y[tr])] if self.multi_fidelity else None
            self.models[t] = self._krig(x_all[tr], y[tr], lv)
            self.ysd[t] = float(np.std(y[tr])) or 1.0
            mu, sig = self._gp(t, x_all[cal])
            self.scores[t] = np.abs(y[cal] - mu) / sig

    def _gp(self, t: str, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """GP mean and std on the (transformed) model scale; std floored so conformal scores stay finite."""
        if not len(x):                                   # no calibration rows (very small tables): SMT cannot predict on none
            return np.empty(0), np.empty(0)
        m = self.models[t]
        mu = m.predict_values(x)[:, 0]
        sig = np.sqrt(np.maximum(m.predict_variances(x)[:, 0], 0.0)) + 1e-6 * self.ysd[t]
        return mu, sig

    # ---- predict ----------------------------------------------------------------------------------------------
    def predict(self, x: Any, alpha: float = 0.1) -> dict[str, dict[str, np.ndarray]]:
        """{target: {"value", "lo", "hi", "std"}} arrays for the rows of x (interval has coverage >= 1 - alpha)."""
        xa = self._x(x)
        out = {}
        for t in self.targets:
            mu, sig = self._gp(t, xa)
            q = _conformal_q(self.scores[t], alpha)
            lo, hi = (mu - q * sig, mu + q * sig) if np.isfinite(q) else (np.full_like(mu, -np.inf), np.full_like(mu, np.inf))
            out[t] = dict(value=self._inv(t, mu), lo=self._inv(t, lo), hi=self._inv(t, hi), std=sig)
        return out

    def _dist(self, xa: np.ndarray) -> np.ndarray:
        return self._tree.query((xa - self.mu) / self.sd, k=1)[0]

    def distance(self, x: Any) -> float:
        """Nearest-neighbour distance from x to the training rows in z-scored feature space."""
        return float(self._dist(self._x(x))[0])

    def query(self, x: Any, alpha: float = 0.1) -> dict[str, Any]:
        """One mission. Out of range -> status "out_of_range" with the distance and no prediction."""
        d = self.distance(x)
        head = dict(badge="EMULATED", distance=d, threshold=self.threshold, n_train=self.n_train + self.n_cal)
        if d > self.threshold:
            return dict(status="out_of_range", **head)
        p = self.predict(x, alpha)
        res = {t: {k: float(v[0]) for k, v in r.items()} for t, r in p.items()}
        v = intervals.verdict_from_p(res["p_fail"]["value"]) if "p_fail" in res else None
        return dict(status="ok", verdict=v, targets=res, alpha=alpha, **head)

    # ---- evaluation -------------------------------------------------------------------------------------------
    def score(self, df: pd.DataFrame, alpha: float = 0.1) -> dict[str, Any]:
        """RMSE (in native units, P for probabilities) and empirical interval coverage on rows the model never saw."""
        p = self.predict(df[self.features], alpha)
        y = {t: df[t].to_numpy() for t in self.targets}
        return dict(n_test=len(df), nominal=1 - alpha,
                    rmse={t: float(np.sqrt(np.mean((p[t]["value"] - y[t]) ** 2))) for t in self.targets},
                    coverage={t: float(np.mean((p[t]["lo"] <= y[t]) & (y[t] <= p[t]["hi"]))) for t in self.targets})

    def holdout_report(self, df: pd.DataFrame, frac: float = 0.2, alpha: float = 0.1) -> dict[str, Any]:
        """Fit a fresh emulator on the other (1 - frac) of the rows, score on the held-out frac."""
        perm = np.random.default_rng(self.seed + 1).permutation(len(df))
        k = int(round(frac * len(df)))
        fresh = Emulator(self.features, self.targets, self.path, self.prob, self.eps, self.noise, self.seed)
        fresh.fit(df.iloc[perm[k:]])
        return dict(fresh.score(df.iloc[perm[:k]], alpha), n_train=fresh.n_train + fresh.n_cal)

    def ledger(self, x: Any) -> dict[str, Any]:
        """The `emulator` stage ledger entry (BRIEF 5.5): size, held-out RMSE and coverage, distance of the queried mission."""
        d = self.distance(x)
        return dict(n_train=self.n_train + self.n_cal, multi_fidelity=self.multi_fidelity, store_format=self.store_format,
                    holdout=self.holdout, distance=d, threshold=self.threshold, out_of_range=bool(d > self.threshold))

    # ---- use --------------------------------------------------------------------------------------------------
    def next_candidate(self, candidates: pd.DataFrame) -> tuple[int, pd.Series]:
        """Active learning: the candidate row with the largest predictive variance (summed over targets, each in units
        of its training variance). Returns (position, row)."""
        xa = self._x(candidates[self.features])
        acq = sum((self._gp(t, xa)[1] / self.ysd[t]) ** 2 for t in self.targets)
        i = int(np.argmax(acq))
        return i, candidates.iloc[i]

    def flip_search(self, x: dict[str, float], bounds: dict[str, tuple[float, float]], steps: int = 21,
                    pair_steps: int = 5) -> dict[str, Any]:
        """Smallest change in the named parameters that moves the predicted P(fail) verdict across a cut-off (0.10, 0.40).

        Candidates: each parameter alone on `steps` points of its bounds, plus the full grid of all named parameters on
        `pair_steps` points each. Cost = Euclidean norm of the changes scaled by each bound's width. Out-of-range
        candidates are ignored. Returns dict(found, ...); `change` is {name: new - old}.
        """
        names = list(bounds)
        base = np.array([[x[f] for f in self.features]])
        p0 = float(self.predict(base)["p_fail"]["value"][0])
        v0 = intervals.verdict_from_p(p0)
        cols = [self.features.index(n) for n in names]
        grids = [np.linspace(*bounds[n], steps) for n in names]
        singles = [np.tile(base, (steps, 1)) for _ in names]
        for c, j, g in zip(singles, cols, grids, strict=True):
            c[:, j] = g
        full = np.array(list(itertools.product(*[np.linspace(*bounds[n], pair_steps) for n in names])))
        cf = np.tile(base, (len(full), 1))
        cf[:, cols] = full
        cand = np.vstack(singles + [cf])
        width = np.maximum([bounds[n][1] - bounds[n][0] for n in names], 1e-12)
        cost = np.sqrt((((cand[:, cols] - base[:, cols]) / width) ** 2).sum(1))
        p = self.predict(cand)["p_fail"]["value"]
        flips = np.array([intervals.verdict_from_p(q) != v0 for q in p]) & (self._dist(cand) <= self.threshold)
        if not flips.any():
            return dict(found=False, base_p=p0, base_verdict=v0)
        i = int(np.argmin(np.where(flips, cost, np.inf)))
        return dict(found=True, base_p=p0, base_verdict=v0, p=float(p[i]), verdict=intervals.verdict_from_p(p[i]),
                    cost=float(cost[i]), change={n: float(cand[i, j] - base[0, j]) for n, j in zip(names, cols, strict=True)})


def synthetic_table(n: int, seed: int = 0, members: int = 512) -> pd.DataFrame:
    """A realistic stand-in for Stage-1 results (for tests and the receipts, never for training the real emulator).

    P(fail) rises with wind and sea state, with a longitude penalty and a duty-cycle/battery trade-off; the observed
    value is a Binomial(members)/members estimate, so it carries the Monte-Carlo noise a real ensemble has.
    """
    rng = np.random.default_rng(seed)
    df = pd.DataFrame(dict(deploy_shift_h=rng.uniform(-12, 12, n), lon_shift_deg=rng.uniform(-1, 1, n),
                           duty_cycle=rng.uniform(0.2, 1.0, n), wind_mean=rng.uniform(3, 9, n),
                           hs_max=rng.uniform(1, 4, n), battery_wh=rng.uniform(200, 600, n)))
    z = (-3.2 + 0.45 * (df.wind_mean - 6) + 0.9 * (df.hs_max - 2.5) * (df.wind_mean > 6) + 1.2 * df.lon_shift_deg ** 2
         + 2.5 * df.duty_cycle * (400 / df.battery_wh) - 1.5 + 0.25 * np.sin(df.deploy_shift_h / 4))
    p = _sigmoid(z.to_numpy())
    df["p_fail"] = rng.binomial(members, p) / members
    df["t_fail_h"] = 168 / (1 + 6 * p) + rng.normal(0, 2, n)
    df["margin_batt"] = 1 - df.duty_cycle * 400 / df.battery_wh + rng.normal(0, 0.02, n)
    return df


FEATURES = ["deploy_shift_h", "lon_shift_deg", "duty_cycle", "wind_mean", "hs_max", "battery_wh"]
TARGETS = ["p_fail", "t_fail_h", "margin_batt"]


def receipts(n: int = 500, seed: int = 3) -> list[dict[str, Any]]:
    """Held-out accuracy, conformal coverage, query time and the range guard on the synthetic table (all can fail)."""
    from cafe import receipts as R

    n0 = len(R.OUT)
    g = "pm.emulator"
    df = synthetic_table(n, seed)
    em = Emulator(FEATURES, TARGETS, path="emulator/_receipt.csv", seed=seed)
    rep = em.holdout_report(df)
    em.fit(df)
    R.bracket(g, "held-out RMSE of P(fail) (20 % held out)", rep["rmse"]["p_fail"], 0.0, 0.05, "P",
              "BRIEF 2.7 acceptance")
    R.bracket(g, "conformal coverage at 90 % nominal, P(fail) (20 % held out)", rep["coverage"]["p_fail"], 0.85, 0.95,
              "fraction", "BRIEF 2.7: within +-5 % of nominal; Lei et al. 2018")
    x = df.iloc[0][FEATURES]
    ts = []
    for _ in range(50):
        t0 = time.perf_counter()
        em.query(x)
        ts.append(time.perf_counter() - t0)
    R.bracket(g, "median query time", 1e3 * float(np.median(ts)), 0.0, 10.0, "ms", "BRIEF 2.7 acceptance")
    far = x.copy()
    far["wind_mean"] = 40.0
    R.bracket(g, "far-off mission distance / calibrated threshold", em.distance(far) / em.threshold, 1.0, 1e9, "",
              "99th percentile of leave-one-out NN distances")
    R.bracket(g, "training mission distance / calibrated threshold", em.distance(x) / em.threshold, 0.0, 1.0, "",
              "99th percentile of leave-one-out NN distances")
    return R.OUT[n0:]
