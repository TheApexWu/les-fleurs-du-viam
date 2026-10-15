"""Pose math for angled stem insertion. Pure Python so it can be tested without a robot.

A stem is held with its axis along the gripper's z-axis, tip pointing away from the gripper.
Viam writes orientation as the direction the tool's z-axis points (o_x, o_y, o_z) plus a spin
theta. Straight down is (0, 0, -1); a stem leaning by `tilt` toward `azimuth` points the tool
along (sin t cos a, sin t sin a, -cos t), i.e. the tip goes down and slightly outward.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class P:
    """Plain pose: position in mm (world frame) plus orientation vector and theta (deg)."""
    x: float
    y: float
    z: float
    o_x: float = 0.0
    o_y: float = 0.0
    o_z: float = -1.0
    theta: float = 0.0


def axis(tilt_deg: float, azimuth_deg: float) -> tuple[float, float, float]:
    t, a = math.radians(tilt_deg), math.radians(azimuth_deg)
    return (math.sin(t) * math.cos(a), math.sin(t) * math.sin(a), -math.cos(t))


def insertion_poses(kenzan_center: tuple[float, float, float], x: float, y: float,
                    tilt_deg: float, azimuth_deg: float, stem_below_grip_mm: float,
                    depth_mm: float, approach_mm: float) -> tuple[P, P]:
    """(pre_insert, insert) gripper poses for one stem.

    The stem tip must end `depth_mm` below the kenzan's pin tops at (x, y). The gripper sits
    `stem_below_grip_mm` back up the stem from the tip, and the pre-insert pose backs off a
    further `approach_mm` along the same axis, so the final move is a straight push.
    """
    ax = axis(tilt_deg, azimuth_deg)
    tip = (kenzan_center[0] + x, kenzan_center[1] + y, kenzan_center[2] - depth_mm)
    grip = tuple(tip[i] - stem_below_grip_mm * ax[i] for i in range(3))
    pre = tuple(grip[i] - approach_mm * ax[i] for i in range(3))
    return P(*pre, *ax), P(*grip, *ax)


def stem_obstacle(kenzan_center: tuple[float, float, float], x: float, y: float,
                  tilt_deg: float, azimuth_deg: float, height_mm: float) -> tuple[P, tuple[float, float, float]]:
    """Center pose and box dims (mm) approximating a placed stem, for the planner's WorldState."""
    ax = axis(tilt_deg, azimuth_deg)
    base = (kenzan_center[0] + x, kenzan_center[1] + y, kenzan_center[2])
    mid = tuple(base[i] - ax[i] * height_mm / 2 for i in range(3))  # -ax points up the stem
    return P(*mid, o_x=-ax[0], o_y=-ax[1], o_z=-ax[2]), (40.0, 40.0, height_mm)
