# Les Fleurs du Viam

A Viam-controlled xArm that builds a bouquet to order. You pick stems by variety and colour in a browser, a wrist camera and a YOLOv8 model find matching flowers on the table, and the arm carries each one to a vase. We built it at the Viam NYC hackathon on 16 and 17 Oct 2026 on robot `armfarm12` (xArm, wrist RealSense, gripper). The project started as an arm that arranges flowers to express a feeling; that path is still in `flowers.py` and `ai.py`. In the live demo on 17 Oct no stem was picked up. Teleop and the taught loop ran on the robot; what the robot logs do and do not show is below.

Team: Amadeus Wu, Shaurya Tiwari, Manojit.

## Final state (Sat 17 Oct, after the demo)

What works:
- Teleop dashboard with hold-to-move, limits and a log of every move (median error 0.13 mm over 103 moves).
- Every planned move is dry-run first. The taught loop (approach, grasp, lift, vase, release) planned and ran end to end on armfarm12 several times between 18:39 and 18:54 UTC.
- Flower detector v3 (`vision/weights/flowers.pt`): rose, carnation, lily by YOLOv8n, colour from bloom pixels. v1 and v2 are kept for rollback.
- Bouquet Studio frontend (`bouquet_ui/`) with the taste lens, wired to real orders by `bouquet.py`.
- Camera-to-table localization and staged pickup (`bouquet_localization.py`, `bouquet_staged.py`).

What did not work: no stem was picked up in the live demo.

What the robot logs and the calibration files show (planner goals from armfarm12, 18:10 to 19:57 UTC):
- Frames are consistent. Each commanded arm pose equals its hand-taught gripper pose moved 105 mm back along the gripper axis (residual under 3.5 mm on 4 poses; 78 to 105 mm without the shift).
- The goals at z 202 between 19:15 and 19:23 are the staged alignment hover: taught grasp 67 + 30 mm hover = 97 at the gripper point, 202 at the flange. The descent to the stem is not in the planner log, so the logs cannot say whether the jaws reached it.
- The camera calibration was never verified on site, by its own record in `vision_inventory.json`: table height is a provisional -10 (an earlier depth reading gave about -23), the depth plane reads 2.3 degrees tilted, the projected reference lands 33 mm from the taught grasp, and `staged_demo.json` has no verified digest. That is why physical pickup ran from operator-aligned hovers rather than from the camera.
- No planner goals were logged after 19:25 UTC.

## How it fits together

- **Driving by hand.** `dashboard.py` (browser) and `teleop.py` (terminal) share `fleurs_core.py`: workspace limits, one move at a time, a per-move log and a 5 Hz trace. `viam_module/` packages the same logic as a Viam generic service.
- **Planned motion.** `flowers.py` asks the builtin motion service for a plan without executing it (`motion.do_command({"plan": MoveRequest})`, rdk v1.12.0) and refuses the move if there is no full plan within 30 s. `pretend_loop` and `pick_and_drop` move through the five poses in `taught_poses.json`.
- **Bouquet orders.** `bouquet.py serve` hosts `bouquet_ui/` and an order API. Each order is checked against stock (`bouquet_core.py`), then run one flower at a time (`bouquet_orders.py`): rescan, pick, release at the taught vase poses, check the source spot is empty.
- **Vision.** Viam `vision-1` finds stems; `vision/flowers_detect.py` names the bloom's variety and colour from the same frame; `bouquet_markers.py` finds the yellow tape band that marks the grasp point; `bouquet_localization.py` projects it onto the measured table plane.
- **Gates.** Physical orders need `--allow-motion` and a verified calibration or staged profile. Nothing in the committed state is verified, so the server stays read-only in practice.

Diagrams and the 16 Oct design notes: [docs/architecture.md](docs/architecture.md).

## Run it

```sh
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cp .env.example .env    # address and API key from the Viam app's CONNECT tab
set -a; source .env; set +a
python flowers.py resources        # first, safe call: lists the machine's resources
```

Tests run offline with no robot (142 tests across 7 files: inventory and order planning, localization, grasp bands, the order runner, geometry, teleop limits):

```sh
python -m pytest -q tests
```

Bouquet UI without hardware:

```sh
python bouquet.py serve --demo     # real backend, in-memory inventory: http://127.0.0.1:8770
python3 bouquet_ui/preview.py      # static preview only: http://127.0.0.1:8000/?demo=1
```

Teleop (exit manual mode first, one person at the stop button):

```sh
python dashboard.py                # http://localhost:8765: camera, pose, jog buttons, STOP
python teleop.py                   # same thing in the terminal
```

Keys: W/S x, A/D y, R/F z, Q/E wrist spin, O/C gripper step, G grab, Tab 20/5 mm steps, M mark a moment, Space STOP. Every session writes `recordings/teleop-<time>.jsonl` and a `-trace.csv`. Limits refuse moves into the table, walls, ceiling, or fingers into the vase. Nothing else is avoided.

Planned moves: `python flowers.py plan_check 300 -283 600` checks a point without moving. `python flowers.py pretend_loop` runs the flowerless path; `python flowers.py pick_and_drop` runs one supervised stem transfer. Teach a pose with `python recorder.py` while hand-guiding in manual mode (support the arm from below before pressing the button), then `python recorder.py promote p12 slot0 --down -15`.

## Repo map

| Path | What it is |
|---|---|
| `flowers.py` | Planner steps (18 verbs, listed in its docstring) and `FlowerBot.pick_and_drop` |
| `bouquet.py` | Bouquet server and calibration commands (`serve`, `scan`, `capture-scan`, `set-table`, `set-workspace`, `set-reference`, ...) |
| `bouquet_core.py`, `bouquet_orders.py` | Stock check and order planning; serialized order runner |
| `bouquet_vision.py`, `bouquet_classifier.py` | Viam and demo inventory backends; adapter to the flower detector |
| `bouquet_localization.py`, `bouquet_markers.py` | Camera-to-table projection; yellow grasp-band checks |
| `bouquet_staged.py`, `bouquet_commissioning.py` | Three taught slots demo; preview bounds and one-flower trial limits |
| `bouquet_ui/` | Browser selector, taste lens, preview server; API contract in its README |
| `vision/` | YOLOv8n flower detector, synthetic training data, weights v1/v2/v3 |
| `dashboard.py`, `teleop.py`, `fleurs_core.py` | Hand driving with limits and logs |
| `recorder.py`, `replay.py` | Record hand-guided poses; replay marked teleop moments |
| `ai.py`, `composition.py`, `geometry.py` | The original "feeling" path: Claude planner and blind critic, Sogetsu stem placement, angled-insertion pose math |
| `config.py` | Machine names, gripper width, measured vase, flags such as `PLAN_CHECK` |
| `viam/`, `viam_module/` | Exported machine config; teleop as a Viam module (its `fleurs_core.py` is a synced copy) |
| `*.json` (root) | Machine state: taught poses, calibration drafts, staged profile, transfer clearance |
| `tests/` | Offline tests and image fixtures |
| `docs/` | Working notes from the event, see below |

Docs: [architecture](docs/architecture.md) · [gripper and one-stem run](docs/gripper.md) · [vision-guided bouquets](docs/vision-bouquet.md) · [three-flower staged demo](docs/staged-demo.md) · [frontend](docs/frontend.md) · [resources](docs/resources.md).

## What we learned, and next steps

- The frames held up: the 105 mm TCP offset matches the logs, and the taught loop ran several times. The gap we did not close was camera-to-table calibration: table height, plane tilt and a 33 mm reference error.
- Top-down grasps only work for a stem gripped near its foot, because the travel height over the vase is capped (z 600 reachable, z 680 not, from plan-only checks). Roses with a bloom above the grip need a side grasp, which was never plan-checked.
- A yellow tape band on each stem made the grasp point something the camera can find without guessing from a bounding box.

If this continues: touch the table once with the fingertips to fix its height, check the projection against a ruler at two known spots, then record the verified digest. After that, verify `transfer_clearance.json` onsite and run one staged flower with `--allow-motion`.

## Safety

Every new move runs slowly the first time, with one person's hand near the stop button. Exit manual mode before running any command that moves the arm. `bouquet.py` is read-only unless started with `--allow-motion`, and `--demo` and `?demo=1` never touch hardware.
