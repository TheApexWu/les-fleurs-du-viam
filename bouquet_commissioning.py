"""Conservative preview bounds and additional supervised one-flower limits.

This policy never verifies calibration or authorizes preview geometry for motion.
"""
from copy import deepcopy
import math

from bouquet_core import validate_pose


def prepare_commissioning(calibration):
    import config as K
    from bouquet_localization import project_pixel_to_table
    from bouquet_vision import camera_geometry_for_scan
    result = deepcopy(calibration)
    preview = result.get("projection_preview")
    if not isinstance(preview, dict):
        raise ValueError("The recorded camera correction is required for commissioning.")
    geometry, _ = camera_geometry_for_scan(result['scan_camera_pose'], preview['intrinsics'], result)
    polygon = [project_pixel_to_table(p, geometry, result['table_plane_z_mm'])[:2]
               for p in result['image_workspace_polygon']]
    poses = result['reference']['pickup_poses']
    if any(not validate_pose(poses.get(key)) for key in ('pickup_approach', 'pretend_grasp', 'lift')):
        raise ValueError("Commissioning requires the three working taught pickup poses.")
    taught = K.taught()
    if any(poses[key] != taught.get(key) for key in ('pickup_approach', 'pretend_grasp', 'lift')):
        raise ValueError("Commissioning must preserve the current working taught pickup poses.")
    result['workspace_bounds'] = {
        'x': [min(p[0] for p in polygon), max(p[0] for p in polygon)],
        'y': [min(p[1] for p in polygon), max(p[1] for p in polygon)],
        'z': [result['table_plane_z_mm'] - 5, max(p['z'] for p in poses.values()) + 15],
    }
    result['max_pickup_offset_mm'] = 60
    result['max_yaw_delta_deg'] = 10
    result['reference']['verified'] = False
    result['commissioning'] = {
        'version': 1, 'world_inventory_polygon': polygon, 'pickup_edge_margin_mm': 25,
        'max_orders_per_process': 1, 'max_flowers_per_order': 1,
        'status': 'Unverified preview geometry; physical execution requires measured, verified calibration',
        'workspace_source': 'Projected measured taped area; axis-aligned bounds plus polygon/edge checks; not independently surveyed robot-world limits',
    }
    return result


def check_commissioning(calibration):
    policy = calibration.get('commissioning', {})
    if policy.get('version') != 1 or not calibration.get('workspace_bounds'):
        raise ValueError("Use the generated commissioning calibration file.")
    for key, maximum in (('max_pickup_offset_mm', 60), ('max_yaw_delta_deg', 10)):
        value = calibration.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= maximum:
            raise ValueError(f"Commissioning {key} must be at most {maximum}.")
    polygon = policy.get('world_inventory_polygon')
    if (not isinstance(polygon, list) or len(polygon) != 4
            or any(not isinstance(p, list) or len(p) != 2
                   or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in p) for p in polygon)):
        raise ValueError("Commissioning needs its projected inventory polygon.")
    margin = policy.get('pickup_edge_margin_mm')
    if isinstance(margin, bool) or not isinstance(margin, (int, float)) or not math.isfinite(margin) or margin < 25:
        raise ValueError("Commissioning pickup-edge margin must be at least 25 mm.")
    return polygon, margin


def check_pickup_region(calibration, candidate):
    from bouquet_markers import inside_polygon
    polygon, margin = check_commissioning(calibration)
    points = [candidate.get('world_grasp')]
    points += [[p[k] for k in 'xyz'] for p in candidate.get('pickup_poses', {}).values()]
    if len(points) != 4 or any(not isinstance(p, (list, tuple)) or len(p) != 3 for p in points):
        raise ValueError("Commissioning needs a localized grasp and three pickup poses.")
    for point in points:
        xy = list(point[:2])
        if not inside_polygon(xy, polygon):
            raise ValueError("Commissioning pickup leaves the projected inventory polygon.")
        for a, b in zip(polygon, polygon[1:] + polygon[:1]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            length = math.hypot(dx, dy)
            if length < 1 or abs(dx * (xy[1] - a[1]) - dy * (xy[0] - a[0])) / length < margin:
                raise ValueError("Commissioning pickup must stay 25 mm inside the inventory edges.")
