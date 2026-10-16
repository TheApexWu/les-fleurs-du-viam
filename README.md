# Les Fleurs du Viam

A robot arm that arranges flowers to express a feeling. You type "gratitude" or "grief", the arm places stems in a vase with heights and leans chosen to say it, and a vision model that never saw the request guesses the feeling from a photo.

Viam hackathon, 16-17 Oct 2026, robot `armfarm12` (xArm, wrist camera, gripper).

**Today's plan, mental model and task list: [TODAY.md](TODAY.md).**

## Where we are (Fri 16 Oct, afternoon)

Done:
- Connected to armfarm12; resources are `arm`, `cam`, `gripper`, plus obstacle boxes `table`, `wall-front`, `wall-side`, `ceiling`.
- Vase measured with the arm (4 rim touches, circle fit within 5 mm): centre (300, -283), rim z 420, radius 59 mm. It sits on a black tape square; if it moves, re-measure.
- `recorder.py` logs hand-guided moves in manual mode and snapshots each resting pose with a photo.
- Code for gentle gripping, a grasp check, slow final approaches and the vase drop (`vase_one`). 11 offline tests pass. **None of the new moves have run on the arm yet.**

Next, in order:
1. Touch the table next to the tape once (gives the vase floor height).
2. `go_hub` with an empty gripper: checks the arm can reach the travel height (currently z 810, likely too high; shorter stems or a lower grip fix it).
3. `grip_calibrate` on a real stem; copy its number into `config.GRIP_STEM`.
4. Teach `slot0` (where the stem stands to be picked) with the recorder + `promote`.
5. `vase_one 0 0 15`: one stem into the vase, slowly, someone at the stop button.

Saturday: several stems with different heights and leans, the photo critic, and the planned-vs-random experiment for the demo.

## Run it

```
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cp .env.example .env    # then paste the address and API key from the Viam app's CONNECT tab
set -a; source .env; set +a
python flowers.py resources      # first, safe call
python3 -m pytest -q tests       # offline, no robot
```

Teaching a pose: start `python recorder.py`, put the arm in manual mode (support it from below before pressing the button), move it, hold still for a second at each spot. Then `python recorder.py promote p12 slot0 --down -15`.

## Files

| File | What it does |
|---|---|
| `flowers.py` | The robot: one command per step (`python flowers.py` lists them) |
| `config.py` | Names, speeds, gripper widths, the measured vase |
| `geometry.py` | Pose maths for picking and dropping (pure, tested) |
| `composition.py` | Turns a planned arrangement into placements |
| `ai.py` | Planner (feeling to arrangement) and blind critic (photo to feeling) |
| `recorder.py` | Records hand-guided poses and photos |
| `PLAN.md` | Original plan; written for a pin frog, the vase replaced it |

## Safety

Every new move runs slowly the first time, with one person's hand near the stop button. Exit manual mode before running any command that moves the arm.
