"""Remote files over HTTPS: verified TLS, byte ranges, resumable hash-checked downloads, CDF-1 headers.

orca.atmos.washington.edu serves the wrong intermediate certificate (InCommon RSA Server CA instead of CA 2), so
verification fails on Linux unless the right intermediate is trusted too. `config/certs/incommon_rsa_server_ca2.pem`
is that certificate (fetched from its AIA URL http://crt.sectigo.com/InCommonRSAServerCA2.crt, chains to the
USERTrust root in the system store). Verification is never turned off.

    RemoteFile(url)            seekable read-only file: h5py.File(RemoteFile(url)) reads HDF5 hyperslabs by range
    cdf1_header(url)           (dims, nrec, {var: dict(dims, dtype, shape, offset, record, attrs)}) of a NetCDF classic file
    cdf1_read(url, var, hdr)   one variable of a CDF-1 file, by range
    download(url, path, sha)   resumable (HTTP Range), verified against size and optional SHA-256
"""
import hashlib, http.client, io, os, pathlib, ssl, struct, time, urllib.error, urllib.request

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[3]
EXTRA_CA = ROOT / "config" / "certs" / "incommon_rsa_server_ca2.pem"
BLOCK = 4 << 20


def context():
    ctx = ssl.create_default_context()
    if EXTRA_CA.exists():
        ctx.load_verify_locations(cafile=str(EXTRA_CA))
    return ctx


_CTX = None


def _open(url, start=None, end=None, timeout=60, tries=4):
    global _CTX
    _CTX = _CTX or context()
    hdr = {"User-Agent": "cafe-premission"}
    err: Exception = ConnectionError("no attempt made")
    if start is not None:
        hdr["Range"] = f"bytes={start}-{'' if end is None else end}"
    for k in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=hdr), context=_CTX, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code in (403, 404, 416):
                raise FileNotFoundError(f"{url}: HTTP {e.code}") from e
            err = e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            err = e
        time.sleep(2 ** k)
    raise ConnectionError(f"{url}: {err}")


def _read(url, start, end, timeout=60, tries=3):
    """Body of a ranged GET. A connection cut mid-body (IncompleteRead, reset, timeout) is retried like a failed connect."""
    err: Exception = ConnectionError("no attempt made")
    for k in range(tries):
        try:
            with _open(url, start, end, timeout) as r:
                if start is not None and r.status != 206:
                    raise ConnectionError(f"{url}: server ignored the Range header (HTTP {r.status}); byte-range reads need it")
                return r.read()
        except (http.client.IncompleteRead, ConnectionResetError, TimeoutError) as e:
            err = e
        time.sleep(2 ** k)
    raise ConnectionError(f"{url}: {err!r}")


def size(url):
    with _open(url, 0, 0) as r:
        cr = r.headers.get("Content-Range", "")
        if not cr.startswith("bytes"):
            raise ConnectionError(f"{url}: server ignored the Range header; byte-range reads need it")
        return int(cr.rsplit("/", 1)[1])


class RemoteFile(io.RawIOBase):
    """Read-only, seekable view of a URL; fetches aligned 4 MB blocks on demand and keeps them (LRU, 64 blocks)."""

    def __init__(self, url, block=BLOCK, keep=64):
        self.url, self.block, self.keep = url, block, keep
        self.n = size(url)
        self.pos, self.cache, self.fetched = 0, {}, 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = {0: off, 1: self.pos + off, 2: self.n + off}[whence]
        return self.pos

    def _blk(self, i):
        if i in self.cache:
            self.cache[i] = self.cache.pop(i)          # move to most-recent
            return self.cache[i]
        a = i * self.block
        b = min(a + self.block, self.n) - 1
        data = _read(self.url, a, b)
        if len(data) != b - a + 1:
            raise ConnectionError(f"{self.url}: short read at {a} ({len(data)} of {b - a + 1} bytes)")
        self.fetched += len(data)
        self.cache[i] = data
        while len(self.cache) > self.keep:
            self.cache.pop(next(iter(self.cache)))
        return data

    def readinto(self, buf):
        want = min(len(buf), max(self.n - self.pos, 0))
        got = 0
        while got < want:
            i, o = divmod(self.pos, self.block)
            d = self._blk(i)[o:o + want - got]
            buf[got:got + len(d)] = d
            got += len(d)
            self.pos += len(d)
        return got


def sha256(path, chunk=8 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def download(url, path, sha=None):
    """Resumable download to `path` (a `.part` file grows until complete), verified by size and optional SHA-256."""
    path = pathlib.Path(path)
    if path.exists() and (sha is None or sha256(path) == sha):
        return path
    part = path.with_name(path.name + ".part")
    total = size(url)
    have = part.stat().st_size if part.exists() else 0
    if have > total:
        part.unlink()
        have = 0
    while have < total:
        with _open(url, have, None, timeout=120) as r, open(part, "ab") as f:
            for b in iter(lambda: r.read(1 << 20), b""):
                f.write(b)
        if part.stat().st_size == have:
            raise ConnectionError(f"{url}: stalled at {have} of {total} bytes; rerun to resume")
        have = part.stat().st_size
    if have != total:
        raise ConnectionError(f"{url}: {have} bytes on disk, server says {total}")
    if sha and sha256(part) != sha:
        part.unlink()
        raise ValueError(f"{url}: SHA-256 mismatch, partial file removed; rerun to fetch it again")
    os.replace(part, path)
    return path


# ------------------------------------------------------------------ NetCDF classic (CDF-1/CDF-2) headers

_NC = {1: ("i1", 1), 2: ("S1", 1), 3: (">i2", 2), 4: (">i4", 4), 5: (">f4", 4), 6: (">f8", 8)}


class _Buf:
    def __init__(self, fetch):
        self.fetch, self.data, self.p = fetch, b"", 0

    def take(self, n):
        while self.p + n > len(self.data):
            more = self.fetch(len(self.data), max(65536, n))
            if not more:
                raise EOFError(f"header ends at byte {len(self.data)}, {self.p + n - len(self.data)} more bytes needed")
            self.data += more
        b = self.data[self.p:self.p + n]
        self.p += n
        return b

    def i4(self):
        return struct.unpack(">i", self.take(4))[0]

    def name(self):
        n = self.i4()
        s = self.take(n).decode()
        self.take(-n % 4)
        return s

    def attrs(self):
        tag, n = self.i4(), self.i4()
        out = {}
        for _ in range(n if tag == 12 else 0):
            k, t, m = self.name(), self.i4(), self.i4()
            dt, w = _NC[t]
            raw = self.take(m * w)
            self.take(-(m * w) % 4)
            out[k] = raw.decode(errors="replace") if t == 2 else np.frombuffer(raw, dt)
        return out


def parse_cdf1(fetch):
    """Parse a classic NetCDF header. fetch(offset, nbytes) -> bytes. Returns (dims, nrec, vars)."""
    b = _Buf(fetch)
    magic = b.take(4)
    if magic[:3] != b"CDF" or magic[3] not in (1, 2):
        raise ValueError(f"not a NetCDF classic file (magic {magic!r})")
    off8 = magic[3] == 2
    nrec = b.i4()
    tag, n = b.i4(), b.i4()
    dims = []
    for _ in range(n if tag == 10 else 0):
        dims.append((b.name(), b.i4()))
    b.attrs()
    tag, n = b.i4(), b.i4()
    out = {}
    for _ in range(n if tag == 11 else 0):
        name = b.name()
        ids = [b.i4() for _ in range(b.i4())]
        atts = b.attrs()
        t, vsize = b.i4(), b.i4()
        begin = struct.unpack(">q" if off8 else ">i", b.take(8 if off8 else 4))[0]
        dn = [dims[i][0] for i in ids]
        shape = [nrec if dims[i][1] == 0 else dims[i][1] for i in ids]
        out[name] = dict(dims=dn, dtype=_NC[t][0], shape=shape, offset=begin, vsize=vsize,
                         record=bool(ids) and dims[ids[0]][1] == 0, attrs=atts)
    rv = [v for v in out.values() if v["record"]]
    recsize = sum(v["vsize"] for v in rv)
    if len(rv) == 1:                         # a lone record variable is packed without padding (netCDF classic format spec)
        recsize = int(np.prod(rv[0]["shape"][1:])) * np.dtype(rv[0]["dtype"]).itemsize
    for v in out.values():
        v["recsize"] = recsize
    return dict(dims), nrec, out


def cdf1_header(url_or_path):
    p = str(url_or_path)
    if p.startswith("http"):
        return parse_cdf1(lambda o, n: _read(p, o, o + n - 1))
    with open(p, "rb") as f:
        return parse_cdf1(lambda o, n: (f.seek(o), f.read(n))[1])


def cdf1_read(url_or_path, var, header, rec=0, rows=None):
    """One variable (one record if it is a record variable), read by byte range or from a local file.

    rows=(a, b) reads only indices a..b-1 of the variable's first non-record axis (one contiguous range), e.g. the
    rows of a (y, x) field or a run of sea points of an (x, th, f) spectrum."""
    v = header[2][var]
    shape = list(v["shape"][1:] if v["record"] else v["shape"])
    item = np.dtype(v["dtype"]).itemsize
    off = v["offset"] + (rec * v["recsize"] if v["record"] else 0)
    if rows is not None:
        a, b = rows
        if not 0 <= a < b <= shape[0]:
            raise IndexError(f"{var}: rows {a}..{b} outside 0..{shape[0]}")
        off += a * int(np.prod(shape[1:])) * item
        shape[0] = b - a
    nbytes = int(np.prod(shape)) * item
    p = str(url_or_path)
    if p.startswith("http"):
        raw = _read(p, off, off + nbytes - 1, timeout=300)
    else:
        with open(p, "rb") as f:
            f.seek(off)
            raw = f.read(nbytes)
    if len(raw) != nbytes:
        raise ConnectionError(f"{p}:{var}: short read ({len(raw)} of {nbytes} bytes)")
    return np.frombuffer(raw, v["dtype"]).reshape(shape).astype(v["dtype"][1:] if v["dtype"][0] == ">" else v["dtype"])
