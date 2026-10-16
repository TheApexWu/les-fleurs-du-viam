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
import math
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
        self.in_vase: list[G.PlacedStem] = []

    # ── primitives ─────────────────────────────────────────────────────────
    async def grip(self, width: int):
        # Width goes through the arm's DoCommand (checked 16 Oct: the gripper component returns
        # nothing for get_gripper), so stems are held at a set width, not grab()'s full force.
        await self.arm.do_command({"setup_gripper": True, "move_gripper": float(width)})

    async def gripper_width(self) -> float:
        return (await self.arm.do_command({"get_gripper": True}))["gripper_position"]

    async def speed(self, fast: bool):
        await self.arm.do_command({"set_speed": K.FAST_DEG_S if fast else K.SLOW_DEG_S})

    async def setup(self):
        await self.arm.do_command({"set_acceleration": K.ACCEL_DEG_S2})
        await self.arm.do_command({"set_gripper_speed": K.GRIP_SPEED})
        await self.speed(fast=True)

    def hub(self) -> G.P:
        return G.P(K.VASE["x"], K.VASE["y"], K.TRAVEL_Z, theta=K.WRIST_DEG)

    def obstacles(self):
        """Vase plus placed stems as boxes, so the planner routes around them (Viam 101, WorldState)."""
        vc, vd = K.VASE_BOX["center"], K.VASE_BOX["dims"]
        geoms = [GeometriesInFrame(reference_frame="world", geometries=[Geometry(
            center=Pose(x=vc[0], y=vc[1], z=vc[2], o_z=1.0),
            box=RectangularPrism(dims_mm=Vector3(x=vd[0], y=vd[1], z=vd[2])), label="vase")])]
        for i, ps in enumerate(self.in_vase):
            lo, hi = G.above_rim(ps, K.VASE["rim_z"])
            d = [hi[k] - lo[k] for k in range(3)]
            n = math.sqrt(sum(v * v for v in d)) or 1.0
            mid = Pose(x=(lo[0] + hi[0]) / 2, y=(lo[1] + hi[1]) / 2, z=(lo[2] + hi[2]) / 2,
                       o_x=d[0] / n, o_y=d[1] / n, o_z=d[2] / n)
            w, b = ps.stem.stem_mm + 10, ps.stem.bloom_mm + 10
            geoms.append(GeometriesInFrame(reference_frame="world", geometries=[
                Geometry(center=mid, box=RectangularPrism(dims_mm=Vector3(x=w, y=w, z=n)), label=f"vase-stem-{i}"),
                Geometry(center=Pose(x=hi[0], y=hi[1], z=hi[2], o_z=1.0),
                         box=RectangularPrism(dims_mm=Vector3(x=b, y=b, z=b)), label=f"bloom-{i}")]))
        for i, (pl, h) in enumerate(self.placed):
            ken = K.taught()["kenzan"]
            center, dims = G.stem_obstacle((ken["x"], ken["y"], ken["z"]), pl.x, pl.y,
                                           pl.tilt_deg, pl.azimuth_deg, h)
            geoms.append(GeometriesInFrame(reference_frame="world", geometries=[Geometry(
                center=pose(center), box=RectangularPrism(dims_mm=Vector3(x=dims[0], y=dims[1], z=dims[2])),
                label=f"stem-{i}")]))
        return WorldState(obstacles=geoms)

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

    async def grip_calibrate(self):
        """Close in small steps on a stem held in the open fingers; the width where the fingers
        stop following the command is the stem. Suggests GRIP_STEM a little inside that."""
        await self.arm.do_command({"set_gripper_speed": K.GRIP_SPEED})
        await self.grip(K.GRIP_OPEN)
        for w in range(K.GRIP_OPEN, 0, -20):
            await self.grip(w)
            got = await self.gripper_width()
            if got - w > 15:
                print(f"contact at {got:.0f}; set GRIP_STEM = {got - 10:.0f} in config.py")
                return
        print("closed fully: nothing between the fingers?")

    async def pick(self, slot):
        s = K.taught()[f"slot{slot}"]
        at = G.P(s["x"], s["y"], s["z"], theta=K.WRIST_DEG)
        above = G.P(s["x"], s["y"], s["z"] + K.LIFT_MM, theta=K.WRIST_DEG)
        await self.grip(K.GRIP_OPEN)
        await self.speed(fast=True)
        await self.move(above)
        await self.speed(fast=False)
        await self.move(at, straight=True)
        await self.grip(K.GRIP_STEM)
        if await self.gripper_width() < K.GRIP_EMPTY_MAX:
            await self.grip(K.GRIP_OPEN)
            await self.move(above, straight=True)
            raise RuntimeError(f"slot {slot}: fingers closed on nothing")
        await self.move(above, straight=True)
        await self.speed(fast=True)

    async def drop(self, lean_az=0.0, tilt=15.0):
        """Hub -> along the stem axis to just above the rim -> release -> back out -> hub."""
        pre, at = G.vase_drop_poses((K.VASE["x"], K.VASE["y"]), K.VASE["rim_z"], K.VASE["rim_r"],
                                    lean_az, tilt, K.WRIST_DEG, grip_above_rim_mm=K.RELEASE_ABOVE_RIM_MM,
                                    min_grip_z=(K.VASE_FLOOR_Z + K.VASE_STEM_BELOW_GRIP_MM + 20)
                                    if K.VASE_FLOOR_Z is not None else float("-inf"))
        await self.move(self.hub())
        await self.move(pre)
        await self.speed(fast=False)
        await self.move(at, straight=True)
        await self.grip(K.GRIP_STEM + K.GRIP_RELEASE_MARGIN)
        await self.move(pre, straight=True)
        await self.speed(fast=True)
        await self.move(self.hub())

    def best_lean(self, stem: G.Stem) -> tuple[float, float]:
        """Lean direction whose settled stem, bloom and release gripper stay furthest from what's
        already in the vase. Returns (azimuth, clearance mm)."""
        v = K.VASE
        scored = []
        for az in K.LEAN_CANDIDATES_DEG:
            new = G.settle(stem, (v["x"], v["y"]), v["rim_z"], v["rim_r"], K.VASE_DEPTH_MM, az)
            _, at = G.vase_drop_poses((v["x"], v["y"]), v["rim_z"], v["rim_r"], az, new.tilt_deg, K.WRIST_DEG,
                                      grip_above_rim_mm=K.RELEASE_ABOVE_RIM_MM)
            scored.append((G.clearance(new, (at.x, at.y, at.z), self.in_vase, v["rim_z"]), az))
        gap, az = max(scored)
        return az, gap

    async def vase_one(self, slot=0, lean_az=None):
        """One stem from slot into the vase. With no lean given, takes the roomiest direction."""
        stem = G.Stem(**K.STEMS[int(slot)])
        if lean_az is None:
            lean_az, gap = self.best_lean(stem)
            print(f"lean {lean_az:.0f} deg, clearance {gap:.0f} mm")
            if gap < K.MIN_CLEARANCE_MM:
                raise RuntimeError(f"no lean direction leaves {K.MIN_CLEARANCE_MM:.0f} mm; vase is full")
        v = K.VASE
        tilt = G.settled_tilt(K.VASE_DEPTH_MM, v["rim_r"], 0.6)
        await self.setup()
        await self.pick(slot)
        await self.drop(float(lean_az), tilt)
        self.in_vase.append(G.settle(stem, (v["x"], v["y"]), v["rim_z"], v["rim_r"], K.VASE_DEPTH_MM, float(lean_az)))

    async def fill(self, n=3):
        """n stems in a row, each in the roomiest direction, each an obstacle for the next."""
        for slot in range(int(n)):
            await self.vase_one(slot)

    async def go_hub(self):
        await self.setup()
        await self.move(self.hub())

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
         ("resources", "teach", "grip_test", "grip_calibrate", "pick", "go_hub", "vase_one", "fill",
          "insert_one", "sogetsu", "photo", "say")}


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
