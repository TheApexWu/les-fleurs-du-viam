# Les Fleurs du Viam

**Bouquet Studio frontend:** see [FRONTEND_HANDOFF.md](FRONTEND_HANDOFF.md) for
local preview setup and instructions for the next contributor's agent.

A robot arm that arranges flowers to express a feeling. You type "gratitude" or "grief", the arm places stems in a vase with heights and leans chosen to say it, and a vision model that never saw the request guesses the feeling from a photo.

Viam hackathon, 16-17 Oct 2026, robot `armfarm12` (xArm, wrist camera, gripper).

**Today's plan, mental model and task list: [TODAY.md](TODAY.md). Diagrams of how it all fits: [ARCHITECTURE.md](ARCHITECTURE.md).** For the saved-pose flowerless loop and one-stem gripper run, see [GRIPPER_MANUAL.md](GRIPPER_MANUAL.md).

## Final state (Sat 17 Oct, after the demo)

What works:
- Teleop dashboard with hold-to-move, limits and a log of every move (median error 0.13 mm over 103 moves).
- Every planned move is dry-run first. The taught loop (approach, grasp, lift, vase, release) planned and ran end to end on armfarm12 several times between 18:39 and 18:54 UTC.
- Flower detector v3 (`vision/weights/flowers.pt`): rose, carnation, lily by YOLOv8n, colour from bloom pixels. v1 and v2 are kept for rollback.
- Bouquet Studio frontend (`bouquet_ui/`) with the taste lens: a rule-based score for harmony, rhythm, proportion and focus, plus a one-stem suggestion.

What did not work: no stem was picked up in the live demo.

What the robot logs show (planner goals pulled from armfarm12, 18:10 to 19:57 UTC):
- Frames are consistent. Each commanded arm pose equals its hand-taught gripper pose moved 105 mm back along the gripper axis (residual under 3.5 mm on 4 poses; 78 to 105 mm without the shift). The taught path itself is not miscalibrated.
- The three camera-driven grasps (19:15 to 19:23) kept x fixed at 264 and z fixed at 202 (gripper point about 97, versus 72 for the taught grasp) and took only y from the camera: 303, 190 and 288, against 142 for the taught grasp. A stem that was off in x or lower than 97 could not be reached.
- No planner goals were logged after 19:25 UTC.

Next, if this continues: get x and z from the depth camera, not only y; check the camera-to-gripper offset with one stem at a known spot; and grasp 25 mm lower, at the taught height.

## Run it

```
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cp .env.example .env    # then paste the address and API key from the Viam app's CONNECT tab
set -a; source .env; set +a
python flowers.py resources      # first, safe call
python3 -m pytest -q tests       # offline, no robot (teleop limits)
```

Teaching a pose: start `python recorder.py`, put the arm in manual mode (support it from below before pressing the button), move it, hold still for a second at each spot. Then `python recorder.py promote p12 slot0 --down -15`.

For the captured flowerless path, run `python flowers.py pretend_loop`; for a supervised one-stem transfer, run `python flowers.py pick_and_drop`. Follow the safety checklist in [GRIPPER_MANUAL.md](GRIPPER_MANUAL.md).

## Driving the arm by hand (teleop)

```
python dashboard.py      # then open http://localhost:8765  (camera, pose, jog buttons, STOP)
python teleop.py         # same thing in the terminal
```
Exit manual mode first, one person at the stop button. Keys: W/S x, A/D y, R/F z, Q/E wrist spin,
O/C gripper step, G grab (gripper default), Tab 20/5 mm steps, M mark a moment, Space STOP.
Every session writes `recordings/teleop-<time>.jsonl` (each command, the pose reached, error in mm, marks)
and `recordings/teleop-<time>-trace.csv` (position, joints, gripper ~5x/s, also mid-move).
Limits refuse moves into the table, walls, ceiling, or fingers into the vase. Nothing else is avoided.

## Plan before moving

Every planned move (`flowers.py`) first asks the motion service for a plan without executing it
(`motion.do_command({"plan": MoveRequest})`, rdk v1.12.0) and refuses if there is no full plan or no answer within 30 s
(the planner searched for over 200 s on some poses).
Check any point without moving: `python flowers.py plan_check 300 -283 600`.
Turn it off with `PLAN_CHECK = False` in `config.py`.

## Files

| File | What it does |
|---|---|
| `flowers.py` | Planner steps: `resources`, `teach`, `plan_check`, `photo` |
| `replay.py` | Plays back the marked moments of a teleop session |
| `config.py` | Names, gripper width, wrist angle, the measured vase |
| `ai.py` | Blind critic: photo to a guessed feeling |
| `recorder.py` | Records hand-guided poses and photos |
| `teleop.py` | Keyboard driving with limits, per-move log and continuous trace |
| `dashboard.py` | Browser version of teleop with the wrist camera |
| `fleurs_core.py` | Shared jog logic: limits, logging, trace (used by teleop, dashboard, module) |
| `viam_module/` | The same teleop as a Viam generic service for the app's CONTROL tab |
| `ARCHITECTURE.md` | Diagrams: pieces, Viam config, one pick-and-place, teleop-to-automation |

## Safety

Every new move runs slowly the first time, with one person's hand near the stop button. Exit manual mode before running any command that moves the arm.

## Resources

Checked links, grouped by what they're for. "Verified" means we opened the source on 16 Oct.

**Viam**
- Python SDK reference: https://python.viam.dev
- Builtin motion service source, incl. the plan-only DoCommand and `plan_file_path` / `log_planner_errors` (verified): https://github.com/viamrobotics/rdk/blob/v1.12.0/services/motion/builtin/builtin.go
- Fake arm with `"arm-model": "xarm6"` for dry runs in the 3D SCENE (verified): https://github.com/viamrobotics/rdk/blob/v1.12.0/components/arm/fake/fake.go
- xArm module: DoCommands (manual mode, gripper, speed, `load`), `collision_sensitivity`, URDFs: https://github.com/viam-modules/viam-ufactory-xarm
- Writing a logic module (generic service, DoCommand): https://docs.viam.com/build-modules/write-a-logic-module/
- Input controllers (gamepad, webgamepad): https://docs.viam.com/hardware/common-components/add-an-input-controller/
- Docs index for AI agents: https://docs.viam.com/llms.txt
- Viam's own xArm6 + RealSense pick-and-place workshop (no licence; read, don't copy): https://github.com/viam-devrel/pick-and-place
- Detections to 3D segments: https://github.com/viam-modules/detections-to-segments
- Colour detector vision service: https://docs.viam.com/reference/services/vision/color_detector/
- YOLOv8 as a Viam vision module: https://github.com/viam-labs/YOLOv8
- Local 3D visualiser for frames and point clouds: https://github.com/viamrobotics/visualization
- Viam MCP / agent kit: https://github.com/viamrobotics/viam-agentic-kit

**Simulation**
- MuJoCo (loads the xArm6 URDF, CPU on a Mac): https://mujoco.readthedocs.io
- Genesis, soft-body stems later: https://github.com/Genesis-Embodied-AI/Genesis
- Isaac Sim behind Viam APIs (needs an NVIDIA GPU): https://github.com/viam-modules/viam-isaac-sim

**Perception**
- YOLOE open-vocabulary detection + masks: https://docs.ultralytics.com/models/yoloe/
- SAM 2 (box-prompted masks): https://github.com/facebookresearch/sam2
- OWLv2 (one-shot image-guided detection): https://huggingface.co/docs/transformers/model_doc/owlv2

**Learning from demonstrations and grasping**
- LeRobot (ACT, diffusion policy, dataset format): https://github.com/huggingface/lerobot
- Movement primitives (replay one demo toward new goals): https://github.com/dfki-ric/movement_primitives
- Stem grasping from RGB-D, closest research code (GPL-3.0): https://github.com/StructuresComp/robotic-pollination
- Contact-GraspNet (6-DoF grasps; needs CUDA): https://github.com/NVlabs/contact_graspnet

**Arrangement and evaluation**
- Ikebana proportions (shin / soe / hikae): https://www.sunset.com/home-garden/flowers-plants/ikebana-flower-arranging-basics
- CLIP zero-shot second critic: https://github.com/mlfoundations/open_clip
- Rater agreement for blind ratings: https://github.com/pln-fing-udelar/fast-krippendorff
