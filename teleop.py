"""Keyboard teleop for the arm, logging every move so a demonstration can be replayed later.

  python teleop.py            terminal version; dashboard.py is the browser version of the same thing

  W/S  x +/-        A/D  y +/-        R/F  z +/-        Q/E  wrist spin -/+ 5 deg
  J/L  swing the whole arm about its base: J toward +y, L toward -y (10 deg, 2 deg in fine mode)
  O/C  gripper open/close a step      G  gripper to GRIP_STEM (gentle hold)
  Tab  step 20 mm <-> 5 mm            M  mark this moment with a label
  Space  stop                         X  quit

Every key is one move: read the pose, add the step, check the limits, move, read back. Keys arriving
while a move runs are refused, so a held key can't queue moves that keep going after release.
Each line of recordings/teleop-<time>.jsonl holds the command and the pose and joints actually reached.
A continuous trace (pose, joints, gripper, ~5x/s, also during moves) goes to recordings/teleop-<time>-trace.csv.
"""
import asyncio
import csv
import json
import math
import sys
import time
from pathlib import Path

import config as K

STEPS_MM = (20.0, 5.0)
BASE_STEPS_DEG = (10.0, 2.0)
SPIN_DEG = 5.0
GRIP_STEP = 50
ACCURACY_MM = 2.0
TELEOP_DEG_S = 15.0
TRACE_HZ = 5.0
FIELDS = ("x", "y", "z", "o_x", "o_y", "o_z", "theta")

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


def swing(x: float, y: float, d_deg: float) -> tuple[float, float]:
    """Where the fingertip lands when joint 1 turns by d_deg: the base axis is the world z axis."""
    a = math.radians(d_deg)
    return x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)


def arc_ok(x: float, y: float, z: float, d_deg: float) -> tuple[bool, str]:
    """Check every degree of a base swing, not just its end: the arc can cross the vase."""
    n = max(1, int(abs(d_deg)))
    for i in range(1, n + 1):
        ok, why = clamp_ok(*swing(x, y, d_deg * i / n), z)
        if not ok:
            return False, f"swing {d_deg * i / n:+.0f} deg: {why}"
    return True, ""


class Jogger:
    """One arm, one log, one move at a time. Shared by the terminal and the dashboard."""

    def __init__(self, arm):
        self.arm = arm
        self.step_i = 0
        self.busy = asyncio.Lock()
        path = Path(__file__).parent / "recordings" / f"teleop-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
        path.parent.mkdir(exist_ok=True)
        self.log_path, self.log = path, path.open("a")
        self.trace_path = path.with_name(path.stem + "-trace.csv")
        self.last = {}
        self.latest = None  # newest trace sample, so the dashboard reads state without extra robot calls
        self._trace_task = None

    async def start(self):
        await self.arm.do_command({"set_speed": TELEOP_DEG_S})
        await self.arm.do_command({"set_gripper_speed": K.GRIP_SPEED})
        self._trace_task = asyncio.create_task(self._trace())

    async def _trace(self):
        """Continuous record of where the arm is, including mid-move, independent of key presses."""
        with self.trace_path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(("t", "busy") + FIELDS + tuple(f"j{i}" for i in range(1, 7)) + ("gripper",))
            n = 0
            while True:
                tick = time.time()
                try:
                    pose, joints, g = await self.snapshot()
                except Exception as e:  # noqa: BLE001 - a dropped read must not end the recording
                    w.writerow((round(tick, 3), "read_failed", type(e).__name__))
                    await asyncio.sleep(1.0)
                    continue
                self.latest = {"pose": pose, "joints": joints, "gripper": g, "t": tick}
                w.writerow([round(tick, 3), int(self.busy.locked())] + [pose[k] for k in FIELDS] + joints + [g])
                n += 1
                if n % 25 == 0:
                    f.flush()
                await asyncio.sleep(max(0.0, 1 / TRACE_HZ - (time.time() - tick)))

    def close(self):
        if self._trace_task:
            self._trace_task.cancel()
        self.log.close()

    def write(self, entry):
        self.log.write(json.dumps(dict(entry, t=round(time.time(), 3))) + "\n")
        self.log.flush()

    async def snapshot(self):
        p, j = await asyncio.gather(self.arm.get_end_position(), self.arm.get_joint_positions())
        g = (await self.arm.do_command({"get_gripper": True})).get("gripper_position")
        pose = {k: round(getattr(p, k), 3) for k in ("x", "y", "z", "o_x", "o_y", "o_z", "theta")}
        return pose, [round(v, 3) for v in j.values], g

    async def stop(self) -> str:
        await self.arm.stop()  # never waits for the lock: stop must always get through
        self.write({"cmd": "stop"})
        return "STOP"

    async def handle(self, key: str, label: str = "") -> str:
        """Run one key. Returns a one-line message for the operator."""
        key = key.lower()
        if key == " ":
            return await self.stop()
        if key == "\t":
            self.step_i = 1 - self.step_i
            return f"step {STEPS_MM[self.step_i]:.0f} mm"
        if self.busy.locked():
            return "busy: previous move still running, key ignored"
        async with self.busy:
            try:
                return await self._run(key, label)
            except Exception as e:  # noqa: BLE001 - e.g. an unreachable target; stop, log, keep the session
                await self.arm.stop()
                self.write({"cmd": {"key": key}, "error": f"{type(e).__name__}: {e}"[:300]})
                return f"error, arm stopped: {type(e).__name__}: {str(e)[:120]}"

    async def _run(self, key: str, label: str) -> str:
        from viam.proto.common import Pose
        pose, joints, g = await self.snapshot()
        if key in MOVES:
            d = [c * STEPS_MM[self.step_i] for c in MOVES[key]]
            target = dict(pose, x=pose["x"] + d[0], y=pose["y"] + d[1], z=pose["z"] + d[2])
            ok, why = clamp_ok(target["x"], target["y"], target["z"])
            if not ok:
                self.write({"cmd": {"key": key, "delta": d}, "refused": why, "pose": pose})
                return f"refused: {why}"
            cmd = {"key": key, "delta": d}
        elif key in ("j", "l"):
            from viam.proto.component.arm import JointPositions
            d = BASE_STEPS_DEG[self.step_i] * (1 if key == "j" else -1)
            ok, why = arc_ok(pose["x"], pose["y"], pose["z"], d)
            if not ok:
                self.write({"cmd": {"key": key, "d_base_deg": d}, "refused": why, "pose": pose})
                return f"refused: {why}"
            tx, ty = swing(pose["x"], pose["y"], d)
            target = dict(pose, x=tx, y=ty)
            await self.arm.move_to_joint_positions(JointPositions(values=[joints[0] + d] + joints[1:]))
            reached, joints, g = await self.snapshot()
            err = math.dist((tx, ty, pose["z"]), (reached["x"], reached["y"], reached["z"]))
            self.write({"cmd": {"key": key, "d_base_deg": d}, "target": target, "pose": reached,
                        "joints": joints, "gripper": g, "err_mm": round(err, 2)})
            self.last = {"pose": reached, "gripper": g, "err_mm": round(err, 2)}
            flag = "  <-- off predicted arc" if err > ACCURACY_MM else ""
            return (f"{key}: base {d:+.0f} deg -> x={reached['x']:.0f} y={reached['y']:.0f} z={reached['z']:.0f}"
                    f"  err {err:.1f} mm{flag}")
        elif key in ("q", "e"):
            target = dict(pose, theta=pose["theta"] + (SPIN_DEG if key == "e" else -SPIN_DEG))
            cmd = {"key": key, "d_theta": target["theta"] - pose["theta"]}
        elif key in ("o", "c", "g"):
            width = K.GRIP_STEM if key == "g" else (g or 0) + (GRIP_STEP if key == "o" else -GRIP_STEP)
            width = float(max(0, min(850, width)))
            await self.arm.do_command({"setup_gripper": True, "move_gripper": width})
            pose, joints, g2 = await self.snapshot()
            self.write({"cmd": {"key": key, "gripper_target": width}, "pose": pose, "joints": joints, "gripper": g2})
            self.last = {"pose": pose, "gripper": g2}
            return f"gripper {g:.0f} -> {g2:.0f}"
        elif key == "m":
            self.write({"mark": label.strip(), "pose": pose, "joints": joints, "gripper": g})
            return f"marked '{label.strip()}' at x={pose['x']:.0f} y={pose['y']:.0f} z={pose['z']:.0f}"
        else:
            return f"unknown key {key!r}"

        await self.arm.move_to_position(Pose(**target))
        reached, joints, g = await self.snapshot()
        err = math.dist((target["x"], target["y"], target["z"]), (reached["x"], reached["y"], reached["z"]))
        self.write({"cmd": cmd, "target": target, "pose": reached, "joints": joints, "gripper": g,
                    "err_mm": round(err, 2)})
        self.last = {"pose": reached, "gripper": g, "err_mm": round(err, 2)}
        flag = "  <-- off target" if err > ACCURACY_MM else ""
        return (f"{key}: x={reached['x']:.0f} y={reached['y']:.0f} z={reached['z']:.0f} "
                f"theta={reached['theta']:.0f}  err {err:.1f} mm{flag}")


def read_key() -> str:
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


async def main():
    import termios
    from viam.components.arm import Arm
    from flowers import connect

    robot = await connect()
    jog = Jogger(Arm.from_robot(robot, K.ARM))
    try:
        await jog.start()
        print(__doc__.split("\n\n")[1])
        print(f"logging to {jog.log_path}\n")
        while True:
            key = await asyncio.to_thread(read_key)
            if key.lower() in ("x", "\x03"):
                break
            label = await asyncio.to_thread(input, "label for this moment: ") if key.lower() == "m" else ""
            print(await jog.handle(key, label))
            termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)  # drop keys pressed during the move
    except BaseException:
        await jog.arm.stop()
        raise
    finally:
        jog.close()
        await robot.close()


if __name__ == "__main__":
    asyncio.run(main())
