"""Keyboard teleop for the arm, logging every move so a demonstration can be replayed later.

  python teleop.py            exit manual mode first; someone at the stop button for the first run

  W/S  x +/-        A/D  y +/-        R/F  z +/-        Q/E  wrist spin -/+ 5 deg
  O/C  gripper open/close a step      G  gripper to GRIP_STEM (gentle hold)
  Tab  step 20 mm <-> 5 mm            M  mark this moment with a label
  Space  stop                         X  quit

Every key is one move: read the pose, add the step, check the limits, move, read back. Keys pressed
while a move runs are thrown away, so a held key can't queue moves that keep going after release.
Each line of recordings/teleop-<time>.jsonl holds the command and the pose and joints actually reached.
"""
import asyncio
import json
import math
import sys
import termios
import time
import tty
from pathlib import Path

import config as K

STEPS_MM = (20.0, 5.0)
SPIN_DEG = 5.0
GRIP_STEP = 50
ACCURACY_MM = 2.0
TELEOP_DEG_S = 15.0

# Safe box, from the cell's obstacle config and the vase measured on 16 Oct.
FLOOR_Z = K.TABLE_TOP_Z + 30.0
X_MAX, Y_MIN, Z_MAX = 650.0, -420.0, 900.0
VASE_KEEPOUT_R = K.VASE["rim_r"] + 20.0
VASE_MIN_Z = K.VASE["rim_z"] + 10.0

MOVES = {"w": (1, 0, 0), "s": (-1, 0, 0), "a": (0, 1, 0), "d": (0, -1, 0), "r": (0, 0, 1), "f": (0, 0, -1)}


def clamp_ok(x: float, y: float, z: float) -> tuple[bool, str]:
    """Is a fingertip target inside the safe box? Pure, so it is tested offline."""
    if z < FLOOR_Z:
        return False, f"z {z:.0f} below table limit {FLOOR_Z:.0f}"
    if z > Z_MAX:
        return False, f"z {z:.0f} above ceiling limit {Z_MAX:.0f}"
    if x > X_MAX:
        return False, f"x {x:.0f} past front wall limit {X_MAX:.0f}"
    if y < Y_MIN:
        return False, f"y {y:.0f} past side wall limit {Y_MIN:.0f}"
    if math.hypot(x - K.VASE["x"], y - K.VASE["y"]) < VASE_KEEPOUT_R and z < VASE_MIN_Z:
        return False, f"over the vase at z {z:.0f}; fingers must stay above {VASE_MIN_Z:.0f}"
    return True, ""


def read_key() -> str:
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def drop_buffered_keys():
    termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)


async def main():
    from viam.components.arm import Arm
    from viam.proto.common import Pose
    from flowers import connect

    robot = await connect()
    arm = Arm.from_robot(robot, K.ARM)
    log_path = Path(__file__).parent / "recordings" / f"teleop-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    log_path.parent.mkdir(exist_ok=True)
    log = log_path.open("a")
    step_i = 0

    async def snapshot():
        p, j = await asyncio.gather(arm.get_end_position(), arm.get_joint_positions())
        g = (await arm.do_command({"get_gripper": True})).get("gripper_position")
        pose = {k: round(getattr(p, k), 3) for k in ("x", "y", "z", "o_x", "o_y", "o_z", "theta")}
        return pose, [round(v, 3) for v in j.values], g

    def write(entry):
        log.write(json.dumps(entry) + "\n")
        log.flush()

    async def grip(width):
        await arm.do_command({"setup_gripper": True, "move_gripper": float(max(0, min(850, width)))})

    try:
        await arm.do_command({"set_speed": TELEOP_DEG_S})
        await arm.do_command({"set_gripper_speed": K.GRIP_SPEED})
        print(__doc__.split("\n\n")[1])
        print(f"logging to {log_path}\n")
        while True:
            key = (await asyncio.to_thread(read_key)).lower()
            if key in ("x", "\x03"):
                break
            if key == " ":
                await arm.stop()
                print("STOP")
                write({"t": time.time(), "cmd": "stop"})
                continue
            if key == "\t":
                step_i = 1 - step_i
                print(f"step {STEPS_MM[step_i]:.0f} mm")
                continue

            pose, joints, g = await snapshot()
            cmd = None
            if key in MOVES:
                d = [c * STEPS_MM[step_i] for c in MOVES[key]]
                target = dict(pose, x=pose["x"] + d[0], y=pose["y"] + d[1], z=pose["z"] + d[2])
                ok, why = clamp_ok(target["x"], target["y"], target["z"])
                if not ok:
                    print(f"refused: {why}")
                    write({"t": time.time(), "cmd": {"key": key, "delta": d}, "refused": why, "pose": pose})
                    continue
                cmd = {"key": key, "delta": d}
            elif key in ("q", "e"):
                target = dict(pose, theta=pose["theta"] + (SPIN_DEG if key == "e" else -SPIN_DEG))
                cmd = {"key": key, "d_theta": target["theta"] - pose["theta"]}
            elif key in ("o", "c", "g"):
                width = K.GRIP_STEM if key == "g" else (g or 0) + (GRIP_STEP if key == "o" else -GRIP_STEP)
                await grip(width)
                pose, joints, g2 = await snapshot()
                print(f"gripper {g:.0f} -> {g2:.0f}")
                write({"t": time.time(), "cmd": {"key": key, "gripper_target": width}, "pose": pose,
                       "joints": joints, "gripper": g2})
                drop_buffered_keys()
                continue
            elif key == "m":
                label = await asyncio.to_thread(input, "label for this moment: ")
                write({"t": time.time(), "mark": label.strip(), "pose": pose, "joints": joints, "gripper": g})
                print(f"marked '{label.strip()}' at x={pose['x']:.0f} y={pose['y']:.0f} z={pose['z']:.0f}")
                continue
            else:
                continue

            await arm.move_to_position(Pose(**target))
            reached, joints, g = await snapshot()
            err = math.dist((target["x"], target["y"], target["z"]), (reached["x"], reached["y"], reached["z"]))
            flag = "  <-- off target" if err > ACCURACY_MM else ""
            print(f"{key}: x={reached['x']:.0f} y={reached['y']:.0f} z={reached['z']:.0f} "
                  f"theta={reached['theta']:.0f}  err {err:.1f} mm{flag}")
            write({"t": time.time(), "cmd": cmd, "target": target, "pose": reached, "joints": joints,
                   "gripper": g, "err_mm": round(err, 2)})
            drop_buffered_keys()
    except BaseException:
        await arm.stop()
        raise
    finally:
        log.close()
        await robot.close()


if __name__ == "__main__":
    asyncio.run(main())
