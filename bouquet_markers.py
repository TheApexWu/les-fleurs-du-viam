"""Image-only validation of yellow grasp bands inside a calibrated image region.

A band is a grasp marker, never evidence of blossom color. It must have a
single narrow stem continuing on both sides. These helpers make no robot calls.
"""
from __future__ import annotations

import colorsys
import math


def image_polygon(value, size):
    if (not isinstance(value, (list, tuple)) or len(value) != 4
            or any(not isinstance(p, (list, tuple)) or len(p) != 2
                   or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in p)
                   or not 0 <= p[0] < size[0] or not 0 <= p[1] < size[1] for p in value)):
        raise ValueError("Yellow-band grasping requires four valid image_workspace_polygon corners.")
    turns = []
    for i in range(4):
        a, b, c = value[i], value[(i + 1) % 4], value[(i + 2) % 4]
        turns.append((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]))
    if not (all(v > 1 for v in turns) or all(v < -1 for v in turns)):
        raise ValueError("Image workspace corners must form a convex, non-crossed quadrilateral.")
    return value


def inside_polygon(point, polygon):
    x, y = point
    sides = [(b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0])
             for a, b in zip(polygon, polygon[1:] + polygon[:1])]
    return all(v >= 0 for v in sides) or all(v <= 0 for v in sides)


def box_intersects_polygon(box, polygon):
    x0, y0, x1, y1 = box
    rectangle = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    for shape in (rectangle, polygon):
        for a, b in zip(shape, shape[1:] + shape[:1]):
            nx, ny = -(b[1] - a[1]), b[0] - a[0]
            left = [nx * x + ny * y for x, y in rectangle]
            right = [nx * x + ny * y for x, y in polygon]
            if max(left) < min(right) or max(right) < min(left):
                return False
    return True


def _fit(points):
    mx, my = [sum(p[i] for p in points) / len(points) for i in (0, 1)]
    xx = sum((x - mx) ** 2 for x, y in points) / len(points)
    yy = sum((y - my) ** 2 for x, y in points) / len(points)
    xy = sum((x - mx) * (y - my) for x, y in points) / len(points)
    angle = 0.5 * math.atan2(2 * xy, xx - yy)
    dx, dy = math.cos(angle), math.sin(angle)
    along = sorted((x - mx) * dx + (y - my) * dy for x, y in points)
    across = sorted(abs(-(x - mx) * dy + (y - my) * dx) for x, y in points)
    lo, hi = along[int((len(along) - 1) * .02)], along[int((len(along) - 1) * .98)]
    return {"center": [mx, my], "direction": [dx, dy], "length": hi - lo,
            "width": 2 * across[int((len(across) - 1) * .90)],
            "endpoints": [[mx + lo * dx, my + lo * dy], [mx + hi * dx, my + hi * dy]]}


def _yellow_pixel(rgb):
    h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
    return 35 <= h * 360 <= 75 and s >= .45 and v >= .35


def find_yellow_bands(image, polygon):
    step = max(1, math.ceil(max(image.size) / 640))
    pixels = image.load()
    points = set()
    for y in range(0, image.height, step):
        for x in range(0, image.width, step):
            if not inside_polygon((x, y), polygon):
                continue
            if _yellow_pixel(pixels[x, y]):
                points.add((x, y))
    bands = []
    while points:
        start = points.pop()
        stack, component = [start], [start]
        while stack:
            x, y = stack.pop()
            for q in ((x - step, y), (x + step, y), (x, y - step), (x, y + step)):
                if q in points:
                    points.remove(q)
                    component.append(q)
                    stack.append(q)
        if len(component) < 12:
            continue
        if any(not inside_polygon((x + ox, y + oy), polygon)
               for x, y in component for ox, oy in ((2 * step, 0), (-2 * step, 0), (0, 2 * step), (0, -2 * step))):
            continue  # A clipped band cannot define its true center.
        fit = _fit(component)
        if not 10 <= fit["length"] <= image.height * .32 or fit["length"] / max(fit["width"], step) < 2:
            continue
        xs, ys = zip(*component)
        fit.update(id=f"grasp-band-{len(bands) + 1}", bbox=[min(xs), min(ys), max(xs) + step, max(ys) + step])
        bands.append(fit)
    return bands


def marked_stem_axis(image, bbox, bands, polygon, stem_pixel):
    """Associate partial detector boxes through visible stem, never proximity alone."""
    possible, failures = [], []
    for band in bands:
        try:
            axis = _axis_at_band(image, band, polygon, stem_pixel)
        except ValueError as error:
            failures.append(str(error))
            continue
        if _stem_reaches_detection(image, axis, bbox, polygon, stem_pixel):
            possible.append(axis)
    if len(possible) != 1:
        detail = f" {failures[0]}" if len(bands) == 1 and failures else ""
        raise ValueError("Exactly one yellow grasp band must connect through visible stem to this detection; "
                         "no nearest-band or fraction fallback is allowed." + detail)
    return possible[0]


def _stem_reaches_detection(image, axis, bbox, polygon, stem_pixel):
    """Require a continuous narrow corridor from a validated band into the box.

    Some detections cover only the upper stem. A band may sit outside that box,
    but an observed stem must bridge the gap and continue inside it for 24 pixels.
    Missing support, leaving the workspace, or multiple eligible bands rejects it.
    """
    mx, my = axis["marker"]["center"]
    dx, dy = axis["direction"]
    x0, y0, x1, y1 = bbox
    pixels = image.load()
    start = math.ceil(axis["marker"]["length"] / 2 + 5)
    limit = math.ceil(math.hypot(*image.size))
    for sign in (-1, 1):
        missing, inside_support = 0, 0
        for along in range(start, limit, 4):
            cx, cy = mx + sign * dx * along, my + sign * dy * along
            if not (0 <= cx < image.width and 0 <= cy < image.height
                    and inside_polygon((cx, cy), polygon)):
                break
            corridor = math.ceil(max(6, min(20, .04 * along)))
            supported = in_box = False
            for across in range(-corridor, corridor + 1):
                x, y = round(cx - dy * across), round(cy + dx * across)
                if (0 <= x < image.width and 0 <= y < image.height
                        and inside_polygon((x, y), polygon) and stem_pixel(pixels[x, y])):
                    supported = True
                    in_box |= x0 <= x <= x1 and y0 <= y <= y1
            missing = 0 if supported else missing + 4
            if missing > 12:
                break
            inside_support = inside_support + 4 if in_box else 0
            if inside_support >= 24:
                return True
    return False


def _axis_at_band(image, band, polygon, stem_pixel):
    """Keep the original narrow-stem, both-sides and occlusion checks."""
    bx0, by0, bx1, by1 = band["bbox"]
    mx, my = band["center"]
    dx, dy = band["direction"]
    span = max(35, min(130, band["length"] * 1.8))
    corridor = max(10, band["width"] * .85)
    pixels = image.load()
    points = []
    marker_box = [bx0, by0, bx1, by1]
    marker_span = band["length"] / 2 + max(12, band["width"] * 2)
    for y in range(max(0, int(my - span)), min(image.height, int(my + span) + 1)):
        for x in range(max(0, int(mx - span)), min(image.width, int(mx + span) + 1)):
            along, across = (x - mx) * dx + (y - my) * dy, abs(-(x - mx) * dy + (y - my) * dx)
            if abs(along) > span or across > corridor or not inside_polygon((x, y), polygon):
                continue
            # Wrapped tape can split into yellow fragments separated by a dark
            # fold. Account for nearby observed yellow within the band's own
            # corridor before excluding its shaded interior from stem fitting.
            # This changes neither the selected grasp center nor width limits.
            if abs(along) <= marker_span and _yellow_pixel(pixels[x, y]):
                marker_box = [min(marker_box[0], x), min(marker_box[1], y),
                              max(marker_box[2], x), max(marker_box[3], y)]
            if stem_pixel(pixels[x, y]):
                points.append((x, y))
    bx0, by0, bx1, by1 = marker_box
    points = [(x, y) for x, y in points
              if not (bx0 - 2 <= x <= bx1 + 2 and by0 - 2 <= y <= by1 + 2)]
    if len(points) < 24:
        raise ValueError("Not enough visible stem continuation around the grasp band.")
    fit = _fit(points)
    dx, dy = fit["direction"]
    across = abs(-(mx - fit["center"][0]) * dy + (my - fit["center"][1]) * dx)
    if fit["length"] < 35 or fit["width"] > max(7, .08 * fit["length"]) or across > max(6, band["width"] / 2):
        raise ValueError("Stem around the grasp band is broad, crossed or misaligned.")
    side = band["length"] / 2 + 5
    before = [(x - mx) * dx + (y - my) * dy for x, y in points]
    if sum(v < -side for v in before) < 12 or sum(v > side for v in before) < 12:
        raise ValueError("A grasp band needs visible stem on both sides; a yellow blossom is not a grasp band.")
    # Outside the yellow band, large empty gaps cannot stand in for a continuous stem.
    for sign in (-1, 1):
        occupied = sorted({int(sign * v / 5) for v in before if sign * v > side})
        if not occupied or any(b - a > 3 for a, b in zip(occupied, occupied[1:])):
            raise ValueError("Stem continuation around the band is fragmented or occluded.")
    fit.update(marker=band, support_pixels=len(points), marker_exclusion_bbox=marker_box)
    return fit


def _connected_to_blossom(image, axis, blossom, polygon, stem_pixel):
    mx, my = axis["marker"]["center"]
    bx, by = blossom["center"]
    distance = math.hypot(bx - mx, by - my)
    dx, dy = (bx - mx) / distance, (by - my) / distance
    corridor = max(6, .06 * distance)
    start = axis["marker"]["length"] / 2 + 5
    end = distance - blossom["radius"] - 2
    pixels = image.load()
    missing = 0
    for along in range(math.ceil(start), math.floor(end), 4):
        supported = False
        for across in range(-math.ceil(corridor), math.ceil(corridor) + 1):
            x, y = round(mx + dx * along - dy * across), round(my + dy * along + dx * across)
            if (0 <= x < image.width and 0 <= y < image.height
                    and inside_polygon((x, y), polygon) and stem_pixel(pixels[x, y])):
                supported = True
                break
        missing = 0 if supported else missing + 4
        if missing > max(10, .04 * distance):
            return False
    return end > start


def band_blossom_matches(blossoms, axis, image, polygon, stem_pixel):
    mx, my = axis["marker"]["center"]
    dx, dy = axis["direction"]
    matches = []
    for blossom in blossoms:
        x0, y0, x1, y1 = blossom["bbox"]
        # A colored fleck on a bare stem is not a visible blossom head.
        # Require head-color evidence visibly wider than the fitted stem.
        if min(x1 - x0, y1 - y0) <= max(2, 1.5 * axis["width"]):
            continue
        x, y = blossom["center"][0] - mx, blossom["center"][1] - my
        along, across = x * dx + y * dy, abs(-x * dy + y * dx)
        radius = blossom["radius"]
        if (abs(along) > axis["marker"]["length"] * .6 + radius * .35
                and across <= radius + max(8, abs(along) * .08)
                and _connected_to_blossom(image, axis, blossom, polygon, stem_pixel)):
            matches.append((blossom, 1 if along > 0 else 0))
    return matches
