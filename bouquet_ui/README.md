# Bouquet studio UI

Live inventory now supports the merged vision classifier's variety/color pairs.
Rows carry `key` (for example `rose:yellow`), `variety`, `color`, `label`,
`detected_count` and `available` (localized, ready-to-pick count). Order items may
include `variety`; omitting it means `rose`. Counts for yellow roses and yellow
lilies are separate. Classification and stem localization use the same image.

For local setup and the next agent's starting instructions, read
[FRONTEND_HANDOFF.md](../FRONTEND_HANDOFF.md). For a standalone preview,
run `python3 bouquet_ui/preview.py` from the repository root and open
<http://127.0.0.1:8000/?demo=1>. Python's standard library is sufficient.

## Integrated mode

For a physical three-slot staged demonstration, use
[`STAGED_DEMO.md`](../STAGED_DEMO.md). After onsite teaching/verification, start
`python bouquet.py serve --staged-demo staged_demo.json --allow-motion`.
The same payload, plan, Build, polling and Stop controls are used. This mode is
visibly labeled as physical; variety/color labels come from operator-staged
slots and camera checks confirm their tape marks. It never converts blossom
pixels into grasp coordinates. Reset the slots before each Build. Source
verification and fresh per-pick scans remain mandatory.

The backend serves `index.html` at `/` and this folder's assets at `/static/`.
Open the server address to use live inventory. Add `?demo=1` for an explicitly
labeled, local-only preview; this mode never calls the robot API.
The server's `--demo` mode is also labeled as a preview, but uses the in-memory
backend API so planning, order polling, and error handling can be tested together.

1. Scan the workbench with the refresh button.
2. Choose up to 12 stems in total with the color cards' **+** and **−** buttons.
3. Select **Check my bouquet** to validate inventory and robot readiness.
4. Select **Build my bouquet** to start the approved order. Each stem is a
   separate pick-and-place operation managed by the backend.
5. Progress appears below the selector. **Stop arm** remains fixed at the
   bottom-right corner and submits `/api/stop`; it requires a live server
   connection.

The frontend does not estimate positions, interpret classifier scores, or send
component-level motion commands. Inventory counts come only from the server;
connection failures replace stale counts with unknown values.
The API-backed `--demo` provides two of each supported variety/color and runs
mixed selections through the existing sequential order runner. Dashed bloom
boxes labeled **head only** preserve the YOLO display; only independent stem
candidates can carry grasp previews. Use `FLOWERS_CLASSIFIER=viam` with
`FLOWERS_FLOWER_VISION=flower-detector` to select the deployed Viam variety
detector, or `FLOWERS_CLASSIFIER=local` for the existing local YOLO classifier.
Neither mode uses in-chat vision at runtime; both retain calibration gates.
When provided, numbered camera boxes, grasp pixels, and table grasp coordinates
show the localization preview. Camera-to-table calibration and a verified grasp
reference are required before physical picking anywhere on the table.

## API contract

- `GET /api/inventory` and `POST /api/scan`: `{mode, colors, ready, blockers,
  detected_at?, camera_url?, raw_detection_count?, execution_enabled?}`. Each color is `{color, label, available,
  confidence?}`. `available` is a nonnegative integer or `null` when unknown.
  Each color entry may also carry `variety` (`rose`, `carnation`, `lily`); without it the UI assumes `rose`.
  The UI keys stems by `variety:color` (e.g. `carnation:red-white`), so the same colour can exist in two varieties.
- `POST /api/plan`: request `{items: [{variety, color, quantity}], rules:
  {selection: "highest_confidence" | "left_to_right"}}`; response
  `{ready, blockers, requested_total, assignments, inventory?}`.
- `POST /api/orders`: same request; response `{id, status, requested_total,
  completed, steps, error?}`.
- `GET /api/orders/current`: the current order, or `{status: "idle", completed: 0}`.
- `POST /api/stop`: `{status: "stopped"}`.

Blockers may be strings or objects with a `message` or `reason`. Order steps may
be strings or objects with `message`/`label`. API errors must return a JSON
`error` or `message` with a non-success HTTP status. The frontend polls order
state every two seconds, with no overlapping polls. Inventory may additionally
include `image_size: [width, height]` and `candidates` with `bbox`, `grasp_pixel`,
`world_grasp`, `color`, `confidence`, `pickable`, and `blockers`. Order step
objects may use `stage` and `color`; order `verification` text is displayed near
progress so completion does not imply a sensor-verified landing in the vase.

Live stem detections alone do not establish rose colors or safe pickup
locations. When `ready` is false, the workbench panel shows the exact backend
blockers and raw detection count (when provided). Quantities remain editable;
an approved plan is required before the build control becomes available.

No framework or build step is required. The stylesheet uses optional hosted
fonts with local serif and system fallbacks. The inline botanical illustrations
are decorative SVG; all actionable controls have accessible names and keyboard
focus styles, and animation honors reduced-motion preferences.
