"""
Novelty 1 -- Active Siren Verification via Temporal Variance Analysis.

Baseline Problem:
    Spatial-only YOLO detectors flag *any* ambulance-shaped vehicle,
    triggering false preemptions for parked or off-duty units.

Solution:
    Maintain a rolling buffer of N frames per tracked vehicle, extract the
    roof light-bar ROI, and compute the temporal variance of emergency-colour
    pixel intensity.  Only classify as ACTIVE_EMERGENCY when both structural
    confidence AND temporal variance exceed their thresholds.

Key Parameters:
    BUFFER_SIZE     = 5   frames
    ROI_RATIO       = 0.40 (upper 40 % of bounding box)
    V_THRESH        = 15.0 (temporal variance threshold)
    CONF_THRESH     = 0.60 (structural confidence gate)
"""

from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None  # graceful fallback for headless environments


# ---------------------------- enumerations -----------------------------

class VehicleStatus(Enum):
    ACTIVE_EMERGENCY = "ACTIVE_EMERGENCY"
    OFF_DUTY = "OFF_DUTY"
    UNKNOWN = "UNKNOWN"


# ---------------------------- data classes -----------------------------

@dataclass
class DetectionResult:
    vehicle_id: str
    status: VehicleStatus
    confidence: float
    temporal_variance: float
    red_fraction: float = 0.0
    blue_fraction: float = 0.0


# ------------------------ synthetic frame generator --------------------

class SyntheticFrameGenerator:
    """
    Generates synthetic RGB frames that mimic active-siren flashing or
    static (off-duty) ambulance rooftop appearances.  Used for unit
    testing without external camera hardware.

    The siren simulation alternates between dominant-RED and dominant-BLUE
    frames so that the temporal variance of each colour channel exceeds
    V_THRESH.  The off-duty generator produces a constant white/grey
    rooftop with no temporal variation.
    """

    def __init__(self, width: int = 120, height: int = 80, seed: int = 42):
        self.width = width
        self.height = height
        self.rng = np.random.RandomState(seed)

    def generate_active_frame(self, frame_idx: int) -> np.ndarray:
        """Return a frame where the upper ROI flashes red <-> blue."""
        frame = self.rng.randint(20, 60, (self.height, self.width, 3), dtype=np.uint8)
        roi_h = int(self.height * 0.40)

        if frame_idx % 2 == 0:
            # Dominant RED flash
            frame[:roi_h, :, 0] = self.rng.randint(200, 255, (roi_h, self.width)).astype(np.uint8)
            frame[:roi_h, :, 1] = self.rng.randint(0, 30, (roi_h, self.width)).astype(np.uint8)
            frame[:roi_h, :, 2] = self.rng.randint(0, 50, (roi_h, self.width)).astype(np.uint8)
        else:
            # Dominant BLUE flash
            frame[:roi_h, :, 0] = self.rng.randint(0, 50, (roi_h, self.width)).astype(np.uint8)
            frame[:roi_h, :, 1] = self.rng.randint(0, 30, (roi_h, self.width)).astype(np.uint8)
            frame[:roi_h, :, 2] = self.rng.randint(200, 255, (roi_h, self.width)).astype(np.uint8)

        return frame

    def generate_offduty_frame(self, _frame_idx: int = 0) -> np.ndarray:
        """Return a frame with constant grey/white rooftop -- no flashing."""
        frame = self.rng.randint(20, 60, (self.height, self.width, 3), dtype=np.uint8)
        roi_h = int(self.height * 0.40)
        # Uniform grey -- no temporal variance
        frame[:roi_h, :, :] = 180
        return frame


# ------------------------ core siren detector --------------------------

class SirenDetector:
    """
    Active Siren Verification Engine.

    For each tracked vehicle ID the detector maintains a rolling deque of
    N bounding-box crops (or full frames).  On each ``update()`` call it:

    1. Extracts the upper 40 % ROI (roof light-bar region).
    2. Converts the ROI to HSV colour space.
    3. Counts high-intensity RED and BLUE pixels per frame.
    4. Computes temporal variance sigma² across the buffer.
    5. Classifies status as ACTIVE_EMERGENCY iff
       (confidence >= CONF_THRESH) AND (sigma² >= V_THRESH).

    Parameters
    ----------
    buffer_size : int
        Number of frames in the rolling buffer (default 5).
    v_thresh : float
        Temporal variance activation threshold (default 15.0).
    conf_thresh : float
        Minimum structural confidence from upstream detector (default 0.60).
    """

    BUFFER_SIZE: int = 5
    V_THRESH: float = 15.0
    CONF_THRESH: float = 0.60
    ROI_RATIO: float = 0.40

    # HSV ranges for emergency colours
    RED_LOW_1 = np.array([0, 150, 200])
    RED_HIGH_1 = np.array([10, 255, 255])
    RED_LOW_2 = np.array([170, 150, 200])
    RED_HIGH_2 = np.array([180, 255, 255])
    BLUE_LOW = np.array([100, 150, 200])
    BLUE_HIGH = np.array([130, 255, 255])

    def __init__(
        self,
        buffer_size: int = 5,
        v_thresh: float = 15.0,
        conf_thresh: float = 0.60,
    ):
        self.BUFFER_SIZE = buffer_size
        self.V_THRESH = v_thresh
        self.CONF_THRESH = conf_thresh

        # vehicle_id -> deque of (red_fraction, blue_fraction)
        self._buffers: Dict[str, deque] = {}

    # -- internal helpers -----------------------------------------------

    def _extract_roi(self, frame: np.ndarray) -> np.ndarray:
        """Return the upper ROI_RATIO portion of the frame (light-bar)."""
        h = frame.shape[0]
        roi_h = max(1, int(h * self.ROI_RATIO))
        return frame[:roi_h, :, :]

    def _compute_colour_fractions(self, roi: np.ndarray) -> Tuple[float, float]:
        """
        Convert ROI to HSV and return (red_fraction, blue_fraction)
        where each fraction - [0, 100].
        """
        if cv2 is not None:
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        else:
            # Lightweight fallback: manual BGR->HSV (approximate)
            hsv = self._manual_bgr2hsv(roi)

        total_pixels = max(1, hsv.shape[0] * hsv.shape[1])

        # Red mask (wraps around hue 0)
        mask_r1 = np.all(
            (hsv >= self.RED_LOW_1) & (hsv <= self.RED_HIGH_1), axis=-1
        )
        mask_r2 = np.all(
            (hsv >= self.RED_LOW_2) & (hsv <= self.RED_HIGH_2), axis=-1
        )
        red_count = int(np.sum(mask_r1 | mask_r2))

        # Blue mask
        mask_b = np.all(
            (hsv >= self.BLUE_LOW) & (hsv <= self.BLUE_HIGH), axis=-1
        )
        blue_count = int(np.sum(mask_b))

        red_frac = (red_count / total_pixels) * 100.0
        blue_frac = (blue_count / total_pixels) * 100.0
        return red_frac, blue_frac

    @staticmethod
    def _manual_bgr2hsv(bgr: np.ndarray) -> np.ndarray:
        """
        Approximate BGR -> HSV conversion using pure NumPy.
        Output HSV ranges: H - [0,180], S - [0,255], V - [0,255].
        """
        img = bgr.astype(np.float32) / 255.0
        b, g, r = img[..., 0], img[..., 1], img[..., 2]
        v = np.max(img, axis=-1)
        delta = v - np.min(img, axis=-1)
        s = np.where(v > 0, delta / (v + 1e-8), 0)

        h = np.zeros_like(v)
        mask_r = (v == r) & (delta > 0)
        mask_g = (v == g) & (delta > 0) & ~mask_r
        mask_b = (delta > 0) & ~mask_r & ~mask_g

        h[mask_r] = 60.0 * (((g[mask_r] - b[mask_r]) / (delta[mask_r] + 1e-8)) % 6)
        h[mask_g] = 60.0 * (((b[mask_g] - r[mask_g]) / (delta[mask_g] + 1e-8)) + 2)
        h[mask_b] = 60.0 * (((r[mask_b] - g[mask_b]) / (delta[mask_b] + 1e-8)) + 4)

        hsv = np.stack([h / 2.0, s * 255.0, v * 255.0], axis=-1).astype(np.uint8)
        return hsv

    # -- public API -----------------------------------------------------

    def update(
        self,
        vehicle_id: str,
        frame: np.ndarray,
        structural_confidence: float,
    ) -> DetectionResult:
        """
        Feed one frame for *vehicle_id* and return the current classification.

        Parameters
        ----------
        vehicle_id : str
            Unique identifier of the tracked vehicle.
        frame : np.ndarray
            BGR image crop of the vehicle (or full frame with bbox).
        structural_confidence : float
            Confidence from the upstream object detector [0, 1].

        Returns
        -------
        DetectionResult
        """
        if vehicle_id not in self._buffers:
            self._buffers[vehicle_id] = deque(maxlen=self.BUFFER_SIZE)

        roi = self._extract_roi(frame)
        red_frac, blue_frac = self._compute_colour_fractions(roi)
        self._buffers[vehicle_id].append((red_frac, blue_frac))

        buf = self._buffers[vehicle_id]
        # Compute temporal variance on INDIVIDUAL channels to detect
        # the red<->blue alternation pattern.  An active siren alternates
        # between high-red/low-blue and low-red/high-blue, producing
        # high variance in each channel independently.
        reds = [r for r, b in buf]
        blues = [b for r, b in buf]
        var_r = float(np.var(reds)) if len(buf) >= 2 else 0.0
        var_b = float(np.var(blues)) if len(buf) >= 2 else 0.0
        variance = max(var_r, var_b)

        if structural_confidence >= self.CONF_THRESH and variance >= self.V_THRESH:
            status = VehicleStatus.ACTIVE_EMERGENCY
        else:
            status = VehicleStatus.OFF_DUTY

        return DetectionResult(
            vehicle_id=vehicle_id,
            status=status,
            confidence=structural_confidence,
            temporal_variance=variance,
            red_fraction=red_frac,
            blue_fraction=blue_frac,
        )

    def reset(self, vehicle_id: Optional[str] = None):
        """Clear buffer(s).  If vehicle_id is None, reset all."""
        if vehicle_id:
            self._buffers.pop(vehicle_id, None)
        else:
            self._buffers.clear()

    # -- batch evaluation for benchmarking ------------------------------

    def evaluate_synthetic(
        self,
        n_active: int = 50,
        n_offduty: int = 50,
        seed: int = 42,
    ) -> Dict[str, int]:
        """
        Run a full synthetic evaluation and return confusion matrix counts
        {TP, FP, TN, FN}.

        Active vehicles get alternating red/blue flash frames -> high sigma².
        Off-duty vehicles get constant grey frames -> sigma² ~= 0.
        """
        gen = SyntheticFrameGenerator(seed=seed)
        tp = fp = tn = fn = 0

        # --- active emergency vehicles (ground truth = ACTIVE) ---
        for v in range(n_active):
            vid = f"amb_active_{v}"
            self.reset(vid)
            conf = 0.60 + random.Random(seed + v).random() * 0.35
            for f in range(self.BUFFER_SIZE):
                frame = gen.generate_active_frame(f)
                result = self.update(vid, frame, conf)
            if result.status == VehicleStatus.ACTIVE_EMERGENCY:
                tp += 1
            else:
                fn += 1

        # --- off-duty vehicles (ground truth = OFF_DUTY) ---
        for v in range(n_offduty):
            vid = f"amb_offduty_{v}"
            self.reset(vid)
            conf = 0.60 + random.Random(seed + 1000 + v).random() * 0.35
            for f in range(self.BUFFER_SIZE):
                frame = gen.generate_offduty_frame(f)
                result = self.update(vid, frame, conf)
            if result.status == VehicleStatus.OFF_DUTY:
                tn += 1
            else:
                fp += 1

        return {"TP": tp, "FP": fp, "TN": tn, "FN": fn}


# ------------------------ CLI self-test --------------------------------

if __name__ == "__main__":
    det = SirenDetector()
    cm = det.evaluate_synthetic(n_active=100, n_offduty=100)
    precision = cm["TP"] / max(1, cm["TP"] + cm["FP"])
    recall = cm["TP"] / max(1, cm["TP"] + cm["FN"])
    f1 = 2 * precision * recall / max(1e-9, precision + recall)
    print(f"Confusion Matrix: {cm}")
    print(f"Precision: {precision:.4f}  Recall: {recall:.4f}  F1: {f1:.4f}")
