"""Robot steps that use the motion planner. Driving by hand is teleop.py / dashboard.py; replay is replay.py.

  python flowers.py resources                 list what the machine exposes
  python flowers.py plan_check x y z           check reachability without moving
  python flowers.py pretend_loop               move through the saved flowerless path
  python flowers.py pick_and_drop              grasp one stem and release it at the vase
  python flowers.py grip_calibrate             check semantic Grab on one stem
  python flowers.py photo                      move to the taught photo pose and ask the critic

Robot motion is plan-checked first when PLAN_CHECK is enabled. The pretend-loop poses are machine-specific.
"""
import asyncio
import json
import math
import os
import sys
from dataclasses import dataclass

from google.protobuf import json_format
from viam.components.arm import Arm
from viam.components.camera import Camera
from viam.components.gripper import Gripper
from viam.proto.common import (Geometry, GeometriesInFrame, Pose, PoseInFrame,
                               RectangularPrism, Vector3, WorldState)
from viam.proto.service.motion import Constraints, LinearConstraint, MoveRequest
from viam.robot.client import RobotClient
from viam.services.motion import MotionClient

import ai
import composition as C
import config as K
import geometry as G


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


PRETEND_POSE_NAMES = (
    "pickup_approach", "pretend_grasp", "lift", "vase_approach", "pretend_release",
)
PRETEND_LOOP_SEQUENCE = (
    "pickup_approach", "pretend_grasp", "lift", "vase_approach", "pretend_release",
    "vase_approach", "lift", "pickup_approach",
)
POSE_FIELDS = ("x", "y", "z", "o_x", "o_y", "o_z", "theta")


def saved_pose(data: dict, name: str) -> G.P:
    """Return a validated world-frame pose saved by the live Viam pose capture workflow."""
    if name not in PRETEND_POSE_NAMES:
        raise ValueError(f"{name!r} is not a captured pretend-loop pose")
    raw = data.get(name)
    if not isinstance(raw, dict):
        raise ValueError(f"missing {name!r} in {K.TAUGHT}; capture it before moving")
    missing = [field for field in POSE_FIELDS if field not in raw]
    if missing:
        raise ValueError(f"{name!r} in {K.TAUGHT} is missing: {', '.join(missing)}")
    values = {}
    for field in POSE_FIELDS:
        value = raw[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{name!r}.{field} must be a finite number")
        values[field] = float(value)
    return G.P(**values)


class FlowerBot:
    def __init__(self, robot: RobotClient):
        self.robot = robot
        self.arm = Arm.from_robot(robot, K.ARM)
        self.gripper = Gripper.from_robot(robot, K.GRIPPER)
        self.motion = MotionClient.from_robot(robot, K.MOTION)
        self.placed = []
        self.in_vase: list[G.PlacedStem] = []

    # ── primitives ─────────────────────────────────────────────────────────
    async def grip(self) -> bool:
        """Close the jaws with the machine's working semantic Gripper.Grab command."""
        return await self.gripper.grab()

    async def gripper_width(self) -> float:
        return (await self.arm.do_command({"get_gripper": True}))["gripper_position"]

    async def plan(self, destination: PoseInFrame, world_state=None) -> dict:
        """Plan without moving (builtin motion DoCommand "plan", rdk v1.12.0). Raises if there is no full plan
        or the planner hasn't answered within PLAN_TIMEOUT_S (it searched >200 s for some poses on 16 Oct)."""
        req = MoveRequest(name=K.MOTION, component_name=K.GRIPPER, destination=destination,
                          world_state=world_state)
        res = await self.motion.do_command({"plan": json_format.MessageToJson(req)}, timeout=K.PLAN_TIMEOUT_S)
        if "plan_partialwp" in res:
            raise RuntimeError(f"plan only reaches waypoint {res['plan_partialwp']}")
        return res

    async def wait_gripper_idle(self, timeout_s: float = 8.0):
        """Wait for the Viam gripper action to finish before checking or moving the arm."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        while await self.gripper.is_moving():
            if loop.time() >= deadline:
                await self.gripper.stop()
                raise TimeoutError(f"gripper did not finish moving within {timeout_s:g} seconds")
            await asyncio.sleep(0.1)

    async def open_gripper(self):
        """Open via the semantic gripper API and verify the arm's reported aperture."""
        await self.gripper.open()
        await self.wait_gripper_idle()
        position = await self.gripper_width()
        min_open = K.GRIP_OPEN - 50
        if position < min_open:
            raise RuntimeError(f"gripper did not reach open position: {position:.0f} (expected at least {min_open})")

    async def speed(self, fast: bool):
        await self.arm.do_command({"set_speed": K.FAST_DEG_S if fast else K.SLOW_DEG_S})

    async def setup(self):
        await self.arm.do_command({"set_acceleration": K.ACCEL_DEG_S2})
        await self.arm.do_command({"set_gripper_speed": K.GRIP_SPEED})
        await self.speed(fast=True)

    def hub(self) -> G.P:
        return G.P(K.VASE["x"], K.VASE["y"], K.TRAVEL_Z, theta=K.WRIST_DEG)

    def obstacles(self):
        """Add dynamic stems; static obstacles (including the vase) are in the Viam config."""
        # The machine config already contributes the generic obstacle named "vase".
        # Repeating it in this request's WorldState makes the motion planner reject the
        # request because geometry names must be unique.
        geoms = []
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
        world_state = self.obstacles()
        # With no temporary stem obstacles, omit WorldState so Viam continues to plan
        # against the machine's configured table and vase obstacles.
        if not world_state.obstacles:
            world_state = None
        destination = PoseInFrame(reference_frame="world", pose=pose(p))
        if K.PLAN_CHECK:
            await self.plan(destination, world_state=world_state)
        return await self.motion.move(component_name=K.GRIPPER,
                                      destination=destination,
                                      world_state=world_state, constraints=constraints)

    # ── steps ──────────────────────────────────────────────────────────────
    async def resources(self):
        for n in sorted(r.name for r in self.robot.resource_names):
            print(" ", n)

    async def teach(self, name):
        """Record the gripper frame targeted by motion.Move, in world coordinates."""
        # The saved poses are later passed to motion.Move with component_name=K.GRIPPER.
        # Capture that same frame; Arm.GetEndPosition reports the arm/flange frame and
        # would omit the configured gripper transform (105 mm on this machine).
        p = (await self.motion.get_pose(K.GRIPPER, "world")).pose
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
    async def grip_test(self):
        """At a safe stationary pose, test semantic open/grab with one stem between the jaws."""
        await self.arm.do_command({"set_gripper_speed": K.GRIP_SPEED})
        await self.open_gripper()
        grabbed = await self.grip()
        await self.wait_gripper_idle()
        position = await self.gripper_width()
        status = await self.gripper.is_holding_something()
        print({"grab_success": grabbed, "reported_width": position,
               "is_holding_something_sensor": status.is_holding_something, "meta": status.meta})
        await self.open_gripper()

    async def grip_calibrate(self):
        """Open, run the actual semantic Grab on one stem, and report its settled aperture.

        Grab closes until it meets resistance; it does not accept a target width. The legacy
        GRIP_STEM setpoint is therefore not calibrated by sending fake width arguments.
        """
        await self.arm.do_command({"set_gripper_speed": K.GRIP_SPEED})
        await self.open_gripper()
        grabbed = await self.grip()
        await self.wait_gripper_idle()
        position = await self.gripper_width()
        status = await self.gripper.is_holding_something()
        print({"grab_success": grabbed, "reported_width": position,
               "is_holding_something_sensor": status.is_holding_something, "meta": status.meta})
        if position <= K.GRIP_EMPTY_MAX:
            print("no stem detected: jaws closed almost fully; center one stem between the fingers and retry")
        elif position > K.GRIP_MAX_STEM_WIDTH:
            print("invalid contact: jaws stopped too wide for a single stem; check the grasp pose")
        else:
            print("aperture is in the single-stem range; visually confirm the stem is held before lifting")

    async def pick(self, slot):
        s = K.taught()[f"slot{slot}"]
        at = G.P(s["x"], s["y"], s["z"], theta=K.WRIST_DEG)
        above = G.P(s["x"], s["y"], s["z"] + K.LIFT_MM, theta=K.WRIST_DEG)
        await self.open_gripper()
        await self.speed(fast=True)
        await self.move(above)
        await self.speed(fast=False)
        await self.move(at, straight=True)
        await self.grip()
        await self.wait_gripper_idle()
        width = await self.gripper_width()
        if width <= K.GRIP_EMPTY_MAX or width > K.GRIP_MAX_STEM_WIDTH:
            await self.open_gripper()
            await self.move(above, straight=True)
            raise RuntimeError(f"slot {slot}: no single stem detected (gripper width {width:.0f})")
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
        await self.open_gripper()
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

    async def move_pose(self, name):
        """Move slowly to one of the five captured pretend-loop poses; never actuate the gripper."""
        target = saved_pose(K.taught(), name)
        await self.speed(fast=False)
        print(f"moving slowly to {name}")
        await self.move(target)

    async def pretend_loop(self):
        """Traverse the captured flowerless path and return to pickup_approach without gripping."""
        data = K.taught()
        # Validate every waypoint before the first physical move, so a missing capture cannot
        # leave the robot partway through the sequence.
        targets = {name: saved_pose(data, name) for name in PRETEND_POSE_NAMES}
        await self.speed(fast=False)
        print("pretend loop: slow motion only; gripper will not open or close")
        for name in PRETEND_LOOP_SEQUENCE:
            print(f"moving to {name}")
            await self.move(targets[name])

    async def pick_and_drop(self):
        """Pick one stem at the taught grasp pose, carry it to the vase, release, and retreat.

        The flower must be placed so its stem is between the fingers at pretend_grasp. This
        uses semantic Grab/Open commands and checks the settled aperture. An empty close reads
        nearly zero; Grab's success boolean and the holding sensor alone are not proof of a stem.
        """
        data = K.taught()
        targets = {name: saved_pose(data, name) for name in PRETEND_POSE_NAMES}
        await self.setup()
        await self.speed(fast=False)
        await self.open_gripper()
        print("pick_and_drop: slow motion; gripper will open, grasp one stem, then release")

        await self.move(targets["pickup_approach"])
        await self.move(targets["pretend_grasp"])
        grabbed = await self.grip()
        await self.wait_gripper_idle()
        position = await self.gripper_width()
        status = await self.gripper.is_holding_something()
        print(f"grab result: {grabbed}; settled width: {position:.0f}; holding sensor (advisory): "
              f"{status.is_holding_something}; meta: {status.meta}")
        if position > K.GRIP_MAX_STEM_WIDTH or position <= K.GRIP_EMPTY_MAX:
            await self.open_gripper()
            await self.move(targets["pickup_approach"])
            raise RuntimeError("gripper did not confirm a single stem by aperture; "
                               "opened and retreated to pickup_approach")

        await self.move(targets["lift"])
        await self.move(targets["vase_approach"])
        await self.move(targets["pretend_release"])
        # Open fully only after reaching the final release pose; holding feedback is advisory.
        await self.open_gripper()
        status = await self.gripper.is_holding_something()
        print(f"holding sensor after full-open (advisory): {status.is_holding_something}; meta: {status.meta}")

        await self.move(targets["vase_approach"])
        await self.move(targets["lift"])
        await self.move(targets["pickup_approach"])

    async def place(self, pl: C.Placement, stem_height_mm=250.0):
        ken = K.taught()["kenzan"]
        pre, ins = G.insertion_poses((ken["x"], ken["y"], ken["z"]), pl.x, pl.y, pl.tilt_deg,
                                     pl.azimuth_deg, K.STEM_BELOW_GRIP_MM, K.INSERT_DEPTH_MM, K.APPROACH_MM)
        await self.pick(pl.slot)
        await self.move(pre)                  # 1) over the target, along the stem's axis
        await self.move(ins, straight=True)   # 2) straight push into the pins
        await self.open_gripper()
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
        if p := K.taught().get("photo"):
            await self.move(P(**p))
        imgs, _ = await Camera.from_robot(self.robot, K.CAMERA).get_images(filter_source_names=["color"])
        with open(path, "wb") as f:
            f.write(imgs[0].data)
        import ai
        print("saved", path, "| critic:", ai.critique(path))


STEPS = {name: getattr(FlowerBot, name) for name in
         ("resources", "teach", "plan_check", "open_gripper", "grip_test", "grip_calibrate", "pick", "go_hub", "move_pose",
          "pretend_loop", "pick_and_drop", "vase_one", "fill",
          "insert_one", "sogetsu", "photo")}


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
