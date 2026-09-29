"""
Benchmark Runner -- Automated Comparative Evaluation.

Runs two experimental batches:
    Batch 1 (Baseline):  Static Shortest Path + Spatial-only detection
    Batch 2 (Proposed):  Dynamic A* + Temporal Siren + ETA Arbitration + VMS

Produces:
    - evaluation/evaluation_results.csv
    - Confusion matrix metrics
    - Comparative summary tables

Invokes generate_charts.py for publication-ready figures.
"""

from __future__ import annotations

import csv
import os
import sys
import time
from typing import Any, Dict, List

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from main_controller import run_simulation
from modules.vision_module import SirenDetector
from evaluation.logger import SimulationLogger
from evaluation.generate_charts import generate_all_charts


def run_vision_benchmark(
    n_active: int = 100,
    n_offduty: int = 100,
) -> Dict[str, Dict[str, int]]:
    """
    Run vision evaluation for both baseline and proposed modes.

    Baseline: spatial-only (no temporal variance) -> reports all high-conf
              detections as ACTIVE, causing false positives on off-duty.
    Proposed: temporal variance gating -> eliminates false positives.
    """
    results = {}

    # --- Proposed: full temporal variance ---
    det_proposed = SirenDetector(buffer_size=5, v_thresh=15.0, conf_thresh=0.60)
    cm_proposed = det_proposed.evaluate_synthetic(n_active=n_active, n_offduty=n_offduty)
    results["proposed"] = cm_proposed

    # --- Baseline: spatial-only (v_thresh = 0 -> any detection is ACTIVE) ---
    det_baseline = SirenDetector(buffer_size=5, v_thresh=0.0, conf_thresh=0.60)
    cm_baseline = det_baseline.evaluate_synthetic(n_active=n_active, n_offduty=n_offduty)
    results["baseline"] = cm_baseline

    return results


def compute_metrics(cm: Dict[str, int]) -> Dict[str, float]:
    """Compute Precision, Recall, F1 from confusion matrix."""
    tp, fp, tn, fn = cm["TP"], cm["FP"], cm["TN"], cm["FN"]
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    f1 = 2 * precision * recall / max(1e-9, precision + recall)
    return {
        "precision": round(precision * 100, 2),
        "recall": round(recall * 100, 2),
        "f1_score": round(f1 * 100, 2),
        "TP": tp, "FP": fp, "TN": tn, "FN": fn,
    }


def run_full_benchmark(base_dir: str) -> Dict[str, Any]:
    """
    Execute the complete comparative benchmark.
    """
    print("=" * 70)
    print("  INTELLIGENT GREEN CORRIDOR SYSTEM -- BENCHMARK RUNNER")
    print("=" * 70)

    eval_dir = os.path.join(base_dir, "evaluation")
    os.makedirs(eval_dir, exist_ok=True)

    # -- Phase 1: Vision Benchmark --------------------------------------
    print("\n[1/4] Running vision benchmark (Active Siren Verification)...")
    vision_results = run_vision_benchmark(n_active=200, n_offduty=200)

    baseline_vision = compute_metrics(vision_results["baseline"])
    proposed_vision = compute_metrics(vision_results["proposed"])

    print(f"  Baseline Vision: Prec={baseline_vision['precision']:.1f}%  "
          f"Rec={baseline_vision['recall']:.1f}%  F1={baseline_vision['f1_score']:.1f}%")
    print(f"  Proposed Vision: Prec={proposed_vision['precision']:.1f}%  "
          f"Rec={proposed_vision['recall']:.1f}%  F1={proposed_vision['f1_score']:.1f}%")

    # -- Phase 2: Baseline Simulation -----------------------------------
    print("\n[2/4] Running BASELINE simulation (static routing, no preemption)...")
    baseline_results, baseline_logger = run_simulation(
        base_dir, mode="baseline", duration=300.0
    )

    # -- Phase 3: Proposed Simulation -----------------------------------
    print("\n[3/4] Running PROPOSED simulation (Dynamic A* + full ITS)...")
    proposed_results, proposed_logger = run_simulation(
        base_dir, mode="proposed", duration=300.0
    )

    # -- Phase 4: Comparative Analysis ----------------------------------
    print("\n[4/4] Computing comparative metrics...")

    # Travel time comparison
    baseline_travel_times = [
        v["travel_time"] for v in baseline_results["ambulances"].values()
    ]
    proposed_travel_times = [
        v["travel_time"] for v in proposed_results["ambulances"].values()
    ]
    avg_baseline_tt = sum(baseline_travel_times) / max(1, len(baseline_travel_times))
    avg_proposed_tt = sum(proposed_travel_times) / max(1, len(proposed_travel_times))
    travel_time_reduction = ((avg_baseline_tt - avg_proposed_tt) / max(1, avg_baseline_tt)) * 100

    # Signal wait
    baseline_signal_waits = [
        v["signal_wait_per_intersection"] for v in baseline_results["ambulances"].values()
    ]
    proposed_signal_waits = [
        v["signal_wait_per_intersection"] for v in proposed_results["ambulances"].values()
    ]
    avg_baseline_sw = sum(baseline_signal_waits) / max(1, len(baseline_signal_waits))
    avg_proposed_sw = sum(proposed_signal_waits) / max(1, len(proposed_signal_waits))

    # Arbitration
    baseline_deadlocks = 0  # baseline has no arbitration -> unknown conflicts
    proposed_deadlocks = proposed_results["arbitration"]["deadlocks"]

    # -- Build consolidated results -------------------------------------
    consolidated = {
        "vision": {
            "baseline": baseline_vision,
            "proposed": proposed_vision,
        },
        "travel_time": {
            "baseline_avg_s": round(avg_baseline_tt, 2),
            "proposed_avg_s": round(avg_proposed_tt, 2),
            "reduction_pct": round(travel_time_reduction, 2),
        },
        "signal_wait": {
            "baseline_per_intersection_s": round(avg_baseline_sw, 2),
            "proposed_per_intersection_s": round(avg_proposed_sw, 2),
        },
        "arbitration": {
            "baseline_deadlocks": "N/A (no resolver)",
            "proposed_deadlocks": proposed_deadlocks,
            "conflicts_resolved": proposed_results["arbitration"]["conflicts_resolved"],
        },
        "vms": proposed_results["vms"],
        "ambulance_details": {
            "baseline": baseline_results["ambulances"],
            "proposed": proposed_results["ambulances"],
        },
    }

    # -- Export CSV -----------------------------------------------------
    csv_path = os.path.join(eval_dir, "evaluation_results.csv")
    _export_summary_csv(csv_path, consolidated)
    print(f"\n  Results exported -> {csv_path}")

    # -- Export per-step data --------------------------------------------
    baseline_csv = os.path.join(eval_dir, "baseline_step_data.csv")
    proposed_csv = os.path.join(eval_dir, "proposed_step_data.csv")
    baseline_logger.export_csv(baseline_csv)
    proposed_logger.export_csv(proposed_csv)

    # -- Generate Charts -------------------------------------------------
    generate_all_charts(consolidated, eval_dir)

    # -- Print Summary --------------------------------------------------
    _print_summary(consolidated)

    return consolidated


def _export_summary_csv(path: str, data: Dict) -> None:
    """Write the comparative summary to CSV."""
    rows = [
        ["Metric", "Baseline", "Proposed", "Target", "Pass"],
        [
            "Vision Precision (%)",
            data["vision"]["baseline"]["precision"],
            data["vision"]["proposed"]["precision"],
            ">= 95.0",
            "-" if data["vision"]["proposed"]["precision"] >= 95.0 else "-",
        ],
        [
            "Vision Recall (%)",
            data["vision"]["baseline"]["recall"],
            data["vision"]["proposed"]["recall"],
            ">= 90.0",
            "-" if data["vision"]["proposed"]["recall"] >= 90.0 else "-",
        ],
        [
            "Vision F1-Score (%)",
            data["vision"]["baseline"]["f1_score"],
            data["vision"]["proposed"]["f1_score"],
            ">= 94.0",
            "-" if data["vision"]["proposed"]["f1_score"] >= 94.0 else "-",
        ],
        [
            "Avg Travel Time (s)",
            data["travel_time"]["baseline_avg_s"],
            data["travel_time"]["proposed_avg_s"],
            f">= 30% reduction",
            "-" if data["travel_time"]["reduction_pct"] >= 30.0 else "-",
        ],
        [
            "Travel Time Reduction (%)",
            "--",
            data["travel_time"]["reduction_pct"],
            ">= 30.0",
            "-" if data["travel_time"]["reduction_pct"] >= 30.0 else "-",
        ],
        [
            "Signal Wait / Intersection (s)",
            data["signal_wait"]["baseline_per_intersection_s"],
            data["signal_wait"]["proposed_per_intersection_s"],
            "<= 5.0",
            "-" if data["signal_wait"]["proposed_per_intersection_s"] <= 5.0 else "-",
        ],
        [
            "Arbitration Deadlocks",
            data["arbitration"]["baseline_deadlocks"],
            data["arbitration"]["proposed_deadlocks"],
            "0",
            "-" if data["arbitration"]["proposed_deadlocks"] == 0 else "-",
        ],
    ]

    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        for row in rows:
            writer.writerow(row)


def _print_summary(data: Dict) -> None:
    """Print a formatted comparison table to stdout."""
    print("\n" + "=" * 70)
    print("  COMPARATIVE EVALUATION RESULTS")
    print("=" * 70)

    rows = [
        ("Vision Precision",
         f"{data['vision']['baseline']['precision']:.1f}%",
         f"{data['vision']['proposed']['precision']:.1f}%",
         ">= 95.0%"),
        ("Vision Recall",
         f"{data['vision']['baseline']['recall']:.1f}%",
         f"{data['vision']['proposed']['recall']:.1f}%",
         ">= 90.0%"),
        ("Vision F1-Score",
         f"{data['vision']['baseline']['f1_score']:.1f}%",
         f"{data['vision']['proposed']['f1_score']:.1f}%",
         ">= 94.0%"),
        ("Avg Travel Time",
         f"{data['travel_time']['baseline_avg_s']:.1f}s",
         f"{data['travel_time']['proposed_avg_s']:.1f}s",
         f">= 30% reduction"),
        ("Travel Time Reduction",
         "--",
         f"{data['travel_time']['reduction_pct']:.1f}%",
         ">= 30.0%"),
        ("Signal Wait / Intersection",
         f"{data['signal_wait']['baseline_per_intersection_s']:.1f}s",
         f"{data['signal_wait']['proposed_per_intersection_s']:.1f}s",
         "<= 5.0s"),
        ("Arbitration Deadlocks",
         str(data["arbitration"]["baseline_deadlocks"]),
         str(data["arbitration"]["proposed_deadlocks"]),
         "0"),
    ]

    print(f"  {'Metric':<30s} {'Baseline':>12s} {'Proposed':>12s} {'Target':>16s}")
    print(f"  {'-'*30} {'-'*12} {'-'*12} {'-'*16}")
    for label, base, prop, target in rows:
        print(f"  {label:<30s} {base:>12s} {prop:>12s} {target:>16s}")

    # Confusion matrices
    print(f"\n  Vision Confusion Matrix (Baseline):")
    _print_cm(data["vision"]["baseline"])
    print(f"\n  Vision Confusion Matrix (Proposed):")
    _print_cm(data["vision"]["proposed"])
    print("=" * 70)


def _print_cm(metrics: Dict) -> None:
    print(f"    TP={metrics['TP']:>4d}  FP={metrics['FP']:>4d}")
    print(f"    FN={metrics['FN']:>4d}  TN={metrics['TN']:>4d}")


# ------------------------ entry point ----------------------------------

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    results = run_full_benchmark(base_dir)
