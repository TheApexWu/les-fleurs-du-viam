"""The robot. One class, one word per step, same shape as Viam 101's palletizer.

  python flowers.py resources         list what the machine exposes (first, safe call)
  python flowers.py teach slot0       record the gripper's current pose under a name
  python flowers.py grip_test         open, close to GRIP_STEM, report the width
  python flowers.py pick 0            pick the stem in tray slot 0 and lift it
  python flowers.py insert_one        pick slot 0 and insert it straight down (milestone 1)
  python flowers.py sogetsu           three-line arrangement from taught slots (milestone 2)
  python flowers.py photo             save photo.jpg from the wrist camera
  python flowers.py say gratitude     plan -> arrange -> critique -> one edit (milestone 4)

Bring-up order matters: resources, teach, grip_test, pick, insert_one. Do not skip ahead.
Lines marked VERIFY use an SDK call not checked against the real machine yet.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

from viam.components.arm import Arm
from viam.components.camera import Camera
from viam.proto.common import (Geometry, GeometriesInFrame, Pose, PoseInFrame,
                               RectangularPrism, Vector3, WorldState)
from viam.proto.service.motion import Constraints, LinearConstraint  # VERIFY import path
from viam.robot.client import RobotClient
from viam.services.motion import MotionClient

import ai
import composition as C
import config as K
import geometry as G


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
        self.placed = []   # (Placement, stem height mm) of stems already in the kenzan

    # ── primitives ─────────────────────────────────────────────────────────
    async def grip(self, width: int):
        # The xArm gripper takes a width through the arm's DoCommand, so stems are held at a set
        # width instead of grab() closing as hard as it can. VERIFY: on the arm vs gripper component.
        await self.arm.do_command({"setup_gripper": True, "move_gripper": float(width)})

    def obstacles(self):
        """Placed stems as boxes, so the planner routes around them (Viam 101, WorldState)."""
        ken = K.taught()["kenzan"]
        geoms = []
        for i, (pl, h) in enumerate(self.placed):
            center, dims = G.stem_obstacle((ken["x"], ken["y"], ken["z"]), pl.x, pl.y,
                                           pl.tilt_deg, pl.azimuth_deg, h)
            geoms.append(GeometriesInFrame(reference_frame="world", geometries=[Geometry(
                center=pose(center), box=RectangularPrism(dims_mm=Vector3(x=dims[0], y=dims[1], z=dims[2])),
                label=f"stem-{i}")]))
        return WorldState(obstacles=geoms) if geoms else None

    async def move(self, p, straight=False):
        constraints = (Constraints(linear_constraint=[LinearConstraint(line_tolerance_mm=2.0)])
                       if straight else None)
        return await self.motion.move(component_name=K.GRIPPER,
                                      destination=PoseInFrame(reference_frame="world", pose=pose(p)),
                                      world_state=self.obstacles(), constraints=constraints)

    # ── steps ──────────────────────────────────────────────────────────────
    async def resources(self):
        for n in sorted(r.name for r in self.robot.resource_names):
            print(" ", n)

    async def teach(self, name):
        """Record the current end pose. Jog or freedrive the arm into place first."""
        p = await self.arm.get_end_position()  # VERIFY: arm base frame vs world, and gripper TCP offset
        data = K.taught()
        data[name] = {"x": p.x, "y": p.y, "z": p.z, "o_x": p.o_x, "o_y": p.o_y, "o_z": p.o_z, "theta": p.theta}
        K.TAUGHT.write_text(json.dumps(data, indent=2))
        print(f"taught {name}: {data[name]}")

    async def grip_test(self):
        await self.grip(K.GRIP_OPEN)
        await self.grip(K.GRIP_STEM)
        print(await self.arm.do_command({"get_gripper": True}))

    async def pick(self, slot):
        s = K.taught()[f"slot{slot}"]
        above = G.P(s["x"], s["y"], s["z"] + K.LIFT_MM)
        await self.grip(K.GRIP_OPEN)
        await self.move(above)
        await self.move(G.P(s["x"], s["y"], s["z"]), straight=True)
        await self.grip(K.GRIP_STEM)
        await self.move(above, straight=True)

    async def place(self, pl: C.Placement, stem_height_mm=250.0):
        ken = K.taught()["kenzan"]
        pre, ins = G.insertion_poses((ken["x"], ken["y"], ken["z"]), pl.x, pl.y, pl.tilt_deg,
                                     pl.azimuth_deg, K.STEM_BELOW_GRIP_MM, K.INSERT_DEPTH_MM, K.APPROACH_MM)
        await self.pick(pl.slot)
        await self.move(pre)                  # 1) over the target, along the stem's axis
        await self.move(ins, straight=True)   # 2) straight push into the pins
        await self.grip(K.GRIP_OPEN)
        await self.move(pre, straight=True)   # 3) back out the way it came
        self.placed.append((pl, stem_height_mm))

    async def insert_one(self):
        await self.place(C.Placement(role="test", slot=0, x=0, y=0, tilt_deg=0, azimuth_deg=0))

    async def arrange(self, placements):
        for pl in placements:
            print(f"  {pl.role:6s} slot {pl.slot} tilt {pl.tilt_deg:.0f} (wanted {pl.intended_tilt_deg:.0f}) az {pl.azimuth_deg:.0f}")
            await self.place(pl)

    async def sogetsu(self):
        await self.arrange(C.sogetsu_basic({"shin": 0, "soe": 1, "hikae": 2}))

    async def photo(self, path="photo.jpg"):
        p = K.taught().get("photo")
        if p:
            await self.move(G.P(**p))
        cam = Camera.from_robot(self.robot, K.CAMERA)
        images, _ = await cam.get_images()   # VERIFY: return shape (list of NamedImage + metadata)
        Path(path).write_bytes(images[0].data)
        print("saved", path)
        return path

    async def say(self, sentiment):
        plan = ai.plan(sentiment, inventory=ai.load_inventory())
        await self.arrange(C.from_params(plan["stems"]))
        verdict = ai.critique(await self.photo())
        print("critic:", verdict)
        edit = verdict.get("edit") or {}
        if verdict.get("guess") != sentiment and edit.get("slot") is not None:
            print("applying one edit:", edit)   # pull-and-reinsert is a later step; log it for now


STEPS = {name: getattr(FlowerBot, name) for name in
         ("resources", "teach", "grip_test", "pick", "insert_one", "sogetsu", "photo", "say")}


async def main(verb, *args):
    robot = await connect()
    try:
        step = STEPS.get(verb)
        if step is None:
            print("steps:", ", ".join(STEPS)); return
        bot = FlowerBot(robot)
        await step(bot, *[int(a) if a.isdigit() else a for a in args])
    finally:
        await robot.close()


if __name__ == "__main__":
    asyncio.run(main(*(sys.argv[1:] or ["resources"])))
