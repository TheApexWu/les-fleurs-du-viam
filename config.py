"""Names and measurements for armfarm12. Secrets come from .env (VIAM_ADDRESS, VIAM_API_KEY_ID,
VIAM_API_KEY, ANTHROPIC_API_KEY), never from this file."""
import json
import os
from pathlib import Path

ARM = os.environ.get("FLOWERS_ARM", "arm")
GRIPPER = os.environ.get("FLOWERS_GRIPPER", "gripper")
CAMERA = os.environ.get("FLOWERS_CAMERA", "cam")
MOTION = "builtin"
PLAN_CHECK = True  # dry-run every planned move and refuse it if there is no full plan
PLAN_TIMEOUT_S = 30.0

GRIP_STEM = 120     # move_gripper width for holding a stem (0 closed, 850 open)
GRIP_SPEED = 1500   # module default; rose stems are stiff enough

# Plan-checked 16 Oct over the vase, gripper down: wrist -15 makes the wrist hit the camera, -105 plans;
# z 600 is the highest reachable point there.
WRIST_DEG = -105.0

# Arm-measured 16 Oct: 4 rim touches fit a circle to +/-5 mm and agree on height to +/-4 mm.
# The team's config puts the vase at (360, 234), top z ~242: reconcile before trusting either.
VASE = {"x": 300.0, "y": -283.0, "rim_z": 420.0, "rim_r": 59.0}
TABLE_TOP_Z = -23.0  # from the cell's table obstacle; not touch-checked
VASE_BOX = {"center": (VASE["x"], VASE["y"], (TABLE_TOP_Z + VASE["rim_z"] + 5) / 2),
            "dims": (2 * VASE["rim_r"] + 20, 2 * VASE["rim_r"] + 20, VASE["rim_z"] + 5 - TABLE_TOP_Z)}

TAUGHT = Path(__file__).parent / "taught_poses.json"


def taught() -> dict:
    return json.loads(TAUGHT.read_text()) if TAUGHT.exists() else {}
