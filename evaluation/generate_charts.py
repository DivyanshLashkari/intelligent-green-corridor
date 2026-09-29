"""
Publication-Ready Chart Generator -- IEEE-Standard Figures at 300 DPI.

Generates three evaluation figures:
    1. fig_metrics_comparison.png  -- Bar chart: Precision, Recall, F1
    2. fig_confusion_matrix.png   -- Heatmap showing FP elimination
    3. fig_transit_time.png       -- Travel time comparison bar chart

All figures use a consistent dark colour scheme, IEEE-standard sizing,
and 300 DPI output.
"""

from __future__ import annotations

import csv
import os
import sys
from typing import Any, Dict, Optional

import numpy as np
import matplotlib
matplotlib.use("Agg")  # headless backend
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import seaborn as sns


# ------------------------ style setup ----------------------------------

def _setup_style():
    """Configure matplotlib for publication-quality figures."""
    plt.rcParams.update({
        "font.family": "serif",
        "font.size": 11,
        "axes.labelsize": 12,
        "axes.titlesize": 13,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "legend.fontsize": 10,
        "figure.dpi": 300,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.1,
        "axes.grid": True,
        "grid.alpha": 0.3,
        "axes.spines.top": False,
        "axes.spines.right": False,
    })


# ------------------------ colour palette -------------------------------

PALETTE = {
    "baseline": "#E74C3C",   # red
    "proposed": "#2ECC71",   # green
    "bg": "#FAFAFA",
    "grid": "#E0E0E0",
    "text": "#2C3E50",
}


# ------------------------ figure 1: metrics comparison -----------------

def generate_metrics_comparison(
    baseline_metrics: Dict[str, float],
    proposed_metrics: Dict[str, float],
    output_path: str,
):
    """
    Bar chart comparing Precision, Recall, and F1-Score
    between Baseline and Proposed systems.
    """
    _setup_style()

    metrics = ["Precision", "Recall", "F1-Score"]
    baseline_vals = [
        baseline_metrics["precision"],
        baseline_metrics["recall"],
        baseline_metrics["f1_score"],
    ]
    proposed_vals = [
        proposed_metrics["precision"],
        proposed_metrics["recall"],
        proposed_metrics["f1_score"],
    ]

    x = np.arange(len(metrics))
    width = 0.32

    fig, ax = plt.subplots(figsize=(7, 4.5))
    fig.patch.set_facecolor(PALETTE["bg"])
    ax.set_facecolor(PALETTE["bg"])

    bars1 = ax.bar(x - width / 2, baseline_vals, width,
                   label="Baseline (Spatial-Only)",
                   color=PALETTE["baseline"], edgecolor="white", linewidth=0.5,
                   zorder=3)
    bars2 = ax.bar(x + width / 2, proposed_vals, width,
                   label="Proposed (Temporal Variance)",
                   color=PALETTE["proposed"], edgecolor="white", linewidth=0.5,
                   zorder=3)

    # Value labels
    for bar in bars1:
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1.0,
                f"{bar.get_height():.1f}%", ha="center", va="bottom",
                fontsize=9, fontweight="bold", color=PALETTE["baseline"])
    for bar in bars2:
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1.0,
                f"{bar.get_height():.1f}%", ha="center", va="bottom",
                fontsize=9, fontweight="bold", color=PALETTE["proposed"])

    # Target line
    ax.axhline(y=95, color="#3498DB", linestyle="--", linewidth=1.2,
               label="Target Threshold (95%)", zorder=2)

    ax.set_xticks(x)
    ax.set_xticklabels(metrics, fontweight="bold")
    ax.set_ylabel("Score (%)")
    ax.set_title("Vision Module: Baseline vs. Proposed Performance", fontweight="bold")
    ax.set_ylim(0, 115)
    ax.legend(loc="upper left", framealpha=0.9)
    ax.grid(axis="y", alpha=0.3, zorder=0)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fig.savefig(output_path)
    plt.close(fig)
    print(f"  [CHART] {output_path}")


# ------------------------ figure 2: confusion matrices -----------------

def generate_confusion_matrix(
    baseline_cm: Dict[str, int],
    proposed_cm: Dict[str, int],
    output_path: str,
):
    """
    Side-by-side heatmaps showing how the proposed system eliminates
    false positives.
    """
    _setup_style()

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2))
    fig.patch.set_facecolor(PALETTE["bg"])

    for ax, cm, title in [
        (axes[0], baseline_cm, "Baseline (Spatial-Only)"),
        (axes[1], proposed_cm, "Proposed (Temporal Variance)"),
    ]:
        matrix = np.array([
            [cm["TP"], cm["FP"]],
            [cm["FN"], cm["TN"]],
        ])
        labels = np.array([
            [f"TP\n{cm['TP']}", f"FP\n{cm['FP']}"],
            [f"FN\n{cm['FN']}", f"TN\n{cm['TN']}"],
        ])

        cmap = "Reds" if "Baseline" in title else "Greens"
        sns.heatmap(
            matrix, annot=labels, fmt="", cmap=cmap,
            xticklabels=["Predicted\nActive", "Predicted\nOff-Duty"],
            yticklabels=["Actual\nActive", "Actual\nOff-Duty"],
            linewidths=2, linecolor="white",
            cbar=False, ax=ax,
            annot_kws={"size": 13, "fontweight": "bold"},
        )
        ax.set_title(title, fontweight="bold", pad=12)

    fig.suptitle("Confusion Matrix Comparison", fontsize=14, fontweight="bold", y=1.02)
    fig.tight_layout()

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fig.savefig(output_path)
    plt.close(fig)
    print(f"  [CHART] {output_path}")


# ------------------------ figure 3: transit time -----------------------

def generate_transit_time_chart(
    baseline_travel: Dict[str, float],
    proposed_travel: Dict[str, float],
    reduction_pct: float,
    output_path: str,
):
    """
    Grouped bar chart comparing travel time and signal wait metrics.
    """
    _setup_style()

    categories = [
        "Avg Travel\nTime (s)",
        "Signal Wait\nper Intersection (s)",
    ]
    baseline_vals = [
        baseline_travel.get("avg_travel_s", 0),
        baseline_travel.get("signal_wait_s", 0),
    ]
    proposed_vals = [
        proposed_travel.get("avg_travel_s", 0),
        proposed_travel.get("signal_wait_s", 0),
    ]

    x = np.arange(len(categories))
    width = 0.32

    fig, ax = plt.subplots(figsize=(7, 4.5))
    fig.patch.set_facecolor(PALETTE["bg"])
    ax.set_facecolor(PALETTE["bg"])

    bars1 = ax.bar(x - width / 2, baseline_vals, width,
                   label="Baseline (Static Route)",
                   color=PALETTE["baseline"], edgecolor="white", linewidth=0.5,
                   zorder=3)
    bars2 = ax.bar(x + width / 2, proposed_vals, width,
                   label="Proposed (Dynamic A*)",
                   color=PALETTE["proposed"], edgecolor="white", linewidth=0.5,
                   zorder=3)

    # Value labels
    for bar in bars1:
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                f"{bar.get_height():.1f}", ha="center", va="bottom",
                fontsize=9, fontweight="bold", color=PALETTE["baseline"])
    for bar in bars2:
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                f"{bar.get_height():.1f}", ha="center", va="bottom",
                fontsize=9, fontweight="bold", color=PALETTE["proposed"])

    # Reduction annotation
    ax.annotate(
        f"v {reduction_pct:.1f}% reduction",
        xy=(0, proposed_vals[0]),
        xytext=(0.5, max(baseline_vals) * 0.85),
        fontsize=11, fontweight="bold", color=PALETTE["proposed"],
        arrowprops=dict(arrowstyle="->", color=PALETTE["proposed"], lw=1.5),
        ha="center",
    )

    ax.set_xticks(x)
    ax.set_xticklabels(categories, fontweight="bold")
    ax.set_ylabel("Time (seconds)")
    ax.set_title("Emergency Vehicle Transit Performance", fontweight="bold")
    ax.legend(loc="upper right", framealpha=0.9)
    ax.grid(axis="y", alpha=0.3, zorder=0)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fig.savefig(output_path)
    plt.close(fig)
    print(f"  [CHART] {output_path}")


# ------------------------ orchestration --------------------------------

def generate_all_charts(results: Dict[str, Any], output_dir: str):
    """
    Generate all three publication figures from benchmark results.
    """
    print("\n  Generating publication-ready figures (300 DPI)...")

    # Figure 1: Metrics comparison
    generate_metrics_comparison(
        baseline_metrics=results["vision"]["baseline"],
        proposed_metrics=results["vision"]["proposed"],
        output_path=os.path.join(output_dir, "fig_metrics_comparison.png"),
    )

    # Figure 2: Confusion matrices
    generate_confusion_matrix(
        baseline_cm=results["vision"]["baseline"],
        proposed_cm=results["vision"]["proposed"],
        output_path=os.path.join(output_dir, "fig_confusion_matrix.png"),
    )

    # Figure 3: Transit time
    generate_transit_time_chart(
        baseline_travel={
            "avg_travel_s": results["travel_time"]["baseline_avg_s"],
            "signal_wait_s": results["signal_wait"]["baseline_per_intersection_s"],
        },
        proposed_travel={
            "avg_travel_s": results["travel_time"]["proposed_avg_s"],
            "signal_wait_s": results["signal_wait"]["proposed_per_intersection_s"],
        },
        reduction_pct=results["travel_time"]["reduction_pct"],
        output_path=os.path.join(output_dir, "fig_transit_time.png"),
    )

    print("  All figures generated successfully.")


# ------------------------ entry point ----------------------------------

if __name__ == "__main__":
    # This is typically called from benchmark_runner.py
    print("generate_charts: run via benchmark_runner.py for full pipeline.")
