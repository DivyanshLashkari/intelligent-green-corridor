"""
Incident Manager -- Live Bottleneck / Accident Injector.

At a configurable simulation time (default t = 60 s), this module
blocks an arterial edge along the ambulance's default shortest path by
either:
    (a) Setting ``traci.edge.setDisallowed(edge_id, ["emergency"])`` to
        deny EV passage, or
    (b) Inserting a stopped dummy vehicle to physically obstruct the lane.

This forces the Dynamic A* routing module to detect the increased travel
time and reroute around the incident.

In evaluation (non-TraCI) mode, the module returns a set of blocked edge
IDs that the routing module treats as impassable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


# ------------------------ data classes ---------------------------------

@dataclass
class Incident:
    edge_id: str
    start_time: float   # simulation seconds
    end_time: float     # simulation seconds (math.inf for permanent)
    description: str = "Lane blockage -- accident"
    active: bool = False


# ------------------------ incident manager -----------------------------

class IncidentManager:
    """
    Manages live incidents that block edges in the simulation.

    Usage::

        mgr = IncidentManager()
        mgr.add_incident("E_0_1_to_0_2", start_time=60, end_time=180)

        # Each simulation step:
        blocked = mgr.tick(sim_time)
        # -> pass blocked set to dynamic_a_star(... blocked_edges=blocked)
    """

    def __init__(self):
        self.incidents: List[Incident] = []
        self._active_set: Set[str] = set()

    def add_incident(
        self,
        edge_id: str,
        start_time: float = 60.0,
        end_time: float = float("inf"),
        description: str = "Lane blockage -- accident",
    ):
        """Schedule an incident on *edge_id*."""
        self.incidents.append(Incident(
            edge_id=edge_id,
            start_time=start_time,
            end_time=end_time,
            description=description,
        ))

    def tick(self, sim_time: float) -> Set[str]:
        """
        Advance the incident state machine and return the set of
        currently blocked edge IDs.
        """
        self._active_set.clear()
        for inc in self.incidents:
            if inc.start_time <= sim_time < inc.end_time:
                inc.active = True
                self._active_set.add(inc.edge_id)
            else:
                inc.active = False
        return set(self._active_set)

    def apply_to_traci(self, traci_module, sim_time: float):
        """
        In live SUMO mode, set edge disallow flags via TraCI.
        """
        blocked = self.tick(sim_time)
        for edge_id in blocked:
            try:
                traci_module.edge.setDisallowed(edge_id, ["emergency", "passenger"])
            except Exception:
                pass

    def get_blocked_edges(self) -> Set[str]:
        return set(self._active_set)

    def setup_default_scenario(self):
        """
        Pre-configure the standard evaluation incident:
        Block edge along ambulance corridor at t=5.0s to force reroute.
        """
        self.add_incident(
            edge_id="E_1_1_to_1_2",
            start_time=5.0,
            end_time=240.0,
            description="Major accident on arterial E_1_1->E_1_2 -- full blockage",
        )


if __name__ == "__main__":
    mgr = IncidentManager()
    mgr.setup_default_scenario()
    for t in [0, 30, 60, 90, 120, 180, 250]:
        blocked = mgr.tick(float(t))
        print(f"t={t:>3d}s  blocked={blocked}")
