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


def vase_drop_poses(vase_xy: tuple[float, float], rim_z: float, rim_r: float, lean_az_deg: float,
                    tilt_deg: float, wrist_deg: float, rim_frac: float = 0.6,
                    grip_above_rim_mm: float = 40.0, approach_mm: float = 60.0,
                    min_grip_z: float = float("-inf")) -> tuple[P, P]:
    """(pre, drop) gripper poses that let a held stem fall into a vase leaning toward `lean_az_deg`.

    The stem crosses the rim plane `rim_frac` of the way out toward the lean side, already tilted,
    so it settles against that side of the rim. The gripper stays `grip_above_rim_mm` up the stem
    from the rim plane, above the vase obstacle, and comes in along the stem axis.
    """
    ax = axis(tilt_deg, lean_az_deg + 180.0)  # the tip points away from the lean
    a = math.radians(lean_az_deg)
    cross = (vase_xy[0] + rim_frac * rim_r * math.cos(a), vase_xy[1] + rim_frac * rim_r * math.sin(a), rim_z)
    grip = tuple(cross[i] - grip_above_rim_mm * ax[i] for i in range(3))
    if grip[2] < min_grip_z:  # a long stem would hit the vase floor first: release higher up the axis
        grip = tuple(grip[i] - (min_grip_z - grip[2]) / -ax[2] * ax[i] for i in range(3))
    pre = tuple(grip[i] - approach_mm * ax[i] for i in range(3))
    return P(*pre, *ax, theta=wrist_deg), P(*grip, *ax, theta=wrist_deg)


# ── stems in a vase ─────────────────────────────────────────────────────────
# A dropped stem settles with its foot against the far wall on the floor and its body resting on
# the near rim, so the vase, not the plan, decides the lean. These model that and check clearance.

Vec = tuple[float, float, float]


@dataclass
class Stem:
    colour: str
    length_mm: float
    bloom_mm: float          # flower head width
    stem_mm: float = 6.0


@dataclass
class PlacedStem:
    stem: Stem
    foot: Vec                # on the vase floor
    top: Vec                 # bloom centre
    tilt_deg: float
    lean_az_deg: float


def settled_tilt(depth_mm: float, rim_r: float, rim_frac: float, floor_r_frac: float = 0.8) -> float:
    """Lean the vase allows: rim crossing `rim_frac` toward the lean side, foot at the far floor edge."""
    return math.degrees(math.atan2(rim_frac * rim_r + floor_r_frac * rim_r, depth_mm))


def settle(stem: Stem, vase_xy: tuple[float, float], rim_z: float, rim_r: float, depth_mm: float,
           lean_az_deg: float, rim_frac: float = 0.6, floor_r_frac: float = 0.8) -> PlacedStem:
    a = math.radians(lean_az_deg)
    foot = (vase_xy[0] - floor_r_frac * rim_r * math.cos(a), vase_xy[1] - floor_r_frac * rim_r * math.sin(a),
            rim_z - depth_mm)
    tilt = settled_tilt(depth_mm, rim_r, rim_frac, floor_r_frac)
    up = (-v for v in axis(tilt, lean_az_deg + 180.0))  # axis() points tip-down; flip for root-to-top
    top = tuple(foot[i] + stem.length_mm * u for i, u in enumerate(up))
    return PlacedStem(stem, foot, top, tilt, lean_az_deg)


def above_rim(ps: PlacedStem, rim_z: float) -> tuple[Vec, Vec]:
    """The part of a placed stem the gripper can hit: from where it crosses the rim to its top."""
    f, t = ps.foot, ps.top
    k = (rim_z - f[2]) / (t[2] - f[2]) if t[2] != f[2] else 0.0
    k = min(max(k, 0.0), 1.0)
    return tuple(f[i] + k * (t[i] - f[i]) for i in range(3)), t


def seg_dist(p1: Vec, q1: Vec, p2: Vec, q2: Vec) -> float:
    """Shortest distance between segments p1q1 and p2q2 (standard clamped closest-points)."""
    d1 = [q1[i] - p1[i] for i in range(3)]
    d2 = [q2[i] - p2[i] for i in range(3)]
    r = [p1[i] - p2[i] for i in range(3)]
    dot = lambda u, v: sum(u[i] * v[i] for i in range(3))
    a, e, f = dot(d1, d1), dot(d2, d2), dot(d2, r)
    if a < 1e-9 and e < 1e-9:
        return math.dist(p1, p2)
    if a < 1e-9:
        s, t = 0.0, min(max(f / e, 0.0), 1.0)
    else:
        c = dot(d1, r)
        if e < 1e-9:
            s, t = min(max(-c / a, 0.0), 1.0), 0.0
        else:
            b = dot(d1, d2)
            den = a * e - b * b
            s = min(max((b * f - c * e) / den, 0.0), 1.0) if den > 1e-9 else 0.0
            t = (b * s + f) / e
            if t < 0:
                s, t = min(max(-c / a, 0.0), 1.0), 0.0
            elif t > 1:
                s, t = min(max((b - c) / a, 0.0), 1.0), 1.0
    c1 = [p1[i] + d1[i] * s for i in range(3)]
    c2 = [p2[i] + d2[i] * t for i in range(3)]
    return math.dist(c1, c2)


def clearance(new: PlacedStem, grip: Vec, placed: list[PlacedStem], rim_z: float,
              gripper_r: float = 60.0) -> float:
    """Smallest gap (mm) between the new stem plus the gripper and every placed stem and bloom.
    Negative means contact. Stems count as their radius, blooms as spheres, the gripper as a sphere."""
    gaps = []
    for ps in placed:
        a0, a1 = above_rim(ps, rim_z)
        b0, b1 = above_rim(new, rim_z)
        r_old, r_new = ps.stem.stem_mm / 2, new.stem.stem_mm / 2
        gaps.append(seg_dist(a0, a1, b0, b1) - r_old - r_new)
        gaps.append(seg_dist(a0, a1, grip, grip) - r_old - gripper_r)
        gaps.append(seg_dist(b0, b1, ps.top, ps.top) - r_new - ps.stem.bloom_mm / 2)
        gaps.append(math.dist(grip, ps.top) - gripper_r - ps.stem.bloom_mm / 2)
        gaps.append(math.dist(new.top, ps.top) - (new.stem.bloom_mm + ps.stem.bloom_mm) / 2)
    return min(gaps) if gaps else float("inf")
