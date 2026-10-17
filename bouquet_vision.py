"""Read-only vision inventory, with separately enabled physical transfer methods.

No constructor, scan, camera request, or cleanup moves the arm/gripper. Physical
methods require allow_motion=True and verified calibration. The supervised
one-flower limit adds restrictions and never bypasses calibration gates.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
import logging
import math
from pathlib import Path

from bouquet_core import COLORS, FLOWER_STOCK, build_inventory, classify_bloom_pixels, validate_pose
import config as K

logger = logging.getLogger(__name__)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def default_calibration():
    return {
        "version": 2, "mode": "table", "camera": K.CAMERA, "vision_service": K.VISION,
        "image_size": [1280, 720], "scan_pose": None, "scan_camera_pose": None,
        "table_plane_z_mm": None, "workspace_bounds": None,
        "reference": {"pixel": None, "axis_pixels": None, "pickup_poses": {}, "verified": False},
        "minimum_confidence": 0.5, "max_pickup_offset_mm": 150,
        "max_yaw_delta_deg": 90, "minimum_separation_mm": 40, "grasp_fraction": 0.6,
    }


def load_calibration(path):
    path = Path(path)
    if not path.exists():
        return default_calibration()
    result = json.loads(path.read_text())
    if not isinstance(result, dict):
        raise ValueError("Vision calibration must be a JSON object")
    return result


def calibration_digest(calibration):
    return hashlib.sha256(json.dumps(calibration, sort_keys=True, allow_nan=False).encode()).hexdigest()


def execution_digest(calibration):
    taught = K.taught()
    return calibration_digest({"vision": calibration, "arm": K.ARM, "gripper": K.GRIPPER,
                               "classifier": K.FLOWER_CLASSIFIER,
                               "classifier_service": K.FLOWER_VISION,
                               "classifier_confidence": K.FLOWER_CLASSIFIER_CONFIDENCE,
                               "transfer_clearance": (json.loads(K.TRANSFER_CLEARANCE.read_text())
                                                      if K.TRANSFER_CLEARANCE.exists() else None),
                               "vase_path": {key: taught.get(key) for key in ("vase_approach", "pretend_release")}})


def normalize_table_candidate(candidate):
    """Localization uses axis endpoints; order tracking compares direction vectors."""
    axis = candidate.get("world_axis")
    if isinstance(axis, (list, tuple)) and len(axis) == 2 and all(
            isinstance(point, (list, tuple)) and len(point) == 3 for point in axis):
        candidate["world_axis_endpoints"] = deepcopy(axis)
        candidate["world_axis"] = [axis[1][index] - axis[0][index] for index in range(3)]
    return candidate


def pose_dict(pose):
    return {field: float(getattr(pose, field)) for field in ("x", "y", "z", "o_x", "o_y", "o_z", "theta")}


def pose_matches(actual, expected, translation_mm=4.0, rotation_deg=4.0):
    """Compare full rotations using Viam's quaternion conversion (including OV poles)."""
    if not validate_pose(actual) or not validate_pose(expected):
        return False
    if math.dist([actual[k] for k in "xyz"], [expected[k] for k in "xyz"]) > translation_mm:
        return False
    from viam.proto.common import Pose
    from viam.spatialmath import Quaternion
    qa, qb = Quaternion.from_pose(Pose(**actual)), Quaternion.from_pose(Pose(**expected))
    dot = abs(sum(getattr(qa, k) * getattr(qb, k) for k in ("w", "i", "j", "k")))
    return math.degrees(2 * math.acos(min(1.0, dot))) <= rotation_deg


def camera_geometry_for_scan(camera_pose, intrinsics, calibration, *, commissioning=False):
    """Keep reported FK checks separate from an explicitly non-executable preview."""
    from viam.proto.common import Pose
    from viam.spatialmath import Quaternion

    preview = calibration.get("projection_preview")
    blockers = []
    projection_pose = camera_pose
    if preview is not None:
        if not isinstance(preview, dict) or not validate_pose(preview.get("camera_pose_world")):
            raise ValueError("Preview camera correction needs a valid camera_pose_world.")
        if intrinsics != preview.get("intrinsics"):
            raise ValueError("Camera intrinsics changed; preview correction is no longer applicable.")
        if not pose_matches(camera_pose, preview.get("reported_camera_pose"), translation_mm=1, rotation_deg=1):
            expected = preview.get("reported_camera_pose")
            detail = ""
            if validate_pose(camera_pose) and validate_pose(expected):
                offset = math.dist([camera_pose[k] for k in "xyz"], [expected[k] for k in "xyz"])
                detail = f" Camera position is {offset:.1f} mm from its saved position."
            raise ValueError("Camera left the measured view; preview correction is no longer applicable."
                             + detail + " Restore the saved scan pose before table localization.")
        projection_pose = preview["camera_pose_world"]
        blockers.append("Camera correction is preview only; robot-world alignment and motion bounds remain unverified.")
    return {"intrinsics": intrinsics, "position": [projection_pose[k] for k in "xyz"],
            "rotation": Quaternion.from_pose(Pose(**projection_pose)).to_rotation_matrix().elements}, blockers


def _center(box):
    return [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2]


def _near_box(a, b):
    """Conservative same-view occupancy matching; ambiguity blocks execution."""
    return math.dist(_center(a), _center(b)) <= 35


class DetectionTracker:
    """Stable identities across scans at the calibrated camera pose."""
    def __init__(self):
        self.tracks = {}
        self.sequence = 0

    def update(self, snapshot):
        candidates = snapshot.get("candidates", [])
        matches = {}
        for index, candidate in enumerate(candidates):
            bbox = candidate.get("bbox")
            if not isinstance(bbox, list) or len(bbox) != 4:
                continue
            matches[index] = [key for key, previous in self.tracks.items()
                              if _near_box(bbox, previous["bbox"])]
        ambiguous = {index for index, ids in matches.items() if len(ids) > 1}
        for ids in matches.values():
            for track_id in ids:
                group = [index for index, other in matches.items() if track_id in other]
                if len(group) > 1:
                    ambiguous.update(group)
        new_tracks = {}
        id_map = {}
        for index, candidate in enumerate(candidates):
            old_id = candidate.get("id")
            ids = matches.get(index, [])
            if index in ambiguous or not ids:
                self.sequence += 1
                track_id = f"rose-{self.sequence:04d}"
            else:
                track_id = ids[0]
            id_map[old_id] = track_id
            candidate.update(id=track_id, slot_id=track_id)
            if index in ambiguous:
                candidate["pickable"] = False
                candidate.setdefault("blockers", []).append("Rose identity is ambiguous between scans.")
            if "bbox" in candidate:
                new_tracks[track_id] = deepcopy(candidate)
        self.tracks = new_tracks
        snapshot["occupied_slot_ids"] = [id_map.get(key, key) for key in snapshot.get("occupied_slot_ids", [])]
        if ambiguous:
            snapshot["ready"] = False
            snapshot.setdefault("blockers", []).append("Roses are too close to track uniquely; separate overlapping stems.")
        for row in snapshot.get("colors", []):
            row["available"] = sum(bool(c.get("pickable")) and c.get("color") == row["color"]
                                   and c.get("variety", "rose") == row.get("variety", "rose") for c in candidates)
        return snapshot


class ViamInventoryBackend:
    def __init__(self, calibration_path=K.BOUQUET_CALIBRATION, *, allow_motion=False, commission_one=False):
        if commission_one and not allow_motion:
            raise ValueError("Commissioning requires explicit --allow-motion.")
        self.calibration_path = Path(calibration_path)
        self.allow_motion = allow_motion
        self.commission_one = commission_one
        self.commissioning_used = False
        self.max_order_size = 1 if commission_one else 12
        if commission_one:
            K.FAST_DEG_S, K.SLOW_DEG_S = min(K.FAST_DEG_S, 6), min(K.SLOW_DEG_S, 6)
            K.ACCEL_DEG_S2 = min(K.ACCEL_DEG_S2, 30)
        self.robot = self.camera = self.detector = self.flower_detector = self.motion = self.bot = None
        self._connect_lock = asyncio.Lock()
        self.snapshot = None
        self.jpeg = None
        self.tracker = DetectionTracker()
        self._last_digest = None
        self._last_pick = None
        self._verification_pending = False
        self._motion_started = False
        self._transfer_calibration = None
        self._transfer_digest = None
        self._resource_names = None

    async def connect(self):
        async with self._connect_lock:
            if self.robot is not None:
                return
            from flowers import connect
            from viam.components.camera import Camera
            from viam.services.motion import MotionClient
            from viam.services.vision import VisionClient
            calibration = load_calibration(self.calibration_path)
            robot = await connect()
            try:
                camera = Camera.from_robot(robot, calibration.get("camera", K.CAMERA))
                detector = VisionClient.from_robot(robot, calibration.get("vision_service", K.VISION))
                motion = MotionClient.from_robot(robot, K.MOTION)
                properties = await detector.get_properties(timeout=10)
                if not properties.detections_supported:
                    raise ValueError("The configured vision service must support object detections.")
                if K.FLOWER_CLASSIFIER == "viam":
                    flower_detector = VisionClient.from_robot(robot, K.FLOWER_VISION)
                    if not (await flower_detector.get_properties(timeout=10)).detections_supported:
                        raise ValueError("The flower vision service must support object detections.")
                    self.flower_detector = flower_detector
                self.robot, self.camera, self.detector, self.motion = robot, camera, detector, motion
                self._resource_names = (calibration.get("camera", K.CAMERA), calibration.get("vision_service", K.VISION))
            except BaseException:
                await robot.close()
                raise

    async def current_pose(self, component=K.GRIPPER):
        await self.connect()
        return pose_dict((await self.motion.get_pose(component, "world", timeout=10)).pose)

    async def capture_frame(self):
        await self.connect()
        frames, metadata = await self.camera.get_images(filter_source_names=["color"], timeout=10)
        frame = next((item for item in frames if item.name == "color"), None)
        if frame is None:
            raise ValueError("Camera returned no color frame.")
        return frame, metadata

    async def _scan_once(self):
        from PIL import Image

        calibration = load_calibration(self.calibration_path)
        if self.commission_one:
            from bouquet_commissioning import check_commissioning
            check_commissioning(calibration)
        await self.connect()
        if self._resource_names != (calibration.get("camera", K.CAMERA), calibration.get("vision_service", K.VISION)):
            raise ValueError("Camera/vision resource names changed; restart the bouquet server.")
        digest = execution_digest(calibration)
        if digest != self._last_digest:
            self.tracker = DetectionTracker()
            self._last_digest = digest
        before = await self.current_pose()
        camera_pose = await self.current_pose(calibration.get("camera", K.CAMERA))
        frame, metadata = await self.capture_frame()
        # The detector and the blossom color code consume exactly the SAME frame.
        image = Image.open(io.BytesIO(frame.data)).convert("RGB")
        flowers = None
        if K.FLOWER_CLASSIFIER == "local":
            from bouquet_classifier import classify_frame
            detections, flowers = await asyncio.gather(
                self.detector.get_detections(frame, timeout=20),
                asyncio.to_thread(classify_frame, image, K.FLOWER_CLASSIFIER_CONFIDENCE))
        elif K.FLOWER_CLASSIFIER == "viam":
            from bouquet_classifier import classify_detections
            detections, flower_boxes = await asyncio.gather(
                self.detector.get_detections(frame, timeout=20),
                self.flower_detector.get_detections(frame, timeout=20))
            flowers = await asyncio.to_thread(classify_detections, image, flower_boxes,
                                             K.FLOWER_CLASSIFIER_CONFIDENCE)
        elif K.FLOWER_CLASSIFIER == "none":
            detections = await self.detector.get_detections(frame, timeout=20)
        else:
            raise ValueError("FLOWERS_CLASSIFIER must be local, viam or none.")
        after = await self.current_pose()
        output = io.BytesIO()
        image.save(output, format="JPEG")
        self.jpeg = output.getvalue()
        context = []
        reference = calibration.get("reference")
        if not isinstance(reference, dict) or reference.get("verified") is not True:
            context.append("Table/reference calibration is unverified; generated poses are preview only.")
        if not K.PLAN_CHECK:
            context.append("Enable motion plan checks before using generated pickup poses.")
        if any(not validate_pose(K.taught().get(key)) for key in ("vase_approach", "pretend_release")):
            context.append("The saved vase approach/release poses are missing or invalid.")
        try:
            from flowers import transfer_clearance
            transfer_clearance()
        except (ValueError, RuntimeError, KeyError, TypeError) as exc:
            context.append(str(exc))
        expected = calibration.get("scan_pose")
        if not pose_matches(before, expected) or not pose_matches(after, expected):
            context.append("Camera is not at its calibrated scan pose; return to that pose or recapture it.")
        if not pose_matches(before, after, translation_mm=1, rotation_deg=1):
            context.append("Arm moved while capturing inventory; repeat the scan while stationary.")
        expected_camera = calibration.get("scan_camera_pose")
        if not pose_matches(camera_pose, expected_camera):
            context.append("Camera frame calibration is missing or differs from the saved scan frame.")
        if list(image.size) != calibration.get("image_size"):
            context.append("Camera resolution differs from calibration.")
        captured_at = None
        timestamp = getattr(metadata, "captured_at", None)
        if timestamp is not None and timestamp.seconds:
            captured_at = timestamp.ToDatetime(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - captured_at).total_seconds()
            if not 0 <= age <= 25:
                context.append("Camera frame timestamp is stale or in the future.")
        else:
            context.append("Camera did not supply a capture timestamp.")
        raw = [{"bbox": [int(d.x_min), int(d.y_min), int(d.x_max), int(d.y_max)],
                "class_name": d.class_name, "confidence": float(d.confidence)} for d in detections]
        if calibration.get("mode", "table") == "table":
            from bouquet_localization import table_inventory
            properties = await self.camera.get_properties(timeout=10)
            p = properties.intrinsic_parameters
            distortion = properties.distortion_parameters
            if distortion and any(abs(value) > 1e-9 for value in distortion.parameters):
                context.append("Nonzero lens distortion needs image undistortion before table projection.")
            intrinsics = {"fx": p.focal_x_px, "fy": p.focal_y_px,
                          "cx": p.center_x_px, "cy": p.center_y_px,
                          "width": p.width_px, "height": p.height_px}
            try:
                geometry, projection_blockers = camera_geometry_for_scan(camera_pose, intrinsics, calibration,
                                                                        commissioning=self.commission_one)
            except ValueError as error:
                # A reachable camera with an invalid calibrated view is not offline.
                # Keep the fresh image/classifier evidence; emit no robot coordinates
                # and do not reuse the old image workspace or reference at this view.
                context.append(str(error))
                geometry = None
                logger.warning("Table localization blocked: %s", error)
                snapshot = {"ready": False, "blockers": list(dict.fromkeys(context)), "warnings": [],
                            "camera": calibration.get("camera"), "vision_service": calibration.get("vision_service"),
                            "raw_detection_count": len(raw), "detections": raw, "candidates": [], "blossoms": [],
                            "occupied_slot_ids": [], "colors": [], "classification_only": True,
                            "occupancy_known": False, "localization_status": "invalid_scan_geometry"}
            else:
                context.extend(projection_blockers)
                snapshot = table_inventory(raw, image, calibration, geometry, context_blockers=context,
                                           flower_detections=flowers, commissioning=self.commission_one)
            if self.commission_one:
                from bouquet_commissioning import check_pickup_region
                for candidate in snapshot.get("candidates", []):
                    if not candidate.get("pickup_poses"):
                        continue
                    try:
                        check_pickup_region(calibration, candidate)
                    except ValueError as error:
                        candidate["blockers"].append(str(error))
                        candidate["pickable"] = False
                if snapshot.get("candidates") and not any(c.get("pickable") for c in snapshot["candidates"]):
                    snapshot["ready"] = False
                    snapshot["blockers"].append("No flower passes the commissioning pickup-region checks.")
                snapshot["commissioning"] = True
                snapshot["commissioning_attempt_used"] = self.commissioning_used
                snapshot["warnings"].append("One supervised flower attempt per server process; verified calibration and workspace are still required.")
            for candidate in snapshot.get("candidates", []):
                normalize_table_candidate(candidate)
                candidate.update(localization_mode="table", calibration_digest=digest)
            if flowers is not None:
                plurals = {"rose": "roses", "carnation": "carnations", "lily": "lilies"}
                snapshot["flower_detections"] = flowers
                snapshot["classifier"] = (f"viam:{K.FLOWER_VISION}" if K.FLOWER_CLASSIFIER == "viam"
                                          else "vision/flowers_detect.py")
                snapshot["colors"] = [
                    {"key": f"{variety}:{color}", "variety": variety, "color": color,
                     "label": f"{color.replace('-', ' ').title()} {plurals[variety]}", "available": 0,
                     "detected_count": sum(b.get("variety") == variety and b.get("color", b.get("colour")) == color
                                           for b in (flowers if geometry is None else snapshot["blossoms"]))}
                    for variety, colors in FLOWER_STOCK.items() for color in colors]
            snapshot = self.tracker.update(snapshot)
        else:
            slot_colors = {}
            for slot in calibration.get("slots", []):
                roi = slot.get("bloom_roi")
                if isinstance(roi, list) and len(roi) == 4 and all(isinstance(v, (int, float)) for v in roi):
                    x0, y0, x1, y1 = roi
                    if 0 <= x0 < x1 <= image.width and 0 <= y0 < y1 <= image.height:
                        crop = image.crop(tuple(map(int, roi)))
                        crop.thumbnail((100, 100))
                        slot_colors[slot["id"]] = classify_bloom_pixels(crop.getdata())
            snapshot = build_inventory(raw, calibration, slot_colors, context,
                                       confidence_threshold=calibration.get("minimum_confidence", 0.5))
            for candidate in snapshot.get("candidates", []):
                candidate["calibration_digest"] = digest
        snapshot.update(mode="live", detected_at=captured_at.isoformat() if captured_at else utc_now(), camera_url="/api/frame.jpg",
                        frame_captured_at=captured_at.isoformat() if captured_at else None,
                        execution_enabled=self.allow_motion, calibration_digest=digest,
                        flower_classifier=K.FLOWER_CLASSIFIER,
                        flower_vision_service=K.FLOWER_VISION if K.FLOWER_CLASSIFIER == "viam" else None,
                        image_size=list(image.size), scan_pose=after)
        logger.info("scan frame=%s detector=%s raw_stems=%d classified_flowers=%s candidates=%d pickable=%d ready=%s blockers=%s",
                    snapshot["frame_captured_at"], calibration.get("vision_service", K.VISION), len(raw),
                    len(flowers) if flowers is not None else "legacy", len(snapshot.get("candidates", [])),
                    sum(c.get("pickable") is True for c in snapshot.get("candidates", [])),
                    snapshot.get("ready"), snapshot.get("blockers", []))
        logger.info("stem detections=%s", raw)
        for candidate in snapshot.get("candidates", []):
            logger.info("candidate=%s flower=%s:%s confidence=%s grasp_mm=%s yaw_deg=%s stem_width_px=%s pickable=%s blockers=%s",
                        candidate.get("id"), candidate.get("variety", "rose"), candidate.get("color"),
                        candidate.get("confidence"), candidate.get("world_grasp"), candidate.get("yaw_delta_deg"),
                        candidate.get("stem_fit_width_px"), candidate.get("pickable"), candidate.get("blockers", []))
        if not raw and flowers:
            logger.warning("Flower heads detected, but %s returned zero stems. No grasp candidate is available; no pickup is permitted.",
                           calibration.get("vision_service", K.VISION))
        return snapshot

    async def scan(self):
        try:
            first = await self._scan_once()
            if self._verification_pending:
                second = await self._scan_once()
                for frame in (first, second):
                    reasons = [reason for reason in frame.get("blockers", [])
                               if reason != "No detected stem has a calibrated pickup and reliable color evidence."]
                    if reasons or frame.get("classification_only"):
                        raise RuntimeError("Source verification needs two valid localized frames: "
                                           + "; ".join(reasons or ["Pickup localization is unavailable."]))
                occupied = set(first.get("occupied_slot_ids", [])) | set(second.get("occupied_slot_ids", []))
                source = self._last_pick
                if source is not None:
                    for snapshot in (first, second):
                        # A raw stem near the old grasp still counts as occupied, even
                        # if blossom matching or identity inference failed this time.
                        if any(_near_box(d["bbox"], source["bbox"]) for d in snapshot.get("detections", [])):
                            occupied.add(source["slot_id"])
                        # A missed stem must not make a still-visible classified
                        # flower head count as a successful source disappearance.
                        if source.get("blossom_bbox") and any(
                                _near_box(b["bbox"], source["blossom_bbox"])
                                for b in snapshot.get("blossoms", [])):
                            occupied.add(source["slot_id"])
                second["occupied_slot_ids"] = sorted(occupied)
                second["source_verification_frames"] = 2
                first = second
                self._verification_pending = False
            self.snapshot = first
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Live inventory scan failed")
            self.snapshot = {"mode": "offline", "ready": False,
                             "blockers": [f"Vision unavailable: {type(exc).__name__}: {str(exc)[:220]}"],
                             "colors": [{"color": color, "label": color.title(), "available": 0} for color in COLORS],
                             "candidates": [], "occupied_slot_ids": [], "raw_detection_count": 0,
                             "detected_at": utc_now(), "execution_enabled": self.allow_motion}
        return deepcopy(self.snapshot)

    async def transfer(self, candidate, on_stage):
        if not self.allow_motion:
            raise RuntimeError("Physical execution is disabled; use the read-only preview tonight.")
        calibration = load_calibration(self.calibration_path)
        if self.commission_one:
            from bouquet_commissioning import check_pickup_region
            if self.commissioning_used:
                raise RuntimeError("The single commissioning attempt is used; inspect the result before restarting.")
            check_pickup_region(calibration, candidate)
        if calibration.get("projection_preview") is not None:
            raise RuntimeError("Preview camera corrections cannot execute physical transfers.")
        reference = calibration.get("reference")
        if not isinstance(reference, dict) or reference.get("verified") is not True:
            raise RuntimeError("Measured calibration must be explicitly verified before any physical transfer.")
        if candidate.get("calibration_digest") != execution_digest(calibration):
            raise RuntimeError("Calibration changed after inventory scan; rescan before moving.")
        if not K.PLAN_CHECK:
            raise RuntimeError("Generated pickup poses require motion plan checks.")
        if not candidate.get("pickable") or not self.snapshot or not self.snapshot.get("ready"):
            raise RuntimeError("Candidate lacks verified localization.")
        if not pose_matches(await self.current_pose(), calibration.get("scan_pose")):
            raise RuntimeError("Arm left the calibrated scan pose before pickup.")
        from flowers import FlowerBot
        self.bot = self.bot or FlowerBot(self.robot)
        self._last_pick = deepcopy(candidate)
        self._transfer_calibration = deepcopy(calibration)
        self._transfer_digest = execution_digest(calibration)
        if self.commission_one:
            self.commissioning_used = True
        self._motion_started = True
        logger.info("transfer candidate=%s pickup_poses=%s", candidate.get("id"), candidate["pickup_poses"])
        await self.bot.pick_and_drop(candidate["pickup_poses"], on_stage=on_stage, use_taught_return=False)
        self._verification_pending = True

    async def return_to_scan(self):
        if not self.allow_motion or not self._motion_started:
            raise RuntimeError("Physical execution is disabled.")
        calibration = self._transfer_calibration
        if execution_digest(load_calibration(self.calibration_path)) != self._transfer_digest:
            raise RuntimeError("Calibration changed during transfer; inspect before continuing.")
        from geometry import P
        await self.bot.speed(fast=False)
        await self.bot.move(P(**calibration["scan_pose"]))

    async def stop(self):
        # Even pressing Stop on a read-only page never sends a hardware command.
        if self.allow_motion and self._motion_started and self.bot is not None:
            results = await asyncio.gather(self.bot.arm.stop(), self.bot.gripper.stop(), return_exceptions=True)
            failures = [type(result).__name__ for result in results if isinstance(result, BaseException)]
            if failures:
                raise RuntimeError("Stop was not acknowledged: " + ", ".join(failures))

    async def close(self):
        if self.robot is not None:
            await self.robot.close()
            self.robot = None


class DemoInventoryBackend:
    """An explicit in-memory simulation; never constructs a robot connection."""
    def __init__(self):
        pose = {"x": 200., "y": 100., "z": 100., "o_x": 0., "o_y": 0., "o_z": -1., "theta": 0.}
        stock = [(variety, color) for variety, colors in FLOWER_STOCK.items()
                 for color in colors for _ in range(2)]
        self.candidates = [{"id": f"demo-{i}", "slot_id": f"demo-{i}", "variety": variety, "color": color,
                            "confidence": 0.98, "bbox": [50 + i % 7 * 160, 80 + i // 7 * 300,
                                                       90 + i % 7 * 160, 280 + i // 7 * 300],
                            "pickable": True, "blockers": [],
                            "pickup_poses": {key: dict(pose, x=200. + i * 40) for key in
                                             ("pickup_approach", "pretend_grasp", "lift")}}
                           for i, (variety, color) in enumerate(stock)]
        self.snapshot = None
        self.jpeg = None

    async def scan(self):
        self.snapshot = {"mode": "demo", "ready": bool(self.candidates),
                         "blockers": [] if self.candidates else ["No detected stem has a calibrated pickup and reliable color evidence."],
                         "candidates": deepcopy(self.candidates), "detected_at": utc_now(),
                         "colors": [{"key": f"{v}:{c}", "variety": v, "color": c,
                                     "label": f"{c.replace('-', ' ').title()} {v}",
                                     "detected_count": sum(x["variety"] == v and x["color"] == c for x in self.candidates),
                                     "available": sum(x["variety"] == v and x["color"] == c for x in self.candidates)}
                                    for v, colors in FLOWER_STOCK.items() for c in colors],
                         "occupied_slot_ids": [c["id"] for c in self.candidates],
                         "raw_detection_count": len(self.candidates), "execution_enabled": False}
        return deepcopy(self.snapshot)

    async def transfer(self, candidate, on_stage):
        for stage in ("pickup_approach", "grasped", "lifted", "rotation_clearance", "released",
                      "vase_withdrawn", "vase_cleared", "returned"):
            await asyncio.sleep(0.15)
            await on_stage(stage)
        self.candidates = [c for c in self.candidates if c["id"] != candidate["id"]]

    async def return_to_scan(self):
        await asyncio.sleep(0)

    async def stop(self):
        pass

    async def close(self):
        pass
