"""Shared fixtures for the ingest tests: a Range-capable HTTP(S) server, the mini orca tree, a no-sleep clock."""
import http.server
import pathlib
import re
import shutil
import ssl
import subprocess
import threading
import types
import urllib.parse

import pytest

from cafe.pm.env import orca, remote
from tests.fixtures.orca import make_fixtures as mk


class Server:
    """Serves files under `root` with HTTP Range (206 + Content-Range, 416 past the end, 404 for a missing file).

    ignore_range   answer every request with 200 and the whole file
    plan[name]     list of actions consumed one per request to that path (plan[None]: any path), then normal service:
                   ("status", code)  reply with only that status      ("drop",)         close without replying
                   ("short", n)      consistent but only n body bytes ("truncate", n)   promise the full body, send n, close
                   ("sleep", s)      stall s seconds first            ("call", fn)      run fn(server) then serve normally
    log            [(path, Range header or None)] of every request"""

    def __init__(self, root, certs=None):
        self.root, self.ignore_range, self.plan, self.log = pathlib.Path(root), False, {}, []
        self.lock = threading.Lock()
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.httpd.daemon_threads, self.httpd.srv = True, self
        if certs:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(*certs)
            self.httpd.socket = ctx.wrap_socket(self.httpd.socket, server_side=True)
        self.scheme = "https" if certs else "http"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base(self):
        return f"{self.scheme}://127.0.0.1:{self.httpd.server_address[1]}"

    def url(self, name):
        return f"{self.base}/{name}"

    def put(self, name, data):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return self.url(name)

    def requests(self, name=None):
        return [r for n, r in self.log if name is None or n == name]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _reply(self, code, body=b"", **hdr):
        self.send_response(code)
        for k, v in {"Content-Length": len(body), **hdr}.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        s = self.server.srv
        name = urllib.parse.unquote(self.path.lstrip("/"))
        rng = self.headers.get("Range")
        with s.lock:
            s.log.append((name, rng))
            acts = s.plan.get(name) or s.plan.get(None)
            act = acts.pop(0) if acts else None
        try:
            self._serve(s, name, rng, act)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _serve(self, s, name, rng, act):
        kind = act[0] if act else None
        if kind == "drop":
            return
        if kind == "status":
            return self._reply(act[1])
        if kind == "sleep":
            threading.Event().wait(act[1])
        if kind == "call":
            act[1](s)
        f = s.root / name
        if ".." in name or not f.is_file():
            return self._reply(404)
        data = f.read_bytes()
        n = len(data)
        m = re.fullmatch(r"bytes=(\d+)-(\d*)", rng or "")
        if not m or s.ignore_range:
            return self._reply(200, data)
        a, b = int(m[1]), min(int(m[2]) if m[2] else n - 1, n - 1)
        if a >= n or a > b:
            return self._reply(416, **{"Content-Range": f"bytes */{n}"})
        body = data[a:b + 1]
        if kind == "short":
            body = body[:act[1]]
        if kind == "truncate":
            self.close_connection = True
            self.send_response(206)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Range", f"bytes {a}-{b}/{n}")
            self.end_headers()
            self.wfile.write(body[:act[1]])
            self.wfile.flush()
            return
        self._reply(206, body, **{"Content-Range": f"bytes {a}-{a + len(body) - 1}/{n}"})


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    """remote.time.sleep records instead of sleeping, so the retry back-off (1, 2, 4, 8 s) costs nothing."""
    slept = []
    monkeypatch.setattr(remote, "time", types.SimpleNamespace(sleep=slept.append))
    return slept


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """CAFE_OFFLINE=1 for every test: the pipeline downloads nothing unless a test clears it (and then points the URLs at a local server)."""
    monkeypatch.setenv("CAFE_OFFLINE", "1")


@pytest.fixture
def server(tmp_path):
    s = Server(tmp_path / "www")
    s.root.mkdir()
    yield s
    s.close()


@pytest.fixture(scope="session")
def tree(tmp_path_factory):
    """The mini orca tree (hours 0..6, restarts at 0 and 6) and its schema dir."""
    root = tmp_path_factory.mktemp("orca") / "orca"
    return types.SimpleNamespace(root=root, schemas=mk.write_tree(root))


@pytest.fixture
def orca_env(tree, tmp_path, monkeypatch):
    """A fresh copy of the tree served over HTTP; orca.BASE and CAFE_SCHEMAS point at it and at the small-grid schemas."""
    www = tmp_path / "www"
    shutil.copytree(tree.root, www)
    s = Server(www)
    monkeypatch.setattr(orca, "BASE", s.base)
    monkeypatch.setenv("CAFE_SCHEMAS", str(tree.schemas))
    yield s
    s.close()


@pytest.fixture(scope="session")
def selfsigned(tmp_path_factory):
    """(cert, key) of a self-signed certificate for 127.0.0.1, made with the openssl CLI."""
    d = tmp_path_factory.mktemp("tls")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-subj", "/CN=localhost",
                    "-addext", "subjectAltName=IP:127.0.0.1", "-keyout", str(d / "k.pem"), "-out", str(d / "c.pem")],
                   check=True, capture_output=True)
    return d / "c.pem", d / "k.pem"


@pytest.fixture(scope="session")
def ci_env(tmp_path_factory):
    """The synthetic CAFE_DATA tree of tests/fixtures/ci_env (analytic fields over the missions/ci_fixture.yaml box and window)."""
    from tests.fixtures.ci_env import make
    return make.make(tmp_path_factory.mktemp("ci_env"))


@pytest.fixture(scope="session")
def ci_full(ci_env):
    """GriddedEnv over the ci_env tree with the ocean (GEBCO-format bathymetry cache) and the derived surface layer."""
    from cafe.pm.config import env_sigmas
    from cafe.pm.env import bathy, ocean, surface
    from cafe.pm.env.environment import GriddedEnv
    box = (-2.0, 2.0, -167.0, -163.0)                                  # (south, north, west, east): the mission box plus its 0.5 degree pad
    oc = ocean.Ocean(ci_env.ocean_store, bathy.choose(box, ci_env.data / "bathy", gofs=ci_env.ocean_store, fetch=False))
    return GriddedEnv(ci_env.cache, env_sigmas(), ocean=oc, subgrid=surface.SurfaceLayer(ci_env.cache))
