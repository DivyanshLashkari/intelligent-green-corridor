"""
Novelty 2 -- Dynamic Congestion-Aware A* Routing Algorithm.

Baseline Problem:
    Traditional Dijkstra / static shortest-path routers use fixed edge
    lengths L_i and dispatch ambulances directly into live traffic jams or
    incident-blocked corridors.

Solution:
    Replace static cost with real-time travel time queried from TraCI:
        g(n) = - traci.edge.getTraveltime(edge_id)

    Heuristic (admissible Euclidean time lower-bound):
        h(n) = euclidean(n, dest) / v_network_max
    where v_network_max = 25.0 m/s.

    Internal junction edges (IDs starting with ':') are transparently
    skipped to avoid phantom nodes.

The module also exposes a *static_shortest_path* function that uses only
physical edge length as cost -- this serves as the baseline comparator.
"""

from __future__ import annotations

import heapq
import math
from typing import Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# We import sumolib for network topology parsing.  TraCI is imported lazily
# inside the cost function so the module can be unit-tested without a live
# SUMO server.
# ---------------------------------------------------------------------------
try:
    import sumolib
except ImportError:
    sumolib = None

# ------------------------ constants ------------------------------------

V_NETWORK_MAX: float = 25.0   # m/s -- maximum free-flow speed in network


# ------------------------ helper geometry ------------------------------

def _edge_coord(edge) -> Tuple[float, float]:
    """Return the centroid (x, y) of an edge's shape polyline."""
    shape = edge.getShape()
    xs = [p[0] for p in shape]
    ys = [p[1] for p in shape]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _euclidean(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


# ------------------------ dynamic A* -----------------------------------

def dynamic_a_star(
    net,
    start_edge_id: str,
    target_edge_id: str,
    travel_time_fn=None,
    blocked_edges: Optional[Set[str]] = None,
) -> List[str]:
    """
    Compute the fastest temporal path from *start_edge_id* to
    *target_edge_id* over the SUMO network *net*.

    Parameters
    ----------
    net : sumolib.net.Net
        Parsed SUMO network object.
    start_edge_id : str
        Origin edge ID.
    target_edge_id : str
        Destination edge ID.
    travel_time_fn : callable, optional
        ``travel_time_fn(edge_id) -> float`` returning real-time travel
        time.  When running with TraCI pass
        ``lambda eid: traci.edge.getTraveltime(eid)``.
        If *None*, falls back to ``edge.getLength() / edge.getSpeed()``.
    blocked_edges : set[str], optional
        Edges to treat as impassable (infinite cost).

    Returns
    -------
    list[str]
        Ordered edge IDs of the fastest path, or empty list if no path.
    """
    blocked = blocked_edges or set()

    start_edge = net.getEdge(start_edge_id)
    target_edge = net.getEdge(target_edge_id)
    target_coord = _edge_coord(target_edge)

    # Priority queue entries: (f_score, counter, edge_id)
    counter = 0
    open_set: list = []
    heapq.heappush(open_set, (0.0, counter, start_edge_id))

    g_score: Dict[str, float] = {start_edge_id: 0.0}
    came_from: Dict[str, str] = {}
    closed: Set[str] = set()

    while open_set:
        f, _, current_id = heapq.heappop(open_set)

        if current_id in closed:
            continue
        closed.add(current_id)

        if current_id == target_edge_id:
            # Reconstruct path
            path = [current_id]
            while current_id in came_from:
                current_id = came_from[current_id]
                path.append(current_id)
            path.reverse()
            return path

        current_edge = net.getEdge(current_id)
        to_node = current_edge.getToNode()

        for next_edge in to_node.getOutgoing():
            nid = next_edge.getID()

            # Skip internal junction edges
            if nid.startswith(":"):
                continue
            if nid in closed or nid in blocked:
                continue

            # --- dynamic cost g(n) ---
            if travel_time_fn is not None:
                try:
                    edge_cost = travel_time_fn(nid)
                except Exception:
                    edge_cost = next_edge.getLength() / max(next_edge.getSpeed(), 1.0)
            else:
                edge_cost = next_edge.getLength() / max(next_edge.getSpeed(), 1.0)

            tentative_g = g_score[current_id] + edge_cost

            if tentative_g < g_score.get(nid, float("inf")):
                g_score[nid] = tentative_g
                came_from[nid] = current_id

                # --- admissible heuristic h(n) ---
                nc = _edge_coord(next_edge)
                h = _euclidean(nc, target_coord) / V_NETWORK_MAX

                counter += 1
                heapq.heappush(open_set, (tentative_g + h, counter, nid))

    return []   # no path found


# ------------------------ static baseline (Dijkstra-like) --------------

def static_shortest_path(
    net,
    start_edge_id: str,
    target_edge_id: str,
    blocked_edges: Optional[Set[str]] = None,
) -> List[str]:
    """
    Baseline comparator: A* with cost = physical edge length only.
    Unaware of live congestion or incidents.
    """
    blocked = blocked_edges or set()
    start_edge = net.getEdge(start_edge_id)
    target_edge = net.getEdge(target_edge_id)
    target_coord = _edge_coord(target_edge)

    counter = 0
    open_set: list = []
    heapq.heappush(open_set, (0.0, counter, start_edge_id))
    g_score: Dict[str, float] = {start_edge_id: 0.0}
    came_from: Dict[str, str] = {}
    closed: Set[str] = set()

    while open_set:
        f, _, current_id = heapq.heappop(open_set)
        if current_id in closed:
            continue
        closed.add(current_id)

        if current_id == target_edge_id:
            path = [current_id]
            while current_id in came_from:
                current_id = came_from[current_id]
                path.append(current_id)
            path.reverse()
            return path

        current_edge = net.getEdge(current_id)
        to_node = current_edge.getToNode()

        for next_edge in to_node.getOutgoing():
            nid = next_edge.getID()
            if nid.startswith(":") or nid in closed or nid in blocked:
                continue
            edge_cost = next_edge.getLength()
            tentative_g = g_score[current_id] + edge_cost

            if tentative_g < g_score.get(nid, float("inf")):
                g_score[nid] = tentative_g
                came_from[nid] = current_id
                nc = _edge_coord(next_edge)
                h = _euclidean(nc, target_coord) / V_NETWORK_MAX
                counter += 1
                heapq.heappush(open_set, (tentative_g + h, counter, nid))

    return []


# ------------------------ CLI self-test --------------------------------

if __name__ == "__main__":
    print("routing_module: import OK -- run via benchmark_runner for full test.")
