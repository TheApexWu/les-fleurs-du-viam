"""Replay the marked moments (M) of one teleop session, in order.

  python replay.py recordings/teleop-<time>.jsonl [base_offset_deg]

Each mark is a pose already reached safely by hand; the risk is the straight joint-space path between
two marks, so the first run is slow with someone at the stop button. base_offset_deg swings the whole
demo about the base, e.g. to reach a rose further along the table.
"""
import asyncio
import json
import sys

from viam.components.arm import Arm
from viam.proto.component.arm import JointPositions

import config as K
from flowers import connect


async def main(log_path, offset_deg=0.0):
    marks = [r for r in map(json.loads, open(log_path)) if "mark" in r]
    if not marks:
        sys.exit(f"no marks in {log_path}: press M at each key moment while driving")
    robot = await connect()
    arm = Arm.from_robot(robot, K.ARM)
    try:
        for m in marks:
            j = m["joints"]
            await arm.move_to_joint_positions(JointPositions(values=[j[0] + offset_deg] + j[1:]))
            await arm.do_command({"setup_gripper": True, "move_gripper": float(m["gripper"])})
            print(f"{m['mark']}: done")
    except BaseException:
        await arm.stop()
        raise
    finally:
        await robot.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 0.0))
