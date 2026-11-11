"""Where can a drone get to, and how fast? Time-to-reach over a grid around a launch point.

Each grid step's speed made good comes from Zermelo's crab-angle relation: to track along unit
direction d through a fluid moving at c with through-fluid speed V, the drone makes good
    s = c.d + sqrt(V^2 - |c x d|^2)      (impossible if the cross-current exceeds V, or s <= 0)
Fastest routes come from Dijkstra over a 16-neighbour grid (the edge costs built for the whole grid at once, scipy's csgraph
solves it); a round trip runs a second Dijkstra for the way back (against the current one way means with it the other) and needs
out + back within the budget. Both are run without a time limit, so that a cell that is merely too far is told from one that no route
reaches. Cells outside the loaded weather box are blocked, never read from the box's edge value.
A glider sees the current averaged over its dive band, not the surface current. The fluid field is held at the launch hour
(ponytail: steady field; time-dependent routing would use the hourly fields along the way). Endurance
caps the radius: reachable means "arrives with the battery reserve still left".
"""
import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

from cafe import ctrl
from cafe.env import lon360
from cafe.mission import Frame

STEPS = [(1, 0), (0, 1), (-1, 0), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1),
         (2, 1), (1, 2), (-1, 2), (-2, 1), (-2, -1), (-1, -2), (1, -2), (2, -1)]


def made_good(V, c, d):
    """Speed made good along unit direction d (N,E) for through-fluid speed V in fluid velocity c (N,E); c may be an array of velocities (..., 2)."""
    c = np.asarray(c, float)
    along = c[..., 0] * d[0] + c[..., 1] * d[1]
    cross = c[..., 0] * d[1] - c[..., 1] * d[0]
    gap = V * V - cross * cross
    s = along + np.sqrt(np.maximum(gap, 0.0))
    s = np.where((gap < 0) | (s <= 1e-6), 0.0, s)
    return s if s.ndim else float(s)


def endurance_h(veh, V, reserve=0.15):
    P, _ = ctrl._level_power(veh, V) if ctrl.family(veh) != "glider" else (veh.hotel_w + 1.0, True)
    return veh.battery_wh * (1 - reserve) / max(P, 1e-6)


def _crosses_land(land, i, j, di, dj):
    """A step may not pass over land between its end cells: a knight step (1, 2) passes between (i, j+1) and
    (i+1, j+1) and is blocked if either is land; a diagonal is blocked only when both corner cells are (a corner cut
    through a solid wall). i and j may be index arrays (one answer per step)."""
    si, sj = (di > 0) - (di < 0), (dj > 0) - (dj < 0)
    if abs(dj) == 2:
        return land[i, j + sj] | land[i + di, j + sj]
    if abs(di) == 2:
        return land[i + si, j] | land[i + si, j + dj]
    if di and dj:
        return land[i + di, j] & land[i, j + dj]
    return np.zeros(np.broadcast(i, j).shape, bool)


def _dijkstra(flow, land, V, h, T_s=np.inf, back=False):
    """Fastest time from the centre cell to every cell (or, back=True, from every cell to the centre); inf where no route exists or it takes longer than
    T_s. Every edge's cost is built at once (a step is dropped when it ends on land, crosses land, or the flow beats V), then csgraph solves it."""
    n = len(land)
    src, dst, cost = [], [], []
    for di, dj in STEPS:
        i = np.arange(max(0, -di), n - max(0, di))[:, None]
        j = np.arange(max(0, -dj), n - max(0, dj))[None, :]
        a, b = i + di, j + dj
        dvec = np.array([di, dj], float)
        dist = h * np.linalg.norm(dvec)
        dvec /= np.linalg.norm(dvec)
        # going back, the drone travels the edge (a,b) -> (i,j): the opposite direction
        sp = made_good(V, 0.5 * (flow[i, j] + flow[a, b]), -dvec if back else dvec)
        ok = (sp > 0) & ~land[a, b] & ~_crosses_land(land, i, j, di, dj)
        src.append((i * n + j)[ok])
        dst.append((a * n + b)[ok])
        cost.append(dist / sp[ok])
    graph = csr_matrix((np.concatenate(cost), (np.concatenate(src), np.concatenate(dst))), shape=(n * n, n * n))
    return dijkstra(graph, directed=True, indices=(n // 2) * n + n // 2, limit=T_s).reshape(n, n)


def _inside(E, lat, lon):
    """Which points lie inside the weather box E holds: Env.at clips to the nearest edge, so outside it a value is the edge's, not the weather there. An
    environment that does not say where its box is (a stub) is taken to cover everything."""
    la, lo = getattr(E, "lat", None), getattr(E, "lon", None)
    if la is None or lo is None:
        return np.ones(np.shape(lat), bool)
    lo360 = lon360(lon)
    return (lat >= np.min(la)) & (lat <= np.max(la)) & (lo360 >= np.min(lo)) & (lo360 <= np.max(lo))


def reach(veh, E, lat0, lon0, hours=24.0, z_up=0.0, n=81, reserve=0.15, round_trip=False, adverse=0.0):
    """-> dict(lat, lon, hours grid (nan = can't get there), why grid, hold grid, speeds).
    adverse: a current/wind of this speed assumed against the drone in every direction (the pessimistic map
    when the data has no currents). ValueError when there is no budget to spend (hours or endurance not above 0, a reserve outside [0, 1)) or the
    launch point is on land or outside the loaded weather box. A cell outside that box is blocked (why = "outside weather data")."""
    if not 0 <= reserve < 1:
        raise ValueError(f"the battery reserve must be in [0, 1), not {reserve:g}")
    V0 = float(ctrl.cruise_speed(veh))
    V = max(V0 - adverse, 0.0)
    kind = veh.kind
    endur = endurance_h(veh, V0, reserve)
    T = min(hours, endur)                                     # the whole budget: one way, or out AND back
    if not T > 0:
        raise ValueError(f"no time or energy budget: nothing is reachable (hours {hours:g}, endurance {endur:.3g} h)")
    fluid_max = 2.5 if kind != "uav" else 30.0
    R = min((V + fluid_max) * T * 3600, 400e3)               # search radius, metres
    fr = Frame(lat0, lon0)
    xs = np.linspace(-R, R, n)
    NN, EE = np.meshgrid(xs, xs, indexing="ij")
    lat, lon = fr.to_ll(NN.ravel(), EE.ravel())
    s = E.at(lat, lon, np.zeros(lat.size), np.full(lat.size, z_up))
    flow = (s["wind_ne"] if kind == "uav" else s["current_ne"]).reshape(n, n, 2)
    if ctrl.family(veh) == "glider":
        top, bottom = (getattr(veh, "limits", None) or {}).get("glide_band", (5.0, 100.0))
        flow = np.mean([E.at(lat, lon, np.zeros(lat.size), np.full(lat.size, -zz))["current_ne"].reshape(n, n, 2)
                        for zz in np.linspace(top, bottom, 6)], axis=0)
    inside = _inside(E, lat, lon).reshape(n, n)
    land = (s["land"].reshape(n, n) if kind != "uav" else np.zeros((n, n), bool)) & inside
    h = xs[1] - xs[0]
    c0 = n // 2
    if not inside[c0, c0]:
        raise ValueError("launch point is outside the loaded weather data")
    if land[c0, c0]:
        raise ValueError("launch point is on land")
    T_s = T * 3600
    blocked = land | ~inside
    t = _dijkstra(flow, blocked, V, h)                              # no time limit: inf then means no route at all
    tb = _dijkstra(flow, blocked, V, h, back=True) if round_trip else np.zeros_like(t)
    total = t + tb
    hours_grid = np.where(total <= T_s, t / 3600, np.nan)           # time to GET there; feasibility on the total
    why = np.select([~inside, land, np.isinf(t), t > T_s, np.isinf(tb), total > T_s],
                    ["outside weather data", "land", "currents/winds too strong or blocked", "beyond endurance or time",
                     "no way back: currents/winds too strong to return against", "beyond endurance or time"], "")
    speed = np.where(inside, np.linalg.norm(flow, axis=2), np.nan)
    hold = speed < 0.8 * V                                        # can it hold station against the local flow? (False outside the data)
    return dict(lat=lat.reshape(n, n)[:, 0].tolist(), lon=lon.reshape(n, n)[0, :].tolist(), radius_km=R / 1e3, round_trip=round_trip,
                hours=np.round(hours_grid, 2).tolist(), why=why.tolist(), hold=hold.tolist(),
                speed_through_fluid=V, endurance_h=endur, horizon_h=T, outside_cells=int((~inside).sum()),
                weather_box=None if inside.all() else [float(np.min(E.lat)), float(np.max(E.lat)), float(np.min(E.lon)), float(np.max(E.lon))],
                flow_max=float(np.nanmax(speed)), flow_kind="wind" if kind == "uav" else "current")


if __name__ == "__main__":
    # Zermelo checks (analytic): still water -> s = V; head-on current c<V -> V-c; cross current c -> sqrt(V^2-c^2)
    assert abs(made_good(1.0, np.array([0.0, 0.0]), np.array([1.0, 0.0])) - 1.0) < 1e-12
    assert abs(made_good(1.0, np.array([-0.4, 0.0]), np.array([1.0, 0.0])) - 0.6) < 1e-12
    assert abs(made_good(1.0, np.array([0.0, 0.6]), np.array([1.0, 0.0])) - 0.8) < 1e-12
    assert made_good(0.3, np.array([-0.5, 0.0]), np.array([1.0, 0.0])) == 0.0      # can't stem a stronger current
    assert made_good(0.3, np.array([0.0, 0.5]), np.array([1.0, 0.0])) == 0.0       # cross current too strong to crab
    print("reach ok")
