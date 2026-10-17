# Demo commands — copy one block at a time

Run these in a new terminal on this Mac. Each shell block contains **one
command**. Complete the instructions between commands before continuing.

The current `staged_demo.json` exists but its three pickup slots are still
empty. Complete the one-time setup below before the first physical Build.
Do not run `init` again or replace this profile with historical pickup offsets.

## 1. Prepare the terminal

**1 — Open the project directory.**

```sh
cd /Users/shauryatiwari/Desktop/Projects/gits/fleurs-du-viam
```

**2 — Activate the existing environment.**

```sh
source .venv/bin/activate
```

**3 — Enable exporting the environment file's variables.**

```sh
set -a
```

**4 — Load the robot credentials.**

```sh
source .env
```

**5 — Finish loading the environment.**

```sh
set +a
```

**6 — Select the existing runtime Viam classifier for the display.**

```sh
export FLOWERS_CLASSIFIER=viam
```

**7 — Select the deployed flower detector.**

```sh
export FLOWERS_FLOWER_VISION=flower-detector
```

Stop any old bouquet server using **Ctrl+C in its own terminal** before
continuing. Port 8770 must be free.

## 2. Teach the orange-lily slot once

Arrange the three labeled pickup marks at least **40 mm apart**. Each flower
needs its own visible, uncrossed stem and yellow tape. Keep the marks fixed
for all future builds.

Using your existing supervised robot controls, position the **open jaws**
directly above the orange lily's tape. This is a manual alignment step; the
capture command below only reads the pose.

For the 30 mm hover, the gripper's **world-frame** Z must be **97.209441 mm**.
Keep the taught grasp orientation: o_x **0.005754638**, o_y **−0.028685648**,
o_z **−0.999571917**, theta **101.425846°**. Confirm from above that the center
between the fingertips is directly over the intended tape grasp point.

**8 — Capture that aligned orange-lily pickup. No motion.**

```sh
python bouquet_staged.py capture orange-lily --hover-mm 30 --aligned
```

**9 — Return to the saved scan pose. This command moves the arm.**

```sh
python flowers.py restore_scan
```

**10 — Start the read-only teaching page. No arm execution is enabled.**

```sh
python -u bouquet.py serve --staged-demo staged_demo.json
```

Leave this command running. Open
<http://127.0.0.1:8770/?teach=1> in your browser. Refresh the scan and click the
orange lily's exact tape grasp point. The page shows **Teaching pixel: U V**.
Write down those two numbers, then press **Ctrl+C in this terminal** to stop
the teaching server and get the shell prompt back.

**11 — Read the orange-lily pixel numbers.** After pasting this command,
type your U and V numbers separated by a space, then press Enter.

```sh
read -r DEMO_ORANGE_U DEMO_ORANGE_V
```

**12 — Bind the orange-lily tape mark. No motion.**

```sh
python bouquet_staged.py marker orange-lily --pixel "$DEMO_ORANGE_U" "$DEMO_ORANGE_V"
```

## 3. Teach the yellow-lily slot once

Use your supervised controls to align the open jaws over the yellow lily's
tape at the **same 30 mm hover height and grasp orientation** described above.
The orange-lily mark and flower must stay in place.

**13 — Capture the aligned yellow-lily pickup. No motion.**

```sh
python bouquet_staged.py capture yellow-lily --hover-mm 30 --aligned
```

**14 — Return to scan. This command moves the arm.**

```sh
python flowers.py restore_scan
```

**15 — Start the read-only teaching page again.**

```sh
python -u bouquet.py serve --staged-demo staged_demo.json
```

Open or refresh <http://127.0.0.1:8770/?teach=1>. Refresh the scan, click the
yellow lily's exact tape grasp point, and write down its U/V numbers.
Press **Ctrl+C in this terminal** before the next command.

**16 — Read the yellow-lily pixel numbers.** Type your U and V separated by a
space, then press Enter.

```sh
read -r DEMO_YELLOW_U DEMO_YELLOW_V
```

**17 — Bind the yellow-lily tape mark. No motion.**

```sh
python bouquet_staged.py marker yellow-lily --pixel "$DEMO_YELLOW_U" "$DEMO_YELLOW_V"
```

## 4. Teach the red-rose slot once

Use your supervised controls to align the open jaws over the red rose's tape
at the **same 30 mm hover height and grasp orientation**. Keep the other marks
and flowers fixed.

**18 — Capture the aligned red-rose pickup. No motion.**

```sh
python bouquet_staged.py capture red-rose --hover-mm 30 --aligned
```

**19 — Return to scan. This command moves the arm.**

```sh
python flowers.py restore_scan
```

**20 — Start the read-only teaching page again.**

```sh
python -u bouquet.py serve --staged-demo staged_demo.json
```

Open or refresh <http://127.0.0.1:8770/?teach=1>. Refresh the scan, click the
red rose's exact tape grasp point, and write down its U/V numbers.
Press **Ctrl+C in this terminal** before the next command.

**21 — Read the red-rose pixel numbers.** Type your U and V separated by a
space, then press Enter.

```sh
read -r DEMO_RED_U DEMO_RED_V
```

**22 — Bind the red-rose tape mark. No motion.**

```sh
python bouquet_staged.py marker red-rose --pixel "$DEMO_RED_U" "$DEMO_RED_V"
```

## 5. Record your onsite verification once

The changed physical path has not been run. Before the verification command,
check the route onsite: the new rotation height is **Z 174.981948 mm**
(50 mm above the old lift), and the post-release withdrawal is **50 mm in
world +Y** at unchanged release Z/orientation before rising. Confirm that
this direction clears the vase and placed flowers.

Measure the usable **robot-world pickup workspace** in millimeters. Its limits
must include all three pickup poses and their clearance lifts. Enter measured
values below; there are no assumed bounds to paste.

**23 — Read the measured X limits.** Type X minimum and X maximum separated
by a space, then press Enter.

```sh
read -r DEMO_X_MIN DEMO_X_MAX
```

**24 — Read the measured Y limits.** Type Y minimum and Y maximum separated
by a space, then press Enter.

```sh
read -r DEMO_Y_MIN DEMO_Y_MAX
```

**25 — Read the measured Z limits.** Type Z minimum and Z maximum separated
by a space, then press Enter.

```sh
read -r DEMO_Z_MIN DEMO_Z_MAX
```

**26 — Record your verification.** Run only after checking the slots, measured
bounds and new clearance route onsite. This command records that confirmation;
it sends no motion and does not perform the physical checks for you.

```sh
python bouquet_staged.py verify --confirm-setup --x "$DEMO_X_MIN" "$DEMO_X_MAX" --y "$DEMO_Y_MIN" "$DEMO_Y_MAX" --z "$DEMO_Z_MIN" "$DEMO_Z_MAX"
```

If any command reports an error, resolve it before continuing. Do not manually
remove blockers or reuse pixels from a different flower arrangement.

## 6. Run Build from the frontend

Reset each flower to its own verified mark. Keep the vase in its taught place
and the arm at scan. No teaching server should still be running.

**27 — Start the physical staged-demo server.** This enables physical orders;
the arm starts its transfer sequence when you submit an approved Build.

```sh
python -u bouquet.py serve --staged-demo staged_demo.json --allow-motion
```

Leave this terminal running and open **<http://127.0.0.1:8770/>**. Use the plain
URL without `?demo=1`.

1. Refresh the scan.
2. Select **1 orange lily, 1 yellow lily and 1 red rose**.
3. Click **Check my bouquet**.
4. If approved, click **Build my bouquet**.

The selected flowers run orange lily → yellow lily → red rose. Each transfer
uses the shared grasp, clearance, vase release and withdrawal sequence, then
returns to scan and checks source clearance before continuing. **Stop arm**
remains available. Landing inside the vase is not camera-verified.

For later runs with the same verified setup, reset the flowers and use the
frontend again. If opening a new terminal, repeat commands **1–7**, then **27**;
the saved slots do not need recapturing unless the setup changed.

To end the session, stop any active order with **Stop arm**, then press
**Ctrl+C in the server terminal**.
