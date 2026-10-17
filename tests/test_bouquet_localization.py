"""Synthetic, read-only camera/table localization and pose-transform tests."""
import copy
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw
from viam.proto.common import Pose
from viam.spatialmath import Quaternion

from bouquet_core import plan_order
from bouquet_localization import (
    EMPTY_INVENTORY_BLOCKER, estimate_stem_axis, project_pixel_to_table, table_inventory, transform_pickup_poses, yaw_delta_deg,
)


def pose(x=-80, y=-10, z=30, o_z=-1, theta=30):
    return {"x": x, "y": y, "z": z, "o_x": 0, "o_y": 0, "o_z": o_z, "theta": theta}


def geometry():
    return {"intrinsics": {"fx": 1000, "fy": 1000, "cx": 160, "cy": 120, "width": 320, "height": 260},
            "position": [0, 0, 1000], "rotation": [1, 0, 0, 0, -1, 0, 0, 0, -1]}


def calibration():
    return {"version": 2, "mode": "table", "camera": "cam", "vision_service": "vision-1", "image_size": [320, 260],
            "scan_pose": pose(z=250), "table_plane_z_mm": 0,
            "workspace_bounds": {"x": [-300, 300], "y": [-300, 300], "z": [-1, 400]},
            "reference": {"pixel": [80, 130], "axis_pixels": [[80, 210], [80, 66]],
                          "pickup_poses": {"pickup_approach": pose(z=100), "pretend_grasp": pose(), "lift": pose(z=180)},
                          "verified": True},
            "minimum_confidence": 0.5, "max_pickup_offset_mm": 180, "max_yaw_delta_deg": 90,
            "minimum_separation_mm": 40, "grasp_fraction": 0.6}


def rose_image(xs=(80,), blossom_color=(220, 10, 20)):
    image = Image.new("RGB", (320, 260), "white")
    draw = ImageDraw.Draw(image)
    for x in xs:
        draw.line((x, 66, x, 210), fill=(25, 140, 30), width=5)
        draw.ellipse((x - 15, 29, x + 15, 59), fill=blossom_color)
    return image


def detection(x=80, score=0.9, label="stem"):
    return {"bbox": [x - 18, 65, x + 18, 220], "confidence": score, "class_name": label}


class ProjectionTests(unittest.TestCase):
    def test_known_camera_ray_table_intersection(self):
        self.assertEqual(project_pixel_to_table([160, 120], geometry(), 0), [0, 0, 0])
        self.assertEqual(project_pixel_to_table([180, 150], geometry(), 0), [20, -30, 0])
        self.assertEqual(project_pixel_to_table([180, 150], geometry(), 500), [10, -15, 500])

    def test_behind_camera_and_near_parallel_rays_rejected(self):
        with self.assertRaisesRegex(ValueError, "behind"):
            project_pixel_to_table([160, 120], geometry(), 1500)
        camera = geometry()
        camera["rotation"] = [1, 0, 0, 0, 0, -1, 0, 1, 0]
        with self.assertRaisesRegex(ValueError, "parallel"):
            project_pixel_to_table([160, 120], camera, 0)

    def test_invalid_intrinsics_transform_and_pixel_rejected(self):
        for key, value in (("fx", 0), ("fy", math.nan), ("width", True)):
            camera = geometry()
            camera["intrinsics"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                project_pixel_to_table([160, 120], camera, 0)
        for pixel in ([math.nan, 120], [-1, 120], [320, 120]):
            with self.subTest(pixel=pixel), self.assertRaises(ValueError):
                project_pixel_to_table(pixel, geometry(), 0)
        camera = geometry()
        camera["rotation"][0] = -1  # reflection
        with self.assertRaisesRegex(ValueError, "determinant"):
            project_pixel_to_table([160, 120], camera, 0)

    def test_yaw_transform_keeps_gripper_and_approach_offsets(self):
        template = {"pickup_approach": pose(110, 200, 100), "pretend_grasp": pose(105, 200, 30), "lift": pose(105, 210, 180)}
        source = [100, 200, 0]
        target = [300, 400, 0]
        source_axis = [[100, 200, 0], [150, 200, 0]]
        target_axis = [[300, 400, 0], [300, 450, 0]]
        result = transform_pickup_poses(template, source, source_axis, target, target_axis)
        self.assertAlmostEqual(result["pretend_grasp"]["x"], 300)
        self.assertAlmostEqual(result["pretend_grasp"]["y"], 405)
        self.assertAlmostEqual(result["lift"]["x"], 290)
        self.assertAlmostEqual(result["lift"]["y"], 405)
        self.assertEqual(result["lift"]["z"], 180)
        expected = Quaternion(math.sqrt(0.5), 0, 0, math.sqrt(0.5)) * Quaternion.from_pose(Pose(**template["pretend_grasp"]))
        actual = Quaternion.from_pose(Pose(**result["pretend_grasp"]))
        dot = abs(expected.w * actual.w + expected.i * actual.i + expected.j * actual.j + expected.k * actual.k)
        self.assertAlmostEqual(dot, 1.0, places=6)

    def test_yaw_wrap_and_pole_orientation(self):
        template = {name: pose(o_z=1, theta=0) for name in ("pickup_approach", "pretend_grasp", "lift")}
        result = transform_pickup_poses(template, [0, 0, 0], [[0, 0, 0], [1, 0, 0]], [0, 0, 0], [[0, 0, 0], [0, -1, 0]])
        self.assertTrue(all(math.isfinite(value) for entry in result.values() for value in entry.values()))
        self.assertAlmostEqual(yaw_delta_deg([[0, 0, 0], [-1, 0.01, 0]], [[0, 0, 0], [-1, -0.01, 0]]), 1.145877395, places=6)


class TableInventoryTests(unittest.TestCase):
    def test_synthetic_red_blossom_and_stem_create_calibrated_pick(self):
        result = table_inventory([detection()], rose_image(), calibration(), geometry())
        self.assertTrue(result["ready"], result)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["color"], "red")
        self.assertEqual(candidate["color_source"], "associated_blossom")
        self.assertIsNotNone(candidate["grasp_pixel"])
        self.assertNotEqual(candidate["grasp_pixel"], [80, (65 + 220) / 2])
        self.assertAlmostEqual(candidate["world_grasp"][0], -80)
        self.assertTrue(candidate["pickup_poses"])
        self.assertTrue(plan_order({"items": [{"color": "red", "quantity": 1}]}, result)["ready"])

    def test_two_reds_anywhere_are_distinct_inventory(self):
        result = table_inventory([detection(80), detection(220)], rose_image((80, 220)), calibration(), geometry())
        self.assertTrue(result["ready"], result)
        order = plan_order({"items": [{"color": "red", "quantity": 2}]}, result)
        self.assertTrue(order["ready"], order)
        self.assertEqual(len({row["id"] for row in order["assignments"]}), 2)

    def test_white_background_and_no_blossom_do_not_become_red(self):
        image = rose_image(blossom_color=(255, 255, 255))
        result = table_inventory([detection()], image, calibration(), geometry())
        self.assertFalse(result["ready"])
        self.assertEqual(result["candidates"][0]["color"], "unknown")

    def test_leaf_mass_and_empty_boxes_reject_axis(self):
        image = Image.new("RGB", (320, 260), "white")
        ImageDraw.Draw(image).ellipse((20, 70, 140, 200), fill=(25, 140, 30))
        with self.assertRaisesRegex(ValueError, "broad|thick"):
            estimate_stem_axis(image, [0, 60, 160, 220])
        with self.assertRaisesRegex(ValueError, "Not enough"):
            estimate_stem_axis(Image.new("RGB", (320, 260), "white"), [0, 60, 160, 220])

    def test_crossed_stems_do_not_become_one_grasp_axis(self):
        image = Image.new("RGB", (320, 260), "white")
        draw = ImageDraw.Draw(image)
        draw.line((30, 70, 150, 210), fill=(25, 140, 30), width=4)
        draw.line((150, 70, 30, 210), fill=(25, 140, 30), width=4)
        with self.assertRaisesRegex(ValueError, "broad|ambiguous"):
            estimate_stem_axis(image, [20, 60, 160, 220])

    def test_blossoms_at_both_ends_are_ambiguous(self):
        image = rose_image()
        ImageDraw.Draw(image).ellipse((65, 222, 95, 252), fill=(220, 10, 20))
        result = table_inventory([detection()], image, calibration(), geometry())
        self.assertFalse(result["ready"])
        self.assertIn("unique blossom", " ".join(result["candidates"][0]["blockers"]))

    def test_shared_blossom_rejects_both_stems(self):
        image = Image.new("RGB", (320, 260), "white")
        draw = ImageDraw.Draw(image)
        for x in (70, 90):
            draw.line((x, 66, x, 210), fill=(25, 140, 30), width=3)
        draw.ellipse((58, 22, 102, 62), fill=(220, 10, 20))
        detections = [{"bbox": [x - 5, 65, x + 5, 220], "confidence": 0.9, "class_name": "stem"} for x in (70, 90)]
        result = table_inventory(detections, image, calibration(), geometry())
        self.assertFalse(result["ready"])
        self.assertTrue(all(any("shared" in reason for reason in candidate["blockers"]) for candidate in result["candidates"]))

    def test_duplicate_detector_boxes_count_once(self):
        duplicate = detection(score=0.8)
        duplicate["bbox"][0] += 1
        result = table_inventory([detection(), duplicate], rose_image(), calibration(), geometry())
        self.assertEqual(result["raw_detection_count"], 2)
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["occupied_slot_ids"], ["provisional-1"])

    def test_unknown_calibration_keeps_detections_but_blocks_pickup(self):
        config = calibration()
        config["table_plane_z_mm"] = None
        config["reference"]["verified"] = False
        result = table_inventory([detection()], rose_image(), config, geometry())
        self.assertEqual(len(result["detections"]), 1)
        self.assertEqual(result["candidates"][0]["color"], "red")
        self.assertFalse(result["candidates"][0]["pickable"])

    def test_missing_or_nonfinite_mechanical_values_never_enable_motion(self):
        for key, value in (("table_plane_z_mm", math.nan), ("workspace_bounds", None),
                           ("grasp_fraction", None), ("minimum_confidence", math.inf),
                           ("max_pickup_offset_mm", 0), ("max_yaw_delta_deg", None),
                           ("minimum_separation_mm", -1)):
            config = calibration()
            config[key] = value
            with self.subTest(key=key):
                result = table_inventory([detection()], rose_image(), config, geometry())
                self.assertFalse(result["ready"])
                self.assertFalse(result["candidates"][0]["pickable"])

    def test_invalid_reference_axis_blocks_even_good_rose(self):
        for axis in (None, [[80, 130], [80, 130]], [[80, 130], [math.nan, 50]]):
            config = calibration()
            config["reference"]["axis_pixels"] = axis
            with self.subTest(axis=axis):
                result = table_inventory([detection()], rose_image(), config, geometry())
                self.assertFalse(result["ready"])
                self.assertFalse(result["candidates"][0]["pickable"])

    def test_low_confidence_and_nonstem_detections_do_not_create_stock(self):
        result = table_inventory([detection(score=0.49), detection(label="person")], rose_image(), calibration(), geometry())
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["raw_detection_count"], 2)

    def test_empty_scene_has_only_the_controller_compatible_empty_reason(self):
        result = table_inventory([], Image.new("RGB", (320, 260), "white"), calibration(), geometry())
        self.assertEqual(result["blockers"], [EMPTY_INVENTORY_BLOCKER])
        self.assertEqual(result["occupied_slot_ids"], [])
        ambiguous = table_inventory([detection()], rose_image(blossom_color="white"), calibration(), geometry())
        self.assertNotIn(EMPTY_INVENTORY_BLOCKER, ambiguous["blockers"])

    def test_malformed_output_cannot_verify_a_cleared_source(self):
        invalid = [None, {"bbox": [70, 70, math.nan, 220], "confidence": 0.9, "class_name": "stem"},
                   {"bbox": [70, 70, 90, 220], "confidence": math.nan, "class_name": "stem"},
                   {"bbox": [70, 70, 90, 220], "confidence": 0.9, "class_name": None},
                   {"bbox": [70, 70, 90, 220], "confidence": 0.9, "class_name": ""}]
        for record in invalid:
            with self.subTest(record=record):
                result = table_inventory([record], rose_image(), calibration(), geometry())
                remaining = [reason for reason in result["blockers"] if reason != EMPTY_INVENTORY_BLOCKER]
                self.assertTrue(remaining, result)
                self.assertTrue(any("occupancy" in reason for reason in remaining))
                self.assertFalse(result["ready"])

    def test_low_confidence_stem_cannot_verify_a_cleared_source(self):
        result = table_inventory([detection(score=0.49)], rose_image(), calibration(), geometry())
        self.assertNotEqual(result["blockers"], [EMPTY_INVENTORY_BLOCKER])
        self.assertTrue(any("low-confidence stem" in reason for reason in result["blockers"]))

    def test_supported_color_label_below_threshold_also_means_uncertain_occupancy(self):
        config = calibration()
        config["label_colors"] = {"red_rose": "red"}
        result = table_inventory([detection(score=0.1, label="red_rose")], rose_image(), config, geometry())
        self.assertTrue(any("occupancy is uncertain" in reason for reason in result["blockers"]))

    def test_valid_unsupported_class_is_only_a_warning(self):
        result = table_inventory([detection(label="person")], rose_image(), calibration(), geometry())
        self.assertEqual(result["blockers"], [EMPTY_INVENTORY_BLOCKER])
        self.assertEqual(len(result["warnings"]), 1)

    def test_mixed_color_blossom_is_unknown(self):
        image = rose_image()
        draw = ImageDraw.Draw(image)
        draw.rectangle((65, 29, 80, 59), fill=(235, 225, 10))
        result = table_inventory([detection()], image, calibration(), geometry())
        self.assertFalse(result["ready"])
        self.assertEqual(result["candidates"][0]["color"], "unknown")

    def test_unverified_reference_returns_pose_previews_only(self):
        config = calibration()
        config["reference"]["verified"] = False
        result = table_inventory([detection()], rose_image(), config, geometry())
        self.assertFalse(result["ready"])
        self.assertFalse(result["candidates"][0]["pickable"])
        self.assertTrue(result["candidates"][0]["pickup_poses"])

    def test_workspace_limit_rejects_generated_approach(self):
        config = calibration()
        config["workspace_bounds"]["z"] = [-1, 80]
        result = table_inventory([detection()], rose_image(), config, geometry())
        self.assertFalse(result["ready"])
        self.assertIn("generated", " ".join(result["candidates"][0]["blockers"]))

    def test_outside_table_bounds_rejects_projection(self):
        config = calibration()
        config["workspace_bounds"]["x"] = [-100, -60]
        result = table_inventory([detection(220)], rose_image((220,)), config, geometry())
        self.assertFalse(result["ready"])
        self.assertIn("outside", " ".join(result["candidates"][0]["blockers"]))

    def test_max_displacement_and_yaw_limits(self):
        config = calibration()
        config["max_pickup_offset_mm"] = 30
        result = table_inventory([detection(220)], rose_image((220,)), config, geometry())
        self.assertFalse(result["ready"])
        self.assertIn("displacement", " ".join(result["candidates"][0]["blockers"]))
        config = calibration()
        config["reference"]["axis_pixels"] = [[10, 130], [100, 130]]
        config["max_yaw_delta_deg"] = 20
        result = table_inventory([detection()], rose_image(), config, geometry())
        self.assertFalse(result["ready"])
        self.assertIn("yaw", " ".join(result["candidates"][0]["blockers"]))

    def test_insufficient_separation_rejects_two_roses(self):
        config = calibration()
        config["minimum_separation_mm"] = 160
        result = table_inventory([detection(80), detection(220)], rose_image((80, 220)), config, geometry())
        self.assertFalse(result["ready"])
        self.assertTrue(all(any("separation" in reason for reason in row["blockers"]) for row in result["candidates"]))

    def test_exact_frame_size_context_and_nonfinite_detection(self):
        config = calibration()
        config["image_size"] = [640, 520]
        bad = detection()
        bad["confidence"] = math.nan
        result = table_inventory([detection(), bad], rose_image(), config, geometry(), ["Arm is away from scan pose."])
        self.assertFalse(result["ready"])
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("scan pose", " ".join(result["blockers"]))

    def test_label_color_conflict_is_not_resolved_arbitrarily(self):
        config = calibration()
        config["label_colors"] = {"yellow_stem": "yellow"}
        result = table_inventory([detection(label="yellow_stem")], rose_image(), config, geometry())
        self.assertFalse(result["ready"])
        self.assertEqual(result["candidates"][0]["color"], "unknown")

    def test_inputs_are_not_mutated(self):
        config, raw, camera = calibration(), [detection()], geometry()
        original = copy.deepcopy((config, raw, camera))
        table_inventory(raw, rose_image(), config, camera)
        self.assertEqual((config, raw, camera), original)


if __name__ == "__main__":
    unittest.main()
