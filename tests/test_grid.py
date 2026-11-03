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


def test_a_leading_dimension_interpolates_each_slice_exactly_as_on_its_own():
    """The 3-D wind interpolates every level in one call; each level (NaN corners, outside points, a mixed-shape query) must equal its own call."""
    rng = np.random.default_rng(3)
    f = rng.normal(size=(4, 5, 6))
    f[rng.random(f.shape) < 0.2] = np.nan
    axes = [Axis(np.linspace(0, 4, 5)), Axis(np.linspace(-1, 1, 6))]
    q = [rng.uniform(-1, 5, (7, 3)), rng.uniform(-2, 2, (3,))]
    got, inside = interp(f, axes, q)
    assert got.shape == (4, 7, 3) and inside.shape == (7, 3)
    for k in range(4):
        assert np.array_equal(got[k], interp(f[k], axes, q)[0], equal_nan=True)
    assert np.array_equal(interp(f[0], axes, [np.nan, 0.0])[0], np.nan, equal_nan=True)     # a NaN query is NaN, as np.clip left it


def test_an_empty_query_returns_empty_arrays_of_the_right_shape():
    """Review round 5, M-20: a box with no sea cells asks for zero points, and the corner-weight reshape raised ValueError on the zero size."""
    x, y = Axis([0, 1, 3]), Axis([10, 20])
    F = np.ones((3, 2))
    v, ins = interp(F, [x, y], [np.empty(0), np.empty(0)])
    assert v.shape == (0,) and ins.shape == (0,) and ins.dtype == bool
    v, ins = interp(np.ones((4, 3, 2)), [x, y], [np.empty((0, 5)), np.empty((0, 5))])               # leading dimensions of the field stay in front
    assert v.shape == (4, 0, 5) and ins.shape == (0, 5)
    v, ins = interp(F, [x, y], [np.empty((2, 0)), np.empty((2, 0))])
    assert v.shape == (2, 0) and ins.shape == (2, 0)
