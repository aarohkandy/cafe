"""Remote files over HTTPS: verified TLS, byte ranges, resumable hash-checked downloads, CDF-1 headers.

orca.atmos.washington.edu serves the wrong intermediate certificate (InCommon RSA Server CA instead of CA 2), so
verification fails on Linux unless the right intermediate is trusted too. `config/certs/incommon_rsa_server_ca2.pem`
is that certificate (fetched from its AIA URL http://crt.sectigo.com/InCommonRSAServerCA2.crt, chains to the
USERTrust root in the system store). Verification is never turned off.

    RemoteFile(url)            seekable read-only file: h5py.File(RemoteFile(url)) reads HDF5 hyperslabs by range; a block from another
                               version of the file than the first probe saw (size, ETag, Last-Modified) is a ConnectionError
    cdf1_header(url)           (dims, nrec, {var: dict(dims, dtype, shape, offset, record, attrs)}) of a NetCDF classic file; for a URL it also holds
                               the identity of the version it was read from (`.ident`), and every read of that file through it is checked against it
    cdf1_read(url, var, hdr)   one variable of a CDF-1 file, by range; a reply from another version than the header's is a ConnectionError
    download(url, path, sha, pin)  resumable (HTTP Range) only while the server file is the one the .part came from; size-checked,
                               `sha` decides whether an existing file is kept, and is checked on a fresh download only with `pin`
"""
from __future__ import annotations

import hashlib, http.client, io, json, math, os, pathlib, ssl, struct, time, urllib.error, urllib.request
from collections.abc import Callable
from typing import Any

import numpy as np
from numpy.typing import NDArray

ROOT = pathlib.Path(__file__).resolve().parents[3]
EXTRA_CA = ROOT / "config" / "certs" / "incommon_rsa_server_ca2.pem"
BLOCK = 4 << 20


def context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if EXTRA_CA.exists():
        ctx.load_verify_locations(cafile=str(EXTRA_CA))
    return ctx


_CTX: ssl.SSLContext | None = None


def _open(url: str, start: int | None = None, end: int | None = None, timeout: float = 60, tries: int = 4,
          if_range: str | None = None) -> http.client.HTTPResponse:
    global _CTX
    _CTX = _CTX or context()
    hdr = {"User-Agent": "cafe-premission"}
    err: Exception = ConnectionError("no attempt made")
    if start is not None:
        hdr["Range"] = f"bytes={start}-{'' if end is None else end}"
        if if_range:
            hdr["If-Range"] = if_range                     # a server whose file changed answers 200 with the whole new body, not the tail of the old
    for k in range(tries):
        try:
            r: http.client.HTTPResponse = urllib.request.urlopen(urllib.request.Request(url, headers=hdr), context=_CTX, timeout=timeout)
            return r
        except urllib.error.HTTPError as e:
            if e.code in (403, 404, 416):
                raise FileNotFoundError(f"{url}: HTTP {e.code}") from e
            err = e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            err = e
        time.sleep(2 ** k)
    raise ConnectionError(f"{url}: {err}")


Ident = tuple[int, dict[str, str]]


class Header(tuple[dict[str, int], int, dict[str, dict[str, Any]]]):
    """(dims, nrec, vars) of a NetCDF classic file. Read from a URL, `ident` is the identity (`_ident`) of the version the header came from: the offsets in
    it are that version's, so `cdf1_read` asks every reply to be a piece of the same one, not a byte range of a file replaced in between (look-ahead L0
    after round 12, M-25). None for a local file."""
    ident: Ident | None = None


def _ident(r: http.client.HTTPResponse, url: str) -> Ident:
    """(total bytes, the validators the server sends: ETag, Last-Modified) of a ranged reply: which version of the file this reply is a piece of. A total
    the server does not state (`bytes a-b/*`, legal, or anything that is not a number) is -1: the reads that only need pieces compare identities as before,
    `_probe` (which needs the size) refuses it (look-ahead L0 after round 12, M-25)."""
    cr = r.headers.get("Content-Range", "")
    if not cr.startswith("bytes"):
        raise ConnectionError(f"{url}: server ignored the Range header; byte-range reads need it")
    try:
        total = int(cr.rpartition("/")[2])
    except ValueError:
        total = -1
    return total, {k: r.headers[k] for k in ("ETag", "Last-Modified") if r.headers.get(k)}


def _read_ident(url: str, start: int | None, end: int | None, timeout: float = 60, tries: int = 3, ident: Ident | None = None) -> tuple[bytes, Ident | None]:
    """(body, identity of the version it came from) of a ranged GET. A connection cut mid-body (IncompleteRead, reset, timeout) is retried like a failed
    connect. With `ident` (what the first probe saw) a reply from another version of the file is a ConnectionError, not bytes to splice in (round 12);
    without it the identity is None for a read with no range (no Content-Range to take it from)."""
    err: Exception = ConnectionError("no attempt made")
    for k in range(tries):
        try:
            with _open(url, start, end, timeout) as r:
                if start is not None and r.status != 206:
                    raise ConnectionError(f"{url}: server ignored the Range header (HTTP {r.status}); byte-range reads need it")
                got = _ident(r, url) if start is not None else None
                if ident is not None and got != ident:
                    raise ConnectionError(f"{url}: the file changed on the server during this session (first seen {ident}, now {got}); start again")
                return r.read(), got
        except (http.client.IncompleteRead, ConnectionResetError, TimeoutError) as e:
            err = e
        time.sleep(2 ** k)
    raise ConnectionError(f"{url}: {err!r}")


def _read(url: str, start: int | None, end: int | None, timeout: float = 60, tries: int = 3, ident: Ident | None = None) -> bytes:
    """Body of a ranged GET (see `_read_ident`)."""
    return _read_ident(url, start, end, timeout, tries, ident)[0]


def _probe(url: str) -> Ident:
    """The identity (see `_ident`) of the file, from a one-byte ranged GET. The size is what `size`, `RemoteFile` and `download` are built on, so a server
    that does not state it is a ConnectionError naming that, not a size of -1. A file of 0 bytes answers 416 and is (0, {}), not a missing file
    (round 13, M-18)."""
    try:
        with _open(url, 0, 0) as r:
            got = _ident(r, url)
    except FileNotFoundError as e:
        c = e.__cause__
        if isinstance(c, urllib.error.HTTPError) and c.code == 416:          # `bytes=0-0` of a file of 0 bytes is "not satisfiable": it is there, and empty
            return 0, {}
        raise
    if got[0] < 0:
        raise ConnectionError(f"{url}: server does not state the file size (Content-Range total is not a number)")
    return got


def _if_range(valid: dict[str, str]) -> str | None:
    """The If-Range value for a file with these validators: its strong ETag, else Last-Modified (a weak ETag cannot be an If-Range validator)."""
    etag = valid.get("ETag", "")
    return etag if etag and not etag.startswith("W/") else valid.get("Last-Modified")


def size(url: str) -> int:
    return _probe(url)[0]


class RemoteFile(io.RawIOBase):
    """Read-only, seekable view of a URL; fetches aligned 4 MB blocks on demand and keeps them (LRU, 64 blocks). Every block's reply must come from the
    version of the file the first probe saw (size, ETag, Last-Modified), else ConnectionError: blocks of two versions are never joined (round 12)."""

    def __init__(self, url: str, block: int = BLOCK, keep: int = 64) -> None:
        self.url, self.block, self.keep = url, block, keep
        self.ident = _probe(url)
        self.n = self.ident[0]
        self.pos, self.cache, self.fetched = 0, dict[int, bytes](), 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, off: int, whence: int = 0) -> int:
        self.pos = {0: off, 1: self.pos + off, 2: self.n + off}[whence]
        return self.pos

    def _blk(self, i: int) -> bytes:
        if i in self.cache:
            self.cache[i] = self.cache.pop(i)          # move to most-recent
            return self.cache[i]
        a = i * self.block
        b = min(a + self.block, self.n) - 1
        data = _read(self.url, a, b, ident=self.ident)
        if len(data) != b - a + 1:
            raise ConnectionError(f"{self.url}: short read at {a} ({len(data)} of {b - a + 1} bytes)")
        self.fetched += len(data)
        self.cache[i] = data
        while len(self.cache) > self.keep:
            self.cache.pop(next(iter(self.cache)))
        return data

    def readinto(self, buf: Any) -> int:
        want = min(len(buf), max(self.n - self.pos, 0))
        got = 0
        while got < want:
            i, o = divmod(self.pos, self.block)
            d = self._blk(i)[o:o + want - got]
            buf[got:got + len(d)] = d
            got += len(d)
            self.pos += len(d)
        return got


def sha256(path: str | pathlib.Path, chunk: int = 8 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def tree_sha256(path: str | pathlib.Path) -> str:
    """sha256 over the relative path and bytes of every file under the directory `path` (a zarr store), in path order: what a store's ledger input
    and the audit compare, so a changed value, a deleted chunk or an added file is a different hash."""
    root = pathlib.Path(path)
    h = hashlib.sha256()
    for f in sorted(p for p in root.rglob("*") if p.is_file()):
        h.update(f.relative_to(root).as_posix().encode() + b"\0")
        with open(f, "rb") as fh:
            for b in iter(lambda: fh.read(8 << 20), b""):
                h.update(b)
    return h.hexdigest()


def download(url: str, path: str | pathlib.Path, sha: str | None = None, pin: bool = False) -> pathlib.Path:
    """Resumable download to `path` (a `.part` file grows until complete), checked against the size the server states.

    `sha` only decides whether an existing `path` is good enough to keep (its hash equals `sha`); the file a fresh download brings is compared with it
    only when `pin` is set, and then a mismatch is a ValueError. A caller that holds the hash of an *earlier* copy (the TAO manifest) must not pin it:
    when upstream replaced the file, the old hash would refuse the new one on every try (round 12, M-26).

    A `.part` left by an earlier call is resumed only when `<name>.part.id` records the same total size, ETag and Last-Modified the server sends now and
    the server sends a validator that can go in If-Range (a strong ETag or Last-Modified); with no record, another version, or no such validator it starts
    again from byte 0, and the resume request carries If-Range so that a file replaced in between comes back whole (round 12, M-25; look-ahead L1: a
    server with no validator cannot tell a v1 part from v2 whatever the size, and no hash is checked here to catch the splice). A transfer cut inside
    one call is still continued from where it stopped: that is seconds, not a restart of the process, and the size and 206 are checked."""
    path = pathlib.Path(path)
    if path.exists() and (sha is None or sha256(path) == sha):
        return path
    part = path.with_name(path.name + ".part")
    mark = part.with_name(part.name + ".id")
    path.parent.mkdir(parents=True, exist_ok=True)
    total, valid = _probe(url)
    ident = dict(valid, total=total)
    try:
        seen = json.loads(mark.read_text())
    except (OSError, ValueError):
        seen = None
    ifr = _if_range(valid)
    if seen != ident or ifr is None:                                   # no validator the server honours: nothing tells a part of v1 from the rest of v2
        part.unlink(missing_ok=True)
        mark.write_text(json.dumps(ident))
    have = part.stat().st_size if part.exists() else 0
    if have > total:
        part.unlink()
        have = 0
    while have < total:
        with _open(url, have, None, timeout=120, if_range=ifr if have else None) as r:
            if have and (r.status != 206 or _ident(r, url) != (total, valid)):      # replaced since the probe (a server that ignores If-Range still says so)
                part.unlink()
                have = 0
                total, valid = _probe(url)
                mark.write_text(json.dumps(dict(valid, total=total)))
                ifr = _if_range(valid)
                continue
            with open(part, "ab" if have else "wb") as f:
                for b in iter(lambda: r.read(1 << 20), b""):
                    f.write(b)
        if part.stat().st_size == have:
            raise ConnectionError(f"{url}: stalled at {have} of {total} bytes; rerun to resume")
        have = part.stat().st_size
    if not total:
        part.touch()                                                   # a file of 0 bytes never opened the part in the loop
    if have != total:
        raise ConnectionError(f"{url}: {have} bytes on disk, server says {total}")
    if pin and sha and sha256(part) != sha:
        part.unlink()
        mark.unlink(missing_ok=True)
        raise ValueError(f"{url}: SHA-256 mismatch against the pinned hash, download removed")
    os.replace(part, path)
    mark.unlink(missing_ok=True)
    return path


# ------------------------------------------------------------------ NetCDF classic (CDF-1/CDF-2) headers

_NC = {1: ("i1", 1), 2: ("S1", 1), 3: (">i2", 2), 4: (">i4", 4), 5: (">f4", 4), 6: (">f8", 8)}
MAX_ITEM = 64 << 20          # one name or one attribute value of a header; the real files' are a few kB, so a longer one is a damaged length (round 13, M-15)


def _bad(what: str) -> ValueError:
    return ValueError(f"damaged NetCDF header: {what}")


class _Buf:
    def __init__(self, fetch: Callable[[int, int], bytes]) -> None:
        self.fetch, self.data, self.p = fetch, b"", 0

    def take(self, n: int) -> bytes:
        if not 0 <= n <= MAX_ITEM:
            raise _bad(f"a field of {n} bytes at byte {self.p}")
        while self.p + n > len(self.data):
            more = self.fetch(len(self.data), max(65536, n))
            if not more:
                raise EOFError(f"header ends at byte {len(self.data)}, {self.p + n - len(self.data)} more bytes needed")
            self.data += more
        b = self.data[self.p:self.p + n]
        self.p += n
        return b

    def i4(self) -> int:
        return int(struct.unpack(">i", self.take(4))[0])

    def count(self) -> int:
        n = self.i4()
        if n < 0:
            raise _bad(f"a count of {n} at byte {self.p - 4}")
        return n

    def name(self) -> str:
        n = self.count()
        try:
            s = self.take(n).decode()
        except UnicodeDecodeError as e:
            raise _bad(f"a name that is not UTF-8 at byte {self.p - n}") from e
        self.take(-n % 4)
        return s

    def kind(self, want: int) -> int:
        """The count of a (tag, count) list header: 0 for an absent list, else the number of entries (the tag must be `want`)."""
        tag, n = self.i4(), self.count()
        if tag not in (0, want) or (tag == 0 and n):
            raise _bad(f"list tag {tag} (expected {want}) at byte {self.p - 8}")
        return n

    def type(self) -> tuple[int, str, int]:
        t = self.i4()
        if t not in _NC:
            raise _bad(f"type code {t} at byte {self.p - 4}")
        return (t, *_NC[t])

    def attrs(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for _ in range(self.kind(12)):
            k = self.name()
            t, dt, w = self.type()
            m = self.count()
            raw = self.take(m * w)
            self.take(-(m * w) % 4)
            out[k] = raw.decode(errors="replace") if t == 2 else np.frombuffer(raw, dt)
        return out


def parse_cdf1(fetch: Callable[[int, int], bytes]) -> Header:
    """Parse a classic NetCDF header. fetch(offset, nbytes) -> bytes. Returns (dims, nrec, vars).

    The file's lengths, counts, ids, type codes and sizes are the server's, so each is checked where it is read: a damaged header is a ValueError saying
    what and where, never an IndexError or KeyError, a name read from a negative length, or a negative shape (round 13, M-15). A header that ends early
    is still an EOFError (the caller may fetch more), and a fetch that fails is its own error."""
    b = _Buf(fetch)
    magic = b.take(4)
    if magic[:3] != b"CDF" or magic[3] not in (1, 2):
        raise ValueError(f"not a NetCDF classic file (magic {magic!r})")
    off8 = magic[3] == 2
    nrec = b.i4()
    dims: list[tuple[str, int]] = []
    for _ in range(b.kind(10)):
        dims.append((b.name(), b.count()))
    b.attrs()
    out: dict[str, dict[str, Any]] = {}
    for _ in range(b.kind(11)):
        name = b.name()
        ids = [b.count() for _ in range(b.count())]
        if any(i >= len(dims) for i in ids):
            raise _bad(f"{name}: dimension id {max(ids)} of {len(dims)} dimensions")
        atts = b.attrs()
        t, vsize = b.type()[0], b.i4()
        begin = struct.unpack(">q" if off8 else ">i", b.take(8 if off8 else 4))[0]
        dn = [dims[i][0] for i in ids]
        shape = [nrec if dims[i][1] == 0 else dims[i][1] for i in ids]
        if min(shape, default=0) < 0 or begin < 0:                       # not vsize: unsigned in the file (the 2.4 GB restart F is negative signed)
            raise _bad(f"{name}: shape {shape}, offset {begin}")
        out[name] = dict(dims=dn, dtype=_NC[t][0], shape=shape, offset=begin, vsize=vsize,
                         record=bool(ids) and dims[ids[0]][1] == 0, attrs=atts)
    rv = [v for v in out.values() if v["record"]]
    recsize = sum(v["vsize"] for v in rv)
    if len(rv) == 1:                         # a lone record variable is packed without padding (netCDF classic format spec)
        recsize = math.prod(rv[0]["shape"][1:]) * np.dtype(rv[0]["dtype"]).itemsize
    for v in out.values():
        v["recsize"] = recsize
    return Header((dict(dims), nrec, out))


def _is_url(p: str) -> bool:
    """A remote file, as opposed to a local path that merely starts with "http" (httpx.nc, http_cache/...)."""
    return p.lower().startswith(("http://", "https://"))


def cdf1_header(url_or_path: str | pathlib.Path) -> Header:
    p = str(url_or_path)
    try:
        return _header(p)
    except ValueError as e:                                     # not a classic file, or a damaged header: say whose
        raise ValueError(f"{p}: {e}") from e


def _header(p: str) -> Header:
    if _is_url(p):
        seen: list[Ident] = []                                  # the first piece says which version this is; every later piece must be of it

        def piece(o: int, n: int) -> bytes:
            body, got = _read_ident(p, o, o + n - 1, ident=seen[0] if seen else None)
            if got is not None and not seen:
                seen.append(got)
            return body
        hdr = parse_cdf1(piece)
        hdr.ident = seen[0] if seen else None
        return hdr
    with open(p, "rb") as f:
        return parse_cdf1(lambda o, n: (f.seek(o), f.read(n))[1])


def cdf1_read(url_or_path: str | pathlib.Path, var: str, header: Header, rec: int = 0, rows: tuple[int, int] | None = None) -> NDArray[Any]:
    """One variable (one record if it is a record variable), read by byte range or from a local file.

    rows=(a, b) reads only indices a..b-1 of the variable's first non-record axis (one contiguous range), e.g. the
    rows of a (y, x) field or a run of sea points of an (x, th, f) spectrum."""
    v = header[2][var]
    if v["record"] and not 0 <= rec < header[1]:
        raise IndexError(f"{var}: record {rec} outside 0..{header[1]}")
    shape = list(v["shape"][1:] if v["record"] else v["shape"])
    item = np.dtype(v["dtype"]).itemsize
    off = v["offset"] + (rec * v["recsize"] if v["record"] else 0)
    if rows is not None:
        a, b = rows
        if not 0 <= a < b <= shape[0]:
            raise IndexError(f"{var}: rows {a}..{b} outside 0..{shape[0]}")
        off += a * math.prod(shape[1:]) * item
        shape[0] = b - a
    nbytes = math.prod(shape) * item
    p = str(url_or_path)
    if _is_url(p):
        raw = _read(p, off, off + nbytes - 1, timeout=300, ident=getattr(header, "ident", None))      # a header built by hand has none
    else:
        with open(p, "rb") as f:
            f.seek(off)
            raw = f.read(nbytes)
    if len(raw) != nbytes:
        raise ConnectionError(f"{p}:{var}: short read ({len(raw)} of {nbytes} bytes)")
    return np.frombuffer(raw, v["dtype"]).reshape(shape).astype(v["dtype"][1:] if v["dtype"][0] == ">" else v["dtype"])
