"""Names and measurements for armfarm12. Secrets come from .env (VIAM_ADDRESS, VIAM_API_KEY_ID,
VIAM_API_KEY, ANTHROPIC_API_KEY), never from this file."""
import json
import os
from pathlib import Path

ARM = os.environ.get("FLOWERS_ARM", "arm")
GRIPPER = os.environ.get("FLOWERS_GRIPPER", "gripper")
CAMERA = os.environ.get("FLOWERS_CAMERA", "cam")
MOTION = "builtin"
VISION = os.environ.get("FLOWERS_VISION", "vision-1")
FLOWER_CLASSIFIER = os.environ.get("FLOWERS_CLASSIFIER", "local")  # local, viam, or none (legacy HSV)
FLOWER_VISION = os.environ.get("FLOWERS_FLOWER_VISION", "flower-detector")
FLOWER_CLASSIFIER_CONFIDENCE = float(os.environ.get("FLOWERS_CLASSIFIER_CONFIDENCE", "0.3"))
BOUQUET_CALIBRATION = Path(__file__).parent / "vision_inventory.json"
PLAN_CHECK = True  # dry-run every planned move and refuse it if there is no full plan
PLAN_TIMEOUT_S = 30.0

# Gripper widths for the xArm module's DoCommand move_gripper (0 = closed, 850 = open).
# Automated picking uses semantic Grab/Open; GRIP_STEM is for teleop.py's G key.
GRIP_OPEN = 850
GRIP_STEM = 120          # teleop.py's G key only; automated pick uses semantic Grab()
GRIP_RELEASE_MARGIN = 150  # legacy direct-width release margin; semantic release uses Open()
GRIP_SPEED = 1000        # of 5000; faster calibration/grasp, still below the module's 1500 default
GRIP_EMPTY_MAX = 15      # a closed reading below this means the fingers met nothing
GRIP_MAX_STEM_WIDTH = 300  # reject contact this wide; a single stem should not stop near-open jaws

# Arm speed per move: quick in open air, slow within ~10 cm of the stem, pitcher or vase.
FAST_DEG_S, SLOW_DEG_S, ACCEL_DEG_S2 = 10.0, 10.0, 30.0
WRIST_DEG = -105.0       # plan-checked orientation; the saved pretend-loop poses use their captured orientations
VASE_STEM_BELOW_GRIP_MM = 200.0  # held chopstick below the fingers; measure on the real stems
VASE_DEPTH_MM = 250.0    # inside depth rim to floor: GUESS until measured with a ruler or a table touch
VASE_FLOOR_Z = None      # set after one fingertip touch on the table; until then only the rim is used
# Crossing height: the held stem's tip must clear the vase rim, not just the gripper.
TRAVEL_Z = 420.0 + VASE_STEM_BELOW_GRIP_MM + 40.0

STEMS = [
    {"colour": "red", "length_mm": 450, "bloom_mm": 70},
    {"colour": "red", "length_mm": 450, "bloom_mm": 70},
    {"colour": "yellow", "length_mm": 450, "bloom_mm": 70},
    {"colour": "yellow", "length_mm": 450, "bloom_mm": 70},
    {"colour": "magenta", "length_mm": 450, "bloom_mm": 70},
]
LEAN_CANDIDATES_DEG = (0, 60, 120, 180, 240, 300)
MIN_CLEARANCE_MM = 15.0
RELEASE_ABOVE_RIM_MM = 100.0

# Legacy slot/insertion commands; the bouquet flow uses the captured pickup template.
STEM_BELOW_GRIP_MM, INSERT_DEPTH_MM, APPROACH_MM, LIFT_MM = 90.0, 15.0, 50.0, 300.0

# Arm-measured 16 Oct: 4 rim touches fit a circle to +/-5 mm and agree on height to +/-4 mm.
# The team's config puts the vase at (360, 234), top z ~242: reconcile before trusting either.
VASE = {"x": 300.0, "y": -283.0, "rim_z": 420.0, "rim_r": 59.0}
TABLE_TOP_Z = -23.0  # from the cell's table obstacle; not touch-checked
VASE_BOX = {"center": (VASE["x"], VASE["y"], (TABLE_TOP_Z + VASE["rim_z"] + 5) / 2),
            "dims": (2 * VASE["rim_r"] + 20, 2 * VASE["rim_r"] + 20, VASE["rim_z"] + 5 - TABLE_TOP_Z)}

TAUGHT = Path(__file__).parent / "taught_poses.json"
TRANSFER_CLEARANCE = Path(__file__).parent / "transfer_clearance.json"


def taught() -> dict:
    return json.loads(TAUGHT.read_text()) if TAUGHT.exists() else {}
