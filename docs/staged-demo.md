# Three-flower physical demo

Written 17 Oct during the event. In the committed files `staged_demo.json` has no verified digest and `transfer_clearance.json` has `verified: false`, so a physical staged order is still blocked.

This mode runs the frontend's normal plan/Build/order/Stop API against **three
fixed, taught slots**: orange lily, yellow lily, red rose. Flower labels come
from how you stage those slots. Camera pixels check the marks; they never
generate robot coordinates. Reset each flower to its own mark before every
Build. One of each is available; unsupported quantities are rejected.

The new path is shared by `FlowerBot.pick_and_drop`, including direct terminal
runs. Grasp and vase release poses retain their taught values. The changes are:

1. Approach, descend, grasp and check aperture as before.
2. Lift vertically at the grasp orientation to **Z 174.981948 mm**, which is
   **50 mm above the original taught lift**. Rotate only after reaching that
   height. The rotation and trip to the vase use constrained straight paths.
3. Reach the existing vase approach and release poses, then open fully.
4. Move **50 mm along world +Y** toward the scan side, at the release's exact
   Z and orientation. Only after that withdrawal, rise at the withdrawn XY.
   The path does not return alongside the vase or descend to the low pickup.
5. Return to scan, verify the old source in two frames, and proceed to the next
   selected flower. Order is orange lily, yellow lily, red rose, omitting any
   unselected slot. A shifted/ambiguous mark, failed grasp, changed setup, stale
   scan or failed source check stops the order without automatic retry.

`transfer_clearance.json` contains the requested 50 mm settings and remains
unverified. **The changed physical path has not been run.** Verify its height,
withdrawal direction, open-jaw clearance and reachability onsite. The arm's
configured obstacles and native complete-path planning remain active.

## One-time slot setup

The generated `staged_demo.json` is a draft with no executable pickup poses.
The three previous pickups used changing arrangements; their historical offsets
are not a three-slot layout. Mark three distinct locations at least 40 mm apart,
with a single visible stem and yellow tape at each grasp.

```sh
source .venv/bin/activate
set -a
source .env
set +a
# Only on a fresh checkout without staged_demo.json:
# python bouquet_staged.py init
```

For each flower, use the existing supervised dashboard/teleop controls to put
the **open jaws** 30 mm above that mark. Use the taught grasp orientation and
world Z **97.209441 mm**. Confirm from above that the jaws center over the tape.
The taught grasp orientation is o_x 0.005754638, o_y -0.028685648,
o_z -0.999571917, theta 101.425846 degrees. Confirm from above that the point
between the fingertips sits over the tape grasp point.
Keep the flower and its mark fixed throughout capture and all later builds.
Then run the corresponding pair of capture commands:

To read U/V values, run the staged server without `--allow-motion` and open
**http://127.0.0.1:8770/?teach=1**. At scan, refresh and click the actual tape
grasp point in the image. Its pixel coordinates appear above the camera; the
click sends no motion command. Stop the server with Ctrl+C before positioning/capturing the
next slot; port 8770 must be free. Normal bouquet users do not see the teaching interaction.

```sh
# At the operator-aligned orange-lily hover (reads only):
python bouquet_staged.py capture orange-lily --hover-mm 30 --aligned
python flowers.py restore_scan
# Replace U_ORANGE V_ORANGE with that exact grasp's pixels in the scan image:
python bouquet_staged.py marker orange-lily --pixel U_ORANGE V_ORANGE

# Repeat the aligned hover for the yellow lily, then:
python bouquet_staged.py capture yellow-lily --hover-mm 30 --aligned
python flowers.py restore_scan
python bouquet_staged.py marker yellow-lily --pixel U_YELLOW V_YELLOW

# Repeat the aligned hover for the red rose, then:
python bouquet_staged.py capture red-rose --hover-mm 30 --aligned
python flowers.py restore_scan
python bouquet_staged.py marker red-rose --pixel U_RED V_RED
```

`capture` and `marker` never move the arm. `restore_scan` does. Do not run
`init` again once slots are captured, and do not reuse pixels from a different
flower arrangement. If any command reports an error, fix the cause; do not
remove blockers by hand.

Capture/marker commands never move the arm or jaws. They preserve the taught
grasp Z/orientations, translate all three pickup poses together, and require a
stationary pose. The marker must contain one visible narrow stem and remain
within three image pixels of its recorded center. Marks/flowers must not cross.

After checking the new 50 mm route and measuring the usable pickup XYZ limits
(including the high lifts), record **your** setup verification. Substitute the
measured numbers below; this command does not invent bounds or run a transfer:

```sh
python bouquet_staged.py verify --confirm-setup \
  --x X_MIN X_MAX --y Y_MIN Y_MAX --z Z_MIN Z_MAX
```

Verification binds the profile to the exact slots, camera view, taught path and
clearance settings. Editing any of them invalidates it. The existing free-table
calibration files are not modified or marked verified by this workflow.

## Run from the frontend

Stop any old server on port 8770 first. A read-only staged preview is available
with `python bouquet.py serve --staged-demo staged_demo.json`.

After the onsite setup is verified, reset all three flowers and run:

```sh
source .venv/bin/activate
set -a
source .env
set +a
FLOWERS_CLASSIFIER=viam FLOWERS_FLOWER_VISION=flower-detector \
  python -u bouquet.py serve --staged-demo staged_demo.json --allow-motion
```

Open **http://127.0.0.1:8770/** (without `?demo=1`). Refresh the scan, select one
orange lily, one yellow lily and one red rose, choose **Check my bouquet**, then
**Build my bouquet**. Only an approved plan enables Build. The page explicitly
labels the physical staged demo; Stop remains available. YOLO boxes stay visible
as **head only** display evidence. `--demo` and `?demo=1` remain simulations and
never move hardware.

Completion verifies release and source clearance. Landing inside the vase is
not camera-verified, so this implementation does not establish flawless motion
before the changed route is checked onsite.
