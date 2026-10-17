"""Fixed taught slots for a labeled physical demo; pixels never generate poses.

Flower labels are the operator's staging contract, not classifier predictions.
The free-table backend and its calibration gates are independent and unchanged.
Setup commands only read hardware. No command here teaches by moving the arm.
"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import io
import json
import math
from pathlib import Path

from bouquet_core import FLOWER_STOCK, PICKUP_POSES, validate_pose
from bouquet_localization import _stem_pixel
from bouquet_markers import _axis_at_band, find_yellow_bands, image_polygon
from bouquet_vision import (ViamInventoryBackend, calibration_digest, load_calibration,
                            pose_matches, utc_now)
import config as K

EMPTY = "No detected stem has a calibrated pickup and reliable color evidence."
DEFAULT_PROFILE = Path(__file__).with_name("staged_demo.json")
LABELS = (("orange-lily", "lily", "orange"), ("yellow-lily", "lily", "yellow"),
          ("red-rose", "rose", "red"))


def digest(profile):
    return calibration_digest({"profile": {k: v for k, v in profile.items() if k != "verified_digest"},
                               "taught": K.taught(), "arm": K.ARM, "gripper": K.GRIPPER,
                               "clearance": json.loads(K.TRANSFER_CLEARANCE.read_text())})


def profile_errors(profile, *, require_verified=True):
    from flowers import clearance_waypoints, transfer_clearance
    errors = []
    if profile.get("version") != 1 or profile.get("mode") != "staged":
        errors.append("Use a separately captured staged-demo profile.")
    if any(not validate_pose(profile.get(key)) for key in ("scan_pose", "scan_camera_pose")):
        errors.append("Staged demo needs captured scan and camera poses.")
    slots = profile.get("slots", [])
    if not isinstance(slots, list) or len(slots) != 3:
        return errors + ["Capture three distinct staged pickup slots."]
    if {s.get("id") for s in slots} != {s[0] for s in LABELS}:
        errors.append("Use the three named orange-lily, yellow-lily and red-rose slots.")
    try:
        transfer_clearance()
    except (ValueError, RuntimeError, KeyError, TypeError) as exc:
        errors.append(str(exc))
    bounds = profile.get("workspace_bounds")
    valid_bounds = (isinstance(bounds, dict) and all(
        isinstance(bounds.get(k), list) and len(bounds[k]) == 2
        and all(isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n) for n in bounds[k])
        and bounds[k][0] < bounds[k][1] for k in "xyz"))
    if not valid_bounds:
        errors.append("Record measured XYZ bounds for the taught pickup slots and their clearance lifts.")
    seen, grasps = set(), []
    for slot in slots:
        label = slot.get("id", "unknown")
        if label in seen:
            errors.append("Staged slot IDs must be unique.")
        seen.add(label)
        if slot.get("color") not in FLOWER_STOCK.get(slot.get("variety"), ()):
            errors.append(f"Slot {label} has an unsupported staging label.")
        expected_label = next(((v, c) for i, v, c in LABELS if i == label), None)
        if (slot.get("variety"), slot.get("color")) != expected_label:
            errors.append(f"Slot {label} must retain its assigned variety/color.")
        poses, marker = slot.get("pickup_poses", {}), slot.get("marker")
        if not all(validate_pose(poses.get(n)) for n in PICKUP_POSES):
            errors.append(f"Capture the onsite-aligned pickup for {label}.")
            continue
        if (not isinstance(marker, dict) or not isinstance(marker.get("grasp_pixel"), list)
                or len(marker["grasp_pixel"]) != 2 or not isinstance(marker.get("band"), dict)):
            errors.append(f"Bind the scan-view tape mark for {label}.")
        grasps.append((label, [poses["pretend_grasp"][k] for k in "xyz"]))
        if valid_bounds:
            check = dict(poses)
            try:
                check.update(clearance_waypoints(dict(K.taught(), **poses)))
            except (ValueError, RuntimeError, KeyError, TypeError):
                pass
            for name in (*PICKUP_POSES, "pickup_clearance", "high_lift"):
                if name not in check:
                    continue
                p = check[name]
                xyz = [p[k] if isinstance(p, dict) else getattr(p, k) for k in "xyz"]
                if any(not bounds[k][0] <= value <= bounds[k][1] for k, value in zip("xyz", xyz)):
                    errors.append(f"{label} {name} is outside the measured pickup workspace.")
    for i, (first, point) in enumerate(grasps):
        for second, other in grasps[i + 1:]:
            if math.dist(point, other) < 40:
                errors.append(f"Teach {first} and {second} at least 40 mm apart.")
    marked = [s for s in slots if isinstance(s.get("marker"), dict)]
    for i, first in enumerate(marked):
        for second in marked[i + 1:]:
            if math.dist(first["marker"]["grasp_pixel"], second["marker"]["grasp_pixel"]) < 20:
                errors.append("Each staged slot needs a distinct tape mark.")
    if not K.PLAN_CHECK:
        errors.append("Native collision planning must remain enabled.")
    if require_verified and profile.get("verified_digest") != digest(profile):
        errors.append("Verify the resettable slots and new clearance route onsite; run staged verify afterward.")
    return list(dict.fromkeys(errors))


def marker_at(image, profile, pixel):
    polygon = image_polygon(profile["image_workspace_polygon"], image.size)
    bands = find_yellow_bands(image, polygon)
    matches = [b for b in bands if b["bbox"][0] <= pixel[0] < b["bbox"][2]
               and b["bbox"][1] <= pixel[1] < b["bbox"][3]]
    if len(matches) != 1:
        raise ValueError("The grasp pixel must lie inside exactly one visible yellow stem band.")
    band = matches[0]
    axis = _axis_at_band(image, band, polygon, _stem_pixel)
    dx, dy = band["direction"]
    delta = [pixel[k] - band["center"][k] for k in (0, 1)]
    if abs(delta[0] * dy - delta[1] * dx) > 5:
        raise ValueError("Grasp pixel is not on the tape's stem centerline.")
    if min(math.dist(pixel, end) for end in band["endpoints"]) < 5:
        raise ValueError("Choose a grasp point inside the band, clear of its ends.")
    return {"grasp_pixel": list(pixel), "band": band, "stem_direction": axis["direction"]}


class StagedInventoryBackend(ViamInventoryBackend):
    """Same serialized runner and FlowerBot, with three independently taught slots."""
    def __init__(self, profile_path=DEFAULT_PROFILE, *, allow_motion=False):
        super().__init__(profile_path, allow_motion=allow_motion)
        self.max_order_size = 3
        self.order_sequence = [row[0] for row in LABELS]
        self.verification = ("Staged physical demo: labels come from operator-assigned fixed slots. "
                             "Fresh marks, gripper release and two-frame source clearance are checked. "
                             "Landing inside the vase is not camera-verified.")

    async def _scan_once(self):
        from PIL import Image
        from bouquet_classifier import classify_detections, classify_frame
        profile = load_calibration(self.calibration_path)
        await self.connect()
        before = await self.current_pose()
        camera_pose = await self.current_pose(profile["camera"])
        frame, metadata = await self.capture_frame()
        image = Image.open(io.BytesIO(frame.data)).convert("RGB")
        output = io.BytesIO()
        image.save(output, "JPEG")
        self.jpeg = output.getvalue()
        errors = profile_errors(profile)
        # The legacy detector stays visible, without becoming a grasp source.
        flowers = []
        if K.FLOWER_CLASSIFIER == "viam":
            flowers = classify_detections(image, await self.flower_detector.get_detections(frame, timeout=10),
                                          K.FLOWER_CLASSIFIER_CONFIDENCE)
        elif K.FLOWER_CLASSIFIER == "local":
            flowers = await asyncio.to_thread(classify_frame, image, K.FLOWER_CLASSIFIER_CONFIDENCE)
        after = await self.current_pose()
        captured = metadata.captured_at.ToDatetime(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - captured).total_seconds()
        if not -2 <= age <= 10:
            errors.append("The staged camera frame is stale; scan again.")
        if (not pose_matches(before, profile.get("scan_pose"))
                or not pose_matches(after, profile.get("scan_pose"))
                or not pose_matches(camera_pose, profile.get("scan_camera_pose"))):
            errors.append("Return to the captured staged scan pose before building.")
        if (not pose_matches(before, after, translation_mm=1, rotation_deg=1)
                or await self.bot_is_moving()):
            errors.append("The arm must be stationary for a staged scan.")
        if list(image.size) != profile.get("image_size"):
            errors.append("The camera resolution changed; recapture staged setup.")
        polygon = image_polygon(profile["image_workspace_polygon"], image.size)
        bands = find_yellow_bands(image, polygon)
        candidates, occupied = [], []
        for slot in profile["slots"]:
            marker = slot.get("marker")
            if not marker:
                continue
            target = marker["grasp_pixel"]
            box = marker["band"]["bbox"]
            nearby = [b for b in bands if box[0] - 8 <= b["center"][0] <= box[2] + 8
                      and box[1] - 8 <= b["center"][1] <= box[3] + 8]
            # Bare stem at the old grasp also means occupied, even if tape vanished.
            patch = image.crop((max(0, round(target[0]) - 5), max(0, round(target[1]) - 12),
                                min(image.width, round(target[0]) + 6), min(image.height, round(target[1]) + 13)))
            if nearby or sum(_stem_pixel(rgb) for rgb in patch.getdata()) >= 12:
                occupied.append(slot["id"])
            else:
                continue
            reasons = []
            try:
                current = marker_at(image, profile, target)
                if len(nearby) != 1 or math.dist(current["band"]["center"], marker["band"]["center"]) > 3:
                    raise ValueError("Tape mark shifted or is ambiguous; reset this slot.")
                a, b = current["stem_direction"], marker["stem_direction"]
                if abs(sum(x * y for x, y in zip(a, b))) < math.cos(math.radians(5)):
                    raise ValueError("Stem direction changed; reset this slot.")
            except ValueError as exc:
                reasons.append(str(exc))
            poses = deepcopy(slot.get("pickup_poses", {}))
            candidates.append({"id": slot["id"], "slot_id": slot["id"], "variety": slot["variety"],
                               "color": slot["color"], "label_source": "operator_staged_slot",
                               "confidence": 1.0, "bbox": box, "grasp_pixel": target,
                               "pickup_poses": poses, "pickable": not reasons and not errors,
                               "blockers": reasons + errors, "localization_mode": "staged_slot",
                               "calibration_digest": digest(profile),
                               "world_grasp": [poses["pretend_grasp"][k] for k in "xyz"] if poses else None})
        if not any(c["pickable"] for c in candidates):
            errors.append(EMPTY)
        return {"mode": "live", "staged_demo": True, "ready": not errors,
                "blockers": errors, "detected_at": captured.isoformat(), "frame_captured_at": captured.isoformat(),
                "execution_enabled": self.allow_motion, "camera_url": "/api/frame.jpg", "image_size": list(image.size),
                "image_workspace_polygon": polygon, "grasp_bands": bands, "candidates": candidates,
                "occupied_slot_ids": occupied, "flower_detections": flowers, "raw_detection_count": len(bands),
                "label_source": "Operator-staged flowers; classifier boxes are display only.",
                "colors": [{"key": f"{s['variety']}:{s['color']}", "variety": s["variety"], "color": s["color"],
                            "label": f"{s['color'].title()} {s['variety']}",
                            "available": sum(c["slot_id"] == s["id"] and c["pickable"] for c in candidates),
                            "detected_count": int(s["id"] in occupied)} for s in profile["slots"]]}

    async def bot_is_moving(self):
        from viam.components.arm import Arm
        return await Arm.from_robot(self.robot, K.ARM).is_moving(timeout=10)

    async def scan(self):
        try:
            first = await self._scan_once()
            if self._verification_pending:
                second = await self._scan_once()
                for frame in (first, second):
                    if any(reason != EMPTY for reason in frame["blockers"]):
                        raise ValueError("Both source-verification frames need valid staged setup.")
                second["occupied_slot_ids"] = sorted(set(first["occupied_slot_ids"]) | set(second["occupied_slot_ids"]))
                second["source_verification_frames"] = 2
                first = second
                self._verification_pending = False
            self.snapshot = first
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.snapshot = {"mode": "offline", "staged_demo": True, "ready": False, "colors": [],
                             "blockers": [f"Staged scan blocked: {exc}"], "detected_at": utc_now(),
                             "candidates": [], "occupied_slot_ids": []}
        return deepcopy(self.snapshot)

    async def transfer(self, candidate, on_stage):
        profile = load_calibration(self.calibration_path)
        problems = profile_errors(profile)
        if not self.allow_motion or problems:
            raise RuntimeError("Staged physical execution is disabled. " + "; ".join(problems))
        if candidate.get("calibration_digest") != digest(profile):
            raise RuntimeError("Staged setup changed; rescan and recheck the order.")
        if not candidate.get("pickable") or not self.snapshot or not self.snapshot.get("ready"):
            raise RuntimeError("Staged mark is not ready for pickup.")
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(self.snapshot["detected_at"])).total_seconds()
        if not 0 <= age <= 10 or not pose_matches(await self.current_pose(), profile["scan_pose"]) or await self.bot_is_moving():
            raise RuntimeError("A fresh stationary scan is required before each staged pickup.")
        slot = next(s for s in profile["slots"] if s["id"] == candidate["slot_id"])
        if candidate["pickup_poses"] != slot["pickup_poses"]:
            raise RuntimeError("Staged poses differ from the taught slot.")
        from flowers import FlowerBot
        self.bot = self.bot or FlowerBot(self.robot)
        self._transfer_calibration, self._transfer_digest = profile, digest(profile)
        self._motion_started = True
        async def checked_stage(stage):
            if digest(load_calibration(self.calibration_path)) != self._transfer_digest:
                raise RuntimeError("Staged setup changed during transfer; stopped.")
            await on_stage(stage)
        await self.bot.pick_and_drop(slot["pickup_poses"], on_stage=checked_stage, use_taught_return=False)
        self._verification_pending = True

    async def return_to_scan(self):
        if not self.allow_motion or not self._motion_started:
            raise RuntimeError("Staged physical execution is disabled.")
        if digest(load_calibration(self.calibration_path)) != self._transfer_digest:
            raise RuntimeError("Staged setup changed before scan return.")
        from geometry import P
        await self.bot.move(P(**self._transfer_calibration["scan_pose"]))


def save(path, profile):
    from tempfile import NamedTemporaryFile
    path = Path(path)
    with NamedTemporaryFile("w", dir=path.parent, prefix=".staged-", delete=False) as stream:
        json.dump(profile, stream, indent=2, allow_nan=False)
        stream.write("\n")
        temp = Path(stream.name)
    temp.replace(path)


async def setup(args):
    path = Path(args.profile)
    if args.command == "init":
        if path.exists():
            raise ValueError("The staged profile already exists; preserve it.")
        original = load_calibration(K.BOUQUET_CALIBRATION)
        profile = {k: deepcopy(original.get(k)) for k in
                   ("camera", "vision_service", "image_size", "scan_pose", "scan_camera_pose", "image_workspace_polygon")}
        profile.update(version=1, mode="staged", workspace_bounds=None, verified_digest=None,
                       slots=[{"id": i, "variety": v, "color": c, "pickup_poses": {}, "marker": None}
                              for i, v, c in LABELS])
        save(path, profile)
        print(f"Created {path}: draft only; capture all three onsite-aligned slots.")
        return
    profile = load_calibration(path)
    if args.command == "verify":
        # This command is the operator's explicit verification, never run by init or the server.
        old = K.TRANSFER_CLEARANCE.read_text()
        try:
            clearance = json.loads(old)
            clearance["verified"] = True
            save(K.TRANSFER_CLEARANCE, clearance)
            profile["workspace_bounds"] = {k: getattr(args, k) for k in "xyz"}
            errors = profile_errors(profile, require_verified=False)
            if errors:
                raise ValueError("; ".join(errors))
            profile["verified_digest"] = digest(profile)
            save(path, profile)
        except BaseException:
            K.TRANSFER_CLEARANCE.write_text(old)
            raise
        print("Recorded the operator's onsite slot/workspace/clearance verification. No motion sent.")
        return
    slot = next((s for s in profile["slots"] if s["id"] == args.slot), None)
    if slot is None:
        raise ValueError("Use orange-lily, yellow-lily or red-rose.")
    backend = StagedInventoryBackend(path)
    try:
        await backend.connect()
        if await backend.bot_is_moving():
            raise ValueError("Stop and hold the arm stationary before capture.")
        actual = await backend.current_pose()
        if args.command == "capture":
            from viam.components.arm import Arm
            width = (await Arm.from_robot(backend.robot, K.ARM).do_command({"get_gripper": True}))["gripper_position"]
            if width < K.GRIP_OPEN - 50:
                raise ValueError("Capture the alignment hover with jaws open.")
            reference = K.taught()["pretend_grasp"]
            expected = dict(reference, x=actual["x"], y=actual["y"], z=reference["z"] + args.hover_mm)
            if args.hover_mm < 30 or not pose_matches(actual, expected, translation_mm=2, rotation_deg=2):
                raise ValueError("Use an aligned hover at least 30 mm above the taught grasp, with its exact orientation.")
            delta = {k: actual[k] - reference[k] for k in ("x", "y")}
            slot["pickup_poses"] = {n: dict(K.taught()[n], **{k: K.taught()[n][k] + delta[k] for k in delta})
                                    for n in PICKUP_POSES}
            slot["marker"] = None
            slot["operator_aligned_at"] = utc_now()
        else:
            if not pose_matches(actual, profile["scan_pose"]) or not pose_matches(
                    await backend.current_pose(profile["camera"]), profile["scan_camera_pose"]):
                raise ValueError("Return to the saved scan pose before binding a marker.")
            if not all(validate_pose(slot.get("pickup_poses", {}).get(n)) for n in PICKUP_POSES):
                raise ValueError("Capture the aligned pickup first.")
            from PIL import Image
            frame, metadata = await backend.capture_frame()
            age = (datetime.now(timezone.utc) - metadata.captured_at.ToDatetime(tzinfo=timezone.utc)).total_seconds()
            if not -2 <= age <= 10:
                raise ValueError("The marker frame is stale; capture again.")
            slot["marker"] = marker_at(Image.open(io.BytesIO(frame.data)).convert("RGB"), profile, args.pixel)
            slot["marker"]["captured_at"] = metadata.captured_at.ToJsonString()
        if (await backend.bot_is_moving() or not pose_matches(actual, await backend.current_pose(),
                                                            translation_mm=1, rotation_deg=1)):
            raise ValueError("The arm moved during capture; hold still and repeat.")
        profile["verified_digest"] = None
        save(path, profile)
        print(f"Captured {args.command} for {args.slot}; setup verification is required. No motion sent.")
    finally:
        await backend.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    capture = sub.add_parser("capture", help="Read an onsite-aligned open-jaw hover, without moving")
    capture.add_argument("slot", choices=[s[0] for s in LABELS])
    capture.add_argument("--hover-mm", type=float, default=30)
    capture.add_argument("--aligned", action="store_true", required=True,
                         help="Operator confirms the jaws are aligned over this slot's tape")
    marker = sub.add_parser("marker", help="Bind this slot's tape pixel in the saved scan view")
    marker.add_argument("slot", choices=[s[0] for s in LABELS])
    marker.add_argument("--pixel", nargs=2, type=float, required=True)
    verify = sub.add_parser("verify", help="Record operator verification after checking the new route onsite")
    verify.add_argument("--confirm-setup", action="store_true", required=True)
    for k in "xyz":
        verify.add_argument(f"--{k}", nargs=2, type=float, required=True)
    args = parser.parse_args()
    asyncio.run(setup(args))


if __name__ == "__main__":
    main()
