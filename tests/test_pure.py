"""Offline tests for the parts that need no robot: composition rules and pose geometry."""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import composition as C  # noqa: E402
import geometry as G  # noqa: E402


def test_sogetsu_tilts_are_clamped_but_intent_is_kept():
    ps = {p.role: p for p in C.sogetsu_basic({"shin": 0, "soe": 1, "hikae": 2})}
    assert ps["shin"].tilt_deg == 12.0
    assert ps["soe"].tilt_deg == C.MAX_TILT_DEG and ps["soe"].intended_tilt_deg == 45.0
    assert ps["hikae"].tilt_deg == C.MAX_TILT_DEG and ps["hikae"].intended_tilt_deg == 75.0


def test_insertion_order_is_back_to_front():
    ys = [p.y for p in C.sogetsu_basic({"shin": 0, "soe": 1, "hikae": 2})]
    assert ys == sorted(ys, reverse=True)


def test_points_outside_the_kenzan_are_pulled_onto_it():
    (p,) = C.from_params([{"slot": 0, "x": 300, "y": 0, "tilt": 0}])
    assert math.isclose(math.hypot(p.x, p.y), C.KENZAN_RADIUS_MM)


def test_random_baseline_is_reproducible_and_within_limits():
    a, b = C.random_baseline([0, 1, 2], seed=7), C.random_baseline([0, 1, 2], seed=7)
    assert [(p.x, p.tilt_deg) for p in a] == [(p.x, p.tilt_deg) for p in b]
    assert all(p.tilt_deg <= C.MAX_TILT_DEG for p in a)


def test_vertical_axis_points_straight_down():
    assert G.axis(0, 123) == (0.0, 0.0, -1.0)


def test_insertion_is_a_straight_push_along_the_stem_axis():
    pre, ins = G.insertion_poses((500, 0, 100), 0, 0, tilt_deg=20, azimuth_deg=0,
                                 stem_below_grip_mm=80, depth_mm=15, approach_mm=50)
    d = (ins.x - pre.x, ins.y - pre.y, ins.z - pre.z)
    norm = math.sqrt(sum(c * c for c in d))
    assert math.isclose(norm, 50, rel_tol=1e-9)
    assert all(math.isclose(d[i] / norm, (ins.o_x, ins.o_y, ins.o_z)[i], abs_tol=1e-9) for i in range(3))
    assert pre.z > ins.z  # approach comes from above


def test_stem_tip_lands_at_target_depth():
    _, ins = G.insertion_poses((500, 0, 100), 5, -5, 0, 0, stem_below_grip_mm=80, depth_mm=15, approach_mm=50)
    assert (ins.x, ins.y, ins.z) == (505, -5, 100 - 15 + 80)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
