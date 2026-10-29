"""cafe.pm.env.remote against a local Range-capable server and against netCDF4's reading of the same files."""
import hashlib
import ssl

import netCDF4
import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from cafe.pm.env import remote

RNG = np.random.default_rng(7)
FIXTURE = settings(deadline=None, max_examples=60, suppress_health_check=[HealthCheck.function_scoped_fixture])


# ------------------------------------------------------------------ TLS context

def test_context_verifies_and_trusts_the_extra_intermediate(monkeypatch, tmp_path):
    ctx = remote.context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    monkeypatch.setattr(remote, "EXTRA_CA", tmp_path / "absent.pem")
    plain = remote.context()
    assert plain.verify_mode == ssl.CERT_REQUIRED and plain.check_hostname
    assert len(ctx.get_ca_certs()) == len(plain.get_ca_certs()) + 1      # the InCommon intermediate from config/certs


def test_https_is_verified_and_only_the_extra_ca_changes_the_verdict(server, selfsigned, monkeypatch, tmp_path):
    from tests.conftest import Server
    s = Server(server.root, certs=selfsigned)
    try:
        s.put("a", b"hello")
        monkeypatch.setattr(remote, "_CTX", None)
        monkeypatch.setattr(remote, "EXTRA_CA", tmp_path / "absent.pem")
        with pytest.raises(ConnectionError, match="CERTIFICATE_VERIFY_FAILED"):
            remote._open(s.url("a"), tries=1)
        monkeypatch.setattr(remote, "_CTX", None)
        monkeypatch.setattr(remote, "EXTRA_CA", selfsigned[0])
        with remote._open(s.url("a")) as r:
            assert r.read() == b"hello"
    finally:
        s.close()


# ------------------------------------------------------------------ _open / size

def test_open_sends_range_headers(server):
    u = server.put("a", bytes(range(100)))
    with remote._open(u) as r:
        assert r.status == 200 and len(r.read()) == 100
    with remote._open(u, 10, 19) as r:
        assert r.status == 206 and r.read() == bytes(range(10, 20))
    with remote._open(u, 90) as r:
        assert r.read() == bytes(range(90, 100))
    assert server.requests("a") == [None, "bytes=10-19", "bytes=90-"]


@pytest.mark.parametrize("code", [403, 404, 416])
def test_open_missing_is_not_retried(server, clock, code):
    server.plan["x"] = [("status", code)]
    with pytest.raises(FileNotFoundError, match=f"HTTP {code}"):
        remote._open(server.url("x"))
    assert len(server.requests("x")) == 1 and clock == []


def test_open_missing_file_404(server):
    with pytest.raises(FileNotFoundError, match="HTTP 404"):
        remote._open(server.url("nope"), 0, 0)


def test_open_retries_http_errors_and_dropped_connections(server, clock):
    u = server.put("a", b"abc")
    server.plan["a"] = [("status", 503), ("drop",), ("status", 500)]
    with remote._open(u) as r:
        assert r.read() == b"abc"
    assert len(server.requests("a")) == 4 and clock == [1, 2, 4]


def test_open_gives_up_after_four_tries(server, clock):
    server.put("a", b"abc")
    server.plan["a"] = [("status", 503)] * 9
    with pytest.raises(ConnectionError, match="HTTP Error 503"):
        remote._open(server.url("a"))
    assert len(server.requests("a")) == 4 and clock == [1, 2, 4, 8]


def test_open_retries_a_stalled_server(server, clock):
    u = server.put("a", b"abc")
    server.plan["a"] = [("sleep", 0.6)]
    with remote._open(u, timeout=0.2) as r:
        assert r.read() == b"abc"
    assert clock == [1]


def test_open_unreachable_and_no_attempt(server, clock):
    u = server.url("a")
    server.close()
    with pytest.raises(ConnectionError, match="Connection refused"):
        remote._open(u, tries=2)
    assert clock == [1, 2]
    with pytest.raises(ConnectionError, match="no attempt made"):
        remote._open(u, tries=0)


def test_size_reads_content_range_total(server):
    assert remote.size(server.put("a", b"x" * 1234)) == 1234
    assert remote.size(server.put("b", b"y")) == 1


def test_size_refuses_a_server_that_ignores_range(server):
    u = server.put("a", b"x" * 50)
    server.ignore_range = True
    with pytest.raises(ConnectionError, match="ignored the Range header"):
        remote.size(u)


def test_ranged_reads_refuse_a_server_that_ignores_range(server):
    u = server.put("a", bytes(range(200)))
    server.ignore_range = True
    with pytest.raises(ConnectionError, match="ignored the Range header"):
        remote._read(u, 10, 19)


def test_size_missing(server):
    with pytest.raises(FileNotFoundError):
        remote.size(server.url("missing"))


# ------------------------------------------------------------------ RemoteFile

@pytest.fixture
def blob(server):
    data = RNG.integers(0, 256, 1000, dtype=np.uint8).tobytes()
    return data, server.put("blob", data)


def test_remotefile_is_a_seekable_reader(blob):
    data, u = blob
    f = remote.RemoteFile(u, block=64)
    assert f.readable() and f.seekable() and f.n == 1000 and f.tell() == 0
    assert f.read(10) == data[:10] and f.tell() == 10
    assert f.seek(5) == 5 and f.seek(3, 1) == 8 and f.seek(-10, 2) == 990
    assert f.read(100) == data[990:]                                     # clipped at EOF
    assert f.read(5) == b"" and f.tell() == 1000
    f.seek(0)
    assert f.read() == data                                              # readall crosses every block boundary


@given(st.sampled_from([1, 7, 64, 100, 999, 1000, 4096]),
       st.lists(st.tuples(st.integers(0, 1100), st.integers(0, 300)), max_size=8))
@FIXTURE
def test_remotefile_matches_the_bytes_on_disk(blob, block, reads):
    data, u = blob
    f = remote.RemoteFile(u, block=block, keep=1000)
    for off, n in reads:
        f.seek(off)
        assert f.read(n) == data[off:off + n]
        assert f.tell() == min(off + n, 1000) if off < 1000 else f.tell() == off


def test_remotefile_lru_eviction(blob, server):
    data, u = blob
    f = remote.RemoteFile(u, block=8, keep=2)

    def touch(i):
        f.seek(i * 8)
        assert f.read(1) == data[i * 8:i * 8 + 1]
    for i in (0, 1, 0, 2):                                               # 1 is least recently used when 2 arrives
        touch(i)
    assert list(f.cache) == [0, 2] and f.fetched == 24
    touch(1)                                                             # refetched, evicting 0
    assert list(f.cache) == [2, 1] and f.fetched == 32
    touch(2)
    assert f.fetched == 32                                               # still cached
    assert len(server.requests("blob")) == 1 + 4                         # size probe + blocks 0, 1, 2, 1


def test_remotefile_last_block_is_short(blob):
    data, u = blob
    f = remote.RemoteFile(u, block=64)
    f.seek(960)
    assert f.read(100) == data[960:] and f.fetched == 40


def test_remotefile_short_read_is_an_error(blob, server):
    data, u = blob
    f = remote.RemoteFile(u, block=100)
    server.plan["blob"] = [("short", 30)]
    with pytest.raises(ConnectionError, match=r"short read at 0 \(30 of 100 bytes\)"):
        f.read(10)


def test_remotefile_retries_a_truncated_body(blob, server):
    data, u = blob
    f = remote.RemoteFile(u, block=100)
    server.plan["blob"] = [("truncate", 30)]
    assert f.read(100) == data[:100]


def test_a_body_that_keeps_truncating_is_a_connection_error(blob, server):
    data, u = blob
    f = remote.RemoteFile(u, block=100)
    server.plan["blob"] = [("truncate", 30)] * 9
    with pytest.raises(ConnectionError, match="IncompleteRead"):
        f.read(100)


# ------------------------------------------------------------------ download

def test_sha256_matches_hashlib(tmp_path):
    p = tmp_path / "f"
    p.write_bytes(b"abcdefghij" * 5)
    assert remote.sha256(p, chunk=7) == hashlib.sha256(b"abcdefghij" * 5).hexdigest()


def test_download_streams_many_chunks_and_is_idempotent(server, tmp_path):
    data = RNG.integers(0, 256, (5 << 19), dtype=np.uint8).tobytes()      # 2.5 MB: three 1 MB reads
    u = server.put("big", data)
    sha = hashlib.sha256(data).hexdigest()
    (tmp_path / "out").mkdir()
    p = remote.download(u, tmp_path / "out" / "big", sha)
    assert p.read_bytes() == data and not (tmp_path / "out" / "big.part").exists()
    n = len(server.log)
    assert remote.download(u, p, sha) == p and remote.download(u, p) == p
    assert len(server.log) == n                                          # a verified file is not fetched again


def test_download_replaces_a_file_that_fails_its_sha(server, tmp_path):
    u = server.put("a", b"fresh bytes")
    p = tmp_path / "a"
    p.write_bytes(b"stale")
    remote.download(u, p, hashlib.sha256(b"fresh bytes").hexdigest())
    assert p.read_bytes() == b"fresh bytes"


def test_download_resumes_a_partial_file(server, tmp_path):
    data = bytes(range(256)) * 40
    u = server.put("a", data)
    (tmp_path / "a.part").write_bytes(data[:3000])
    p = remote.download(u, tmp_path / "a", hashlib.sha256(data).hexdigest())
    assert p.read_bytes() == data
    assert server.requests("a") == ["bytes=0-0", "bytes=3000-"]


def test_download_resumes_after_a_connection_cut_mid_body(server, tmp_path):
    data = bytes(range(256)) * 40
    u = server.put("a", data)
    server.plan["a"] = [("call", lambda s: None), ("truncate", 1000)]    # size probe fine, first body cut after 1000 bytes
    p = remote.download(u, tmp_path / "a")
    assert p.read_bytes() == data
    assert server.requests("a") == ["bytes=0-0", "bytes=0-", "bytes=1000-"]


def test_download_discards_an_oversized_part(server, tmp_path):
    u = server.put("a", b"short")
    (tmp_path / "a.part").write_bytes(b"x" * 100)
    assert remote.download(u, tmp_path / "a").read_bytes() == b"short"


def test_download_sha_mismatch_removes_the_part_and_the_target(server, tmp_path):
    u = server.put("a", b"payload")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        remote.download(u, tmp_path / "a", "0" * 64)
    assert not (tmp_path / "a").exists() and not (tmp_path / "a.part").exists()


def test_download_size_mismatch_when_the_file_grew(server, tmp_path):
    u = server.put("a", b"x" * 100)
    server.plan["a"] = [("call", lambda s: None), ("call", lambda s: s.put("a", b"x" * 150))]
    with pytest.raises(ConnectionError, match="150 bytes on disk, server says 100"):
        remote.download(u, tmp_path / "a")
    assert (tmp_path / "a.part").exists() and not (tmp_path / "a").exists()


def test_download_a_stalled_transfer_fails_instead_of_looping(server, tmp_path):
    u = server.put("a", b"x" * 100)
    server.plan["a"] = [("call", lambda s: None)] + [("short", 0)] * 40
    with pytest.raises(ConnectionError, match="stalled at 0 of 100"):
        remote.download(u, tmp_path / "a")


def test_download_missing(server, tmp_path):
    with pytest.raises(FileNotFoundError):
        remote.download(server.url("nope"), tmp_path / "x")


# ------------------------------------------------------------------ NetCDF classic

FORMATS = ["NETCDF3_CLASSIC", "NETCDF3_64BIT_OFFSET"]
NREC = 3


def make_cdf(path, fmt, nrec=NREC):
    """Fixed and record variables of every classic type, odd sizes (padding), attributes of every type, scalar variable."""
    with netCDF4.Dataset(path, "w", format=fmt) as nc:
        nc.title, nc.version = "global text", np.int32(3)
        for d, n in (("Time", None), ("y", 3), ("x", 5), ("c", 7)):
            nc.createDimension(d, n)
        b = nc.createVariable("b", "i1", ("x",))
        b[:] = np.arange(1, 6, dtype="i1")
        b.units, b.long_name, b.gain = "m", "abcde", np.float64(2.5)
        b.valid, b.flags = np.array([1, 2, 3], "i2"), np.array([1, 2, 3], "i1")
        b.fl, b.one = np.array([0.5, 1.5], "f4"), np.int32(7)
        nc.createVariable("txt", "S1", ("c",))[:] = np.frombuffer(b"abcdefg", "S1")
        nc.createVariable("s", "i2", ("y", "x"))[:] = np.arange(15, dtype="i2").reshape(3, 5) - 7
        nc.createVariable("i", "i4", ("y",))[:] = np.array([-1, 0, 1 << 30], "i4")
        nc.createVariable("f", "f4", ("y", "x"))[:] = np.arange(15, dtype="f4").reshape(3, 5) / 4
        nc.createVariable("sc", "f8", ())[...] = 3.25
        nc.createVariable("pad", "i1", ("y",))[:] = np.array([1, 2, 3], "i1")
        nc.createVariable("r1", "f4", ("Time", "x"))
        nc.createVariable("r2", "i2", ("Time", "x"))
        nc.createVariable("r3", "i1", ("Time", "c"))
        nc.createVariable("r4", "f8", ("Time",))
        for r in range(nrec):
            nc["r1"][r] = np.arange(5, dtype="f4") + 10 * r
            nc["r2"][r] = np.arange(5, dtype="i2") - 100 * r
            nc["r3"][r] = np.arange(7, dtype="i1") + r
            nc["r4"][r] = r + 0.5
        nc["r1"].units = "K"


@pytest.fixture(scope="module", params=FORMATS)
def cdf_file(request, tmp_path_factory):
    p = tmp_path_factory.mktemp("cdf") / "t.nc"
    make_cdf(p, request.param)
    return p


@pytest.fixture(params=["local", "http"])
def cdf(request, cdf_file, server):
    """(path or URL, local path): the same CDF file read directly and through the server."""
    return (str(cdf_file) if request.param == "local" else server.put("t.nc", cdf_file.read_bytes())), cdf_file


def test_header_matches_netcdf4(cdf):
    src, path = cdf
    dims, nrec, vs = remote.cdf1_header(src)
    with netCDF4.Dataset(path) as ref:
        assert dims == {n: 0 if d.isunlimited() else len(d) for n, d in ref.dimensions.items()}
        assert nrec == len(ref.dimensions["Time"]) == NREC
        assert set(vs) == set(ref.variables)
        for n, v in ref.variables.items():
            h = vs[n]
            assert h["dims"] == list(v.dimensions) and h["shape"] == list(v.shape)
            assert np.dtype(h["dtype"]).newbyteorder("=") == v.dtype
            assert h["record"] == bool(v.dimensions and ref.dimensions[v.dimensions[0]].isunlimited())
            assert set(h["attrs"]) == set(v.ncattrs())
            for k in v.ncattrs():
                a = v.getncattr(k)
                if isinstance(a, str):
                    assert h["attrs"][k] == a
                else:
                    got = h["attrs"][k]
                    assert got.dtype.kind == np.asarray(a).dtype.kind and got.dtype.itemsize == np.asarray(a).dtype.itemsize
                    np.testing.assert_array_equal(got, np.atleast_1d(a))


def test_read_every_variable_matches_netcdf4(cdf):
    src, path = cdf
    hdr = remote.cdf1_header(src)
    with netCDF4.Dataset(path) as ref:
        ref.set_auto_mask(False)
        for n, v in ref.variables.items():
            for r in range(NREC if hdr[2][n]["record"] else 1):
                got = remote.cdf1_read(src, n, hdr, rec=r)
                want = v[r] if hdr[2][n]["record"] else v[...]
                np.testing.assert_array_equal(got, want)
                assert got.dtype == v.dtype and got.dtype.byteorder in ("=", "|")


def test_read_rows(cdf):
    src, path = cdf
    hdr = remote.cdf1_header(src)
    with netCDF4.Dataset(path) as ref:
        for n, a, b in (("s", 1, 3), ("s", 0, 1), ("f", 2, 3), ("i", 1, 3), ("b", 2, 5), ("r1", 0, 1), ("r2", 0, 5)):
            rec = 2 if hdr[2][n]["record"] else 0
            want = (ref[n][rec] if hdr[2][n]["record"] else ref[n][:])[a:b]
            got = remote.cdf1_read(src, n, hdr, rec=rec, rows=(a, b))
            np.testing.assert_array_equal(got, want)


@pytest.mark.parametrize("rows", [(-1, 2), (2, 2), (3, 2), (0, 4), (3, 4)])
def test_read_bad_rows(cdf, rows):
    src, _ = cdf
    with pytest.raises(IndexError, match="outside 0..3"):
        remote.cdf1_read(src, "s", remote.cdf1_header(src), rows=rows)


def test_record_index_past_the_end(cdf):
    src, _ = cdf
    hdr = remote.cdf1_header(src)
    with pytest.raises((ConnectionError, FileNotFoundError)):
        remote.cdf1_read(src, "r1", hdr, rec=NREC + 5)


def test_a_single_narrow_record_variable_is_not_padded(tmp_path, server):
    """netCDF packs the records of a lone byte/char/short record variable back to back (no 4-byte padding)."""
    p = tmp_path / "one.nc"
    with netCDF4.Dataset(p, "w", format="NETCDF3_CLASSIC") as nc:
        nc.createDimension("t", None)
        nc.createDimension("x", 3)
        v = nc.createVariable("a", "i1", ("t", "x"))
        for r in range(4):
            v[r] = np.array([r * 10 + 1, r * 10 + 2, r * 10 + 3], "i1")
        w = nc.createVariable("w", "i1", ("x",))
        w[:] = [9, 9, 9]
    for src in (str(p), server.put("one.nc", p.read_bytes())):
        hdr = remote.cdf1_header(src)
        for r in range(4):
            np.testing.assert_array_equal(remote.cdf1_read(src, "a", hdr, rec=r), [r * 10 + 1, r * 10 + 2, r * 10 + 3])


def test_large_header_is_fetched_in_several_pieces(tmp_path, server):
    p = tmp_path / "big.nc"
    with netCDF4.Dataset(p, "w", format="NETCDF3_CLASSIC") as nc:
        nc.createDimension("x", 2)
        v = nc.createVariable("v", "f4", ("x",))
        v.long = "z" * 150_000
        v[:] = [1.5, 2.5]
    for src in (str(p), server.put("big.nc", p.read_bytes())):
        hdr = remote.cdf1_header(src)
        assert len(hdr[2]["v"]["attrs"]["long"]) == 150_000
        np.testing.assert_array_equal(remote.cdf1_read(src, "v", hdr), [1.5, 2.5])


def test_not_a_classic_file(tmp_path):
    for magic in (b"\x89HDF\r\n\x1a\n", b"CDF\x05", b"CDF\x00", b"junk"):
        p = tmp_path / "x"
        p.write_bytes(magic + bytes(100))
        with pytest.raises(ValueError, match="not a NetCDF classic file"):
            remote.cdf1_header(p)


def test_truncated_header_fails_instead_of_hanging(cdf_file):
    calls = []

    def fetch(o, n):
        calls.append(o)
        assert len(calls) < 6, "fetch called again and again past the end of the file"
        return cdf_file.read_bytes()[:50][o:o + n]
    with pytest.raises(EOFError, match="header ends"):
        remote.parse_cdf1(fetch)


def test_short_local_and_remote_reads(cdf_file, server, tmp_path):
    hdr = remote.cdf1_header(cdf_file)
    cut = cdf_file.read_bytes()[:hdr[2]["r1"]["offset"] + 12]            # ends inside the first record of r1
    local = tmp_path / "cut.nc"
    local.write_bytes(cut)
    for src in (str(local), server.put("cut.nc", cut)):
        np.testing.assert_array_equal(remote.cdf1_read(src, "s", hdr), remote.cdf1_read(cdf_file, "s", hdr))
        with pytest.raises(ConnectionError, match="short read"):
            remote.cdf1_read(src, "r1", hdr)


def test_cdf1_reads_retry_a_truncated_body(cdf_file, server):
    u = server.put("t.nc", cdf_file.read_bytes())
    server.plan["t.nc"] = [("truncate", 20)]
    hdr = remote.cdf1_header(u)                                          # the header fetch survives a cut body
    server.plan["t.nc"] = [("truncate", 4)]
    np.testing.assert_array_equal(remote.cdf1_read(u, "f", hdr), remote.cdf1_read(cdf_file, "f", hdr))
