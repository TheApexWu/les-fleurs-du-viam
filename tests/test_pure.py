"""Offline tests: teleop limits and base-swing arc checks."""
import math
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import teleop as T

def test_teleop_limits():
    v = T.K.VASE
    assert not T.clamp_ok(300, 0, T.FLOOR_Z - 10)[0]                      # into the table
    assert not T.clamp_ok(v["x"], v["y"], v["rim_z"] - 20)[0]              # fingers into the vase
    assert T.clamp_ok(v["x"] + 200, v["y"] + 200, v["rim_z"] - 20)[0]     # same height, clear of the vase
    assert not T.clamp_ok(T.X_MAX + 1, 0, 300)[0] and not T.clamp_ok(300, T.Y_MIN - 1, 300)[0]
    assert T.clamp_ok(300, 0, 300) == (True, "")

def test_base_swing_keeps_radius_and_checks_the_whole_arc():
    x, y = T.swing(200, 0, 90)
    assert math.isclose(x, 0, abs_tol=1e-9) and math.isclose(y, 200)
    v = T.K.VASE
    r = math.hypot(v["x"], v["y"])
    start = (r, 0.0)                      # same radius as the vase, on the +x axis
    vase_az = math.degrees(math.atan2(v["y"], v["x"]))
    low = v["rim_z"] - 50
    # ending well past the vase is fine at the end point, but the arc crosses it low down
    end_x, end_y = T.swing(*start, vase_az - 30)
    assert T.clamp_ok(end_x, end_y, low)[0]
    assert not T.arc_ok(*start, low, vase_az - 30)[0]
    assert T.arc_ok(*start, v["rim_z"] + 50, vase_az - 30)[0]
if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
