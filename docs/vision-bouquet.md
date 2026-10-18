# Vision-guided bouquets

Written 16 and 17 Oct during the event. The calibration state it describes is still what the committed `vision_inventory.json` holds: `reference.verified` is false.

## Current physical execution gates

For the separately taught, resettable three-flower physical demonstration, see
[staged-demo.md](staged-demo.md). It uses fixed robot poses, operator-assigned
flower labels and fresh tape checks through the existing order runner. It does
not enable free-table image-to-world motion. The new 50 mm rotation/withdrawal
route requires onsite verification for both direct and API transfers.

Both free-table calibration files currently contain unverified geometry and a preview-only
camera correction. Physical execution requires verified calibration and measured
robot-world workspace bounds. The preview correction also blocks execution.
`--commission-one` adds a one-flower limit, slow speeds and region checks; it does
not bypass any of these requirements. Projected tape bounds in
`commissioning_inventory.json` do not establish independently measured world limits.

For detection diagnosis, use the read-only server:

```sh
python -u bouquet.py --calibration commissioning_inventory.json serve
```

## Live diagnostics

Every server writes rotating logs to `logs/bouquet.log` and the terminal. In a
second terminal, from the repository:

```sh
tail -n 80 -F logs/bouquet.log
```

Logs include order stages and failure tracebacks, same-frame stem/head counts,
stem confidences, candidate grasp points and individual validation blockers.
`GET /api/orders/current` also exposes the failed stage and error without moving
the robot. A classified flower head without a fresh `vision-1` stem detection
is not a pickable flower. Do not reuse old poses or skip the pre-pick scan to
compensate for a missed detection.

If the wrist camera leaves its saved calibration view, scans retain the live
image and raw classification evidence but report `invalid_scan_geometry` with no
grasp coordinates or pickup poses. Restore the original scan pose to reuse that
calibration, or recalibrate the camera, reference and image region for the new
view. `capture-scan` alone cannot make an old correction valid at a new view.
The fixed `flowers.py pick_and_drop` command now returns to its separately saved
`post_pick_return` pose; that pose is not automatically a calibrated vision view.

To explicitly move back to the original saved vision view, stop the bouquet
server and supervise `python flowers.py restore_scan`. This uses the native
collision-checked motion planner and does not actuate the jaws. It does not
capture a new calibration or mark an existing one verified. Restart the server
and rescan afterward; other calibration and workspace blockers still apply.

The October 17 failed order stopped at `rescan_before_pick`: one red rose head
was classified but `vision-1` returned zero stems. No transfer started. A later
read-only scan recovered the stem at approximately 54% confidence. The failed
order, inventory and cached frame are saved under `logs/live-failure-20261017/`.

## Integrated vision branch

### Runtime classifier choices

In-chat image understanding and MCP camera calls are not a classifier endpoint
available to `/api/orders`. No ChatGPT vision service is configured here.
The live Viam `flower-detector` is a callable YOLO variety detector and can now
replace local YOLO inference with `FLOWERS_CLASSIFIER=viam` and
`FLOWERS_FLOWER_VISION=flower-detector`. It receives the exact captured frame
sent to `vision-1`; bloom-pixel color inference and stem/band association stay
in the backend. Its labels must be `rose`, `carnation`, or `lily`. A service
failure blocks the scan; it never falls back to stale or in-chat coordinates.

`FLOWERS_CLASSIFIER=local` remains the default merged YOLO implementation;
`none` retains the legacy HSV preview. Flower-head boxes remain visible as
dashed **head only** overlays, separate from numbered stem/grasp previews.
Insufficient color evidence returns unknown and cannot authorize a pickup.

The smallest next step for a different vision model is a runtime adapter at
`bouquet_classifier.py` returning same-frame `{variety, colour, confidence,
bbox}` bloom records, with a configured API/model and explicit timeout/error
handling. Such an adapter still must use the independent stem localization;
flower-head boxes never establish a grasp point.

Quick startup (no physical orders during development):

```sh
source .venv/bin/activate
python bouquet.py serve --demo
# Or a live READ-ONLY preview using the deployed flower detector:
set -a; source .env; set +a
FLOWERS_CLASSIFIER=viam FLOWERS_FLOWER_VISION=flower-detector python bouquet.py serve
```

Use only one server on port 8770 at a time. The API-backed demo contains two
of every supported variety/color, so a mixed selection exercises the real
planner and sequential runner without connecting to hardware. Camera capture
time drives freshness; both source-verification frames must retain valid
localization. Existing unverified reference, missing measured workspace bounds,
preview-correction and scan-view blockers still prevent physical orders.

The `vision` branch (`ced18be`) is merged into `pretend-loop`. The backend now
passes the exact camera frame to both Viam `vision-1` for stem detections and
`vision/flowers_detect.py` for bloom variety/color. Each bloom must pair uniquely
with a stem and grasp band before it receives pickup poses. Bloom box centers
are never used as robot grasp points.

The selector distinguishes red/yellow/pink roses, white/red-white carnations,
and orange/yellow lilies. Orders accept
`{"items":[{"variety":"rose","color":"red","quantity":1}]}`.
Legacy color-only requests mean roses. Detected counts and ready-to-pick counts
are displayed separately. Each ordered flower is rescanned, picked, released
using the taught vase poses, and checked for source clearing before the next.

Run from the repository:

```sh
source .venv/bin/activate
python -m pip install -r requirements.txt
set -a
source .env
set +a
export FLOWERS_CLASSIFIER=local
python bouquet.py serve --allow-motion
```

Open http://127.0.0.1:8770, scan, select one flower, check the bouquet, then build.
Remove rulers/tools from the inventory area first. Startup and scanning do not
move the arm. `--allow-motion` permits a validated order to execute; existing
calibration, workspace, collision-planning and preview-correction gates still
apply. Current onsite calibration remains unverified, so report the displayed
blocker before any physical trial. `FLOWERS_CLASSIFIER=none` restores the legacy HSV preview.

The existing `python3 flowers.py pick_and_drop` still uses your working pickup and vase poses. The new bouquet app adds color/quantity selection, camera inventory, table localization, and a serialized order runner. It replaces only the three pickup poses; the captured vase approach/release remain the same.

## Preview now

```sh
source .venv/bin/activate
python3 bouquet.py serve --demo
```

Open **http://127.0.0.1:8770**. Select two red roses, check the bouquet, then run the demo. This uses an in-memory inventory and never connects to the robot. `?demo=1` is also available as a purely local UI preview.

For a live **read-only** camera/inventory preview:

```sh
set -a; source .env; set +a
python3 bouquet.py serve
```

The server defaults to read-only. Scan, inventory, calibration reads, order polling, and shutdown send no arm/gripper movement commands. The Stop button in a read-only session also sends no hardware command. An order cannot execute unless the server is explicitly launched with `--allow-motion` and measured calibration is verified. The server listens on localhost.

Dependencies are in `requirements.txt` (`viam-sdk`, `aiohttp`, and `Pillow` are used by this flow).

## What the live configuration provides

- Camera: `cam`, 1280×720, wrist-mounted RealSense with color/depth sensors and configured camera frame.
- Trained model: `rose-model`, using the `rose-detector` TFLite package.
- Vision service: `vision-1`, wrapping that model. It reports **detections**, labeled `stem`; it does not currently return color labels or whole-image classifications.
- The adapter sends one color frame to `GetDetections`, then uses that exact frame for blossom-color association. It does not combine stem boxes from one frame with colors from another.

The read-only check on October 16 returned one stem at approximately 61% confidence. The view contained stems/leaves and a loose petal, without reliable blossom-to-stem color evidence. That is not enough to claim two red roses are available. The legacy `multicolor_detector` also points to `flower_color_detector`, while the saved color-service names have `-cyan`/`-orange` suffixes; this app calls `vision-1` directly and does not depend on that generic service.

The API behavior follows the [Viam vision reference](https://docs.viam.com/reference/apis/services/vision/).

## Onsite calibration

This first free-table version supports **separate roses lying on one measured horizontal surface**, with visible blossoms and a clear stem section. It rejects crossed/overlapping stems and uncertain color matches. Piles, upright stems, or objects at varying heights need validated depth-based localization instead of the table-plane model.

`vision_inventory.json` remains an **unverified draft**. It contains the working
pickup poses, captured scan view, reference band/axis and the measured 457 × 550 mm
inner rectangle. Table Z is provisionally -10 mm from the approximate base-height
measurement; measured robot-world workspace bounds remain unset.

The October 17 ruler assessment supports the projection scale: vertical 100 mm
spans project to 99.7–100.3 mm, and a horizontal 100 mm tape span measures about
100.1 mm after accounting for its elevation using depth. Image endpoints have
roughly 2 mm sensitivity, with additional systematic uncertainty. These checks
do not establish robot-world alignment or physical pickup accuracy.

`projection_preview` applies the candidate camera correction to the read-only
pickup preview while preserving the actual reported scan-camera pose for view
checks. It requires the saved intrinsics and camera view to match. Its presence
blocks physical transfers, including if `reference.verified` is changed or
`--commission-one` is supplied.
It does not change the live robot camera mounting transform or collision geometry.
Remove it only after the actual camera frame, world points, workspace and pickup
orientations have been independently validated and calibration recaptured.

1. Arrange the camera so the whole pickup area, blossoms, and stems are visible. With the arm stationary at that scan view, run:

   ```sh
   python3 bouquet.py capture-scan
   ```

   This only reads and saves the gripper/camera world poses and image resolution. It never jogs the arm. Inventory scans must use this same view.

2. Measure the world Z of the surface on which the stems lie, and the usable world XYZ bounds. Bounds must include the stem surface and all generated pickup/approach/lift poses. Replace the capitalized names below with measured numbers:

   ```sh
   python3 bouquet.py set-table --z MEASURED_Z_MM
   python3 bouquet.py set-workspace --x X_MIN X_MAX --y Y_MIN Y_MAX --z Z_MIN Z_MAX
   ```

   Do not substitute the old guessed table/vase heights. Check the configured camera mounting transform and actual obstacle geometry on site.

3. Put a rose at the original working pickup location. In the saved scan view, record the actual successful grasp pixel and two stem-axis pixels directed **cut/base → blossom**:

   ```sh
   python3 bouquet.py set-reference --pixel U V --axis BASE_U BASE_V BLOSSOM_U BLOSSOM_V
   ```

   The three pickup poses in the draft came from `taught_poses.json`. If those were recaptured, update them with `python3 bouquet.py copy-reference`. The reference pixel must represent the same physical grasp as those taught poses.

4. Run `python3 bouquet.py scan` or scan in the UI. Check the proposed grasp locations and stem directions against measured points at several places across the workspace. The code projects camera rays onto the measured surface, then translates/rotates the complete working pickup template. It preserves the gripper offset and uses Viam quaternion conversion for orientation.

5. After checking the table/camera measurements, reference alignment, permitted displacement/yaw, and generated pickup bounds, set `reference.verified` to `true` in `vision_inventory.json`. Every calibration command resets this flag to `false`. This flag records your calibration check; synthetic tests do not establish physical accuracy.

6. Only when someone is present to supervise the first transfer, launch:

   ```sh
   python3 bouquet.py serve --allow-motion
   ```

   Validate one rose first, then select two red roses. This command was **not run during development tonight**.

## Roses with yellow grasp bands

The onsite setup can opt into `"grasp_mode": "yellow_band"` in `vision_inventory.json`.
It also requires `image_workspace_polygon`: four convex image-pixel corners inside
the white pickup area, ordered around its boundary. Keep the black/yellow border
outside this polygon. The polygon is tied to the saved scan pose and resolution;
it does not replace measured robot-world workspace bounds.

In this mode, every detected stem needs exactly one yellow band connected through
visible stem pixels, with narrow stem continuing on both sides and one uniquely
associated blossom. Partial detector boxes may exclude the band: an observed
continuous stem corridor must extend from the band into that box for at least
24 image pixels. Nearest-band matching and missing stem support are rejected.
The preview outlines all found bands in cyan and the saved inventory boundary
with a green dashed line, independently of detector boxes. The
band center is the grasp point. Missing or ambiguous bands block the pickup;
the code never falls back to the 60% stem position. Yellow bands are excluded
from blossom-color evidence, and dark red petals are handled separately.
The stem fit excludes the marker itself, including shaded tape.
Wrapped tape may split into disconnected yellow fragments. The local fit masks
nearby observed yellow fragments and the shaded area between them within the
marker corridor, while preserving the measured grasp center and the original
stem-width, crossing, continuity and both-sides checks. A blossom's
color region must be wider than 1.5 times the exposed stem width; smaller red
flecks on a stem do not establish a flower head. Multiple eligible heads still
make the pairing ambiguous and block pickup.

At the successful reference placement, record the band center and the local
bare-stem direction around the band, directed cut end toward blossom. Compare
the preview with the physical marks before validating translated or rotated
pickups. Crossed stem extents and shared bands/blossoms are rejected. Keep
`reference.verified` false until the camera transform, table plane, workspace,
reference offsets and pickup orientations have been checked onsite.

The actual onsite reference frame is retained in `tests/fixtures/marked_reference.jpg`
as an offline regression. Its test confirms red-versus-tape interpretation and
that unverified calibration still blocks execution; it does not validate motion.

## Order behavior

An order checks the entire requested stock before movement. Each rose needs an independent stem detection, unique blossom-color association, stable identity, and calibrated pickup. The runner rescans before every pick, carries one rose through the existing vase segment, returns to the scan pose, and checks the old source location in two frames before advancing the count. It does not retry a failed or uncertain transfer automatically.

The order completes only after the release commands and source checks succeed. The flower landing inside the vase is still not camera/sensor verified. White flowers cannot be reliably separated from a white background by the current color heuristic; use a trained color-labeled detector for that case. The blossom/color and stem-axis algorithms are prototypes that need your actual flower images and on-site validation.

Selection rules currently supported: highest detection confidence, or left-to-right. Requests use exact color/count pairs, for example `{"items":[{"color":"red","quantity":2}]}`. Natural-language arrangement rules are not implemented yet.

## Offline checks

```sh
python -m pytest -q tests
```

The tests use synthetic images, fake robot methods, and an in-memory demo backend. They cover two distinct red roses, projection/orientation math, stock shortages, duplicate detections, uncertain source clearance, cancellation, and refusal of physical execution in read-only mode.
