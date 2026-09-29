"""
Simulation Network & Route Generator.

Autonomously constructs a 4×4 multi-intersection grid network and
heterogeneous traffic routes when no pre-existing .net.xml file is
available.  Generates pure XML -- no dependency on SUMO's netgenerate
binary, ensuring the simulation can bootstrap on any machine with only
the ``sumolib`` pip package.

Grid Specification:
    - 4×4 intersection grid  ->  16 nodes, ~48 directional edges
    - Edge speed: 13.89 m/s (50 km/h) for arterials
    - 2 lanes per direction
    - Traffic light control at every intersection
    - Heterogeneous demand: passenger cars, buses, delivery trucks
"""

from __future__ import annotations

import os
import math
import random
import xml.etree.ElementTree as ET
from typing import List, Tuple

# ------------------------ grid parameters ------------------------------

GRID_ROWS = 4
GRID_COLS = 4
EDGE_LENGTH = 200.0       # metres between intersections
LANE_COUNT = 2
SPEED_LIMIT = 13.89        # m/s ~= 50 km/h
AMBULANCE_SPEED = 22.22    # m/s ~= 80 km/h


def _node_id(r: int, c: int) -> str:
    return f"J{r}_{c}"


def _edge_id(from_r: int, from_c: int, to_r: int, to_c: int) -> str:
    return f"E_{from_r}_{from_c}_to_{to_r}_{to_c}"


# ------------------------ network generator ----------------------------

def generate_network_xml(output_path: str) -> str:
    """
    Write a 4×4 grid network to *output_path* and return the filepath.
    """
    root = ET.Element("net", attrib={
        "version": "1.20",
        "junctionCornerDetail": "5",
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xsi:noNamespaceSchemaLocation": "http://sumo.dlr.de/xsd/net_file.xsd",
    })

    # --- location element ---
    ET.SubElement(root, "location", attrib={
        "netOffset": "0.00,0.00",
        "convBoundary": f"0.00,0.00,{(GRID_COLS-1)*EDGE_LENGTH:.2f},{(GRID_ROWS-1)*EDGE_LENGTH:.2f}",
        "origBoundary": "-10000000000.00,-10000000000.00,10000000000.00,10000000000.00",
        "projParameter": "!",
    })

    nodes = []
    edges_info = []

    # --- nodes (junctions) ---
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
            nid = _node_id(r, c)
            x = c * EDGE_LENGTH
            y = r * EDGE_LENGTH
            nodes.append((nid, x, y))

            jtype = "traffic_light"
            junction = ET.SubElement(root, "junction", attrib={
                "id": nid,
                "type": jtype,
                "x": f"{x:.2f}",
                "y": f"{y:.2f}",
                "incLanes": "",
                "intLanes": "",
                "shape": "",
            })

    # --- edges ---
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
            # right
            if c + 1 < GRID_COLS:
                _add_edge(root, edges_info, r, c, r, c + 1)
                _add_edge(root, edges_info, r, c + 1, r, c)  # reverse
            # up
            if r + 1 < GRID_ROWS:
                _add_edge(root, edges_info, r, c, r + 1, c)
                _add_edge(root, edges_info, r + 1, c, r, c)  # reverse

    # --- connections (all-to-all at each junction) ---
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
            nid = _node_id(r, c)
            incoming = [e for e in edges_info if e[2] == nid]
            outgoing = [e for e in edges_info if e[1] == nid]
            for inc_eid, _, _ in incoming:
                for out_eid, _, _ in outgoing:
                    if inc_eid == out_eid:
                        continue
                    for lane in range(LANE_COUNT):
                        ET.SubElement(root, "connection", attrib={
                            "from": inc_eid,
                            "to": out_eid,
                            "fromLane": str(lane),
                            "toLane": str(lane),
                            "dir": "s",
                            "state": "o",
                        })

    # --- traffic light programs ---
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
            nid = _node_id(r, c)
            n_inc = sum(1 for e in edges_info if e[2] == nid)
            n_links = n_inc * LANE_COUNT * 3  # approximate
            green_state = "G" * max(n_links, 4)
            red_state = "r" * max(n_links, 4)
            yellow_state = "y" * max(n_links, 4)

            tl = ET.SubElement(root, "tlLogic", attrib={
                "id": nid,
                "type": "static",
                "programID": "0",
                "offset": "0",
            })
            ET.SubElement(tl, "phase", attrib={"duration": "30", "state": green_state})
            ET.SubElement(tl, "phase", attrib={"duration": "3", "state": yellow_state})
            ET.SubElement(tl, "phase", attrib={"duration": "30", "state": red_state})
            ET.SubElement(tl, "phase", attrib={"duration": "3", "state": yellow_state})

    # Update junction incLanes
    for junc in root.findall("junction"):
        jid = junc.get("id")
        inc_lanes = []
        for e in edges_info:
            if e[2] == jid:
                for l in range(LANE_COUNT):
                    inc_lanes.append(f"{e[0]}_{l}")
        junc.set("incLanes", " ".join(inc_lanes))

    _indent_xml(root)
    tree = ET.ElementTree(root)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    tree.write(output_path, encoding="unicode", xml_declaration=True)
    return output_path


def _add_edge(root: ET.Element, edges_info: list,
              fr: int, fc: int, tr: int, tc: int):
    eid = _edge_id(fr, fc, tr, tc)
    from_n = _node_id(fr, fc)
    to_n = _node_id(tr, tc)
    edges_info.append((eid, from_n, to_n))

    x1, y1 = fc * EDGE_LENGTH, fr * EDGE_LENGTH
    x2, y2 = tc * EDGE_LENGTH, tr * EDGE_LENGTH
    length = math.hypot(x2 - x1, y2 - y1)

    edge_el = ET.SubElement(root, "edge", attrib={
        "id": eid,
        "from": from_n,
        "to": to_n,
        "priority": "2",
        "numLanes": str(LANE_COUNT),
        "speed": f"{SPEED_LIMIT:.2f}",
    })
    for l in range(LANE_COUNT):
        ET.SubElement(edge_el, "lane", attrib={
            "id": f"{eid}_{l}",
            "index": str(l),
            "speed": f"{SPEED_LIMIT:.2f}",
            "length": f"{length:.2f}",
            "shape": f"{x1:.2f},{y1:.2f} {x2:.2f},{y2:.2f}",
        })


# ------------------------ route generator ------------------------------

def generate_routes_xml(
    output_path: str,
    net_edges: list | None = None,
    n_passenger: int = 60,
    n_bus: int = 8,
    n_truck: int = 12,
    n_ambulance: int = 2,
    seed: int = 42,
) -> str:
    """
    Generate heterogeneous traffic routes.  Ambulances always traverse
    a long corridor to stress-test the green corridor system.
    """
    rng = random.Random(seed)

    root = ET.Element("routes", attrib={
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xsi:noNamespaceSchemaLocation": "http://sumo.dlr.de/xsd/routes_file.xsd",
    })

    # Vehicle types
    ET.SubElement(root, "vType", attrib={
        "id": "passenger", "vClass": "passenger",
        "length": "5.0", "maxSpeed": f"{SPEED_LIMIT:.2f}",
        "accel": "2.6", "decel": "4.5", "sigma": "0.5",
        "color": "0.8,0.8,0.8",
    })
    ET.SubElement(root, "vType", attrib={
        "id": "bus", "vClass": "bus",
        "length": "12.0", "maxSpeed": "11.11",
        "accel": "1.2", "decel": "3.0", "sigma": "0.5",
        "color": "0.2,0.4,0.8",
    })
    ET.SubElement(root, "vType", attrib={
        "id": "truck", "vClass": "truck",
        "length": "10.0", "maxSpeed": "11.11",
        "accel": "1.0", "decel": "3.5", "sigma": "0.5",
        "color": "0.6,0.4,0.2",
    })
    ET.SubElement(root, "vType", attrib={
        "id": "emergency", "vClass": "emergency",
        "length": "6.5", "maxSpeed": f"{AMBULANCE_SPEED:.2f}",
        "accel": "3.5", "decel": "5.0", "sigma": "0.2",
        "color": "1.0,0.0,0.0",
        "guiShape": "emergency",
    })

    # Build all valid edge IDs
    all_edges = _get_all_edges()

    # Horizontal corridors for ambulances
    amb_corridor_1 = _corridor_horizontal(0, 0, 0, GRID_COLS - 1)  # bottom row L->R
    amb_corridor_2 = _corridor_horizontal(GRID_ROWS - 1, GRID_COLS - 1,
                                          GRID_ROWS - 1, 0)  # top row R->L

    vid_counter = 0

    # --- ambulances (depart early, long corridors) ---
    for i in range(n_ambulance):
        corridor = amb_corridor_1 if i % 2 == 0 else amb_corridor_2
        route_id = f"route_amb_{i}"
        ET.SubElement(root, "route", attrib={
            "id": route_id,
            "edges": " ".join(corridor),
        })
        ET.SubElement(root, "vehicle", attrib={
            "id": f"amb_{i}",
            "type": "emergency",
            "route": route_id,
            "depart": f"{10 + i * 5:.1f}",
            "departSpeed": "max",
        })

    # --- background traffic ---
    for vtype, count, prefix in [
        ("passenger", n_passenger, "car"),
        ("bus", n_bus, "bus"),
        ("truck", n_truck, "trk"),
    ]:
        for i in range(count):
            route_edges = _random_route(all_edges, rng, min_len=3, max_len=8)
            if not route_edges:
                continue
            rid = f"route_{prefix}_{i}"
            ET.SubElement(root, "route", attrib={
                "id": rid,
                "edges": " ".join(route_edges),
            })
            depart = rng.uniform(0, 120)
            ET.SubElement(root, "vehicle", attrib={
                "id": f"{prefix}_{i}",
                "type": vtype,
                "route": rid,
                "depart": f"{depart:.1f}",
            })

    _indent_xml(root)
    tree = ET.ElementTree(root)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    tree.write(output_path, encoding="unicode", xml_declaration=True)
    return output_path


# ------------------------ route helpers ---------------------------------

def _get_all_edges() -> List[str]:
    """Return all non-junction edge IDs in the 4×4 grid."""
    edges = []
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
            if c + 1 < GRID_COLS:
                edges.append(_edge_id(r, c, r, c + 1))
                edges.append(_edge_id(r, c + 1, r, c))
            if r + 1 < GRID_ROWS:
                edges.append(_edge_id(r, c, r + 1, c))
                edges.append(_edge_id(r + 1, c, r, c))
    return edges


def _corridor_horizontal(start_r: int, start_c: int,
                          end_r: int, end_c: int) -> List[str]:
    """Build a contiguous horizontal corridor edge list."""
    edges = []
    c = start_c
    step = 1 if end_c > start_c else -1
    while c != end_c:
        nc = c + step
        edges.append(_edge_id(start_r, c, end_r, nc))
        c = nc
    return edges


def _random_route(all_edges: List[str], rng: random.Random,
                  min_len: int = 3, max_len: int = 8) -> List[str]:
    """
    Generate a random connected route by walking the grid adjacency.
    Falls back to a random subset if adjacency walk fails.
    """
    # Parse edge -> (from_row, from_col, to_row, to_col)
    def parse_edge(eid):
        parts = eid.replace("E_", "").split("_to_")
        fr, fc = parts[0].split("_")
        tr, tc = parts[1].split("_")
        return int(fr), int(fc), int(tr), int(tc)

    adjacency = {}
    for eid in all_edges:
        fr, fc, tr, tc = parse_edge(eid)
        adjacency.setdefault((fr, fc), []).append((eid, tr, tc))

    # Pick random start node
    start_node = rng.choice(list(adjacency.keys()))
    route = []
    visited = set()
    cur = start_node
    route_len = rng.randint(min_len, max_len)

    for _ in range(route_len):
        if cur not in adjacency:
            break
        options = [(eid, tr, tc) for eid, tr, tc in adjacency[cur]
                   if (tr, tc) not in visited]
        if not options:
            options = adjacency[cur]
        if not options:
            break
        eid, tr, tc = rng.choice(options)
        route.append(eid)
        visited.add(cur)
        cur = (tr, tc)

    return route if len(route) >= min_len else []


# ------------------------ SUMO config generator ------------------------

def generate_sumo_config(
    config_path: str,
    net_file: str,
    route_file: str,
    begin: float = 0,
    end: float = 300,
) -> str:
    """Write a .sumocfg configuration file."""
    root = ET.Element("configuration")
    inp = ET.SubElement(root, "input")
    ET.SubElement(inp, "net-file", attrib={"value": net_file})
    ET.SubElement(inp, "route-files", attrib={"value": route_file})

    time_el = ET.SubElement(root, "time")
    ET.SubElement(time_el, "begin", attrib={"value": str(begin)})
    ET.SubElement(time_el, "end", attrib={"value": str(end)})

    _indent_xml(root)
    tree = ET.ElementTree(root)
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    tree.write(config_path, encoding="unicode", xml_declaration=True)
    return config_path


# ------------------------ XML indentation ------------------------------

def _indent_xml(elem, level=0):
    """Add pretty-print indentation to an ElementTree."""
    indent = "\n" + "  " * level
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = indent + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = indent
        for child in elem:
            _indent_xml(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = indent
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = indent


# ------------------------ main entry point -----------------------------

def bootstrap_simulation_assets(base_dir: str) -> dict:
    """
    Generate all simulation assets if they don't already exist.
    Returns a dict of file paths.
    """
    net_path = os.path.join(base_dir, "network", "grid.net.xml")
    route_path = os.path.join(base_dir, "network", "routes.rou.xml")
    config_path = os.path.join(base_dir, "config", "simulation.sumocfg")

    if not os.path.exists(net_path):
        generate_network_xml(net_path)
        print(f"[GEN] Network written -> {net_path}")

    if not os.path.exists(route_path):
        generate_routes_xml(route_path)
        print(f"[GEN] Routes written  -> {route_path}")

    # Config uses relative paths from its own directory
    net_rel = os.path.relpath(net_path, os.path.dirname(config_path))
    route_rel = os.path.relpath(route_path, os.path.dirname(config_path))
    if not os.path.exists(config_path):
        generate_sumo_config(config_path, net_rel, route_rel)
        print(f"[GEN] Config written  -> {config_path}")

    return {
        "net": net_path,
        "routes": route_path,
        "config": config_path,
    }


if __name__ == "__main__":
    import sys
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    paths = bootstrap_simulation_assets(base)
    for k, v in paths.items():
        print(f"  {k}: {v}")
