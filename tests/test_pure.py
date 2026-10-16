"""Offline tests for the parts that need no robot: composition rules and pose geometry."""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import composition as C  # noqa: E402
import geometry as G  # noqa: E402
import teleop as T  # noqa: E402


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



def test_vase_drop_keeps_gripper_above_rim_and_comes_in_along_the_stem():
    pre, drop = G.vase_drop_poses((300, -283), rim_z=420, rim_r=59, lean_az_deg=90, tilt_deg=20, wrist_deg=-15)
    assert drop.z > 420 and pre.z > drop.z
    d = (drop.x - pre.x, drop.y - pre.y, drop.z - pre.z)
    norm = math.sqrt(sum(c * c for c in d))
    assert all(math.isclose(d[i] / norm, (drop.o_x, drop.o_y, drop.o_z)[i], abs_tol=1e-9) for i in range(3))


def test_vase_drop_crosses_the_rim_on_the_lean_side():
    _, drop = G.vase_drop_poses((300, -283), 420, 59, lean_az_deg=90, tilt_deg=20, wrist_deg=0)
    # stem axis back down to the rim plane lands inside the opening, toward +y (azimuth 90)
    t = (420 - drop.z) / drop.o_z
    cross = (drop.x + t * drop.o_x, drop.y + t * drop.o_y)
    assert math.hypot(cross[0] - 300, cross[1] + 283) < 59
    assert cross[1] > -283
    assert drop.o_y < 0  # tip heads away from the lean, so the top rests on the +y rim


def test_vertical_drop_is_straight_down():
    pre, drop = G.vase_drop_poses((0, 0), 100, 50, lean_az_deg=0, tilt_deg=0, wrist_deg=0)
    assert (drop.o_x, drop.o_y, drop.o_z) == (0.0, 0.0, -1.0) and math.isclose(pre.x, drop.x)



def test_long_stem_is_released_high_enough_to_clear_the_vase_floor():
    _, low = G.vase_drop_poses((0, 0), 420, 59, 0, 20, 0)
    _, high = G.vase_drop_poses((0, 0), 420, 59, 0, 20, 0, min_grip_z=600)
    assert low.z < 600 and math.isclose(high.z, 600)
    assert (high.o_x, high.o_y, high.o_z) == (low.o_x, low.o_y, low.o_z)



def test_vase_limits_the_lean_deeper_is_steeper():
    shallow = G.settled_tilt(depth_mm=200, rim_r=59, rim_frac=0.6)
    deep = G.settled_tilt(depth_mm=400, rim_r=59, rim_frac=0.6)
    assert 10 < deep < shallow < 35


def test_settled_stem_leans_toward_its_side_and_rises_above_the_rim():
    st = G.Stem("red", length_mm=450, bloom_mm=60)
    ps = G.settle(st, (0, 0), rim_z=300, rim_r=59, depth_mm=250, lean_az_deg=0)
    assert ps.foot[0] < 0 < ps.top[0]           # foot on the far side, top out over the lean side
    assert ps.top[2] > 300
    assert math.isclose(math.dist(ps.foot, ps.top), 450)


def test_seg_dist_known_cases():
    assert math.isclose(G.seg_dist((0, 0, 0), (10, 0, 0), (0, 5, 0), (10, 5, 0)), 5)       # parallel
    assert math.isclose(G.seg_dist((0, 0, 0), (10, 0, 0), (5, -5, 3), (5, 5, 3)), 3)       # crossing
    assert math.isclose(G.seg_dist((0, 0, 0), (1, 0, 0), (4, 0, 0), (9, 0, 0)), 3)         # collinear gap
    assert math.isclose(G.seg_dist((0, 0, 0), (0, 0, 0), (3, 4, 0), (3, 4, 0)), 5)         # points


def test_opposite_lean_has_more_clearance_than_the_same_lean():
    st = G.Stem("red", 450, 60)
    first = G.settle(st, (0, 0), 300, 59, 250, lean_az_deg=0)
    same = G.settle(st, (0, 0), 300, 59, 250, lean_az_deg=0)
    opposite = G.settle(st, (0, 0), 300, 59, 250, lean_az_deg=180)
    grip_same, grip_opp = same.top, opposite.top
    assert G.clearance(same, grip_same, [first], 300) < 0 < G.clearance(opposite, grip_opp, [first], 300)



def test_big_blooms_on_close_leans_collide_even_when_stems_clear():
    far = (0.0, 0.0, 5000.0)  # gripper out of the way, so only stems and blooms count
    def gap(bloom):
        st = G.Stem("y", 450, bloom)
        a = G.settle(st, (0, 0), 300, 59, 250, lean_az_deg=0)
        b = G.settle(st, (0, 0), 300, 59, 250, lean_az_deg=30)
        return G.clearance(b, far, [a], 300)
    assert gap(bloom=20) > 0 > gap(bloom=90)



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
    assert T.arc_ok(*start, v["rim_z"] + 50, vase_az - 30)[0]   # same swing above the rim is fine


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
