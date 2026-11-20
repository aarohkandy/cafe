"""Round 23, batch E (M-10 a): `rfband.pair_band` does not depend on the order of the two heights. The card prints the band of the link's pair, and a link
names its ends in the order of the mission file: a band that changed with that order would print another figure for the same two antennas. `pair_band` sorts
its heights. The three functions it calls are symmetric in them only to about 1e-9 dB (2.4e-9 dB at 5 m with 500 m, 915 MHz, at a deep null, measured on
orca), so without the sort the two orders differ in the last digits and the test below fails; with it they are equal to the last bit. Reviewer A's mutant
`noswap_sorted` (the sort removed) survived every test of rounds 21 and 22 because they compare each order with an independent Fresnel reference to 1e-9 dB, not
with each other. The test holds the property: a non-symmetric edit of `two_ray_loss_db`, `fresnel_loss_db` or `radio_horizon_km` fails it too."""
import itertools

import pytest

from cafe.pm.physics import rfband

# 15 heights from the least an antenna can have (0.1 m) to the most a band is defined for (1,000 m), the demo's own (2.2 m USV whip, 15 m ship mast, 18.1 m and
# 108.1 m UAS legs) and the ones the earlier rounds measured (0.3, 0.5, 10, 30, 60), so every kind of pair is there: two low, low with high, two high, equal.
HEIGHTS = (0.1, 0.3, 0.5, 1.0, 2.2, 5.0, 10.0, 15.0, 18.1, 30.0, 60.0, 108.1, 250.0, 500.0, 1000.0)
FREQS = (rfband.F_DEFAULT_HZ, 2440e6)                                                       # the RFD900x and the XBee Pro (radios.yaml)


@pytest.mark.parametrize("f_hz", FREQS)
def test_pair_band_is_the_same_for_either_order_of_the_heights(f_hz):
    for a, b in itertools.combinations_with_replacement(HEIGHTS, 2):
        assert rfband.pair_band(a, b, f_hz) == rfband.pair_band(b, a, f_hz), (a, b, f_hz)      # all six numbers, equal to the last bit


def test_the_default_frequency_is_the_915_mhz_one():
    assert all(rfband.pair_band(a, b) == rfband.pair_band(b, a, rfband.F_DEFAULT_HZ) for a, b in [(0.1, 1000.0), (2.2, 108.1), (15.0, 15.0)])


@pytest.mark.parametrize("bad", [0.0, 0.0999, 1000.0001, float("nan"), float("inf"), -1.0, True, "2.2", None])
def test_an_invalid_height_is_refused_in_either_position(bad):
    for args in ((bad, 15.0), (15.0, bad)):
        with pytest.raises(ValueError, match="rfband.pair_band"):
            rfband.pair_band(*args)
