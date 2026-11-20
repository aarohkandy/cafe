"""Round 22, merge step (code part): the hunks the batches handed each other and the siblings batch D listed, each closed with the existing `finite_real` and
nothing new. Each test here fails on the tree at 83240d0 (the five batches merged) and passes with the merge commit; the allow-list counts of
`tests/test_round21_e.py` moved with the tree and are held by that file, not here."""
import importlib.util
import pathlib

import numpy as np
import pytest

from cafe import hangar, vehicle
from tests.test_round22_d import NAN, INF, FIELDS, fleet, refused, sample  # noqa: F401  (`fleet` is a fixture)

ROOT = pathlib.Path(__file__).parent.parent
BAD_NUMBERS = [True, False, NAN, INF, -INF, 10 ** 400, -(10 ** 400), "1.5", None, [1.0]]
BAD_IDS = ["true", "false", "nan", "inf", "-inf", "10**400", "-10**400", "numeral", "null", "list"]


# ---------------------------------------------------------------------------------------------------------- _vec3: a bool or a numeral in text is no number
@pytest.mark.parametrize("key", FIELDS)
@pytest.mark.parametrize("at", [0, 1, 2])
@pytest.mark.parametrize("bad", [True, False, "1.0", "0", np.True_], ids=["true", "false", "numeral", "numeral 0", "numpy bool"])
def test_a_bool_or_a_numeral_in_text_is_not_an_item_of_a_force_moment_or_viscous_vector(key, at, bad):
    """Before: `np.asarray([True, 2.0, 3.0], float)` is [1.0, 2.0, 3.0] and `"1.0"` is 1.0, so a hand-edited result built a drag table."""
    v = [1.0, 2.0, 3.0]
    v[at] = bad
    with pytest.raises(ValueError, match=rf"direction \+x: `{key}` is not three finite numbers"):
        vehicle._vec3({key: v}, key, "+x")


@pytest.mark.parametrize("good", [[1, 2, 3], (1.0, -2.5, 0.0), np.array([1.0, 2.0, 3.0], np.float32), np.array([1, 2, 3]),
                                  [np.float64(1), np.int32(2), np.float32(3)]],
                         ids=["ints", "tuple", "float32 array", "int array", "numpy scalars"])
def test_numbers_of_every_kind_still_make_a_vector(good):
    assert np.array_equal(vehicle._vec3({"force": good}, "force", "+x"), np.asarray(good, float))


@pytest.mark.parametrize("bad", [np.float32("nan"), np.float32("inf"), np.float64("nan")], ids=["float32 nan", "float32 inf", "float64 nan"])
def test_a_numpy_nan_or_inf_item_is_still_refused(bad):
    with pytest.raises(ValueError, match="is not three finite numbers"):
        vehicle._vec3({"force": [1.0, bad, 3.0]}, "force", "+x")


# ---------------------------------------------------------------------------------------------------------- the free-surface resistance
def wigley(resistances):
    kind, mesh, spec = sample("wigley")
    speeds = {f"{u}": dict(resistance=r, gci=0.02) for u, r in resistances.items()}
    return kind, mesh, spec, {"fs": dict(speeds=speeds)}


@pytest.mark.parametrize("bad", [None, NAN, INF, -INF, 10 ** 400, True, "7.5"], ids=["null", "nan", "inf", "-inf", "10**400", "true", "numeral"])
@pytest.mark.parametrize("where", ["first", "last"])
def test_a_resistance_that_is_not_a_finite_number_is_refused_naming_the_speed(bad, where):
    """Before: a null (the NaN `hangar` writes as null) was an unnamed TypeError in the sum below and a bare NaN built a silent NaN resistance table."""
    res = {1.0: 5.0, 2.0: 21.0}
    res[1.0 if where == "first" else 2.0] = bad
    kind, mesh, spec, hangar_result = wigley(res)
    with pytest.raises(ValueError, match=r"speed (1\.0|2\.0): `resistance` is not a finite number") as e:
        vehicle.build(kind, mesh, spec, hangar_result)
    assert str(1.0 if where == "first" else 2.0) in str(e.value)


def test_a_finite_resistance_table_is_built_as_before():
    kind, mesh, spec, hangar_result = wigley({1.0: 5.0, 2.0: 21.0})
    v = vehicle.build(kind, mesh, spec, hangar_result)
    assert v.resistance[1][-2:].tolist() == [5.0, 21.0] and v.limits["resistance_gci"] == 0.02


# ---------------------------------------------------------------------------------------------------------- check_fleet: a link's max_m and need
def with_link(make, **lk):
    body = make(5)
    body["links"] = [dict(a="a", b="b", **lk)]
    return body


@pytest.mark.parametrize("field", ["max_m", "need"])
@pytest.mark.parametrize("bad", BAD_NUMBERS, ids=BAD_IDS)
def test_a_link_max_m_or_need_that_is_no_finite_number_is_a_400(fleet, field, bad):  # noqa: F811
    """Before: `true` was 1.0 m or a need of 1, and a numeral in text ("1.5") was a number: `float()` took both."""
    a, make = fleet
    lk = dict(max_m=1000.0, need=0.9)
    lk[field] = bad
    assert "link a-b: max_m must be a number" in refused(a.check_fleet, with_link(make, **lk))


def test_a_link_with_numbers_in_range_is_accepted_and_one_out_of_range_is_the_old_400(fleet):  # noqa: F811
    a, make = fleet
    assert a.check_fleet(with_link(make, max_m=1000.0, need=0.9)) and a.check_fleet(with_link(make, max_m=1, need=1))
    assert a.check_fleet(with_link(make, max_m=500))                                            # `need` defaults to 0.95
    for lk in (dict(max_m=0, need=0.9), dict(max_m=-1.0), dict(max_m=1000.0, need=0), dict(max_m=1000.0, need=1.0000001)):
        assert "max_m > 0 and need in (0, 1]" in refused(a.check_fleet, with_link(make, **lk))
    assert "max_m must be a number" in refused(a.check_fleet, with_link(make))                    # no max_m at all


# ---------------------------------------------------------------------------------------------------------- hangar.check: a spec number
@pytest.mark.parametrize("bad", [True, 10 ** 400, NAN, INF, "5", None, 0, -1], ids=["true", "10**400", "nan", "inf", "numeral", "null", "0", "-1"])
@pytest.mark.parametrize("key", ["mass", "power_w", "battery_wh"])
def test_a_spec_number_that_is_no_positive_finite_number_is_an_error_message_never_a_traceback(key, bad):
    """Before: `True` passed as 1 and `np.isfinite` of an integer is a TypeError when it does not fit 64 bits (the next test)."""
    spec = dict(mass=1.0, power_w=1.0, battery_wh=1.0)
    spec[key] = bad
    errors, warnings = hangar.check("uuv", None, spec)
    assert errors == [f"{key} must be a positive, finite number (got {bad!r})"] and warnings == []


def test_a_spec_integer_above_64_bits_is_a_finite_number_not_a_traceback():
    """`np.isfinite(2**64)` is a TypeError; the number is finite, so it passes this test and the checks after it say what is wrong with it."""
    kind, mesh, spec = sample("torpedo")
    errors, _ = hangar.check(kind, mesh, dict(spec, power_w=2 ** 64))
    assert not any("power_w" in e for e in errors)


# ---------------------------------------------------------------------------------------------------------- bench/throughput.py reads through load_json
def test_the_bench_reads_its_file_through_load_json(tmp_path, monkeypatch):
    """Before: `json.loads` read a 400-digit integer of a hand-edited `config/throughput.json` and the bench wrote it back."""
    spec = importlib.util.spec_from_file_location("bench_throughput", ROOT / "bench" / "throughput.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = tmp_path / "throughput.json"
    monkeypatch.setattr(mod, "OUT", out)
    out.write_text('{"foam": {"x": 1' + "0" * 400 + "}}")
    with pytest.raises(ValueError, match="too large for a number"):
        mod.save("lbm", {"y": 2})
    out.write_text('{"foam": {"x": 1}}')
    mod.save("lbm", {"y": 2})
    assert mod.load_json(out.read_text()) == {"foam": {"x": 1}, "lbm": {"y": 2}}


# ---------------------------------------------------------------------------------------------------------- the card of a UAS end it could not use
UNUSABLE = "u (no usable height (unreadable, or outside 0.1 to 1000 m): 18.1 and 108.1 m assumed)"


@pytest.mark.parametrize("when", ["always", "surfacing", "uas_airborne"])
@pytest.mark.parametrize("spec, usable_when_airborne", [
    (([], 8.0, 0.1), False), ((None, 8.0, 0.1), False), (([float("nan")], 8.0, 0.1), False), (([-50.0], 8.0, 0.1), False), (([5000.0], 8.0, 0.1), False),
    (([10 ** 400], 8.0, 0.1), False), (([True], 8.0, 0.1), False),                                  # levels that cannot be read, or lie outside 0.1 to 1000 m
    (([10.0], 0.0, 0.0), True), (([10.0], -5.0, 0.0), True)],                     # levels fine; the deck (0 m, or below the sea) is the unusable height
    ids=["empty", "none", "nan", "below the sea", "5 km", "huge int", "bool", "deck 0", "deck below the sea"])
def test_a_uas_end_with_no_usable_height_gets_one_sentence_that_is_true_for_each_cause(monkeypatch, spec, usable_when_airborne, when):
    """Before: 'its flight levels could not be read', also for a deck at 0 m with an antenna 0 above the body on a link required on the deck, and for
    levels that were read and lie outside 0.1 to 1000 m. Now: unreadable, or outside the band's heights, whichever it is; a UAS whose levels are fine and
    which is required only while airborne keeps its legs."""
    from tests.test_round21_b import has_figure, note_of
    note = note_of(monkeypatch, ("u", ("uas", spec)), ("g", ("glider", 2.2)), when=when)
    assert has_figure(note) and "flight levels" not in note and "no single height" not in note
    assert (UNUSABLE in note) == (not (usable_when_airborne and when == "uas_airborne")), (when, note)


# ------------------------------------------------------------------------------------------------ tests/test_usv.py::test_table_equals_direct_coupled_solve
def tw_pair(wind_from, speed, heading, cspeed, cdir):
    """The direct current-coupled solve and the table, for arrays of states; the wind relative to the water and the angle `gam` the test of test_usv uses."""
    from cafe.pm.env import conventions as cv
    from cafe.pm.physics import usv
    P = usv.load_platform()
    pol, _ = usv.tables(P)
    w, c = cv.vec_from_from(speed, wind_from), cv.vec_from_to(cspeed, cdir)
    gam = (cv.from_deg(w - c) - heading + 180.0) % 360.0 - 180.0
    return gam, usv.through_water(P, w, c, heading), usv.through_water_table(P, pol, w, c, heading)


def test_the_table_and_the_direct_solve_take_the_same_tack_on_a_dead_run():
    """Hypothesis found wind_from 180, speed 5, heading 0, no current (a dead run: the wind comes from exactly astern). The speeds were equal to 1e-16 and the
    tracks 5.64 deg apart: the direct solve takes the tack from the sign of the wind's cross-boat component, which is -1.2e-15 there (sin 180 deg is not 0 in a
    float), the table from `gam`, which the wrap to [-180, 180) sends to -180, so two code paths broke the tie of a dead run in two ways, and the leeway
    (2.8 deg) changed side. Before: the track differs by 2 x the leeway; after: the same track."""
    gam, a, b = tw_pair(180.0, 5.0, 0.0, 0.0, 0.0)
    assert abs(gam) == 180.0 and abs(a["leeway_deg"]) > 2.0                       # a dead run, and a leeway that has a side to be on
    assert np.isclose(a["stw"], b["stw"], atol=1e-9) and a["leeway_deg"] == pytest.approx(b["leeway_deg"], abs=1e-9)
    assert abs((a["track_to"] - b["track_to"] + 180) % 360 - 180) < 1e-9


def test_the_table_equals_the_direct_solve_on_every_axis_aligned_state_with_the_test_usv_tolerances():
    """The states Hypothesis finds are the axis-aligned ones (a heading or a wind direction of 0, 90, 180: sin and cos of a multiple of 90 deg are not
    exact), the ones that sit on a tie. Every multiple of 15 deg of wind direction and heading, three speeds, two current speeds and the four axis currents,
    those with |gam| above 45 deg: speed within 0.08 m/s, and where both move (above 0.5 m/s) the leeway on the same side and the track within 1.5 deg
    (test_usv's own tolerances). The grid has dead runs in it (|gam| = 180) and no empty side."""
    deg = np.arange(0.0, 360.0, 15.0)
    wf, hd, sp, cs, cd = (x.ravel() for x in np.meshgrid(deg, deg, [1.0, 5.0, 14.0], [0.0, 0.9], [0.0, 90.0, 180.0, 270.0], indexing="ij"))
    gam, a, b = tw_pair(wf, sp, hd, cs, cd)
    far = np.abs(gam) > 45.0
    assert far.sum() > 8000 and (np.abs(np.abs(gam[far]) - 180.0) < 1e-9).sum() > 100 and (gam[far] > 0).any() and (gam[far] < 0).any()
    assert np.abs(a["stw"] - b["stw"])[far].max() <= 0.08
    moving = far & (a["stw"] > 0.5) & (b["stw"] > 0.5)              # a boat that makes no way has no leeway to be on a side
    assert moving.sum() > 4000 and (np.sign(a["leeway_deg"]) == np.sign(b["leeway_deg"]))[moving].all()
    assert (np.abs((a["track_to"] - b["track_to"] + 180) % 360 - 180)[moving] < 1.5).all()
