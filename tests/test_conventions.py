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
