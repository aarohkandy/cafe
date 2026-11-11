import numpy as np
from hypothesis import given, strategies as st

from cafe.pm.env import conventions as cv

ang = st.floats(0, 359.999, allow_nan=False)
spd = st.floats(0.01, 50, allow_nan=False)


def test_three_conventions_differ():
    # Wind FROM the north-east (45), waves travelling TOWARD the south-west in UMWM math radians,
    # current TOWARD the east. All three are different conventions describing different vectors.
    wind = cv.vec_from_from(10.0, 45.0)
    assert np.allclose(wind, [-10 / np.sqrt(2), -10 / np.sqrt(2)])           # blows toward SW
    umwm_theta = np.radians(-135.0)                                           # math: toward SW
    assert np.isclose(cv.math_rad_to_compass_to(umwm_theta), 225.0)
    cur = cv.vec_from_to(0.5, 90.0)
    assert np.allclose(cur, [0.5, 0.0])
    assert np.isclose(cv.from_deg(wind), 45.0) and np.isclose(cv.to_deg(wind), 225.0)
    # a sign flip in any of them breaks one of these
    assert not np.isclose(cv.math_rad_to_compass_to(-umwm_theta), 225.0)


def test_umwm_zero_is_east():
    assert np.isclose(cv.math_rad_to_compass_to(0.0), 90.0)
    assert np.isclose(cv.math_rad_to_compass_to(np.pi / 2), 0.0)


def test_grid_rotation_identity_and_quarter_turn():
    assert cv.rotate_grid_to_earth(3.0, 4.0, 1.0, 0.0) == (3.0, 4.0)
    ue, ve = cv.rotate_grid_to_earth(1.0, 0.0, 0.0, 1.0)                      # grid x points north
    assert np.isclose(ue, 0.0) and np.isclose(ve, 1.0)


@given(spd, ang)
def test_to_roundtrip(s, d):
    v = cv.vec_from_to(s, d)
    assert np.isclose(cv.speed(v), s)
    assert np.isclose((cv.to_deg(v) - d + 180) % 360 - 180, 0, atol=1e-6)


@given(spd, ang)
def test_from_is_opposite_of_to(s, d):
    assert np.allclose(cv.vec_from_from(s, d), -cv.vec_from_to(s, d))


@given(ang)
def test_math_compass_roundtrip(d):
    back = cv.math_rad_to_compass_to(cv.compass_to_to_math_rad(d))
    assert np.isclose((back - d + 180) % 360 - 180, 0, atol=1e-6)


def test_r12_l1_m24_box_words_names_south_north_west_east_and_takes_any_four_numbers():
    assert cv.box_words((-7.0, 7.0, 165.0, 195.0)) == "lat -7 to 7, lon 165 to 195"
    assert cv.box_words([-1, 1, 350, 10]) == "lat -1 to 1, lon 350 to 10"


def test_r15_m20_lon_median_does_not_care_where_the_antimeridian_is():
    """Round 15 M-20: the raw median of 179.99 and -179.99 is 0, the other side of the globe. The slice is reduced about its circular mean first."""
    def apart(a, b):
        return abs((a - b + 180.0) % 360.0 - 180.0)
    assert apart(float(cv.lon_median([179.99, -179.99])), 180.0) < 1e-9
    assert apart(float(cv.lon_median([179.9, 179.95, -179.99])), 179.95) < 1e-9                   # the middle one of three, whichever side it is written on
    assert apart(float(cv.lon_median([-179.9, -179.95, 179.99])), -179.95) < 1e-9
    m = np.array([[179.99, -179.99, 179.98], [10.0, 11.0, 12.0], [np.nan, np.nan, np.nan]])
    out = cv.lon_median(m, 1)
    assert apart(out[0], 179.99) < 1e-9 and out[1] == 11.0 and np.isnan(out[2])
    assert (out[np.isfinite(out)] >= -180).all() and (out[np.isfinite(out)] < 180).all()
    # The wrap-back into [-180, 180): `apart` cannot see it (180 and -180 are one place), so the value is pinned (round 15 M-20 adversary: `return m` survived).
    assert cv.lon_median([179.99, -179.99]) == -180.0 and cv.lon_median([179.99, 179.99, -179.99, -179.99]) == -180.0
    assert (cv.lon_median([[179.99, -179.99], [179.99, 179.99]], 1) == [-180.0, 179.99]).all()                    # along an axis, the slices wrap on their own
    x = np.array([-170.123456789, -165.987654321, -167.5])
    assert cv.lon_median(x) == np.median(x) and cv.lon_median(np.array([np.nan, -166.1, np.nan])) == -166.1        # bit for bit away from the line
