"""Background recorder for hand-guided teaching: pose + joints at up to 5x/s, and a
snapshot (pose + one camera frame) wherever the arm rests.

  python recorder.py                          run while moving the arm in manual mode
  python recorder.py promote p3 slot0         copy a snapshot into taught_poses.json
  python recorder.py promote p3 slot0 --down 90   same, but exactly vertical with wrist at 90°

Read-only on the robot. Each run writes recordings/<start time>/: trace.csv
and p<N>.jpg per snapshot. Snapshots also go to auto_poses.json so numbering continues across runs.
"""
import asyncio
import csv
import json
import math
import sys
import time
from pathlib import Path

import config as K

ROOT = Path(__file__).parent
SNAPS = ROOT / "auto_poses.json"
POSE_HZ, MOVE_MM, STILL_MM, STILL_S, IDLE_STOP_S = 5, 20.0, 3.0, 1.0, 20.0
FIELDS = ("x", "y", "z", "o_x", "o_y", "o_z", "theta")


def dist(a, b):
    return math.dist((a["x"], a["y"], a["z"]), (b["x"], b["y"], b["z"]))


async def record():
    from viam.components.arm import Arm
    from viam.components.camera import Camera
    from flowers import connect
    robot = await connect()
    arm, cam = Arm.from_robot(robot, K.ARM), Camera.from_robot(robot, K.CAMERA)
    run = ROOT / "recordings" / time.strftime("%Y%m%d-%H%M%S")
    run.mkdir(parents=True)
    snaps = json.loads(SNAPS.read_text()) if SNAPS.exists() else {}

    async def reconnect():
        nonlocal robot, arm, cam
        try:
            await robot.close()
        except Exception:  # noqa: BLE001 - the old link is already dead
            pass
        await asyncio.sleep(1)
        robot = await connect()
        arm, cam = Arm.from_robot(robot, K.ARM), Camera.from_robot(robot, K.CAMERA)

    async def snapshot_frame(name):
        imgs, _ = await cam.get_images()
        jpg = next((i.data for i in imgs if i.mime_type == "image/jpeg"), None)
        if jpg:
            (run / f"{name}.jpg").write_bytes(jpg)

    async def poses():
        last_snap = still_since = prev = start = None
        moved = False
        n, t0 = 0, time.time()
        with (run / "trace.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(("t",) + FIELDS + tuple(f"j{i}" for i in range(1, 7)))
            while True:
                tick = time.time()
                try:
                    p, j = await asyncio.gather(arm.get_end_position(), arm.get_joint_positions())
                except Exception as e:  # noqa: BLE001 - the WebRTC link drops now and then; reconnect, don't die
                    print(f"  link lost ({type(e).__name__}), reconnecting")
                    f.flush()
                    await reconnect()
                    continue
                cur = {k: getattr(p, k) for k in FIELDS}
                start = start or cur
                moved = moved or dist(cur, start) > MOVE_MM
                w.writerow([round(time.time(), 3)] + [round(cur[k], 3) for k in FIELDS]
                           + [round(v, 2) for v in j.values])
                n += 1
                if n % 50 == 0:
                    f.flush()
                    print(f"  {n / (time.time() - t0):.1f} samples/s")
                still_since = (still_since or time.time()) if prev and dist(cur, prev) < STILL_MM else None
                parked = still_since and time.time() - still_since >= STILL_S
                if parked and (last_snap is None or dist(cur, last_snap) > MOVE_MM):
                    name = f"p{len(snaps) + 1}"
                    snaps[name] = cur
                    SNAPS.write_text(json.dumps(snaps, indent=2))
                    await snapshot_frame(name)
                    last_snap = cur
                    print(f"{name}: x={cur['x']:.0f} y={cur['y']:.0f} z={cur['z']:.0f} o_z={cur['o_z']:.2f} theta={cur['theta']:.0f}")
                prev = cur
                # The xArm state code doesn't expose manual mode, so a long rest after moving stands in for "done".
                if moved and still_since and time.time() - still_since >= IDLE_STOP_S:
                    print(f"no movement for {IDLE_STOP_S:.0f}s, stopping")
                    return
                await asyncio.sleep(max(0.0, 1 / POSE_HZ - (time.time() - tick)))

    print(f"recording to {run}; Ctrl-C to stop")
    try:
        await poses()
    finally:
        await robot.close()


def promote(snap, name, down_theta=None):
    """Hand-guided orientation is a few degrees off; --down keeps the taught position and
    sets the gripper exactly vertical with a shared wrist angle, so moves don't twist."""
    pose = json.loads(SNAPS.read_text())[snap]
    if down_theta is not None:
        pose.update(o_x=0.0, o_y=0.0, o_z=-1.0, theta=down_theta)
    taught = K.taught()
    taught[name] = pose
    K.TAUGHT.write_text(json.dumps(taught, indent=2))
    print(f"{snap} -> {name}: x={pose['x']:.0f} y={pose['y']:.0f} z={pose['z']:.0f} "
          f"o=({pose['o_x']:.2f},{pose['o_y']:.2f},{pose['o_z']:.2f}) theta={pose['theta']:.0f}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["promote"]:
        down = float(sys.argv[sys.argv.index("--down") + 1]) if "--down" in sys.argv else None
        promote(sys.argv[2], sys.argv[3], down)
    else:
        asyncio.run(record())
