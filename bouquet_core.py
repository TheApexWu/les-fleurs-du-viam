"""Pure inventory and order planning for camera-calibrated flower pickup slots.

Pixels only identify a calibrated slot. They are never converted to arm coordinates.
This module has no robot/network dependencies and never moves hardware.
"""
from __future__ import annotations

import colorsys
import math
from collections import Counter
from collections.abc import Mapping
from copy import deepcopy


COLORS = ("red", "yellow", "magenta", "pink", "white", "red-white", "orange", "purple", "cyan", "blue")
VARIETIES = ("rose", "carnation", "lily")
FLOWER_STOCK = {"rose": ("red", "yellow", "pink"), "carnation": ("white", "red-white"), "lily": ("orange", "yellow")}
POSE_FIELDS = ("x", "y", "z", "o_x", "o_y", "o_z", "theta")
PICKUP_POSES = ("pickup_approach", "pretend_grasp", "lift")
MAX_ORDER_SIZE = 12


def _number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, ValueError):
        return False


def _sequence(value, length):
    return isinstance(value, (list, tuple)) and len(value) == length


def validate_pose(pose):
    """Return whether a complete finite Viam orientation-vector pose is usable."""
    return (
        isinstance(pose, Mapping)
        and all(_number(pose.get(key)) for key in POSE_FIELDS)
        and math.hypot(pose["o_x"], pose["o_y"], pose["o_z"]) > 1e-9
    )


def _image_size(value):
    if not _sequence(value, 2):
        return None
    if not all(isinstance(n, int) and not isinstance(n, bool) and n > 0 for n in value):
        return None
    return list(value)


def _box(value, image_size):
    if not _sequence(value, 4) or not all(_number(n) for n in value):
        return None
    x0, y0, x1, y1 = value
    if not (0 <= x0 < x1 <= image_size[0] and 0 <= y0 < y1 <= image_size[1]):
        return None
    return list(value)


def _iou(a, b):
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0, min(a[3], b[3]) - max(a[1], b[1])
    )
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union else 0.0


def _contains_center(roi, bbox):
    x, y = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    return roi[0] <= x < roi[2] and roi[1] <= y < roi[3]


def _unique(values):
    return list(dict.fromkeys(values))


def classify_bloom_pixels(pixels):
    """Conservatively classify an RGB blossom ROI, returning evidence and a reason.

    Green leaves, dark pixels, and unsaturated background do not vote. White cannot
    be distinguished from an unmasked background, so requires a detector label.
    A mostly background/leaf ROI or mixed flower colors returns unknown.
    """
    votes = Counter()
    count = 0
    for pixel in pixels:
        if not _sequence(pixel, 3) or not all(_number(n) and 0 <= n <= 255 for n in pixel):
            continue
        count += 1
        hue, saturation, value = colorsys.rgb_to_hsv(*(channel / 255 for channel in pixel))
        hue *= 360
        if saturation < 0.28 or value < 0.23:
            continue
        color = None
        if hue < 18 or hue >= 345:
            color = "pink" if saturation < 0.57 and value >= 0.65 else "red"
        elif hue < 43:
            color = "orange"
        elif hue < 72:
            color = "yellow"
        elif 170 <= hue < 200:
            color = "cyan"
        elif 200 <= hue < 255:
            color = "blue"
        elif 255 <= hue < 290:
            color = "purple"
        elif 290 <= hue < 345:
            color = "pink" if saturation < 0.57 and value >= 0.65 else "magenta"
        if color:
            votes[color] += 1
    if not count or not votes:
        return {"color": "unknown", "confidence": 0.0, "sample_count": count,
                "reason": "No reliable colored blossom pixels; white requires detector label evidence."}
    color, winning = votes.most_common(1)[0]
    colored = sum(votes.values())
    confidence = winning / count
    if colored / count < 0.30 or winning / colored < 0.70 or confidence < 0.25:
        return {"color": "unknown", "confidence": confidence, "sample_count": count,
                "reason": "Blossom ROI is mostly background/leaves or contains mixed colors."}
    return {"color": color, "confidence": confidence, "sample_count": count, "reason": None}


def build_inventory(detections, calibration, slot_colors=None, context_blockers=None, *, confidence_threshold=0.5):
    """Build a conservative snapshot from one detection/image frame.

    ``slot_colors`` is same-frame evidence keyed by slot id: either a color string
    or a ``classify_bloom_pixels`` result. The caller must sample the configured
    bloom ROI from the exact image used by the detector. Snapshot-level blockers
    prevent every pick; candidate blockers only exclude the affected slot.
    """
    blockers = list(context_blockers or [])
    warnings = []
    calibration = calibration if isinstance(calibration, Mapping) else {}
    image_size = _image_size(calibration.get("image_size"))
    if image_size is None:
        blockers.append("Calibration image_size must contain positive integer width and height.")
    if calibration.get("version") != 1 or isinstance(calibration.get("version"), bool):
        blockers.append("Calibration version must be 1.")
    for key in ("camera", "vision_service"):
        if not isinstance(calibration.get(key), str) or not calibration[key].strip():
            blockers.append(f"Calibration {key} is missing.")
    if not validate_pose(calibration.get("scan_pose")):
        blockers.append("Calibration scan_pose must be a complete finite pose with a nonzero orientation vector.")
    if not _number(confidence_threshold) or not 0 < confidence_threshold <= 1:
        blockers.append("Detection confidence threshold must be greater than 0 and at most 1.")
        confidence_threshold = 0.5

    label_colors = calibration.get("label_colors", {})
    if not isinstance(label_colors, Mapping) or any(
        not isinstance(label, str) or not label.strip() or color not in COLORS
        for label, color in label_colors.items()
    ):
        blockers.append("label_colors must map detector labels to supported colors.")
        label_colors = {}
    label_colors = {label.strip().lower(): color for label, color in label_colors.items()}
    stem_labels = calibration.get("stem_labels", ["stem"])
    if not isinstance(stem_labels, (list, tuple)) or not stem_labels or any(
        not isinstance(label, str) or not label.strip() for label in stem_labels
    ):
        blockers.append("stem_labels must be a nonempty list of detector labels.")
        stem_labels = ["stem"]
    accepted_labels = {label.strip().lower() for label in stem_labels} | set(label_colors)

    raw_slots = calibration.get("slots", [])
    if not isinstance(raw_slots, list):
        blockers.append("Calibration slots must be a list.")
        raw_slots = []
    if not raw_slots:
        blockers.append("No calibrated pickup slots are configured.")
    slots = []
    slot_ids = set()
    for index, raw in enumerate(raw_slots):
        if not isinstance(raw, Mapping) or not isinstance(raw.get("id"), str) or not raw["id"].strip():
            blockers.append(f"Calibration slot {index + 1} needs a nonempty id.")
            continue
        slot_id = raw["id"]
        if slot_id in slot_ids:
            blockers.append(f"Duplicate calibration slot id: {slot_id}.")
            continue
        slot_ids.add(slot_id)
        errors = []
        stem_roi = _box(raw.get("stem_roi"), image_size) if image_size else None
        bloom_roi = _box(raw.get("bloom_roi"), image_size) if image_size else None
        if stem_roi is None:
            errors.append(f"Slot {slot_id} stem_roi is invalid or outside the calibrated image.")
        if raw.get("bloom_roi") is not None and bloom_roi is None:
            errors.append(f"Slot {slot_id} bloom_roi is invalid or outside the calibrated image.")
        poses = raw.get("pickup_poses", {})
        if not isinstance(poses, Mapping) or any(not validate_pose(poses.get(name)) for name in PICKUP_POSES):
            errors.append(f"Slot {slot_id} needs valid pickup_approach, pretend_grasp and lift poses.")
        slots.append({"id": slot_id, "stem_roi": stem_roi, "bloom_roi": bloom_roi,
                      "pickup_poses": deepcopy(poses) if isinstance(poses, Mapping) else {}, "blockers": errors})
    for index, first in enumerate(slots):
        first_grasp = first["pickup_poses"].get("pretend_grasp")
        if not validate_pose(first_grasp):
            continue
        for second in slots[index + 1:]:
            second_grasp = second["pickup_poses"].get("pretend_grasp")
            if not validate_pose(second_grasp):
                continue
            distance = math.dist([first_grasp[key] for key in ("x", "y", "z")],
                                 [second_grasp[key] for key in ("x", "y", "z")])
            if distance <= 5:
                reason = f"Slots {first['id']} and {second['id']} have grasp positions within 5 mm; teach distinct pickup locations."
                first["blockers"].append(reason)
                second["blockers"].append(reason)

    raw_detections = detections if isinstance(detections, (list, tuple)) else []
    if not isinstance(detections, (list, tuple)):
        blockers.append("Detector results must be a list.")
    normalized = []
    for index, detection in enumerate(raw_detections):
        if not isinstance(detection, Mapping):
            warnings.append(f"Detection {index + 1} is malformed.")
            continue
        bbox = _box(detection.get("bbox"), image_size) if image_size else None
        confidence = detection.get("confidence")
        label = detection.get("class_name")
        if bbox is None or not _number(confidence) or not 0 <= confidence <= 1 or not isinstance(label, str):
            warnings.append(f"Detection {index + 1} has an invalid box, label or confidence.")
            continue
        if confidence < confidence_threshold or label.strip().lower() not in accepted_labels:
            continue
        normalized.append({"bbox": bbox, "confidence": confidence, "class_name": label,
                           "_colors": {label_colors[label.strip().lower()]} if label.strip().lower() in label_colors else set(),
                           "blockers": []})
    # Class-agnostic NMS: duplicate labels for one physical stem cannot inflate stock.
    normalized.sort(key=lambda row: (-row["confidence"], *row["bbox"], row["class_name"]))
    kept = []
    for detection in normalized:
        duplicates = [row for row in kept if _iou(row["bbox"], detection["bbox"]) >= 0.5]
        if duplicates:
            # A box bridging two otherwise distinct retained boxes is ambiguous.
            for duplicate in duplicates:
                duplicate["_colors"].update(detection["_colors"])
                if len(duplicates) > 1:
                    duplicate["blockers"].append("Overlapping detector boxes cannot identify distinct stems reliably.")
            continue
        kept.append(detection)
    for index, detection in enumerate(kept):
        detection["id"] = f"detection-{index + 1}"
        labels = detection.pop("_colors")
        detection["label_color"] = next(iter(labels)) if len(labels) == 1 else "unknown"
        if len(labels) > 1:
            detection["blockers"].append("Overlapping detector labels disagree on the flower color.")

    slot_matches = {slot["id"]: [] for slot in slots}
    for detection in kept:
        matches = [slot for slot in slots if slot["stem_roi"] and _contains_center(slot["stem_roi"], detection["bbox"])]
        detection["slot_ids"] = [slot["id"] for slot in matches]
        if not matches:
            detection["blockers"].append("Stem center is outside every calibrated pickup slot.")
        elif len(matches) > 1:
            detection["blockers"].append("Stem matches multiple pickup slots; recalibrate overlapping ROIs.")
        for slot in matches:
            slot_matches[slot["id"]].append(detection)

    candidates = []
    slot_colors = slot_colors if isinstance(slot_colors, Mapping) else {}
    for slot in slots:
        matches = slot_matches[slot["id"]]
        if not matches:
            continue
        best = max(matches, key=lambda row: row["confidence"])
        errors = list(slot["blockers"])
        for match in matches:
            errors.extend(match["blockers"])
        if len(matches) != 1:
            errors.append(f"Multiple stems occupy slot {slot['id']}; only one stem per pickup slot is supported.")
        color = best["label_color"]
        color_source = "detector_label" if color != "unknown" else None
        observed = slot_colors.get(slot["id"], "unknown")
        if isinstance(observed, Mapping):
            observed_confidence = observed.get("confidence")
            observed = observed.get("color", "unknown") if _number(observed_confidence) and 0 < observed_confidence <= 1 else "unknown"
        # White requires detector label evidence; a pale ROI can just be background.
        observed = observed if isinstance(observed, str) and observed in COLORS and observed != "white" else "unknown"
        if slot["bloom_roi"] is None:
            observed = "unknown"
        if color == "unknown" and observed != "unknown" and not any("disagree" in error for error in errors):
            color, color_source = observed, "bloom_roi"
        elif observed != "unknown" and color != "unknown" and observed != color:
            errors.append("Detector label and blossom ROI disagree on the flower color.")
            color = "unknown"
            color_source = None
        if color == "unknown":
            errors.append(f"Slot {slot['id']} has no reliable flower color evidence.")
        candidates.append({"id": slot["id"], "slot_id": slot["id"], "color": color,
                           "color_source": color_source, "confidence": best["confidence"],
                           "bbox": best["bbox"], "pickable": not errors and not blockers,
                           "blockers": _unique(errors + blockers), "pickup_poses": deepcopy(slot["pickup_poses"])})
    if not any(candidate["pickable"] for candidate in candidates):
        blockers.append("No detected stem has a calibrated pickup and reliable color evidence.")
    colors = [{"color": color, "label": color.title(),
               "available": sum(candidate["pickable"] and candidate["color"] == color for candidate in candidates)}
              for color in COLORS]
    return {"ready": not blockers, "blockers": _unique(blockers), "warnings": warnings,
            "colors": colors, "candidates": candidates, "detections": kept,
            "raw_detection_count": len(raw_detections), "image_size": image_size,
            "occupied_slot_ids": [slot["id"] for slot in slots if slot_matches[slot["id"]]],
            "unassigned_detection_count": sum(not detection["slot_ids"] for detection in kept),
            "camera": calibration.get("camera"), "vision_service": calibration.get("vision_service")}


def plan_order(payload, snapshot):
    """Validate an order and allocate each requested flower to a distinct slot.

    A failed order always has zero assignments; callers cannot accidentally run a
    partial bouquet. Freshness and physical scan-pose checks belong to the adapter.
    """
    blockers = []
    items = []
    assignments = []
    requested_total = 0
    rules = {"selection": "highest_confidence"}
    if not isinstance(payload, Mapping):
        payload = {}
        blockers.append("Order must be a JSON object.")
    if set(payload) - {"items", "rules"}:
        blockers.append("Order has unsupported fields.")
    raw_rules = payload.get("rules", {})
    if not isinstance(raw_rules, Mapping) or set(raw_rules) - {"selection"}:
        blockers.append("Only rules.selection is supported.")
    else:
        selection = raw_rules.get("selection", "highest_confidence")
        if selection not in ("highest_confidence", "left_to_right"):
            blockers.append("rules.selection must be highest_confidence or left_to_right.")
        else:
            rules["selection"] = selection
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        blockers.append("Order must include at least one color and positive integer quantity.")
        raw_items = []
    quantities = Counter()
    for item in raw_items:
        if (not isinstance(item, Mapping) or not {"color", "quantity"} <= set(item)
                or set(item) - {"variety", "color", "quantity"}):
            blockers.append("Each order item needs color, quantity, and optionally variety.")
            continue
        color, quantity = item.get("color"), item.get("quantity")
        variety = item.get("variety", "rose")
        if variety not in VARIETIES:
            blockers.append("Order contains an unsupported flower variety.")
            continue
        if not isinstance(color, str) or color not in COLORS:
            blockers.append("Order contains an unsupported flower color.")
            continue
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
            blockers.append(f"Quantity for {color} must be a positive integer.")
            continue
        quantities[(variety, color)] += quantity
    items = [{"variety": variety, "color": color, "quantity": quantity}
             for (variety, color), quantity in quantities.items()]
    requested_total = sum(quantities.values())
    if requested_total > MAX_ORDER_SIZE:
        blockers.append(f"A bouquet can contain at most {MAX_ORDER_SIZE} flowers.")
    snapshot = snapshot if isinstance(snapshot, Mapping) else {}
    if snapshot.get("ready") is not True:
        blockers.extend(snapshot.get("blockers") or ["Inventory is not ready; scan calibrated pickup slots first."])
    raw_candidates = snapshot.get("candidates", [])
    if not isinstance(raw_candidates, list):
        raw_candidates = []
        blockers.append("Inventory candidates are malformed.")
    candidates = []
    seen_ids = set()
    for candidate in raw_candidates:
        if not isinstance(candidate, Mapping) or candidate.get("pickable") is not True:
            continue
        candidate_id = candidate.get("id")
        slot_id = candidate.get("slot_id")
        if not isinstance(candidate_id, str) or not isinstance(slot_id, str) or not candidate_id or not slot_id:
            blockers.append("Inventory contains an invalid candidate id.")
            continue
        if slot_id in seen_ids:
            blockers.append("Inventory contains duplicate pickup slots.")
            continue
        seen_ids.add(slot_id)
        poses = candidate.get("pickup_poses", {})
        if (not _number(candidate.get("confidence")) or not 0 <= candidate["confidence"] <= 1
                or not isinstance(poses, Mapping)
                or any(not validate_pose(poses.get(name)) for name in PICKUP_POSES)
                or candidate.get("color") not in COLORS or candidate.get("blockers")):
            blockers.append(f"Inventory candidate {candidate_id} is not valid for pickup.")
            continue
        bbox = candidate.get("bbox")
        if not _sequence(bbox, 4) or not all(_number(n) for n in bbox) or not (bbox[0] < bbox[2] and bbox[1] < bbox[3]):
            blockers.append(f"Inventory candidate {candidate_id} has an invalid detection box.")
            continue
        candidates.append(candidate)
    for item in items:
        matching = [candidate for candidate in candidates if candidate["color"] == item["color"]
                    and candidate.get("variety", "rose") == item["variety"]]
        if len(matching) < item["quantity"]:
            blockers.append(f"Requested {item['quantity']} {item['color']} {item['variety']}; only {len(matching)} calibrated stems are available.")
        if rules["selection"] == "left_to_right":
            matching.sort(key=lambda row: ((row["bbox"][0] + row["bbox"][2]) / 2, -row["confidence"], row["slot_id"]))
        else:
            matching.sort(key=lambda row: (-row["confidence"], row["slot_id"]))
        assignments.extend(deepcopy(matching[:item["quantity"]]))
    return {"ready": not blockers, "blockers": _unique(blockers), "requested_total": requested_total,
            "assignments": [] if blockers else assignments, "items": items, "rules": rules}
