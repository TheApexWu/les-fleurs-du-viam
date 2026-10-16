"""Robot steps that use the motion planner. Driving by hand is teleop.py / dashboard.py; replay is replay.py.

  python flowers.py resources              list what the machine exposes
  python flowers.py teach <name>           save the current pose under a name
  python flowers.py plan_check x y z       would the gripper (pointing down) get there? never moves
  python flowers.py photo                  move to the taught "photo" pose, save photo.jpg, ask the critic
"""
import asyncio
import json
import os
import sys
from dataclasses import dataclass

from google.protobuf import json_format
from viam.components.arm import Arm
from viam.components.camera import Camera
from viam.proto.common import Geometry, GeometriesInFrame, Pose, PoseInFrame, RectangularPrism, Vector3, WorldState
from viam.proto.service.motion import MoveRequest
from viam.robot.client import RobotClient
from viam.services.motion import MotionClient

import config as K


@dataclass
class P:
    x: float
    y: float
    z: float
    o_x: float = 0.0
    o_y: float = 0.0
    o_z: float = -1.0
    theta: float = 0.0


async def connect() -> RobotClient:
    opts = RobotClient.Options.with_api_key(api_key=os.environ["VIAM_API_KEY"],
                                            api_key_id=os.environ["VIAM_API_KEY_ID"])
    return await RobotClient.at_address(os.environ["VIAM_ADDRESS"], opts)


def pose(p) -> Pose:
    return Pose(x=p.x, y=p.y, z=p.z, o_x=p.o_x, o_y=p.o_y, o_z=p.o_z, theta=p.theta)


class FlowerBot:
    def __init__(self, robot: RobotClient):
        self.robot = robot
        self.arm = Arm.from_robot(robot, K.ARM)
        self.motion = MotionClient.from_robot(robot, K.MOTION)

    def obstacles(self) -> WorldState:
        c, d = K.VASE_BOX["center"], K.VASE_BOX["dims"]
        return WorldState(obstacles=[GeometriesInFrame(reference_frame="world", geometries=[Geometry(
            center=Pose(x=c[0], y=c[1], z=c[2], o_z=1.0),
            box=RectangularPrism(dims_mm=Vector3(x=d[0], y=d[1], z=d[2])), label="vase-measured")])])

    async def plan(self, destination: PoseInFrame) -> dict:
        """Plan without moving (builtin motion DoCommand "plan", rdk v1.12.0). Raises if there is no full plan
        or the planner hasn't answered within PLAN_TIMEOUT_S (it searched >200 s for some poses on 16 Oct)."""
        req = MoveRequest(name=K.MOTION, component_name=K.GRIPPER, destination=destination,
                          world_state=self.obstacles())
        res = await self.motion.do_command({"plan": json_format.MessageToJson(req)}, timeout=K.PLAN_TIMEOUT_S)
        if "plan_partialwp" in res:
            raise RuntimeError(f"plan only reaches waypoint {res['plan_partialwp']}")
        return res

    async def move(self, p: P):
        dest = PoseInFrame(reference_frame="world", pose=pose(p))
        if K.PLAN_CHECK:
            await self.plan(dest)  # a refusal raises here, before anything moves
        await self.motion.move(component_name=K.GRIPPER, destination=dest, world_state=self.obstacles())

    # ── steps ──────────────────────────────────────────────────────────────
    async def resources(self):
        for n in sorted(r.name for r in self.robot.resource_names):
            print(" ", n)

    async def teach(self, name):
        p = await self.arm.get_end_position()
        data = K.taught()
        data[name] = {k: getattr(p, k) for k in ("x", "y", "z", "o_x", "o_y", "o_z", "theta")}
        K.TAUGHT.write_text(json.dumps(data, indent=2))
        print(f"taught {name}: {data[name]}")

    async def plan_check(self, *xyz):
        x, y, z = (float(v) for v in xyz)
        try:
            res = await self.plan(PoseInFrame(reference_frame="world", pose=pose(P(x, y, z, theta=K.WRIST_DEG))))
            print(f"plan OK to ({x:.0f}, {y:.0f}, {z:.0f}): {len(res.get('plan') or [])} steps")
        except Exception as e:  # noqa: BLE001 - report, never move
            print(f"no plan to ({x:.0f}, {y:.0f}, {z:.0f}): {type(e).__name__}: {str(e)[:160]}")

    async def photo(self, path="photo.jpg"):
        if p := K.taught().get("photo"):
            await self.move(P(**p))
        imgs, _ = await Camera.from_robot(self.robot, K.CAMERA).get_images(filter_source_names=["color"])
        with open(path, "wb") as f:
            f.write(imgs[0].data)
        import ai
        print("saved", path, "| critic:", ai.critique(path))


STEPS = {name: getattr(FlowerBot, name) for name in ("resources", "teach", "plan_check", "photo")}


async def main(verb="resources", *args):
    if verb not in STEPS:
        print("steps:", ", ".join(STEPS))
        return
    robot = await connect()
    try:
        await STEPS[verb](FlowerBot(robot), *args)
    finally:
        await robot.close()


if __name__ == "__main__":
    asyncio.run(main(*sys.argv[1:]))
