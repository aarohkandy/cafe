"""Where can a drone get to, and how fast? Time-to-reach over a grid around a launch point.

Each grid step's speed made good comes from Zermelo's crab-angle relation: to track along unit
direction d through a fluid moving at c with through-fluid speed V, the drone makes good
    s = c.d + sqrt(V^2 - |c x d|^2)      (impossible if the cross-current exceeds V, or s <= 0)
Fastest routes come from Dijkstra over a 16-neighbour grid; a round trip runs a second Dijkstra for the
way back (against the current one way means with it the other) and needs out + back within the budget.
A glider sees the current averaged over its dive band, not the surface current. The fluid field is held at the launch hour
(ponytail: steady field; time-dependent routing would use the hourly fields along the way). Endurance
caps the radius: reachable means "arrives with the battery reserve still left".
"""
import heapq
import numpy as np

from cafe import ctrl
from cafe.mission import Frame

STEPS = [(1, 0), (0, 1), (-1, 0), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1),
         (2, 1), (1, 2), (-1, 2), (-2, 1), (-2, -1), (-1, -2), (1, -2), (2, -1)]


def made_good(V, c, d):
    """Speed made good along unit direction d (N,E) for through-fluid speed V in fluid velocity c (N,E)."""
    along = c @ d
    cross = c[0] * d[1] - c[1] * d[0]
    if V * V < cross * cross:
        return 0.0
    s = along + np.sqrt(V * V - cross * cross)
    return s if s > 1e-6 else 0.0


def endurance_h(veh, V, reserve=0.15):
    P, _ = ctrl._level_power(veh, V) if ctrl.family(veh) != "glider" else (veh.hotel_w + 1.0, True)
    return veh.battery_wh * (1 - reserve) / max(P, 1e-6)


def _dijkstra(flow, land, V, h, T_s, back=False):
    """Fastest time from the centre cell to every cell (or, back=True, from every cell to the centre)."""
    n = len(land)
    t = np.full((n, n), np.inf)
    c0 = n // 2
    t[c0, c0] = 0.0
    q = [(0.0, c0, c0)]
    while q:
        tt, i, j = heapq.heappop(q)
        if tt > t[i, j] or tt > T_s:
            continue
        for di, dj in STEPS:
            a, b = i + di, j + dj
            if not (0 <= a < n and 0 <= b < n) or land[a, b]:
                continue
            dvec = np.array([di, dj], float)
            dist = h * np.linalg.norm(dvec)
            dvec /= np.linalg.norm(dvec)
            # going back, the drone travels the edge (a,b) -> (i,j): the opposite direction
            sp = made_good(V, 0.5 * (flow[i, j] + flow[a, b]), -dvec if back else dvec)
            if sp <= 0:
                continue
            nt = tt + dist / sp
            if nt < t[a, b]:
                t[a, b] = nt
                heapq.heappush(q, (nt, a, b))
    return t


def reach(veh, E, lat0, lon0, hours=24.0, z_up=0.0, n=81, reserve=0.15, round_trip=False, adverse=0.0):
    """-> dict(lat, lon, hours grid (nan = can't get there), why grid, hold grid, speeds).
    adverse: a current/wind of this speed assumed against the drone in every direction (the pessimistic map
    when the data has no currents)."""
    V0 = float(ctrl.cruise_speed(veh))
    V = max(V0 - adverse, 0.0)
    kind = veh.kind
    endur = endurance_h(veh, V0, reserve)
    T = min(hours, endur)                                     # the whole budget: one way, or out AND back
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
    land = s["land"].reshape(n, n) if kind != "uav" else np.zeros((n, n), bool)
    h = xs[1] - xs[0]
    c0 = n // 2
    if land[c0, c0]:
        raise ValueError("launch point is on land")
    t = _dijkstra(flow, land, V, h, T * 3600)
    total = t + _dijkstra(flow, land, V, h, T * 3600, back=True) if round_trip else t
    hours_grid = np.where(total <= T * 3600, t / 3600, np.nan)       # time to GET there; feasibility on the total
    why = np.where(land, "land", np.where(np.isnan(hours_grid), np.where(np.isinf(t), "currents/winds too strong or blocked",
                                                                          "beyond endurance or time"), ""))
    hold = np.linalg.norm(flow, axis=2) < 0.8 * V                 # can it hold station against the local flow?
    return dict(lat=lat.reshape(n, n)[:, 0].tolist(), lon=lon.reshape(n, n)[0, :].tolist(), radius_km=R / 1e3, round_trip=round_trip,
                hours=np.round(hours_grid, 2).tolist(), why=why.tolist(), hold=hold.tolist(),
                speed_through_fluid=V, endurance_h=endur, horizon_h=T,
                flow_max=float(np.nanmax(np.linalg.norm(flow, axis=2))), flow_kind="wind" if kind == "uav" else "current")


if __name__ == "__main__":
    # Zermelo checks (analytic): still water -> s = V; head-on current c<V -> V-c; cross current c -> sqrt(V^2-c^2)
    assert abs(made_good(1.0, np.array([0.0, 0.0]), np.array([1.0, 0.0])) - 1.0) < 1e-12
    assert abs(made_good(1.0, np.array([-0.4, 0.0]), np.array([1.0, 0.0])) - 0.6) < 1e-12
    assert abs(made_good(1.0, np.array([0.0, 0.6]), np.array([1.0, 0.0])) - 0.8) < 1e-12
    assert made_good(0.3, np.array([-0.5, 0.0]), np.array([1.0, 0.0])) == 0.0      # can't stem a stronger current
    assert made_good(0.3, np.array([0.0, 0.5]), np.array([1.0, 0.0])) == 0.0       # cross current too strong to crab
    print("reach ok")
