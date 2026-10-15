"""Turn a composition (which stem goes where, at what tilt) into insertion targets.

Pure Python, no robot: this is the "taste" function, the flower version of Viam 101's
_place_pose. Angles follow Sogetsu basic upright, measured from vertical (iloveikebana.com):
shin 10-15° toward the arranger's left, soe 45° left, hikae 75° right. A parallel gripper
inserts reliably only at modest tilts, so every tilt is clamped to MAX_TILT_DEG; the
unclamped intent is kept so the gap is visible in the demo.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

MAX_TILT_DEG = 30.0          # robot-insertion limit; raise only after it works on the day
KENZAN_RADIUS_MM = 30.0      # usable pin area of a ~6-8 cm kenzan, keep margin from the rim

# Sogetsu basic upright, arranger's view. azimuth 180 = toward arranger's left, 0 = right,
# 270 = toward the arranger (front). Lengths are relative to shin.
SOGETSU = {
    "shin":  {"tilt": 12.0, "azimuth": 200.0, "length": 1.00, "offset": (-8.0, 6.0)},
    "soe":   {"tilt": 45.0, "azimuth": 225.0, "length": 0.75, "offset": (-10.0, -8.0)},
    "hikae": {"tilt": 75.0, "azimuth": 315.0, "length": 0.56, "offset": (10.0, -10.0)},
}


@dataclass
class Placement:
    role: str            # shin / soe / hikae / filler
    slot: int            # tray slot the stem comes from
    x: float             # insertion point on the kenzan, mm, relative to its center
    y: float
    tilt_deg: float      # from vertical, after clamping
    azimuth_deg: float   # direction of lean in the kenzan's frame
    intended_tilt_deg: float = field(default=0.0)


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _on_kenzan(x: float, y: float) -> tuple[float, float]:
    r = (x * x + y * y) ** 0.5
    if r <= KENZAN_RADIUS_MM:
        return x, y
    return x * KENZAN_RADIUS_MM / r, y * KENZAN_RADIUS_MM / r


def from_params(params: list[dict]) -> list[Placement]:
    """Validate planner output (role, slot, tilt, azimuth, x, y) into safe placements."""
    out = []
    for p in params:
        x, y = _on_kenzan(float(p.get("x", 0.0)), float(p.get("y", 0.0)))
        intended = float(p.get("tilt", 0.0))
        out.append(Placement(
            role=p.get("role", "filler"), slot=int(p["slot"]), x=x, y=y,
            tilt_deg=clamp(intended, 0.0, MAX_TILT_DEG),
            azimuth_deg=float(p.get("azimuth", 0.0)) % 360.0,
            intended_tilt_deg=intended,
        ))
    return order_for_insertion(out)


def sogetsu_basic(slots: dict[str, int]) -> list[Placement]:
    """The classic three-line arrangement, given which tray slot holds each role's stem."""
    return from_params([
        {"role": role, "slot": slots[role], "tilt": s["tilt"], "azimuth": s["azimuth"],
         "x": s["offset"][0], "y": s["offset"][1]}
        for role, s in SOGETSU.items() if role in slots
    ])


def random_baseline(slots: list[int], seed: int) -> list[Placement]:
    """Control condition: same stems, placement and tilt drawn at random."""
    rng = random.Random(seed)
    return from_params([
        {"role": "random", "slot": s, "tilt": rng.uniform(0, MAX_TILT_DEG),
         "azimuth": rng.uniform(0, 360), "x": rng.uniform(-25, 25), "y": rng.uniform(-25, 25)}
        for s in slots
    ])


def order_for_insertion(placements: list[Placement]) -> list[Placement]:
    """Back to front (largest y first), so the gripper never reaches over a placed stem."""
    return sorted(placements, key=lambda p: -p.y)
