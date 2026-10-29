"""cafe.pm.env.bathy: GEBCO cut to a box by HTTP byte ranges (contiguous and chunked layouts, across the dateline), the GOFS and
UMWM fallbacks, the fallback order, and the Tagged answers."""
import json

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from cafe.pm import Tagged
from cafe.pm.env import bathy as b
from tests.fixtures.hycom import make_fixtures as mk

LON = np.arange(-179.5, 180, 1.0)                    # a 1-degree stand-in for GEBCO's 15 arc-second grid, cell centres
LAT = np.arange(-89.5, 90, 1.0)


def elevation():
    lo, la = np.meshgrid(LON, LAT)
    e = -2500.0 - 1500.0 * np.sin(np.radians(3 * lo)) * np.cos(np.radians(4 * la))
    e[(np.abs(la) < 1.0) & (lo >= -179.5) & (lo <= -178.5)] = 120.0               # an island just east of the dateline (lon 180.5, 181.5)
    return e.astype("<i2")


def write_nc(path, chunked=False):
    import h5py
    with h5py.File(path, "w") as f:
        f["lon"], f["lat"] = LON, LAT
        kw = dict(chunks=(30, 90), compression="gzip") if chunked else {}
        f.create_dataset("elevation", data=elevation(), **kw)
        f.attrs["title"] = b"synthetic GEBCO stand-in"
        f.attrs["id"] = b"DOI: 10.0/test"


@pytest.fixture
def gebco(server, tmp_path):
    write_nc(tmp_path / "g.nc")
    write_nc(tmp_path / "gc.nc", chunked=True)
    return dict(flat=server.put("g.nc", (tmp_path / "g.nc").read_bytes()), chunked=server.put("gc.nc", (tmp_path / "gc.nc").read_bytes()),
                size=(tmp_path / "g.nc").stat().st_size)


BOX = (-3.2, 3.2, 178.2, 182.0)                       # across the dateline: file lon 178.5..179.5 and -179.5..-178.5 (= 180.5..181.5)


def requested_bytes(server):
    total = 0
    for _, rng in server.log:
        if rng:
            a, bb = rng[6:].split("-")
            total += int(bb) - int(a) + 1 if bb else 0
    return total


@pytest.fixture(scope="session")
def store(tmp_path_factory):
    return mk.make(tmp_path_factory.mktemp("bathy_fx"))["gofs_zarr"]


# ------------------------------------------------------------------ GEBCO by byte range


def test_fetch_gebco_reads_only_the_box_and_joins_across_the_dateline(server, gebco, tmp_path):
    out = b.fetch_gebco(BOX, tmp_path / "c" / "g.npz", gebco["flat"], workers=4)
    z = np.load(out)
    assert np.allclose(z["lon"], [178.5, 179.5, 180.5, 181.5]) and np.allclose(z["lat"], np.arange(-2.5, 3, 1.0)) and z["elevation"].dtype == np.dtype("<i2")
    full = elevation()
    rows = (LAT >= -3.2) & (LAT <= 3.2)
    ref = np.concatenate([full[np.ix_(rows, LON > 178)], full[np.ix_(rows, LON < -178)]], axis=1)
    assert np.array_equal(z["elevation"], ref)
    meta = json.loads(str(z["attrs"]))
    assert meta["remote_bytes"] == gebco["size"] and meta["doi"] == "DOI: 10.0/test" and meta["title"].startswith("synthetic") and len(meta["sha256"]) == 64


def test_fetch_gebco_asks_for_the_box_not_the_file(server, tmp_path):
    import h5py
    lon, lat = np.arange(-179.95, 180, 0.1), np.arange(-89.95, 90, 0.1)               # 3600 x 1800 int16 = 13 MB
    with h5py.File(tmp_path / "big.nc", "w") as f:
        f["lon"], f["lat"] = lon, lat
        f.create_dataset("elevation", data=np.full((1800, 3600), -4000, "<i2"))
    url = server.put("big.nc", (tmp_path / "big.nc").read_bytes())
    z = np.load(b.fetch_gebco((-1.5, 1.5, 178.5, 181.5), tmp_path / "b.npz", url))
    assert z["elevation"].shape == (30, 30) and (z["elevation"] == -4000).all()
    assert requested_bytes(server) < 0.4 * (tmp_path / "big.nc").stat().st_size       # the 4 MB metadata block + 30 rows of 60 bytes


def test_chunked_layout_gives_the_same_raster(server, gebco, tmp_path):
    a = np.load(b.fetch_gebco(BOX, tmp_path / "a.npz", gebco["flat"]))["elevation"]
    c = np.load(b.fetch_gebco(BOX, tmp_path / "c.npz", gebco["chunked"]))["elevation"]
    assert np.array_equal(a, c)


def test_fetch_gebco_boxes_on_one_side_of_the_seam_and_empty_boxes(server, gebco, tmp_path):
    east = np.load(b.fetch_gebco((-2, 2, 10, 14), tmp_path / "e.npz", gebco["flat"]))
    assert np.allclose(east["lon"], [10.5, 11.5, 12.5, 13.5]) and east["elevation"].shape == (4, 4)
    west = np.load(b.fetch_gebco((-2, 2, 200, 203), tmp_path / "w.npz", gebco["flat"]))
    cols = np.isin(np.mod(LON, 360), west["lon"])
    assert np.allclose(west["lon"], [200.5, 201.5, 202.5]) and np.array_equal(west["elevation"], elevation()[np.ix_((LAT >= -2) & (LAT <= 2), cols)])
    with pytest.raises(ValueError, match="no grid points"):
        b.fetch_gebco((-2, 2, 10.6, 10.9), tmp_path / "x.npz", gebco["flat"])


def test_short_range_reads_are_an_error(server, gebco, tmp_path):
    server.plan["g.nc"] = [None, None] + [("short", 3)] * 400          # size probe and the metadata block are fine, every row comes back short
    with pytest.raises(ConnectionError, match="short read"):
        b.fetch_gebco(BOX, tmp_path / "s.npz", gebco["flat"], workers=1)


# ------------------------------------------------------------------ Bathymetry answers


def cache(server, gebco, tmp_path):
    return b.from_gebco(b.fetch_gebco(BOX, tmp_path / "g.npz", gebco["flat"]))


def test_gebco_bathymetry_is_depth_positive_zero_on_land_and_tagged(server, gebco, tmp_path):
    g = cache(server, gebco, tmp_path)
    t = g(180.5, 0.5)
    assert isinstance(t, Tagged) and t.kind == "data" and "GEBCO_2026" in t.source and "0.46 km" in t.source and "DOI: 10.0/test" in t.source
    assert float(t.value) == 0.0                                                  # land (elevation +120 m)
    assert g(-179.5, 0.5).value == g(180.5, 0.5).value                              # same point, either longitude convention
    e = elevation().astype(float)
    node = g(179.5, 2.5)
    assert np.isclose(node.value, -e[np.argmin(abs(LAT - 2.5)), np.argmin(abs(LON - 179.5))]) and np.isclose(node.uncertainty, 0.05 * node.value)
    v = g(np.array([178.5, 179.5]), np.array([1.5, -1.5]))
    assert v.value.shape == (2,) and (v.value > 0).all() and g.resolution_m == pytest.approx(463.3, abs=1)
    with pytest.raises(ValueError, match="outside the GEBCO_2026"):
        g(190.0, 0.0)
    with pytest.raises(ValueError, match="1 point"):
        g(179.0, 40.0)


@given(st.floats(170.0, 188.99), st.floats(0.0, 8.99), st.integers(-2, 2))
@settings(max_examples=60, deadline=None)
def test_bilinear_depth_is_exact_for_a_linear_field_and_the_same_in_any_longitude_convention(lon, lat, k):
    lons, lats = np.arange(170.0, 190.0), np.arange(0.0, 10.0)
    g = b.Bathymetry(lons, lats, 10.0 * (lons[None] - 170.0) + lats[:, None], "unit", 1000.0, 0.0)
    d = float(g(lon + 360.0 * k, lat).value)
    assert np.isclose(d, 10.0 * (lon - 170.0) + lat, atol=1e-7)


def test_negative_depth_cannot_happen_and_nan_is_land():
    g = b.Bathymetry([0.0, 1.0], [0.0, 1.0], np.array([[np.nan, -5.0], [10.0, 20.0]]), "x", 1.0, 1.0)
    assert (g.depth >= 0).all() and g(0.0, 0.0).value == 0.0


def test_cache_with_altered_raster_is_refused(server, gebco, tmp_path):
    p = b.fetch_gebco(BOX, tmp_path / "g.npz", gebco["flat"])
    z = dict(np.load(p))
    z["elevation"] = z["elevation"] + 1
    np.savez(p, **z)
    with pytest.raises(ValueError, match="SHA-256 differs"):
        b.from_gebco(p)


# ------------------------------------------------------------------ GOFS and UMWM


def test_gofs_floor_is_the_deepest_valid_level_with_its_quantization(store):
    g = b.from_gofs(store)
    assert "HYCOM GOFS" in g.source and g.resolution_m == pytest.approx(0.08 * b.M_PER_DEG, rel=1e-4)
    lon, lat = mk.LON, mk.LAT
    assert np.isclose(g(lon[0], lat[0]).value, 0.0)                                # the all-land column
    shallow = g(lon[4], lat[3])
    assert np.isclose(shallow.value, 100.0) and np.isclose(shallow.uncertainty, 50.0 / np.sqrt(12.0))   # wet to 100 m; the next level is 150 m
    deep = g(lon[5], lat[5])
    assert np.isclose(deep.value, 1500.0) and np.isclose(deep.uncertainty, 0.0)                         # last level: nothing deeper to bracket it
    assert np.isclose(g(0.5 * (lon[5] + lon[6]), lat[5]).value, 1500.0)


def test_umwm_depth_is_a_12_km_grid():
    lon, lat = np.array([-170.0, -169.9]), np.array([0.0, 0.1])
    d = np.array([[4000.0, 4100.0], [4200.0, 4300.0]])
    u = b.from_umwm(lon, lat, d)
    t = u(190.0, 0.05)
    assert t.source.startswith("UMWM depth (12.00 km") and np.isclose(t.value, 4100.0) and np.isclose(t.uncertainty, 410.0)


# ------------------------------------------------------------------ fallback order


def test_choose_prefers_gebco_and_reuses_the_cache(server, gebco, store, tmp_path):
    g = b.choose(BOX, tmp_path / "bathy", store, None, True, gebco["flat"])
    assert "GEBCO_2026" in g.source and g.tried == ()
    n = len(server.log)
    g2 = b.choose(BOX, tmp_path / "bathy", None, None, True, "http://127.0.0.1:9/never")
    assert "GEBCO_2026" in g2.source and len(server.log) == n                         # cache hit: no request


def test_choose_falls_back_gebco_then_gofs_then_umwm_and_says_why(server, store, tmp_path):
    umwm = dict(lon=np.array([180.0, 181.0]), lat=np.array([-1.0, 1.0]), depth=np.array([[3000.0, 3000.0], [3000.0, 3000.0]]))
    g = b.choose(BOX, tmp_path / "c1", store, umwm, False)
    assert g.source.startswith("HYCOM GOFS") and g.tried and "gebco: FileNotFoundError" in g.tried[0] and "fetch=False" in g.tried[0]
    g = b.choose(BOX, tmp_path / "c2", None, umwm, True, "http://127.0.0.1:9/dead.nc")
    assert g.source.startswith("UMWM") and len(g.tried) == 2 and "gebco: " in g.tried[0] and "gofs: FileNotFoundError: no GOFS store given" in g.tried[1]
    with pytest.raises(LookupError, match=r"(?s)no bathymetry source worked.*gebco.*gofs.*umwm: FileNotFoundError: no UMWM depth given"):
        b.choose(BOX, tmp_path / "c3", None, None, False)


def test_a_gofs_store_without_a_temperature_kind_is_refused_and_falls_through(store, tmp_path):
    import xarray as xr
    bare = tmp_path / "bare.zarr"
    xr.open_zarr(store, decode_times=False, consolidated=False).drop_attrs().to_zarr(bare, consolidated=False)
    umwm = dict(lon=np.array([180.0, 181.0]), lat=np.array([-1.0, 1.0]), depth=np.full((2, 2), 3000.0))
    g = b.choose(BOX, tmp_path / "c", bare, umwm, False)
    assert g.source.startswith("UMWM") and "never guessed" in g.tried[1]


# ------------------------------------------------------------------ receipts


def test_receipts_pass_alone_with_a_cache_and_with_the_remote_cross_check(server, gebco, tmp_path):
    from cafe import receipts as R
    R.OUT.clear()
    assert b.receipts()
    assert len(R.OUT) == 1 and R.OUT[0]["ok"]
    cache_path = b.fetch_gebco(BOX, tmp_path / "g.npz", gebco["flat"])
    R.OUT.clear()
    assert b.receipts(cache_path, gebco["flat"])
    mine = [r for r in R.OUT if r["group"] == "Bathymetry"]
    assert len(mine) == 3 and all(r["ok"] for r in mine) and "byte-range" in mine[2]["claim"]


def test_an_off_by_one_column_in_the_byte_offset_fails_the_remote_cross_check(server, gebco, tmp_path, monkeypatch):
    from cafe import receipts as R
    cache_path = b.fetch_gebco(BOX, tmp_path / "g.npz", gebco["flat"])
    real = b._rows
    monkeypatch.setattr(b, "_rows", lambda url, base, ncols, j, i0, i1, dtype, workers: real(url, base, ncols, j, i0 + 1, i1 + 1, dtype, workers))
    R.OUT.clear()
    b.receipts(cache_path, gebco["flat"])
    assert [r["claim"][:20] for r in R.OUT if r["ok"] is False] == ["GEBCO per-row byte-r"]


def test_a_sign_flip_in_depth_fails_the_node_receipt(server, gebco, tmp_path, monkeypatch):
    from cafe import receipts as R
    cache_path = b.fetch_gebco(BOX, tmp_path / "g.npz", gebco["flat"])
    flip = b.Bathymetry.__call__
    monkeypatch.setattr(b.Bathymetry, "__call__", lambda self, lon, lat: flip(self, lon, lat)._replace(value=-flip(self, lon, lat).value))
    R.OUT.clear()
    b.receipts(cache_path)
    assert [r["claim"][:12] for r in R.OUT if r["ok"] is False] == ["bilinear dep", "GEBCO cache:"]
