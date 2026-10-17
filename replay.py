"""Replay the marked moments (M) of one teleop session, in order.

  python replay.py recordings/teleop-<time>.jsonl [base_offset_deg]

Each mark is a pose already reached safely by hand; the risk is the straight joint-space path between
two marks, so it runs at REPLAY_DEG_S and waits for Enter with a hand on the stop button.
base_offset_deg swings only the pick marks about the base, to reach a rose further along the table;
marks labelled with "vase" or "release" (and everything after the first of them) stay where they were
taught, so the stem still goes into the vase. Every offset pose is checked against the teleop limits.
"""
import asyncio
import json
import os
import sys

from viam.components.arm import Arm
from viam.proto.component.arm import JointPositions

import config as K
import fleurs_core as core
from flowers import connect

core.configure(vase=K.VASE, table_top_z=K.TABLE_TOP_Z)
REPLAY_DEG_S = float(os.environ.get("REPLAY_DEG_S", 15))


def offsets(marks, offset_deg):
    """Offset per mark: offset_deg up to the first vase/release mark, then 0."""
    out, reached_vase = [], False
    for m in marks:
        reached_vase = reached_vase or any(w in m["mark"].lower() for w in ("vase", "release"))
        out.append(0.0 if reached_vase else offset_deg)
    return out


def check(marks, offs):
    for m, d in zip(marks, offs):
        if d:
            p = m["pose"]
            ok, why = core.arc_ok(p["x"], p["y"], p["z"], d)
            if not ok:
                return f"mark '{m['mark']}' with offset {d:+.0f} deg: {why}"
    return ""


async def main(log_path, offset_deg=0.0):
    marks = [r for r in map(json.loads, open(log_path)) if "mark" in r]
    if not marks:
        sys.exit(f"no marks in {log_path}: press M at each key moment while driving")
    offs = offsets(marks, offset_deg)
    if why := check(marks, offs):
        sys.exit(f"refused: {why}")
    print("\n".join(f"  {m['mark']}: base offset {d:+.0f} deg" for m, d in zip(marks, offs)))
    input(f"{len(marks)} marks at {REPLAY_DEG_S:.0f} deg/s. Hand on the stop button, then press Enter. ")
    robot = await connect()
    arm = Arm.from_robot(robot, K.ARM)
    try:
        await arm.do_command({"set_speed": REPLAY_DEG_S})
        for m, d in zip(marks, offs):
            j = m["joints"]
            await arm.move_to_joint_positions(JointPositions(values=[j[0] + d] + j[1:]))
            await arm.do_command({"setup_gripper": True, "move_gripper": float(m["gripper"])})
            print(f"{m['mark']}: done")
    except BaseException:
        await arm.stop()
        raise
    finally:
        await robot.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 0.0))
