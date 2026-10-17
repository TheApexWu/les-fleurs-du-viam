# Gripper and one-stem run

Short checklist for repeating the gripper check and supervised flower transfer.

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

1. Place one stem so its stem is centered between the jaws at the saved `pretend_grasp` position; keep the vase in its taped, measured position.
2. If you want to recheck the flowerless path first, run `python3 flowers.py pretend_loop` with the pickup area clear.
3. With the flower positioned, run:

   ```sh
   python3 flowers.py pick_and_drop
   ```

The arm moves slowly through the saved pickup and vase poses, uses `Grab()` at `pretend_grasp`, and opens at `pretend_release`. Supervise the whole run and be ready to stop it. One invocation handles one stem; it does not verify that the flower landed in the vase.

If calibration reports aperture `<= 15` (empty) or `> 300` (too wide/misaligned), do not run the transfer: reposition the stem/grasp and retry. If the vase/table or flower-holder layout changed, do not reuse the old saved poses without checking them.
