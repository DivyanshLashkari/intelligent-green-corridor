"""
Novelty 6 -- Dual-Domain Data Logger.

Records per-step and per-vehicle metrics for both the Vision domain
(TP/FP/TN/FN, confidence, variance) and the Simulation domain (speed,
delay, wait time, distance, phase changes).

Exports consolidated CSV for downstream analysis and chart generation.
"""

from __future__ import annotations

import csv
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class StepRecord:
    """One row of per-step, per-vehicle data."""
    step: int
    sim_time: float
    vehicle_id: str
    status: str           # ACTIVE_EMERGENCY | OFF_DUTY
    speed: float          # m/s
    cumulative_delay: float
    traveled_distance: float
    wait_time: float      # accumulated time with v < 0.1
    phase: str            # current TLS phase for this approach
    route_edges: str      # comma-separated edge list
    # Vision fields
    confidence: float = 0.0
    temporal_variance: float = 0.0
    ground_truth: str = ""
    prediction: str = ""


class SimulationLogger:
    """
    Dual-domain logger -- collects records during simulation and exports
    them to CSV.
    """

    def __init__(self):
        self.records: List[StepRecord] = []
        self._confusion: Dict[str, int] = {"TP": 0, "FP": 0, "TN": 0, "FN": 0}

    def log(self, record: StepRecord):
        self.records.append(record)

    def add_vision_result(self, ground_truth: str, prediction: str):
        """Accumulate confusion matrix counts."""
        if ground_truth == "ACTIVE" and prediction == "ACTIVE":
            self._confusion["TP"] += 1
        elif ground_truth == "OFF_DUTY" and prediction == "ACTIVE":
            self._confusion["FP"] += 1
        elif ground_truth == "OFF_DUTY" and prediction == "OFF_DUTY":
            self._confusion["TN"] += 1
        elif ground_truth == "ACTIVE" and prediction == "OFF_DUTY":
            self._confusion["FN"] += 1

    @property
    def confusion_matrix(self) -> Dict[str, int]:
        return dict(self._confusion)

    def set_confusion(self, cm: Dict[str, int]):
        self._confusion.update(cm)

    def precision(self) -> float:
        tp = self._confusion["TP"]
        fp = self._confusion["FP"]
        return tp / max(1, tp + fp)

    def recall(self) -> float:
        tp = self._confusion["TP"]
        fn = self._confusion["FN"]
        return tp / max(1, tp + fn)

    def f1_score(self) -> float:
        p = self.precision()
        r = self.recall()
        return 2 * p * r / max(1e-9, p + r)

    def export_csv(self, output_path: str) -> str:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        fieldnames = [
            "step", "sim_time", "vehicle_id", "status", "speed",
            "cumulative_delay", "traveled_distance", "wait_time", "phase",
            "route_edges", "confidence", "temporal_variance",
            "ground_truth", "prediction",
        ]
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for rec in self.records:
                writer.writerow({
                    "step": rec.step,
                    "sim_time": rec.sim_time,
                    "vehicle_id": rec.vehicle_id,
                    "status": rec.status,
                    "speed": f"{rec.speed:.3f}",
                    "cumulative_delay": f"{rec.cumulative_delay:.3f}",
                    "traveled_distance": f"{rec.traveled_distance:.3f}",
                    "wait_time": f"{rec.wait_time:.3f}",
                    "phase": rec.phase,
                    "route_edges": rec.route_edges,
                    "confidence": f"{rec.confidence:.4f}",
                    "temporal_variance": f"{rec.temporal_variance:.4f}",
                    "ground_truth": rec.ground_truth,
                    "prediction": rec.prediction,
                })
        return output_path

    def summary_dict(self) -> Dict[str, Any]:
        """Return a summary suitable for the final report."""
        return {
            "total_records": len(self.records),
            "confusion_matrix": self.confusion_matrix,
            "precision": round(self.precision(), 4),
            "recall": round(self.recall(), 4),
            "f1_score": round(self.f1_score(), 4),
        }
