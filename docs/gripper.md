# Gripper and one-stem run

Short checklist for repeating the gripper check and supervised flower transfer. Written 16 and 17 Oct during the event; the poses and numbers below are tied to armfarm12's table layout on those days.

For the next vision-guided color/quantity workflow and selector UI, see [vision-bouquet.md](vision-bouquet.md). This manual remains the fixed-pickup baseline.

## Before starting

In a terminal at the repository:

```sh
source .venv/bin/activate
set -a; source .env; set +a
python3 flowers.py resources
```

Confirm the listed arm and gripper match the Viam machine (`arm` and `gripper` on the current setup). Exit Viam's manual mode before software motion. Keep the emergency stop within reach, clear the table/vase path, and use one stem only.

The five captured waypoints are in `taught_poses.json`: `pickup_approach`, `pretend_grasp`, `lift`, `vase_approach`, and `pretend_release`. They are committed on this branch but tied to this robot/table layout. If the setup moved, recapture/verify the poses before moving the robot.

## Check the gripper

1. At a safe stationary pose, put one stem between the jaws.
2. Run:

   ```sh
   python3 flowers.py grip_calibrate
   ```

   Expected: `grab_success: True` and a reported aperture above 15 and at most 300. The last calibration read was 45. Confirm visually that the stem is actually held; the sensor is advisory, not proof.
3. To release the calibration stem at that same safe pose, run:

   ```sh
   python3 flowers.py open_gripper
   ```

`grip_calibrate` uses the gripper's semantic `Grab()` command. Do not copy its reported aperture into `GRIP_STEM`; that setting is only for the teleop `G` key.

## Run one flower

The subsequent 50 mm clearance change now lifts at fixed grasp orientation
before rotation and withdraws horizontally before rising from the vase. The
new route has not been physically run. Direct and API transfers require onsite
verification in `transfer_clearance.json`; see [staged-demo.md](staged-demo.md)
for the precise path, setup capture and frontend startup sequence.

For an onsite-verified lateral offset from the taught pickup, the same routine
can translate all three pickup waypoints along one robot-world axis:

```sh
python flowers.py pick_and_drop_axis y MEASURED_OFFSET_MM
```

Positive/negative offsets are millimeters in robot-world X or Y, not image
pixels. The reference is the saved grasp at X 264.663764, Y 142.546183 mm.
The grasp Z, full orientations, vase segment and final return are retained.
This is an explicit taught-motion command; it does not validate camera
geometry or enable uncalibrated frontend orders. Marks must lie on the same
verified fixed-X line for Y-only movement (or fixed-Y line for X-only movement).

The run record for the paragraph below is under `logs/`, which is gitignored and not in this repo.

The October 17 supervised demo completed one orange lily, one yellow lily and
one red rose through this shared routine. Each target was checked onsite at an
open-jaw hover 30 mm above the grasp before descending. Grasp apertures were
49, 57 and 53; each release opened fully. Fresh scan images confirmed each
requested flower left the source, and the arm finished stationary at scan.
Remaining stems shifted between transfers, so every offset was recalculated.
These individual alignment checks do not verify free-table camera calibration
or unlock automatic frontend orders. The run record is
`logs/supervised-three-flower-demo-20261017.json`; vase landing was not visually verified.

1. Place one stem so its stem is centered between the jaws at the saved `pretend_grasp` position; keep the vase in its taped, measured position.
2. If you want to recheck the flowerless path first, run `python3 flowers.py pretend_loop` with the pickup area clear.
3. With the flower positioned, run:

   ```sh
   python3 flowers.py pick_and_drop
   ```

The arm moves slowly through the saved pickup and vase poses, uses `Grab()` at `pretend_grasp`, and opens at `pretend_release`. Supervise the whole run and be ready to stop it. One invocation handles one stem; it does not verify that the flower landed in the vase.

The saved vase release waypoint is now Z 287.119412 mm, lowered 5 mm after
the October 17 run. The arm keeps the jaws closed until it reaches this lower
waypoint, then opens and retreats through `vase_approach`. The direct terminal
retry exercised this lower waypoint and completed the release and return.

The saved grasp is now Z 67.209441 mm after two successive 2 mm reductions
from Z 71.209441 mm on October 17. The approach remains Z 86.474715 mm and the
lift remains Z 124.981948 mm. Both arm speeds are set to 10 degrees/s, with
acceleration at 30 degrees/s squared.

The latest direct terminal `flowers.py pick_and_drop` run exited successfully:
the grasp aperture was 45, the jaws opened fully at the saved release pose,
and the arm returned to `post_pick_return`. The final camera image shows the
original pickup area clear; the flower's landing inside the vase was not
visually verified. Both vision pickup templates were synchronized and remain
unverified for image-guided motion; this run does not validate arbitrary pickups.

`post_pick_return` was captured through Viam MCP from the stationary gripper in
world coordinates at X 251.407209, Y 185.304128, Z 543.656273 mm, with its full
orientation saved. After a successful release, the fixed routine retreats to
`vase_approach`, then uses the collision-checked planner to return to this pose.
An unsuccessful grasp still stops after the established approach retreat.
The vision controller uses its separately calibrated scan-return path.

If calibration reports aperture `<= 15` (empty) or `> 300` (too wide/misaligned), do not run the transfer: reposition the stem/grasp and retry. If the vase/table or flower-holder layout changed, do not reuse the old saved poses without checking them.
