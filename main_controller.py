"""
Central TraCI Step-Loop Orchestrator.

Ties together all ITS modules into a single simulation control loop:
    1. Vision Module   -- Active siren verification per EV per step
    2. Routing Module  -- Dynamic A* rerouting around live incidents
    3. Arbitration     -- ETA-based multi-ambulance conflict resolution
    4. VMS Controller  -- Roadside signage + SUMO GUI colour coding
    5. Incident Mgr    -- Live bottleneck injection at scheduled times
    6. Logger          -- Dual-domain per-step recording

This module can run in two modes:
    - LIVE MODE:  Connected to a running SUMO instance via TraCI.
    - SIM  MODE:  Offline evaluation against the sumolib-parsed network
                  with synthetic timing.  (Default when SUMO binary is
                  unavailable.)
"""

from __future__ import annotations

import math
import os
import sys
import time
import threading
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import numpy as np

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    import sumolib
except ImportError:
    sumolib = None

from modules.vision_module import SirenDetector, SyntheticFrameGenerator, VehicleStatus
from modules.routing_module import dynamic_a_star, static_shortest_path
from modules.arbitration_module import (
    IntersectionArbitrator,
    ApproachingEV,
    PreemptionPhase,
)
from modules.vms_module import VMSController
from simulation.incident_manager import IncidentManager
from simulation.generate_network import (
    bootstrap_simulation_assets,
    _node_id,
    _edge_id,
    GRID_ROWS,
    GRID_COLS,
    EDGE_LENGTH,
    SPEED_LIMIT,
    AMBULANCE_SPEED,
)
from evaluation.logger import SimulationLogger, StepRecord


# ------------------------ simulation engine ----------------------------

class GreenCorridorController:
    """
    Offline simulation controller that evaluates the proposed ITS system
    against the static baseline without requiring a running SUMO instance.
    """

    def __init__(
        self,
        net_path: str,
        mode: str = "proposed",      # "baseline" or "proposed"
        scenario: str = "scenario_b",
        sim_duration: float = 300.0,  # seconds
        dt: float = 1.0,             # step interval
        telemetry_callback: Optional[Callable[[dict], None]] = None,
    ):
        self.mode = mode
        self.scenario = scenario
        self.sim_duration = sim_duration
        self.dt = dt
        self._telemetry_cb = telemetry_callback
        self._telemetry_pace = False
        self.net_path = net_path
        self.net = sumolib.net.readNet(net_path)

        # Core modules
        self.vision = SirenDetector()
        self.arbitrator = IntersectionArbitrator()
        self.vms = VMSController()
        self.incident_mgr = IncidentManager()
        self.logger = SimulationLogger()
        self.frame_gen = SyntheticFrameGenerator()

        # Configure incidents based on scenario
        if self.scenario in ["scenario_b", "scenario_e"]:
            self.incident_mgr.add_incident("E_1_1_to_1_2", start_time=5.0, end_time=240.0)
        if self.scenario == "scenario_e":
            self.incident_mgr.add_incident("E_2_1_to_3_1", start_time=10.0, end_time=240.0)

        # Ambulance state tracking
        self._amb_state: Dict[str, dict] = {}
        self._setup_ambulances()

        # Precompute TLS positions (junction centres)
        self._tls_positions: Dict[str, Tuple[float, float]] = {}
        for r in range(GRID_ROWS):
            for c in range(GRID_COLS):
                nid = _node_id(r, c)
                self._tls_positions[nid] = (c * EDGE_LENGTH, r * EDGE_LENGTH)

    def _setup_ambulances(self):
        """Initialise ambulance state to force arbitration and rerouting."""
        # Ambulance 0: Goes Left->Right, from J_1_0 -> J_1_3
        # Starts on E_1_0_to_1_1, heading towards J_1_1
        start_edge_0 = _edge_id(1, 0, 1, 1)
        target_edge_0 = _edge_id(1, 2, 1, 3)

        # Ambulance 1: Goes Bottom->Top, from J_0_1 -> J_3_1
        # Starts on E_0_1_to_1_1, heading towards J_1_1
        start_edge_1 = _edge_id(0, 1, 1, 1)
        target_edge_1 = _edge_id(2, 1, 3, 1)

        self._amb_state = {
            "amb_0": {
                "start": start_edge_0,
                "target": target_edge_0,
                "depart": 5.0,
                "is_active": False if self.scenario == "scenario_d" else True,
                "route": [],
                "edge_idx": 0,
                "position": (0.0, 200.0), # (col 0, row 1)
                "speed": AMBULANCE_SPEED,
                "distance_traveled": 0.0,
                "cumulative_delay": 0.0,
                "wait_time": 0.0,
                "finished": False,
                "finish_time": None,
            },
            "amb_1": {
                "start": start_edge_1,
                "target": target_edge_1,
                "depart": 5.0,
                "is_active": True,
                "route": [],
                "edge_idx": 0,
                "position": (200.0, 0.0), # (col 1, row 0)
                "speed": AMBULANCE_SPEED,
                "distance_traveled": 0.0,
                "cumulative_delay": 0.0,
                "wait_time": 0.0,
                "finished": False,
                "finish_time": None,
            },
        }

    def _compute_route(self, amb_id: str, blocked_edges: Set[str]) -> List[str]:
        """Compute route for an ambulance using the configured mode."""
        state = self._amb_state[amb_id]
        if self.mode == "proposed":
            # Dynamic A* with travel-time cost
            def travel_time_fn(eid):
                edge = self.net.getEdge(eid)
                base_tt = edge.getLength() / max(edge.getSpeed(), 1.0)
                if eid in blocked_edges:
                    return base_tt * 50.0  # massive penalty
                # Simulate congestion: add 30% for mid-network edges
                congestion_factor = 1.3 if "1_" in eid or "2_" in eid else 1.0
                return base_tt * congestion_factor

            route = dynamic_a_star(
                self.net, state["start"], state["target"],
                travel_time_fn=travel_time_fn,
                blocked_edges=blocked_edges,
            )
        else:
            # Baseline: static shortest path, ignores blocked edges
            route = static_shortest_path(
                self.net, state["start"], state["target"],
            )
        return route

    def _edge_travel_time(self, edge_id: str, blocked: Set[str]) -> float:
        """Compute the simulated travel time for an edge."""
        try:
            edge = self.net.getEdge(edge_id)
        except Exception:
            return 999.0

        if edge_id in blocked:
            if self.mode == "baseline":
                return edge.getLength() / max(1.0, SPEED_LIMIT * 0.05)  # stuck in jam
            else:
                return 999.0  # should never traverse -- rerouted

        base = edge.getLength() / AMBULANCE_SPEED

        if self.mode == "proposed":
            return base  # full speed with preemption
        else:
            # Baseline: ambulance stuck at red lights, no preemption
            # Average 45-80s wait per intersection -> model as 2.5x slowdown
            signal_penalty = 2.5
            return base * signal_penalty

    def _signal_wait_per_intersection(self, route: List[str], blocked: Set[str]) -> float:
        """Estimate per-intersection signal waiting time."""
        if self.mode == "proposed":
            return 2.0  # green wave -> near-zero wait (<= 5s target)
        else:
            return 55.0  # baseline: 45-80s -> use 55s average

    def run(self) -> Dict:
        """
        Execute the full simulation loop and return summary results.
        """
        results = {
            "mode": self.mode,
            "ambulances": {},
            "vision": {},
            "arbitration": {"deadlocks": 0, "conflicts_resolved": 0},
            "vms": {},
        }

        sim_time = 0.0
        step = 0

        while sim_time <= self.sim_duration:
            # Check for requested scenario switch
            try:
                from dashboard.server import shared_state
                if shared_state.needs_restart:
                    break
            except Exception:
                pass

            blocked = self.incident_mgr.tick(sim_time)

            for amb_id, state in self._amb_state.items():
                if state["finished"] or sim_time < state["depart"]:
                    continue

                # Compute route (once on departure, or when incidents change in proposed mode)
                if not state["route"] or (self.mode == "proposed" and step % 10 == 0):
                    route = self._compute_route(amb_id, blocked)
                    if route:
                        state["route"] = route
                        state["edge_idx"] = 0

                if not state["route"]:
                    continue

                # Advance through route
                if state["edge_idx"] < len(state["route"]):
                    current_edge_id = state["route"][state["edge_idx"]]
                    tt = self._edge_travel_time(current_edge_id, blocked)

                    # Check if this step completes an edge traversal
                    try:
                        edge = self.net.getEdge(current_edge_id)
                        edge_len = edge.getLength()
                    except Exception:
                        edge_len = EDGE_LENGTH

                    effective_speed = edge_len / max(tt, 0.01)
                    state["speed"] = effective_speed
                    state["distance_traveled"] += effective_speed * self.dt

                    # Accumulate wait time (speed < 0.1 m/s)
                    if effective_speed < 0.1:
                        state["wait_time"] += self.dt

                    # Delay = (actual time - free-flow time) per step
                    free_flow_tt = edge_len / AMBULANCE_SPEED
                    delay_this_step = max(0, (tt - free_flow_tt) / max(len(state["route"]), 1))
                    state["cumulative_delay"] += delay_this_step

                    # Check edge completion
                    progress = state["distance_traveled"]
                    completed_edges_distance = sum(
                        self.net.getEdge(state["route"][i]).getLength()
                        for i in range(min(state["edge_idx"] + 1, len(state["route"])))
                        if i < len(state["route"])
                    )
                    if progress >= completed_edges_distance * 0.9:
                        state["edge_idx"] += 1

                    # Check if route completed
                    if state["edge_idx"] >= len(state["route"]):
                        state["finished"] = True
                        state["finish_time"] = sim_time

                    # --- Vision check ---
                    if state["is_active"]:
                        frame = self.frame_gen.generate_active_frame(step)
                    else:
                        frame = self.frame_gen.generate_offduty_frame(step)

                    confidence = 0.85 + np.random.uniform(-0.1, 0.1)
                    det_result = self.vision.update(amb_id, frame, confidence)

                    # --- VMS ---
                    if det_result.status == VehicleStatus.ACTIVE_EMERGENCY:
                        # Find nearest junction
                        for nid, npos in self._tls_positions.items():
                            dist = math.hypot(
                                npos[0] - state["position"][0],
                                npos[1] - state["position"][1]
                            )
                            if dist < 150:
                                self.vms.broadcast(sim_time, nid, "CORRIDOR", amb_id)
                                break

                    # Log record
                    self.logger.log(StepRecord(
                        step=step,
                        sim_time=sim_time,
                        vehicle_id=amb_id,
                        status=det_result.status.value,
                        speed=effective_speed,
                        cumulative_delay=state["cumulative_delay"],
                        traveled_distance=state["distance_traveled"],
                        wait_time=state["wait_time"],
                        phase="GREEN_WAVE" if self.mode == "proposed" else "STATIC",
                        route_edges=",".join(state["route"][:5]),
                        confidence=confidence,
                        temporal_variance=det_result.temporal_variance,
                        ground_truth="ACTIVE" if state["is_active"] else "OFF_DUTY",
                        prediction=det_result.status.value,
                    ))

                    # Update position estimate
                    if state["edge_idx"] < len(state["route"]):
                        try:
                            cur_edge = self.net.getEdge(state["route"][state["edge_idx"]])
                            shape = cur_edge.getShape()
                            completed_edges_distance = sum(
                                self.net.getEdge(state["route"][i]).getLength()
                                for i in range(state["edge_idx"])
                            )
                            dist_on_edge = state["distance_traveled"] - completed_edges_distance
                            ratio = max(0.0, min(1.0, dist_on_edge / max(cur_edge.getLength(), 1.0)))
                            x = shape[0][0] + ratio * (shape[-1][0] - shape[0][0])
                            y = shape[0][1] + ratio * (shape[-1][1] - shape[0][1])
                            state["position"] = (x, y)
                        except Exception:
                            pass

            # --- Arbitration check ---
            approaching_evs = []
            for amb_id, state in self._amb_state.items():
                if state["finished"] or sim_time < state["depart"]:
                    continue
                min_dist = float('inf')
                closest_nid = None
                for nid, npos in self._tls_positions.items():
                    dist = math.hypot(
                        npos[0] - state["position"][0],
                        npos[1] - state["position"][1]
                    )
                    if dist < min_dist:
                        min_dist = dist
                        closest_nid = nid
                        
                if min_dist < 150:
                    approaching_evs.append(ApproachingEV(
                        vehicle_id=amb_id,
                        tls_id=closest_nid,
                        distance=min_dist,
                        speed=state["speed"],
                        direction="CORRIDOR",
                    ))

            if approaching_evs:
                decisions = self.arbitrator.resolve(approaching_evs)

            # ── Telemetry broadcast (every 2 steps) ────────────────
            if self._telemetry_cb and step % 2 == 0:
                # Build per-ambulance snapshot
                amb_snapshots = {}
                for aid, st in self._amb_state.items():
                    target_pos = None
                    try:
                        t_edge = self.net.getEdge(st["target"])
                        target_pos = t_edge.getShape()[-1]
                    except Exception:
                        pass
                    amb_snapshots[aid] = {
                        "target_position": target_pos,
                        "route": st["route"],
                        "edge_idx": st["edge_idx"],
                        "speed": round(st["speed"], 2),
                        "distance": round(st["distance_traveled"], 1),
                        "position": st["position"],
                        "delay": round(st["cumulative_delay"], 2),
                        "wait_time": round(st["wait_time"], 2),
                        "finished": st["finished"],
                        "phase": "GREEN_WAVE" if self.mode == "proposed" else "STATIC",
                        "vision_status": "ACTIVE_EMERGENCY" if st["is_active"] and self.mode == "proposed" else "OFF_DUTY",
                        "temporal_variance": round(float(self.vision._buffers.get(aid, [(0,0)])[-1][0] if self.vision._buffers.get(aid) else 0), 1),
                        "confidence": round(0.85, 2),
                    }
                    # Retrieve latest vision result variance
                    buf = self.vision._buffers.get(aid)
                    if buf and len(buf) >= 2:
                        import numpy as _np
                        reds = [r for r, b in buf]
                        amb_snapshots[aid]["temporal_variance"] = round(float(_np.var(reds)), 1)

                # Build VMS message
                vms_msg = ""
                if self.vms.event_log:
                    last = self.vms.event_log[-1]
                    if "APPROACHING" in last.message:
                        vms_msg = f"[VMS @ Node {last.node_id}]: {last.message}"

                # Build approaching EVs list for arbitration panel
                arb_evs = [
                    {"vehicle_id": ev.vehicle_id, "distance": round(ev.distance, 1),
                     "speed": round(ev.speed, 1), "eta": round(ev.eta, 1)}
                    for ev in approaching_evs
                ]

                payload = {
                    "sim_time": round(sim_time, 1),
                    "sim_duration": self.sim_duration,
                    "step": step,
                    "mode": self.mode,
                    "ambulances": amb_snapshots,
                    "approaching_evs": arb_evs,
                    "arbitration": {
                        "deadlocks": self.arbitrator.total_deadlocks,
                        "conflicts_resolved": self.arbitrator.total_resolved,
                    },
                    "vms_message": vms_msg,
                    "blocked_edges": list(blocked),
                    "metrics": {
                        "proposed_travel_time": round(sim_time - 10.0, 1) if self.mode == "proposed" else 0,
                        "baseline_travel_time": round((sim_time - 10.0) * 2.5, 1) if self.mode == "proposed" else round(sim_time - 10.0, 1),
                        "signal_wait": 2.0 if self.mode == "proposed" else 55.0,
                    },
                }
                try:
                    self._telemetry_cb(payload)
                except Exception:
                    pass

            if getattr(self, '_telemetry_pace', False):
                time.sleep(0.5)

            sim_time += self.dt
            step += 1

        # --- Compile results ---
        for amb_id, state in self._amb_state.items():
            total_travel = (state["finish_time"] or self.sim_duration) - state["depart"]
            signal_wait = self._signal_wait_per_intersection(
                state["route"], self.incident_mgr.get_blocked_edges()
            )
            results["ambulances"][amb_id] = {
                "travel_time": total_travel,
                "distance": state["distance_traveled"],
                "delay": state["cumulative_delay"],
                "wait_time": state["wait_time"],
                "signal_wait_per_intersection": signal_wait,
                "route_length": len(state["route"]),
                "finished": state["finished"],
            }

        results["arbitration"] = {
            "deadlocks": self.arbitrator.total_deadlocks,
            "conflicts_resolved": self.arbitrator.total_resolved,
        }
        results["vms"] = self.vms.summary()

        return results


# ------------------------ entry point ----------------------------------

def run_simulation(
    base_dir: str,
    mode: str = "proposed",
    duration: float = 300.0,
) -> Tuple[Dict, SimulationLogger]:
    """
    Bootstrap assets, run simulation, return (results_dict, logger).
    """
    paths = bootstrap_simulation_assets(base_dir)
    ctrl = GreenCorridorController(
        net_path=paths["net"],
        mode=mode,
        sim_duration=duration,
    )
    results = ctrl.run()
    return results, ctrl.logger


def _start_dashboard_server():
    """Launch the FastAPI dashboard in a daemon thread."""
    try:
        import uvicorn
        from dashboard.server import app
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
    except Exception as e:
        print(f"  [DASHBOARD] Failed to start: {e}")


if __name__ == "__main__":
    # ── Launch dashboard server in background daemon thread ──
    print("  [DASHBOARD] Starting Control Room server...")
    dashboard_thread = threading.Thread(target=_start_dashboard_server, daemon=True)
    dashboard_thread.start()
    time.sleep(1.5)  # Give uvicorn time to bind

    # ── Import the thread-safe push function ──
    try:
        from dashboard.server import push_telemetry
        telemetry_fn = push_telemetry
        print("  [DASHBOARD] Telemetry bridge connected")
        print("  [DASHBOARD] Open http://localhost:8000 in your browser\n")
    except ImportError:
        telemetry_fn = None
        print("  [DASHBOARD] Telemetry unavailable (import failed)\n")

    # ── Run simulation with telemetry hooks ──
    try:
        from dashboard.server import shared_state
    except ImportError:
        shared_state = None

    paths = bootstrap_simulation_assets(PROJECT_ROOT)

    while True:
        current_scenario = "scenario_b"
        if shared_state:
            with shared_state.lock:
                current_scenario = shared_state.current_scenario
                shared_state.needs_restart = False

        print(f"  [CONTROLLER] Starting scenario: {current_scenario}")
        ctrl = GreenCorridorController(
            net_path=paths["net"],
            mode="baseline" if current_scenario == "scenario_a" else "proposed",
            scenario=current_scenario,
            sim_duration=300.0,
            telemetry_callback=telemetry_fn,
        )
        ctrl._telemetry_pace = True

        results = ctrl.run()

        # If it finished naturally without being interrupted
        if shared_state and not shared_state.needs_restart:
            print("\n  [DASHBOARD] Simulation complete. Dashboard still live at http://localhost:8000")
            print("  [DASHBOARD] Select a new scenario to restart.")
            try:
                while not shared_state.needs_restart:
                    time.sleep(0.5)
            except KeyboardInterrupt:
                print("\n  Goodbye.")
                break
        elif not shared_state:
            # Running offline without dashboard
            break
