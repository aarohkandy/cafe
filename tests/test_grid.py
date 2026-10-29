import numpy as np
import pytest
from hypothesis import given, strategies as st

from cafe.pm.env.grid import Axis, interp

f = st.floats(-10, 10, allow_nan=False)


def test_bilinear_reproduces_plane():
    x, y = Axis([0, 1, 3]), Axis([10, 20])
    F = 2 * x.x[:, None] - 0.5 * y.x[None, :] + 7
    v, ins = interp(F, [x, y], [np.array([0.5, 2.2]), np.array([12.0, 19.0])])
    assert np.allclose(v, 2 * np.array([0.5, 2.2]) - 0.5 * np.array([12, 19]) + 7) and ins.all()


def test_nan_corner_dropped_and_all_nan_is_nan():
    a = Axis([0, 1])
    F = np.array([[1.0, np.nan], [3.0, np.nan]])
    v, _ = interp(F, [a, a], [0.5, 0.0])
    assert np.isclose(v, 2.0)
    v, _ = interp(F, [a, a], [0.5, 0.25])
    assert np.isclose(v, 2.0)                       # the NaN column's weight is dropped, not counted as zero
    assert np.isnan(interp(F, [a, a], [0.5, 1.0])[0])   # all weight on the NaN column
    G = np.full((2, 2), np.nan)
    assert np.isnan(interp(G, [a, a], [0.3, 0.3])[0])


def test_outside_is_flagged_and_clamped():
    a = Axis([0, 1, 2])
    v, ins = interp(np.array([0.0, 1.0, 4.0]), [a], [np.array([-1.0, 5.0])])
    assert not ins.any() and np.allclose(v, [0.0, 4.0])


def test_bad_axes():
    with pytest.raises(ValueError):
        Axis([0, 0, 1])
    with pytest.raises(ValueError):
        Axis(np.zeros((2, 2)))


def test_single_point_axis():
    v, ins = interp(np.array([[5.0, 6.0]]), [Axis([3.0]), Axis([0, 1])], [3.0, 0.5])
    assert np.isclose(v, 5.5) and ins


@given(f, f, st.floats(0, 1), st.floats(0, 1))
def test_bounded_by_corners(a, b, wx, wy):
    F = np.array([[a, b], [b, a]])
    v, _ = interp(F, [Axis([0, 1]), Axis([0, 1])], [wx, wy])
    assert min(a, b) - 1e-9 <= v <= max(a, b) + 1e-9


@given(st.floats(0, 1))
def test_symmetric(w):
    F = np.array([1.0, 3.0])
    v1, _ = interp(F, [Axis([0, 1])], [w])
    v2, _ = interp(F[::-1].copy(), [Axis([0, 1])], [1 - w])
    assert np.isclose(v1, v2)
