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
GRIP_STEM = 120          # replace with grip_calibrate's suggestion for the real stems
GRIP_RELEASE_MARGIN = 150  # open only this far past the stem on release, so it doesn't swing
GRIP_SPEED = 1500        # of 5000, the module default; rose stems are stiff enough (16 Oct)
GRIP_EMPTY_MAX = 15      # a closed reading below this means the fingers met nothing

# Arm speed per move: quick in open air, slow within ~10 cm of the stem, pitcher or vase.
FAST_DEG_S, SLOW_DEG_S, ACCEL_DEG_S2 = 40.0, 12.0, 150.0
WRIST_DEG = -15.0        # shared wrist spin for every pick and drop, so moves never twist
VASE_STEM_BELOW_GRIP_MM = 350.0  # held chopstick below the fingers; measure on the real stems
VASE_DEPTH_MM = 250.0    # inside depth rim to floor: GUESS until measured with a ruler or a table touch
VASE_FLOOR_Z = None      # set after one fingertip touch on the table; until then only the rim is used
# Crossing height: the held stem's tip must clear the vase rim, not just the gripper.
TRAVEL_Z = 420.0 + VASE_STEM_BELOW_GRIP_MM + 40.0

# Stem handling, mm. stem_below_grip = how far the stem tip hangs below the gripper's TCP.
STEM_BELOW_GRIP_MM = 90.0
INSERT_DEPTH_MM = 15.0
APPROACH_MM = 50.0
LIFT_MM = 300.0  # taped chopsticks are ~45 cm; this clears a ~20 cm pitcher

# Vase measured with the arm on 16 Oct: 4 fingertip touches on the rim fit a circle to +/-5 mm and
# agree on height to +/-4 mm. Box = rim diameter + 20 mm margin, table top up to just over the rim.
# Only valid while the vase sits on its black tape square.
VASE = {"x": 300.0, "y": -283.0, "rim_z": 420.0, "rim_r": 59.0}
TABLE_TOP_Z = -23.0  # from the cell's table obstacle; not yet checked by touch
VASE_BOX = {"center": (VASE["x"], VASE["y"], (TABLE_TOP_Z + VASE["rim_z"] + 5) / 2),
            "dims": (2 * VASE["rim_r"] + 20, 2 * VASE["rim_r"] + 20, VASE["rim_z"] + 5 - TABLE_TOP_Z)}

# The flowers bought 16 Oct. Lengths and bloom widths are placeholders until measured after trimming.
STEMS = [
    {"colour": "red", "length_mm": 450, "bloom_mm": 70},
    {"colour": "red", "length_mm": 450, "bloom_mm": 70},
    {"colour": "yellow", "length_mm": 450, "bloom_mm": 70},
    {"colour": "yellow", "length_mm": 450, "bloom_mm": 70},
    {"colour": "magenta", "length_mm": 450, "bloom_mm": 70},
]
LEAN_CANDIDATES_DEG = (0, 60, 120, 180, 240, 300)
MIN_CLEARANCE_MM = 15.0
# Release this far up the stem from the rim. Modelled 16 Oct (placeholder stems): the gripper, not the
# stems, limits the third stem; 40 mm gives -16 mm clearance, 100 mm gives +3, 160 mm gives -1.
RELEASE_ABOVE_RIM_MM = 100.0

TAUGHT = Path(__file__).parent / "taught_poses.json"


def taught() -> dict:
    """Poses recorded with `python flowers.py teach <name>`: tray slots, kenzan center, photo, home."""
    return json.loads(TAUGHT.read_text()) if TAUGHT.exists() else {}
