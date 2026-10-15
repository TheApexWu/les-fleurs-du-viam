"""Everything you set on the day. Names must match the machine's CONFIGURE tab.

Secrets come from the environment (.env, never committed):
  VIAM_ADDRESS, VIAM_API_KEY_ID, VIAM_API_KEY, ANTHROPIC_API_KEY
"""
import json
import os
from pathlib import Path

ARM = os.environ.get("FLOWERS_ARM", "arm-1")
GRIPPER = os.environ.get("FLOWERS_GRIPPER", "gripper-1")
CAMERA = os.environ.get("FLOWERS_CAMERA", "cam")
MOTION = "builtin"

# Gripper widths for the xArm module's DoCommand move_gripper (0 = closed, 850 = open).
# Tune on the day so a stem is held firmly without crushing: measure, don't guess.
GRIP_OPEN = 600
GRIP_STEM = 120

# Stem handling, mm. stem_below_grip = how far the stem tip hangs below the gripper's TCP.
STEM_BELOW_GRIP_MM = 90.0
INSERT_DEPTH_MM = 15.0
APPROACH_MM = 50.0
LIFT_MM = 120.0

TAUGHT = Path(__file__).parent / "taught_poses.json"


def taught() -> dict:
    """Poses recorded with `python flowers.py teach <name>`: tray slots, kenzan center, photo, home."""
    return json.loads(TAUGHT.read_text()) if TAUGHT.exists() else {}
