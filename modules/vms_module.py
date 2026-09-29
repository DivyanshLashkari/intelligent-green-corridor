"""
Novelty 4 -- Variable Message Sign (VMS) Compliance & Display Module.

Simulates real-time roadside signage alerts at approaching intersection
approaches, broadcasting structured event messages and managing vehicle
colour coding in the SUMO GUI.

Capabilities:
    1. Broadcast VMS messages when an EV is actively preempting.
    2. Colour-code ambulances in the SUMO GUI:
       - Bright GREEN (0, 255, 0) during active preemption
       - RED/WHITE  (255, 50, 50) when off-duty
    3. Maintain a timestamped event log for evaluation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ------------------------ data classes ---------------------------------

@dataclass
class VMSEvent:
    timestamp: float           # simulation time (s)
    node_id: str               # intersection node
    corridor: str              # approach corridor label
    vehicle_id: str            # EV causing the alert
    message: str               # human-readable broadcast
    color_code: Tuple[int, int, int, int] = (0, 255, 0, 255)

    def __str__(self) -> str:
        return (
            f"[VMS BROADCAST @ Node {self.node_id}]: "
            f'"{self.message}"'
        )


# ------------------------ colours --------------------------------------

COLOR_ACTIVE = (0, 255, 0, 255)      # bright green -- active preemption
COLOR_OFFDUTY = (255, 50, 50, 255)    # red -- off-duty / cleared


# ------------------------ controller -----------------------------------

class VMSController:
    """
    Manages Variable Message Sign broadcasts and vehicle appearance.

    In live SUMO mode, call ``apply_to_traci()`` each step to push
    colour changes.  In evaluation mode, the event log can be exported
    for compliance analysis.
    """

    def __init__(self):
        self.event_log: List[VMSEvent] = []
        self._active_signs: Dict[str, VMSEvent] = {}   # node_id -> latest

    def broadcast(
        self,
        sim_time: float,
        node_id: str,
        corridor: str,
        vehicle_id: str,
    ) -> VMSEvent:
        """Create and log a VMS broadcast event."""
        msg = (
            f"EMERGENCY VEHICLE APPROACHING ON CORRIDOR {corridor}. "
            f"MERGE RIGHT AND YIELD."
        )
        event = VMSEvent(
            timestamp=sim_time,
            node_id=node_id,
            corridor=corridor,
            vehicle_id=vehicle_id,
            message=msg,
            color_code=COLOR_ACTIVE,
        )
        self.event_log.append(event)
        self._active_signs[node_id] = event
        return event

    def clear(self, node_id: str, sim_time: float):
        """Clear a VMS display after the EV has passed."""
        if node_id in self._active_signs:
            ev = self._active_signs[node_id]
            clear_event = VMSEvent(
                timestamp=sim_time,
                node_id=node_id,
                corridor=ev.corridor,
                vehicle_id=ev.vehicle_id,
                message="ALL CLEAR -- RESUME NORMAL TRAFFIC FLOW.",
                color_code=COLOR_OFFDUTY,
            )
            self.event_log.append(clear_event)
            del self._active_signs[node_id]

    def get_vehicle_color(self, is_active: bool) -> Tuple[int, int, int, int]:
        """Return the appropriate SUMO GUI colour tuple."""
        return COLOR_ACTIVE if is_active else COLOR_OFFDUTY

    def apply_to_traci(
        self,
        traci_module,
        vehicle_id: str,
        is_active: bool,
    ):
        """
        Push colour change to the live SUMO GUI via TraCI.

        Parameters
        ----------
        traci_module
            The ``traci`` module (or a mock).
        vehicle_id : str
        is_active : bool
        """
        colour = self.get_vehicle_color(is_active)
        try:
            traci_module.vehicle.setColor(vehicle_id, colour)
        except Exception:
            pass  # vehicle may have left the network

    def summary(self) -> Dict[str, int]:
        """Return summary counts of broadcast events."""
        n_alerts = sum(1 for e in self.event_log if "APPROACHING" in e.message)
        n_clears = sum(1 for e in self.event_log if "ALL CLEAR" in e.message)
        return {"broadcasts": n_alerts, "clears": n_clears, "total": len(self.event_log)}


# ------------------------ standalone test ------------------------------

if __name__ == "__main__":
    vms = VMSController()
    e = vms.broadcast(sim_time=45.0, node_id="J3", corridor="A", vehicle_id="amb_1")
    print(e)
    vms.clear("J3", sim_time=55.0)
    print(f"Summary: {vms.summary()}")
