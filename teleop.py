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
import sys

import config as K

import fleurs_core as core

core.configure(vase=K.VASE, table_top_z=K.TABLE_TOP_Z, grip_speed=K.GRIP_SPEED, grip_stem=K.GRIP_STEM)
from fleurs_core import *  # noqa: E402,F401,F403 - re-exported for tests and the dashboard
from fleurs_core import Jogger  # noqa: E402


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
