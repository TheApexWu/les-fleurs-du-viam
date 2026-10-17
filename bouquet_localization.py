"""Read-only, calibrated localization of separate roses lying on a table.

No hardware or network calls are made here. Image-derived pickup poses are only
previews until the measured table/reference calibration is explicitly verified.
"""
from __future__ import annotations

import colorsys
import math
from collections import Counter
from collections.abc import Mapping

from bouquet_core import COLORS, VARIETIES, PICKUP_POSES, POSE_FIELDS, _box, _iou, _number, _sequence, _unique, validate_pose

EMPTY_INVENTORY_BLOCKER = "No detected stem has a calibrated pickup and reliable color evidence."


def _vector(value, size):
    return _sequence(value, size) and all(_number(item) for item in value)


def _geometry(geometry):
    if not isinstance(geometry, Mapping) or not isinstance(geometry.get("intrinsics"), Mapping):
        raise ValueError("Measured camera intrinsics and world transform are required.")
    intrinsics = geometry["intrinsics"]
    if (not all(_number(intrinsics.get(key)) for key in ("fx", "fy", "cx", "cy"))
            or intrinsics["fx"] <= 0 or intrinsics["fy"] <= 0
            or not all(isinstance(intrinsics.get(key), int) and not isinstance(intrinsics[key], bool)
                       and intrinsics[key] > 0 for key in ("width", "height"))):
        raise ValueError("Camera intrinsics must be finite with positive focal lengths and image dimensions.")
    rotation, position = geometry.get("rotation"), geometry.get("position")
    if not _vector(rotation, 9) or not _vector(position, 3):
        raise ValueError("Camera rotation/position must be finite row-major 3x3 and XYZ values.")
    rows = [rotation[index:index + 3] for index in (0, 3, 6)]
    if any(abs(sum(a * b for a, b in zip(first, second)) - (i == j)) > 1e-3
           for i, first in enumerate(rows) for j, second in enumerate(rows)):
        raise ValueError("Camera rotation must be orthonormal.")
    determinant = (rotation[0] * (rotation[4] * rotation[8] - rotation[5] * rotation[7])
                   - rotation[1] * (rotation[3] * rotation[8] - rotation[5] * rotation[6])
                   + rotation[2] * (rotation[3] * rotation[7] - rotation[4] * rotation[6]))
    if abs(determinant - 1) > 1e-3:
        raise ValueError("Camera rotation must have determinant +1.")
    return intrinsics, position, rotation


def project_pixel_to_table(pixel, camera_geometry, table_plane_z_mm):
    """Intersect a camera optical ray with a measured horizontal world plane.

    Camera coordinates use +X right, +Y down, +Z forward. ``rotation`` maps
    optical coordinates into world coordinates. Behind-camera rays are rejected.
    """
    intrinsics, position, rotation = _geometry(camera_geometry)
    if not _vector(pixel, 2) or not 0 <= pixel[0] < intrinsics["width"] or not 0 <= pixel[1] < intrinsics["height"]:
        raise ValueError("Pixel is nonfinite or outside the calibrated camera image.")
    if not _number(table_plane_z_mm):
        raise ValueError("A measured table_plane_z_mm is required.")
    ray = [(pixel[0] - intrinsics["cx"]) / intrinsics["fx"],
           (pixel[1] - intrinsics["cy"]) / intrinsics["fy"], 1.0]
    direction = [sum(rotation[row * 3 + column] * ray[column] for column in range(3)) for row in range(3)]
    if abs(direction[2]) < 1e-8:
        raise ValueError("Camera ray is parallel or nearly parallel to the table.")
    distance = (table_plane_z_mm - position[2]) / direction[2]
    if not _number(distance) or distance <= 0:
        raise ValueError("Table intersection lies behind the camera.")
    point = [position[index] + distance * direction[index] for index in range(3)]
    if not _vector(point, 3):
        raise ValueError("Camera ray produced a nonfinite world point.")
    return point


def _axis_angle(axis):
    if not _sequence(axis, 2) or not all(_vector(point, 3) for point in axis):
        raise ValueError("World stem axis requires two finite XYZ endpoints.")
    dx, dy = axis[1][0] - axis[0][0], axis[1][1] - axis[0][1]
    if math.hypot(dx, dy) < 1e-6:
        raise ValueError("World stem axis has no usable table-plane length.")
    return math.atan2(dy, dx)


def yaw_delta_deg(reference_axis, target_axis):
    delta = _axis_angle(target_axis) - _axis_angle(reference_axis)
    return math.degrees(math.atan2(math.sin(delta), math.cos(delta)))


def transform_pickup_poses(template, reference_world, reference_axis, target_world, target_axis):
    """Apply a measured world XY translation/yaw to every taught pickup pose.

    The transform rotates about the measured reference grasp, retaining gripper
    offsets and approach/lift offsets. Z heights stay taught; world-Z yaw is
    composed with each complete Viam orientation rather than changing theta.
    """
    if not isinstance(template, Mapping) or any(not validate_pose(template.get(key)) for key in PICKUP_POSES):
        raise ValueError("Reference requires three valid taught pickup poses.")
    if not _vector(reference_world, 3) or not _vector(target_world, 3):
        raise ValueError("Reference and target grasp points must be finite XYZ values.")
    from viam.proto.common import Pose
    from viam.spatialmath import Quaternion

    angle = math.radians(yaw_delta_deg(reference_axis, target_axis))
    cosine, sine = math.cos(angle), math.sin(angle)
    rotation = Quaternion(math.cos(angle / 2), 0, 0, math.sin(angle / 2))
    result = {}
    for name in PICKUP_POSES:
        pose = template[name]
        dx, dy = pose["x"] - reference_world[0], pose["y"] - reference_world[1]
        x = target_world[0] + cosine * dx - sine * dy
        y = target_world[1] + sine * dx + cosine * dy
        orientation = rotation * Quaternion.from_pose(Pose(**{key: pose[key] for key in POSE_FIELDS}))
        transformed = orientation.to_pose(x, y, pose["z"])
        result[name] = {key: getattr(transformed, key) for key in POSE_FIELDS}
        # Rust spatialmath can return ~1e-16 XY at an exact OV pole. Feeding that
        # numerical residue back into OV->quaternion chooses a different azimuth.
        # Canonicalize exact poles, then verify the complete orientation roundtrip.
        if math.hypot(result[name]["o_x"], result[name]["o_y"]) < 1e-10:
            result[name]["o_x"] = result[name]["o_y"] = 0.0
            result[name]["o_z"] = math.copysign(1.0, result[name]["o_z"])
        if not validate_pose(result[name]):
            raise ValueError("Pickup pose transform produced an invalid orientation.")
        roundtrip = Quaternion.from_pose(Pose(**result[name]))
        agreement = abs(orientation.w * roundtrip.w + orientation.i * roundtrip.i
                        + orientation.j * roundtrip.j + orientation.k * roundtrip.k)
        if abs(agreement - 1) > 1e-6:
            raise ValueError("Pickup orientation could not be converted to a faithful Viam pose.")
    return result


def _hsv_color(rgb, *, dark_red=False):
    hue, saturation, value = colorsys.rgb_to_hsv(*(channel / 255 for channel in rgb))
    hue *= 360
    if saturation < 0.28:
        return None
    if value < 0.38:
        return "red" if dark_red and value >= 0.08 and saturation >= 0.45 and (hue < 18 or hue >= 345) else None
    if hue < 18 or hue >= 345:
        return "pink" if saturation < 0.57 and value >= 0.65 else "red"
    if hue < 43:
        return "orange" if value >= 0.65 else None  # brown stem/table pixels are not blossoms
    if hue < 72:
        return "yellow"
    if 170 <= hue < 200:
        return "cyan"
    if 200 <= hue < 255:
        return "blue"
    if 255 <= hue < 290:
        return "purple"
    if 290 <= hue < 345:
        return "pink" if saturation < 0.57 and value >= 0.65 else "magenta"
    return None


def _stem_pixel(rgb):
    hue, saturation, value = colorsys.rgb_to_hsv(*(channel / 255 for channel in rgb))
    hue *= 360
    return saturation >= 0.24 and value >= 0.14 and (72 <= hue <= 169 or 18 <= hue <= 60 and value < 0.65)


def _percentile(values, fraction):
    values = sorted(values)
    return values[min(len(values) - 1, int((len(values) - 1) * fraction))]


def estimate_stem_axis(image, bbox):
    """Fit a narrow, continuous stem-colored axis, rejecting leaf/crossing mass."""
    x0, y0, x1, y1 = [int(value) for value in bbox]
    step = max(1, math.ceil(max(x1 - x0, y1 - y0) / 220))
    pixels = image.load()
    points = [(x, y) for y in range(y0, y1, step) for x in range(x0, x1, step) if _stem_pixel(pixels[x, y])]
    if len(points) < 18:
        raise ValueError("Not enough visible green/brown stem pixels to estimate a grasp axis.")
    mx, my = sum(point[0] for point in points) / len(points), sum(point[1] for point in points) / len(points)
    xx = sum((point[0] - mx) ** 2 for point in points) / len(points)
    yy = sum((point[1] - my) ** 2 for point in points) / len(points)
    xy = sum((point[0] - mx) * (point[1] - my) for point in points) / len(points)
    root = math.hypot(xx - yy, 2 * xy)
    major, minor = (xx + yy + root) / 2, (xx + yy - root) / 2
    if major < 25 or major / max(minor, 0.01) < 12:
        raise ValueError("Stem pixels are broad or ambiguous; separate leaves/crossed stems.")
    angle = 0.5 * math.atan2(2 * xy, xx - yy)
    dx, dy = math.cos(angle), math.sin(angle)
    along = [(point[0] - mx) * dx + (point[1] - my) * dy for point in points]
    across = [abs(-(point[0] - mx) * dy + (point[1] - my) * dx) for point in points]
    start, end = _percentile(along, 0.02), _percentile(along, 0.98)
    length = end - start
    if length < 24 or _percentile(across, 0.9) > max(7, 0.06 * length):
        raise ValueError("Stem axis is too short/thick to choose a reliable grasp point.")
    line_tolerance = max(3.5, 0.025 * length)
    if sum(distance <= line_tolerance for distance in across) / len(points) < 0.75:
        raise ValueError("Stem pixels do not support a single narrow centerline.")
    bins = {min(9, max(0, int((value - start) / length * 10))) for value, distance in zip(along, across)
            if start <= value <= end and distance <= line_tolerance}
    if len(bins) < 8:
        raise ValueError("Stem centerline is fragmented; grasp location is uncertain.")
    return {"endpoints": [[mx + start * dx, my + start * dy], [mx + end * dx, my + end * dy]],
            "length_pixels": length, "support_pixels": len(points), "linearity": major / max(minor, 0.01)}


def _blossoms(image, *, polygon=None, excluded_boxes=(), dark_red=False):
    from bouquet_markers import inside_polygon
    step = max(1, math.ceil(max(image.size) / 640))
    pixels = image.load()
    colored = {(x, y): color for y in range(0, image.height, step) for x in range(0, image.width, step)
               if (polygon is None or inside_polygon((x, y), polygon))
               and not any(x0 - step <= x <= x1 + step and y0 - step <= y <= y1 + step
                           for x0, y0, x1, y1 in excluded_boxes)
               and (color := _hsv_color(pixels[x, y], dark_red=dark_red))}
    components = []
    while colored:
        start, color = colored.popitem()
        stack, points, votes = [start], [start], Counter({color: 1})
        while stack:
            x, y = stack.pop()
            for neighbor in ((x - step, y), (x + step, y), (x, y - step), (x, y + step)):
                color = colored.pop(neighbor, None)
                if color:
                    stack.append(neighbor)
                    points.append(neighbor)
                    votes[color] += 1
        if len(points) < 9 or len(points) * step * step > image.width * image.height * 0.12:
            continue
        xs, ys = [point[0] for point in points], [point[1] for point in points]
        width, height = max(xs) - min(xs) + step, max(ys) - min(ys) + step
        if max(width, height) / min(width, height) > 4:
            continue
        color, winning = votes.most_common(1)[0]
        components.append({"id": f"blossom-{len(components) + 1}", "color": color if winning / len(points) >= 0.75 else "unknown",
                           "center": [sum(xs) / len(xs), sum(ys) / len(ys)],
                           "bbox": [min(xs), min(ys), max(xs) + step, max(ys) + step], "radius": max(width, height) / 2})
    return components


def _near_endpoint(blossom, endpoints, index):
    endpoint, other = endpoints[index], endpoints[1 - index]
    dx, dy = endpoint[0] - other[0], endpoint[1] - other[1]
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    bx, by = blossom["center"][0] - endpoint[0], blossom["center"][1] - endpoint[1]
    along, across = bx * ux + by * uy, abs(-bx * uy + by * ux)
    radius = blossom["radius"]
    return (-0.1 * length - 0.3 * radius <= along <= 0.6 * length + radius
            and across <= max(12, 0.10 * length) + 0.5 * radius
            and math.hypot(bx, by) <= max(35, 0.45 * length) + radius)


def _bounds(value):
    if not isinstance(value, Mapping) or any(not _vector(value.get(key), 2) or value[key][0] >= value[key][1]
                                             for key in ("x", "y", "z")):
        return None
    return value


def _in_bounds(point, bounds):
    return bounds is not None and all(bounds[key][0] <= point[index] <= bounds[key][1] for index, key in enumerate(("x", "y", "z")))


def _segments_cross(first, second):
    def orientation(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    a, b = first
    c, d = second
    return orientation(a, b, c) * orientation(a, b, d) < 0 and orientation(c, d, a) * orientation(c, d, b) < 0


def table_inventory(detections, image, calibration, camera_geometry, context_blockers=None, flower_detections=None,
                    commissioning=False):
    """Return read-only same-frame detections, blossom colors and calibrated poses.

    ``reference.axis_pixels`` and generated axes point from cut/base toward blossom.
    ``grasp_fraction`` is measured along that direction; it never uses box center.
    """
    calibration = calibration if isinstance(calibration, Mapping) else {}
    blockers, warnings = list(context_blockers or []), []
    try:
        image = image.convert("RGB")
        size = list(image.size)
    except (AttributeError, ValueError):
        image, size = None, None
        blockers.append("An RGB image from the exact detection frame is required.")
    grasp_mode = calibration.get("grasp_mode", "fraction")
    polygon, bands = None, []
    if grasp_mode not in ("fraction", "yellow_band"):
        blockers.append("grasp_mode must be fraction or yellow_band.")
    if grasp_mode == "yellow_band":
        from bouquet_markers import image_polygon, find_yellow_bands
        try:
            if image is None:
                raise ValueError("Yellow-band grasping needs an RGB image.")
            polygon = image_polygon(calibration.get("image_workspace_polygon"), size)
            bands = find_yellow_bands(image, polygon)
        except ValueError as error:
            blockers.append(str(error))
    if calibration.get("version") != 2 or calibration.get("mode") != "table":
        blockers.append("Free-table localization requires version 2, mode table calibration.")
    for key in ("camera", "vision_service"):
        if not isinstance(calibration.get(key), str) or not calibration[key].strip():
            blockers.append(f"Calibration {key} is missing.")
    if not validate_pose(calibration.get("scan_pose")):
        blockers.append("Capture a valid camera scan_pose before localization.")
    if not size or calibration.get("image_size") != size:
        blockers.append("Calibration image_size must match this exact camera frame.")
    table_z, bounds = calibration.get("table_plane_z_mm"), _bounds(calibration.get("workspace_bounds"))
    if not _number(table_z):
        blockers.append("A measured table_plane_z_mm is required; no table height is assumed.")
    if bounds is None:
        blockers.append("Measured workspace_bounds for X, Y and Z are required.")
    try:
        intrinsics, _, _ = _geometry(camera_geometry)
        if size != [intrinsics["width"], intrinsics["height"]]:
            blockers.append("Camera intrinsics dimensions do not match the image.")
        geometry_valid = True
    except ValueError as error:
        blockers.append(str(error))
        geometry_valid = False
    reference = calibration.get("reference", {})
    if not isinstance(reference, Mapping):
        reference = {}
    if reference.get("verified") is not True:
        blockers.append("Table/reference calibration is unverified; generated poses are preview only.")
    if commissioning:
        warnings.append("Supervised one-flower limit; calibration and preview-correction gates still apply.")
    reference_world = reference_axis = None
    template = reference.get("pickup_poses", {})
    if not isinstance(template, Mapping) or any(not validate_pose(template.get(name)) for name in PICKUP_POSES):
        blockers.append("Reference needs the three working taught pickup poses.")
    if geometry_valid and _number(table_z):
        try:
            reference_world = project_pixel_to_table(reference.get("pixel"), camera_geometry, table_z)
            axis_pixels = reference.get("axis_pixels")
            if not _sequence(axis_pixels, 2):
                raise ValueError("Reference axis_pixels must contain cut-to-blossom axis endpoints.")
            reference_axis = [project_pixel_to_table(point, camera_geometry, table_z) for point in axis_pixels]
            _axis_angle(reference_axis)
            if bounds and any(not _in_bounds(point, bounds) for point in [reference_world, *reference_axis]):
                raise ValueError("Reference grasp/axis is outside the measured workspace.")
        except ValueError as error:
            blockers.append(str(error))
            reference_world = reference_axis = None
    else:
        blockers.append("Reference pixel and directed axis cannot be projected before camera/table calibration.")
    settings = {}
    for name, lower, upper in (("minimum_confidence", 0, 1), ("max_pickup_offset_mm", 0, 10000),
                               ("max_yaw_delta_deg", 0, 180), ("minimum_separation_mm", 0, 10000),
                               ("grasp_fraction", 0, 1)):
        value = calibration.get(name)
        if not _number(value) or not lower < value <= upper or name == "grasp_fraction" and value >= 1:
            blockers.append(f"Calibration {name} must be explicitly set within ({lower}, {upper}].")
            settings[name] = None
        else:
            settings[name] = value
    label_colors = calibration.get("label_colors", {})
    if not isinstance(label_colors, Mapping) or any(not isinstance(key, str) or value not in COLORS for key, value in label_colors.items()):
        blockers.append("label_colors must map detector labels to supported colors.")
        label_colors = {}
    label_colors = {key.lower().strip(): value for key, value in label_colors.items()}
    raw = detections if isinstance(detections, (list, tuple)) else []
    if not isinstance(detections, (list, tuple)):
        blockers.append("Detector results must be a list.")
    accepted = []
    for index, detection in enumerate(raw):
        if not isinstance(detection, Mapping):
            reason = f"Detection {index + 1} is malformed; source occupancy cannot be verified."
            warnings.append(reason)
            blockers.append(reason)
            continue
        bbox = _box(detection.get("bbox"), size) if size else None
        score, label = detection.get("confidence"), detection.get("class_name")
        if bbox is None or not _number(score) or not 0 <= score <= 1 or not isinstance(label, str) or not label.strip():
            reason = f"Detection {index + 1} has an invalid box, confidence or label; source occupancy cannot be verified."
            warnings.append(reason)
            blockers.append(reason)
            continue
        if polygon is not None:
            from bouquet_markers import box_intersects_polygon
            if not box_intersects_polygon(bbox, polygon):
                continue
        if label.strip().lower() not in ({"stem"} | set(label_colors)):
            warnings.append(f"Detection {index + 1} has unsupported class {label!r}; it is not rose inventory.")
            continue
        if score < (settings["minimum_confidence"] or 0.5):
            blockers.append(f"Detection {index + 1} is a low-confidence stem; source occupancy is uncertain.")
            continue
        accepted.append({"bbox": bbox, "confidence": score, "class_name": label, "blockers": [],
                         "_label_colors": {label_colors[label.strip().lower()]} if label.strip().lower() in label_colors else set()})
    accepted.sort(key=lambda row: (-row["confidence"], *row["bbox"], row["class_name"]))
    retained = []
    for detection in accepted:
        overlaps = [other for other in retained if _iou(other["bbox"], detection["bbox"]) >= 0.5]
        if overlaps:
            for other in overlaps:
                other["_label_colors"].update(detection["_label_colors"])
                if len(overlaps) > 1:
                    other["blockers"].append("Overlapping detector boxes cannot distinguish separate stems.")
            continue
        retained.append(detection)
    blossoms = _blossoms(image, polygon=polygon, excluded_boxes=[b["bbox"] for b in bands],
                         dark_red=grasp_mode == "yellow_band") if image else []
    if flower_detections is not None:
        # The teammate's boxes locate BLOOMS. Stem/band geometry remains the
        # independent source of the grasp and cut-to-blossom direction.
        blossoms = []
        for index, flower in enumerate(flower_detections):
            box = _box(flower.get("bbox"), size)
            color, variety, confidence = flower.get("colour"), flower.get("variety"), flower.get("confidence")
            if (box is None or color not in COLORS or variety not in VARIETIES
                    or not _number(confidence) or not 0 <= confidence <= 1):
                warnings.append(f"Flower classifier result {index + 1} is unsupported or malformed.")
                continue
            x0, y0, x1, y1 = box
            center = [(x0 + x1) / 2, (y0 + y1) / 2]
            if polygon is not None:
                from bouquet_markers import inside_polygon
                if not inside_polygon(center, polygon):
                    continue
                if any(not inside_polygon(point, polygon) for point in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))):
                    blockers.append("A classified blossom extends outside the inventory area; expose the entire flower.")
            blossoms.append({"id": f"flower-{index + 1}", "color": color, "variety": variety,
                             "confidence": confidence, "center": center, "bbox": box,
                             "radius": max(x1 - x0, y1 - y0) / 2})
    candidates = []
    associations = Counter()
    marker_associations = Counter()
    for index, detection in enumerate(retained):
        candidate_id = f"provisional-{index + 1}"
        detection["id"] = candidate_id
        colors = detection.pop("_label_colors")
        label_color = next(iter(colors)) if len(colors) == 1 else "unknown"
        errors = list(detection["blockers"])
        if len(colors) > 1:
            errors.append("Overlapping detector labels disagree on rose color.")
        candidate = {"id": candidate_id, "slot_id": candidate_id, "color": label_color,
                     "color_source": "detector_label" if label_color != "unknown" else None,
                     "confidence": detection["confidence"], "bbox": detection["bbox"], "blockers": errors,
                     "pickup_poses": {}, "grasp_pixel": None, "world_grasp": None, "world_axis": None,
                     "axis_pixels": None, "pickable": False}
        candidates.append(candidate)
        try:
            if grasp_mode == "yellow_band":
                from bouquet_markers import marked_stem_axis
                if polygon is None:
                    raise ValueError("A valid image workspace is required before band localization.")
                axis = marked_stem_axis(image, detection["bbox"], bands, polygon, _stem_pixel)
                marker = axis["marker"]
                candidate.update(grasp_source="yellow_band", grasp_marker_bbox=marker["bbox"], grasp_marker_id=marker["id"])
                marker_associations[marker["id"]] += 1
            else:
                axis = estimate_stem_axis(image, detection["bbox"])
            candidate["axis_pixels"] = axis["endpoints"]
            candidate["axis_support_pixels"] = axis["support_pixels"]
            candidate["stem_fit_width_px"] = axis.get("width")
            candidate["stem_fit_length_px"] = axis.get("length", axis.get("length_pixels"))
            if axis.get("marker_exclusion_bbox"):
                candidate["marker_exclusion_bbox"] = axis["marker_exclusion_bbox"]
        except ValueError as error:
            errors.append(str(error))
            continue
        if grasp_mode == "yellow_band":
            from bouquet_markers import band_blossom_matches
            possible = band_blossom_matches(blossoms, axis, image, polygon, _stem_pixel)
        else:
            possible = [(blossom, end) for blossom in blossoms for end in (0, 1)
                        if _near_endpoint(blossom, axis["endpoints"], end)]
        if len(possible) != 1:
            errors.append("No unique blossom is associated with this stem endpoint; separate/fully expose the rose.")
            continue
        blossom, head = possible[0]
        candidate["variety"] = blossom.get("variety", "rose")
        candidate["classification_confidence"] = blossom.get("confidence")
        if _number(blossom.get("confidence")):
            candidate["confidence"] = min(candidate["confidence"], blossom["confidence"])
        candidate["blossom_id"] = blossom["id"]
        candidate["blossom_bbox"] = blossom["bbox"]
        associations[blossom["id"]] += 1
        if len(colors) > 1:
            candidate["color"] = "unknown"
        elif label_color != "unknown" and blossom["color"] != "unknown" and label_color != blossom["color"]:
            errors.append("Detector label and associated blossom disagree on rose color.")
            candidate["color"] = "unknown"
        elif label_color == "unknown":
            candidate["color"] = blossom["color"]
            candidate["color_source"] = ("vision_branch_classifier" if flower_detections is not None else "associated_blossom") if blossom["color"] != "unknown" else None
        endpoints = [axis["endpoints"][1 - head], axis["endpoints"][head]]
        candidate["axis_pixels"] = endpoints
        fraction = settings["grasp_fraction"]
        if fraction is None:
            continue
        if grasp_mode == "yellow_band":
            pixel = list(axis["marker"]["center"])
            candidate["grasp_axis_pixels"] = endpoints
            # Check full cut-to-blossom extents for crossings, while the local
            # narrow stem direction determines the gripper's pickup rotation.
            candidate["axis_pixels"] = [endpoints[0], blossom["center"]]
        else:
            pixel = [endpoints[0][axis] + fraction * (endpoints[1][axis] - endpoints[0][axis]) for axis in range(2)]
        candidate["grasp_pixel"] = pixel
        if not geometry_valid or not _number(table_z):
            continue
        try:
            world = project_pixel_to_table(pixel, camera_geometry, table_z)
            world_axis = [project_pixel_to_table(point, camera_geometry, table_z) for point in endpoints]
            candidate["world_grasp"], candidate["world_axis"] = world, world_axis
            extent = [project_pixel_to_table(point, camera_geometry, table_z) for point in candidate["axis_pixels"]]
            if bounds and any(not _in_bounds(point, bounds) for point in [world, *world_axis, *extent]):
                raise ValueError("Detected grasp/stem axis is outside the measured workspace.")
            if reference_world is None or reference_axis is None:
                continue
            offset = math.dist(world[:2], reference_world[:2])
            yaw = yaw_delta_deg(reference_axis, world_axis)
            candidate["pickup_offset_mm"], candidate["yaw_delta_deg"] = offset, yaw
            if settings["max_pickup_offset_mm"] is not None and offset > settings["max_pickup_offset_mm"]:
                raise ValueError("Pickup displacement exceeds max_pickup_offset_mm from the working reference.")
            if settings["max_yaw_delta_deg"] is not None and abs(yaw) > settings["max_yaw_delta_deg"]:
                raise ValueError("Stem yaw exceeds max_yaw_delta_deg from the working reference.")
            poses = transform_pickup_poses(template, reference_world, reference_axis, world, world_axis)
            if bounds and any(not _in_bounds([pose[key] for key in ("x", "y", "z")], bounds) for pose in poses.values()):
                raise ValueError("A generated pickup/approach/lift pose is outside the measured workspace.")
            candidate["pickup_poses"] = poses
        except (ValueError, ArithmeticError) as error:
            errors.append(str(error))
    for index, first in enumerate(candidates):
        if first.get("grasp_marker_id") and marker_associations[first["grasp_marker_id"]] > 1:
            first["blockers"].append("The grasp band is shared by multiple stem detections; identity is ambiguous.")
        if first.get("blossom_id") and associations[first["blossom_id"]] > 1:
            first["blockers"].append("This blossom is shared by multiple detected stems; pairing is ambiguous.")
        for second in candidates[index + 1:]:
            if first["axis_pixels"] and second["axis_pixels"] and _segments_cross(first["axis_pixels"], second["axis_pixels"]):
                reason = "Stem centerlines cross; separate the roses before picking."
                first["blockers"].append(reason)
                second["blockers"].append(reason)
            if first["world_grasp"] and second["world_grasp"] and settings["minimum_separation_mm"] is not None:
                if math.dist(first["world_grasp"], second["world_grasp"]) < settings["minimum_separation_mm"]:
                    reason = "Rose grasp points are closer than minimum_separation_mm."
                    first["blockers"].append(reason)
                    second["blockers"].append(reason)
        if first["color"] == "unknown":
            first["blockers"].append("No reliable blossom color evidence; white requires a color-labeled detector.")
        if not first["pickup_poses"]:
            first["blockers"].append("No calibrated pickup poses could be generated for this stem.")
        first["blockers"] = _unique(first["blockers"] + blockers)
        first["pickable"] = not first["blockers"]
    # Pairwise checks can add blockers to a candidate already finalized above.
    for candidate in candidates:
        candidate["blockers"] = _unique(candidate["blockers"])
        candidate["pickable"] = not candidate["blockers"]
    if not candidates:
        # The controller permits this exact empty-scene reason during post-pick
        # source verification. An occupied but ambiguous scene must not get it.
        blockers.append(EMPTY_INVENTORY_BLOCKER)
    elif (not any(candidate["pickable"] for candidate in candidates)
          and any(any(reason not in blockers for reason in candidate["blockers"]) for candidate in candidates)):
        # Global calibration blockers already explain a valid grasp preview.
        # Do not mislabel it as a failed stem/blossom association as well.
        blockers.append("No visible rose has an unambiguous blossom, stem axis and verified calibrated pickup.")
    return {"ready": not blockers, "blockers": _unique(blockers), "warnings": warnings, "mode": "table",
            "grasp_bands": bands, "image_workspace_polygon": polygon,
            "image_size": size, "camera": calibration.get("camera"), "vision_service": calibration.get("vision_service"),
            "raw_detection_count": len(raw), "detections": retained, "candidates": candidates, "blossoms": blossoms,
            "occupied_slot_ids": [candidate["slot_id"] for candidate in candidates], "unassigned_detection_count": 0,
            "colors": [{"color": color, "label": color.title(), "available": sum(candidate["pickable"] and candidate["color"] == color for candidate in candidates)} for color in COLORS]}
