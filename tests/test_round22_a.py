"""Round 22, batch A: the label of an acoustic link. M-2 (one count record for the path with Bellhop and the one without, one label function, `merge` sums
and rebuilds: independent of the batch order), M-3 (the label says each member is run on one pair of transducer depths), M-12 (`far_ge`: a sample at exactly the
cap is counted once), and the enumeration of every key `merge` handles (OD-3: a test, no runtime check)."""
import itertools
import types

import numpy as np
import pytest

from cafe.pm import stage1
from cafe.pm.env.protocol import AnalyticEnv
from cafe.pm.physics import comms
from tests.test_stage1 import MISSION, bellhop_scene

CAP = comms.BELLHOP_EXCESS_CAP_DB
LINK = "glider_eq-ship-acoustic"
DEPTHS = ", each member on one pair of transducer depths, not one per sample"
HEAD = "Thorp/Stojanovic budget on the slant range"


def _further(beyond):
    return (f"; a further {beyond} needed in-range samples are more than {CAP:g} dB from a pass or a fail on Thorp and keep that margin: the Bellhop excess is "
            f"held within {CAP:g} dB, so it cannot change which they are") if beyond else ""


def _none_asked(beyond):
    return (f"{HEAD}; Bellhop was not run: all {beyond} needed in-range samples are more than {CAP:g} dB from a pass or a fail on Thorp, and the Bellhop "
            f"excess is held within {CAP:g} dB, so it cannot change which they are")


def _world(rng, n=14, M=5):
    """Margins (carried in `d`, see `_fake_world`) with every boundary value in them, and the masks."""
    pool = np.array([CAP, -CAP, np.nextafter(CAP, np.inf), np.nextafter(-CAP, -np.inf), np.nextafter(CAP, 0.0), 0.0, np.nan, np.inf, -np.inf])
    margin = np.where(rng.random((n, M)) < 0.35, rng.choice(pool, (n, M)), rng.uniform(-120.0, 120.0, (n, M)))
    need = rng.random((n, M)) < 0.7
    valid = rng.random((n, M)) < 0.8
    dead = rng.random(M) < 0.3                                                  # members that never needed the link, or only out of range
    need[:, dead] = rng.random() < 0.5
    valid[:, dead & (rng.random(M) < 0.5)] = False
    depth = rng.uniform(0.0, 300.0, (2, n, M))
    return margin, need, valid, depth


def _acoustic(margin, need, valid, depth, cols):
    """`stage1._acoustic` on the members `cols`, the Thorp margin being `margin` itself (the fake `comms.acoustic_link` returns its `d`)."""
    z = np.zeros((margin.shape[0], len(cols)))
    A = (z, z, z, depth[0][:, cols])
    B = (z, z, z, depth[1][:, cols])
    return stage1._acoustic("m", "b", margin[:, cols], z, z, need[:, cols], valid[:, cols], A, B, np.arange(margin.shape[0], dtype=float), None)


@pytest.fixture
def fake_world(monkeypatch):
    """Bellhop availability is `avail[0]`; `calls` records (tx, rx) of every `_bellhop_member` call. A member whose median transmitter depth truncates to a
    multiple of 5 has no profile there (None); the others give margin 1.0 less than their Thorp margin, one run to three by depth, and a sample is 'capped'
    when its margin truncates to an even number."""
    avail, calls = [False], []
    monkeypatch.setattr(comms, "acoustic_link", lambda d, modem, band, wind, dz=0.0, **k: dict(margin=types.SimpleNamespace(value=np.array(d, float))))
    monkeypatch.setattr(comms, "bellhop_available", lambda: avail[0])

    def member(env, modem, band, lon, lat, t, tx, rx, d, dz, wind):
        calls.append((tx, rx, d.size))
        if int(tx) % 5 == 0:
            return None
        return stage1._Refined(d - 1.0, np.zeros(d.shape), 1 + int(tx) % 3, np.floor(np.abs(d)) % 2 == 0)
    monkeypatch.setattr(stage1, "_bellhop_member", member)
    return avail, calls


def _expected(margin, need, valid, depth, on):
    """The label and the counts of one run over ALL the members, from the masks alone (independent of `_acoustic` and `_bellhop_label`)."""
    cand = need & valid
    with np.errstate(invalid="ignore"):
        far, refine = cand & (np.abs(margin) > CAP), cand & (np.abs(margin) <= CAP)
    total, beyond = int(refine.sum()), int(far.sum())
    if not (total or beyond):
        return comms.THORP_DECIDES_LABEL, None
    if not total:
        return _none_asked(beyond), dict(done=0, total=0, capped=0, beyond=beyond)
    if not on:
        return f"{comms.THORP_ONLY_LABEL}: {total} needed in-range samples that Bellhop would refine keep their Thorp margin{_further(beyond)}", \
            dict(done=0, total=total, capped=0, beyond=beyond)
    done = capped = 0
    runs = []
    for m in np.flatnonzero(refine.any(0)):
        i = np.flatnonzero(refine[:, m])
        tx = float(np.median(depth[0][i, m]))
        if int(tx) % 5:
            done += i.size
            capped += int((np.floor(np.abs(margin[i, m])) % 2 == 0).sum())
            runs.append(1 + int(tx) % 3)
    out = f"{HEAD}, Bellhop on {done} of {total} needed in-range samples" + (DEPTHS if done else "")
    if runs and max(runs) > 1:
        lo, hi = min(runs), max(runs)
        out += f" (the lowest of {hi if lo == hi else f'{lo} to {hi}'} runs: as named, swapped, both ends at least {comms.BELLHOP_MIN_DEPTH_M:g} m deep)"
    if capped:
        out += f"; {capped} of them had a Bellhop excess beyond +-{CAP:g} dB (the assumed cap) and were held at it"
    return out + _further(beyond) + ("" if done == total else "; the rest Thorp only (no sound-speed profile or depth there)"), \
        dict(done=done, total=total, capped=capped, beyond=beyond)


def _link(margin, need, valid, depth, cols):
    m, label, info, spread = _acoustic(margin, need, valid, depth, cols)
    n = len(cols)
    return dict(frac=np.zeros(n), success=np.zeros(n, bool), margin_db=m, method=label, t=np.arange(margin.shape[0], dtype=float), bellhop=info,
                bellhop_spread_db=spread)


def _merged(links):
    return stage1.merge([dict(U=np.zeros((len(x["frac"]), 1)), X={"a": np.zeros(len(x["frac"]))}, vehicles={}, links={LINK: x}) for x in links])["links"][LINK]


SPLITS = [[[0, 1, 2, 3, 4]], [[0, 1], [2, 3, 4]], [[0], [1, 2, 3], [4]], [[0, 1, 2, 3], [4]], [[2], [0, 4], [1], [3]]]


@pytest.mark.parametrize("on", [False, True])
@pytest.mark.parametrize("seed", range(30))
def test_m2_the_label_of_a_merged_run_is_that_of_one_batch_of_all_its_members_in_every_order_and_split_with_and_without_bellhop(fake_world, seed, on):
    """Over random masks (margins from -120 to +120 dB, NaN, exactly +-60 and one ulp either side; members that never needed it or only out of range), every
    split of the members into batches and every order of the batches: the label equals the one made from the masks alone, its counts are a recount, and
    the merged margin is the margin of the members whichever batch they were in. Before: with Bellhop off the label was the first batch's, with
    its own count (the +-6 dB band, not what Bellhop would refine), or 'Thorp budget decides every link' for a link Bellhop would have refined."""
    avail, calls = fake_world
    avail[0] = on
    margin, need, valid, depth = _world(np.random.default_rng(seed))
    want, counts = _expected(margin, need, valid, depth, on)
    whole = _link(margin, need, valid, depth, [0, 1, 2, 3, 4])
    assert whole["method"] == want and (whole["bellhop"] is None) == (counts is None)
    if counts:
        assert {k: whole["bellhop"][k] for k in counts} == counts and whole["bellhop"]["ran"] is on
        assert set(whole["bellhop"]) == {"done", "total", "capped", "beyond", "runs_lo", "runs_hi", "ran"}
    with np.errstate(invalid="ignore"):
        refine = need & valid & (np.abs(margin) <= CAP)
    ran = np.array([on and refine[:, m].any() and int(np.median(depth[0][refine[:, m], m])) % 5 != 0 for m in range(5)])
    moved = refine & ran                                                                  # only these samples leave their Thorp margin, by the fake's 1 dB
    assert np.array_equal(whole["margin_db"][~moved], margin[~moved], equal_nan=True) and np.array_equal(whole["margin_db"][moved], margin[moved] - 1.0)
    assert (DEPTHS in want) == bool(counts and counts["done"])
    for split in SPLITS:
        parts = [_link(margin, need, valid, depth, c) for c in split]
        for order in itertools.permutations(range(len(parts))):
            got = _merged([parts[k] for k in order])
            assert got["method"] == want, (split, order)
            cols = [c for k in order for c in split[k]]
            assert np.array_equal(got["margin_db"], whole["margin_db"][:, cols], equal_nan=True)


@pytest.mark.parametrize("seed", range(30))
def test_m3_the_depth_sentence_is_in_every_label_where_bellhop_ran_on_a_sample_and_in_no_other_and_it_is_true(fake_world, seed):
    """One `_bellhop_member` call per member with a refined sample, each on the median of its refined samples' depths: what the sentence says."""
    avail, calls = fake_world
    avail[0] = True
    margin, need, valid, depth = _world(np.random.default_rng(1000 + seed))
    parts = [_link(margin, need, valid, depth, c) for c in ([0, 1], [2, 3, 4])]
    with np.errstate(invalid="ignore"):
        refine = need & valid & (np.abs(margin) <= CAP)
    members = np.flatnonzero(refine.any(0))
    assert len(calls) == len(members) and sorted(c[2] for c in calls) == sorted(int(refine[:, m].sum()) for m in members)
    assert sorted((c[0], c[1]) for c in calls) == sorted((float(np.median(depth[0][refine[:, m], m])), float(np.median(depth[1][refine[:, m], m])))
                                                       for m in members)
    dones = [(p["bellhop"] or {}).get("done", 0) for p in parts]
    for x, done in [*zip(parts, dones, strict=True),(_merged(parts), sum(dones)), (_merged(parts[::-1]), sum(dones))]:
        assert (DEPTHS in x["method"]) == (done > 0)


def test_m2_with_bellhop_off_a_link_outside_the_old_band_no_longer_says_thorp_decides_it_and_the_count_is_over_every_batch_in_either_order(fake_world):
    """The reviewer's two cases (A-1, A-2/B-2) as numbers: batches of 7 and 40 needed in-range samples, a Thorp margin of +18 dB everywhere."""
    avail, _ = fake_world
    margin = np.full((47, 2), 18.0)
    need = np.zeros((47, 2), bool)
    need[:7, 0], need[:, 1] = True, False
    need[:40, 1] = True
    valid = np.ones((47, 2), bool)
    depth = np.zeros((2, 47, 2))
    a, b = (_link(margin, need, valid, depth, [m]) for m in (0, 1))
    assert a["method"] == f"{comms.THORP_ONLY_LABEL}: 7 needed in-range samples that Bellhop would refine keep their Thorp margin"
    assert b["method"] == f"{comms.THORP_ONLY_LABEL}: 40 needed in-range samples that Bellhop would refine keep their Thorp margin"
    want = f"{comms.THORP_ONLY_LABEL}: 47 needed in-range samples that Bellhop would refine keep their Thorp margin"
    assert _merged([a, b])["method"] == want == _merged([b, a])["method"]


def test_m2_records_that_disagree_on_whether_bellhop_was_available_are_read_as_ran_where_any_did_both_orders():
    """Not reachable in one run (availability is a property of the machine), so `merge` has to say something true if it ever happens: Bellhop ran on the
    samples it ran on, and the rest are counted as the samples it did not refine."""
    ran = dict(done=3, total=3, capped=0, beyond=0, runs_lo=1, runs_hi=1, ran=True)
    off = dict(done=0, total=2, capped=0, beyond=0, runs_lo=None, runs_hi=None, ran=False)
    z = np.zeros((2, 1))
    mk = lambda info: dict(frac=np.zeros(1), success=np.zeros(1, bool), margin_db=z, method="x", t=np.zeros(2), bellhop=info, bellhop_spread_db=z)
    for pair in ((ran, off), (off, ran)):
        got = _merged([mk(i) for i in pair])["method"]
        assert got.startswith(f"{HEAD}, Bellhop on 3 of 5 needed in-range samples{DEPTHS}")
        assert got.endswith("; the rest Thorp only (no sound-speed profile or depth there)")


@pytest.mark.parametrize("on", [False, True])
def test_m12_a_sample_at_exactly_the_cap_is_refined_once_not_counted_beyond_as_well_and_one_ulp_past_it_is_beyond(fake_world, on):
    """`far_ge` (round 21's surviving mutant): `>=` for `>` counts a sample at +-60 dB in `total` and in `beyond` and leaves it on Thorp, where it is a
    sample Bellhop is asked about (a Thorp +60 that Bellhop's excess of +60 turns into exactly 0, which is no pass: margin > 0)."""
    avail, _ = fake_world
    avail[0] = on
    col = np.array([CAP, -CAP, np.nextafter(CAP, np.inf), np.nextafter(-CAP, -np.inf), 0.0, np.nextafter(CAP, 0.0)])
    margin = np.stack([col, col], 1)
    ones = np.ones(margin.shape, bool)
    out, label, info, _ = _acoustic(margin, ones, ones, np.full((2, 6, 2), 3.0), [0, 1])
    assert (info["total"], info["beyond"], info["ran"]) == (8, 4, on) and "a further 4 needed in-range samples" in label
    assert np.array_equal(out[[2, 3]], margin[[2, 3]])                                                      # one ulp past the cap: Thorp keeps it
    assert np.array_equal(out[[0, 1, 4, 5]], margin[[0, 1, 4, 5]] - (1.0 if on else 0.0))                     # at the cap and inside it: asked of Bellhop


def test_q23_a_link_with_no_needed_in_range_sample_keeps_the_label_q23_printed_with_and_without_bellhop(fake_world, monkeypatch):
    """The demo's acoustic links are 555 and 632 km long: no sample in range, so no record and the constant q23 printed, character for character."""
    avail, calls = fake_world
    for on in (False, True):
        avail[0] = on
        margin = np.full((9, 2), -300.0)
        ones, zeros = np.ones(margin.shape, bool), np.zeros(margin.shape, bool)
        depth = np.zeros((2, 9, 2))
        for need, valid in ((ones, zeros), (zeros, ones), (zeros, zeros)):               # out of range, not needed, neither
            _, label, info, _ = _acoustic(margin, need, valid, depth, [0, 1])
            assert label == "Thorp budget decides every link" and info is None
        assert not calls
        merged = _merged([_link(margin, ones, zeros, depth, [0]), _link(margin, ones, zeros, depth, [1])])
        assert merged["method"] == "Thorp budget decides every link"


@pytest.mark.parametrize("on", [False, True])
def test_q23_the_same_out_of_range_link_through_evaluate_link(monkeypatch, on):
    r, calls, thorp = bellhop_scene(monkeypatch, km=45.0, depth=5.0, available=on)
    assert not calls and r["method"] == "Thorp budget decides every link" and r["bellhop"] is None and r["n_invalid"].tolist() == r["need_count"].tolist()


# ---------------------------------------------------------------- enumeration of what `merge` does with every key (OD-3: a test, not a runtime check)
LINK_RULES = dict(frac="cat", success="cat", margin_db="cat", n_invalid="cat", need_count="cat", dist_m="cat", bellhop_spread_db="cat", hs_filled="sum",
                  method="rebuilt", bellhop="dropped", margin_kind="first", invalid_kind="first", t="first")
VEHICLE_RULES = dict(
    **dict.fromkeys(("lon", "lat", "depth", "alt", "airborne", "surfaced", "heading", "sog_ms", "stw_ms", "u10_ms", "wind_anem_ms", "margin", "profile_margin",
                     "energy_margin", "battery_margin", "scrubbed"), "cat"),
    fail="dict_cat", first="dict_cat", fine="fine", sorties="sorties", hs_filled="sum", wind3d="sum",
    **dict.fromkeys(("t", "class", "antenna_m", "n_wp", "hours_dropped", "margin_name", "profile_margin_name", "energy_margin_name", "battery_margin_name"),
                    "first"),
    sim="dropped", wall_s="dropped")
TOP_RULES = dict(U="cat", X="dict_cat", vehicles="vehicles", links="links", seeds="seeds")


def _cat(xs):
    return np.concatenate(xs, axis=-1 if np.ndim(xs[0]) > 1 else 0)


def _same(a, b):
    return np.array_equal(np.asarray(a), np.asarray(b), equal_nan=np.asarray(a).dtype.kind == "f")


def _check(rule, key, parts, got, where):
    """`got` is what `merge` made of `key` from the batches' `parts`: the rule the table declares for it, held."""
    if rule == "cat":
        assert _same(got, _cat(parts)), (where, key)
    elif rule == "first":
        assert all(_same(p, parts[0]) for p in parts), (where, key, "the batches differ in a key merge takes from the first")
        assert _same(got, parts[0]), (where, key)
    elif rule == "sum":
        assert _same(got, np.sum([np.asarray(p) for p in parts], 0)), (where, key)
    elif rule == "dict_cat":
        assert set(got) == set(parts[0]) and all(_same(got[f], _cat([p[f] for p in parts])) for f in got), (where, key)
    elif rule == "fine":
        assert _same(got["t"], parts[0]["t"]) and all(_same(p["t"], parts[0]["t"]) for p in parts), (where, key)
        assert all(_same(got[f], _cat([p[f] for p in parts])) for f in got if f != "t"), (where, key)
    elif rule == "sorties":
        assert len(got) == len(parts[0]) and all(len(p) == len(parts[0]) for p in parts), (where, key)
        for i, so in enumerate(got):
            assert all(p[i]["t_launch"] == parts[0][i]["t_launch"] for p in parts) and so["t_launch"] == parts[0][i]["t_launch"], (where, key)
            assert all(_same(so[f], _cat([p[i][f] for p in parts])) for f in so if f != "t_launch"), (where, key)
    else:
        raise AssertionError((where, key, rule))


@pytest.fixture(scope="module")
def real_pair():
    """Two real batches of two members each (the CI fixture's four vehicles and three links, an 18 h window, and a second acoustic link `when: always` for the
    ship-to-USV path), merged."""
    links = [*MISSION["links"],
             dict(id="usv-ship-acoustic", a="usv", b="ship", kind="acoustic", modem="benthos_atm960_mf", when="always", required_fraction=0.9)]
    mission = dict(MISSION, links=links, window=dict(start="2023-03-01T18:00:00Z", end="2023-03-02T12:00:00Z"))
    pri, marg = stage1.priors_for(mission)
    env = AnalyticEnv(wind=(-6.0, 2.0), current=(0.15, -0.1), hs=1.0)
    batches = [stage1.run_batch(mission, env, [2 * i, 2 * i + 1], 11, pri, marg) for i in range(2)]
    return batches, stage1.merge(batches), mission


def test_every_key_of_a_link_result_has_a_declared_merge_rule_and_the_merge_follows_it(real_pair):
    """A key that is not in LINK_RULES fails here until it is classified (cat: joined along the members; first: the batches agree and the first is kept;
    sum; rebuilt: the label from the summed counts; dropped)."""
    batches, merged, mission = real_pair
    for lid in (lk["id"] for lk in mission["links"]):
        parts = [b["links"][lid] for b in batches]
        keys = set().union(*parts)
        assert keys <= set(LINK_RULES), (lid, sorted(keys - set(LINK_RULES)), "a new key of a link result: say how `merge` combines it")
        assert all(set(p) == keys for p in parts) and {"frac", "success", "margin_db", "method", "t"} <= keys
        got = merged["links"][lid]
        for k in keys:
            rule = LINK_RULES[k]
            if rule == "dropped":
                assert k not in got, (lid, k)
            elif rule == "rebuilt":
                infos = [p["bellhop"] for p in parts if p.get("bellhop") is not None]
                if infos:
                    assert got[k] == stage1._bellhop_label(dict({f: sum(i[f] for i in infos) for f in ("done", "total", "capped", "beyond")},
                                                                runs_lo=min([i["runs_lo"] for i in infos if i["runs_lo"] is not None], default=None),
                                                                runs_hi=max([i["runs_hi"] for i in infos if i["runs_hi"] is not None], default=None),
                                                                ran=any(i["ran"] for i in infos)))
                else:
                    assert all(p[k] == parts[0][k] for p in parts) and got[k] == parts[0][k], (lid, k)
            else:
                _check(rule, k, [p[k] for p in parts], got[k], lid)
        assert set(got) == (set(keys) - {k for k in keys if LINK_RULES[k] == "dropped"}), lid
    assert {"frac", "n_invalid"} <= set(merged["links"]["usv-ship-acoustic"]) and "bellhop_spread_db" in merged["links"]["usv-ship-acoustic"]
    assert "bellhop_spread_db" not in merged["links"]["usv-shore-iridium"]


def test_every_key_of_a_vehicle_result_has_a_declared_merge_rule_and_the_merge_follows_it(real_pair):
    batches, merged, mission = real_pair
    assert set(batches[0]) <= set(TOP_RULES) and set(merged) == set(batches[0])
    assert _same(merged["U"], np.concatenate([b["U"] for b in batches])) and all(_same(merged["X"][k], _cat([b["X"][k] for b in batches])) for k in merged["X"])
    assert merged["seeds"] == {v: {s: [b["seeds"][v][s] for b in batches] for s in sd} for v, sd in batches[0]["seeds"].items()}
    seen = set()
    for vid in batches[0]["vehicles"]:
        parts = [b["vehicles"][vid] for b in batches]
        keys = set().union(*parts)
        seen |= keys
        assert keys <= set(VEHICLE_RULES), (vid, sorted(keys - set(VEHICLE_RULES)), "a new key of a vehicle result: say how `merge` combines it")
        assert all(set(p) == keys for p in parts)
        got = merged["vehicles"][vid]
        for k in keys:
            if VEHICLE_RULES[k] == "dropped" or (k in ("fine", "wind3d") and all(p[k] is None for p in parts)):
                assert k not in got, (vid, k)
            else:
                _check(VEHICLE_RULES[k], k, [p[k] for p in parts], got[k], vid)
        assert set(got) == keys - {k for k in keys if VEHICLE_RULES[k] == "dropped" or (k in ("fine", "wind3d") and parts[0][k] is None)}, vid
    assert {"lon", "fail", "first", "t", "class", "wall_s"} <= seen


def test_the_enumeration_tables_are_complete_enough_to_catch_a_new_key(real_pair):
    """The check above fails on a key the tables lack: add one to a real result and it is named."""
    batches, _, mission = real_pair
    extra = [dict(b, links={k: dict(v, brand_new=1) for k, v in b["links"].items()}) for b in batches]
    keys = set().union(*(v for b in extra for v in b["links"].values()))
    assert "brand_new" in keys and not keys <= set(LINK_RULES)
    extra = [dict(b, vehicles={k: dict(v, brand_new=1) for k, v in b["vehicles"].items()}) for b in batches]
    assert not set().union(*(v for b in extra for v in b["vehicles"].values())) <= set(VEHICLE_RULES)
