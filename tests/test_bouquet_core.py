"""Offline checks for evidence-based stock counting and atomic bouquet plans."""
import copy
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bouquet_core import build_inventory, classify_bloom_pixels, plan_order, validate_pose


def pose(x=100):
    return {"x": x, "y": 200, "z": 300, "o_x": 0, "o_y": 0, "o_z": 1, "theta": 90}


def slot(name, left, x):
    return {"id": name, "stem_roi": [left, 0, left + 100, 200],
            "bloom_roi": [left, 0, left + 100, 30],
            "pickup_poses": {"pickup_approach": pose(x), "pretend_grasp": pose(x), "lift": pose(x)}}


def calibration():
    return {"version": 1, "camera": "cam", "vision_service": "vision-1", "image_size": [400, 300],
            "scan_pose": pose(), "slots": [slot("a", 0, 100), slot("b", 150, 200)]}


def detection(left=10, confidence=0.8, label="stem"):
    return {"bbox": [left, 40, left + 30, 180], "confidence": confidence, "class_name": label}


def inventory(colors=None):
    return build_inventory([detection(), detection(160, 0.9)], calibration(), colors or {"a": "red", "b": "red"})


class InventoryTests(unittest.TestCase):
    def test_two_red_stems_allocate_two_distinct_slots(self):
        snapshot = inventory()
        result = plan_order({"items": [{"color": "red", "quantity": 2}]}, snapshot)
        self.assertTrue(result["ready"], result["blockers"])
        self.assertEqual([row["slot_id"] for row in result["assignments"]], ["b", "a"])
        self.assertEqual(snapshot["occupied_slot_ids"], ["a", "b"])
        self.assertEqual(snapshot["raw_detection_count"], 2)

    def test_duplicate_boxes_are_not_double_counted(self):
        snapshot = build_inventory([detection(), detection(11, 0.7)], calibration(), {"a": "red"})
        self.assertEqual(len(snapshot["detections"]), 1)
        self.assertEqual(next(row["available"] for row in snapshot["colors"] if row["color"] == "red"), 1)
        self.assertFalse(plan_order({"items": [{"color": "red", "quantity": 2}]}, snapshot)["ready"])

    def test_duplicate_boxes_across_labels_are_not_double_counted(self):
        config = calibration()
        config["label_colors"] = {"red_rose": "red"}
        snapshot = build_inventory([detection(), detection(11, 0.7, "red_rose")], config)
        self.assertEqual(len(snapshot["detections"]), 1)
        self.assertEqual(snapshot["candidates"][0]["color"], "red")
        self.assertTrue(snapshot["candidates"][0]["pickable"])

    def test_conflicting_duplicate_labels_block_pickup(self):
        config = calibration()
        config["label_colors"] = {"red_rose": "red", "yellow_rose": "yellow"}
        snapshot = build_inventory([detection(label="red_rose"), detection(11, 0.7, "yellow_rose")], config, {"a": "red"})
        self.assertEqual(len(snapshot["detections"]), 1)
        self.assertFalse(snapshot["candidates"][0]["pickable"])
        self.assertIn("disagree", " ".join(snapshot["candidates"][0]["blockers"]))

    def test_ambiguous_slot_overlap_blocks_both_slots(self):
        config = calibration()
        config["slots"][1]["stem_roi"] = [0, 0, 120, 200]
        snapshot = build_inventory([detection()], config, {"a": "red", "b": "red"})
        self.assertFalse(any(row["pickable"] for row in snapshot["candidates"]))
        self.assertEqual(snapshot["occupied_slot_ids"], ["a", "b"])
        self.assertIn("multiple pickup slots", " ".join(snapshot["detections"][0]["blockers"]))

    def test_multiple_stems_in_one_slot_are_not_inventory(self):
        snapshot = build_inventory([detection(5), detection(60)], calibration(), {"a": "red"})
        self.assertFalse(snapshot["ready"])
        self.assertEqual(snapshot["occupied_slot_ids"], ["a"])
        self.assertIn("Multiple stems", " ".join(snapshot["candidates"][0]["blockers"]))

    def test_near_identical_grasp_positions_are_not_two_roses(self):
        config = calibration()
        config["slots"][1]["pickup_poses"]["pretend_grasp"] = pose(103)
        snapshot = build_inventory([detection(), detection(160)], config, {"a": "red", "b": "red"})
        self.assertFalse(snapshot["ready"])
        self.assertTrue(all(not row["pickable"] for row in snapshot["candidates"]))
        self.assertIn("within 5 mm", " ".join(snapshot["candidates"][0]["blockers"]))

    def test_missing_color_does_not_assume_red(self):
        snapshot = build_inventory([detection()], calibration())
        self.assertEqual(snapshot["candidates"][0]["color"], "unknown")
        self.assertFalse(snapshot["candidates"][0]["pickable"])

    def test_explicit_label_color_does_not_require_bloom_roi(self):
        config = calibration()
        config["slots"][0].pop("bloom_roi")
        config["label_colors"] = {"white_rose": "white"}
        snapshot = build_inventory([detection(label="white_rose")], config)
        self.assertEqual(snapshot["candidates"][0]["color"], "white")
        self.assertTrue(snapshot["candidates"][0]["pickable"])

    def test_bloom_color_requires_calibrated_roi(self):
        config = calibration()
        config["slots"][0].pop("bloom_roi")
        snapshot = build_inventory([detection()], config, {"a": "red"})
        self.assertEqual(snapshot["candidates"][0]["color"], "unknown")

    def test_white_pixel_evidence_is_not_white_label_evidence(self):
        snapshot = build_inventory([detection()], calibration(), {"a": "white"})
        self.assertEqual(snapshot["candidates"][0]["color"], "unknown")

    def test_missing_pickup_pose_prevents_pick(self):
        config = calibration()
        config["slots"][0]["pickup_poses"].pop("lift")
        snapshot = build_inventory([detection()], config, {"a": "red"})
        self.assertFalse(snapshot["candidates"][0]["pickable"])

    def test_invalid_pose_values_prevent_pick(self):
        for field, value in (("x", math.nan), ("theta", math.inf), ("o_z", 0), ("z", True)):
            with self.subTest(field=field, value=value):
                config = calibration()
                config["slots"][0]["pickup_poses"]["lift"][field] = value
                snapshot = build_inventory([detection()], config, {"a": "red"})
                self.assertFalse(snapshot["candidates"][0]["pickable"])

    def test_missing_scan_pose_and_wrong_image_size_block_all(self):
        for key, value in (("scan_pose", None), ("image_size", [0, 300]), ("image_size", [400.0, 300])):
            with self.subTest(key=key, value=value):
                config = calibration()
                config[key] = value
                snapshot = build_inventory([detection()], config, {"a": "red"})
                self.assertFalse(snapshot["ready"])
                self.assertFalse(any(row["pickable"] for row in snapshot["candidates"]))

    def test_invalid_boxes_and_confidences_are_rejected(self):
        malformed = [
            {"bbox": [0, 0, math.nan, 200], "confidence": 0.9, "class_name": "stem"},
            {"bbox": [0, 0, 30, 200], "confidence": math.nan, "class_name": "stem"},
            {"bbox": [-1, 0, 30, 200], "confidence": 0.9, "class_name": "stem"},
            {"bbox": [30, 0, 0, 200], "confidence": 0.9, "class_name": "stem"},
            {"bbox": [0, 0, 30, 500], "confidence": 0.9, "class_name": "stem"},
            {"bbox": [0, 0, 30, 200], "confidence": True, "class_name": "stem"},
        ]
        snapshot = build_inventory(malformed, calibration(), {"a": "red"})
        self.assertEqual(snapshot["detections"], [])
        self.assertEqual(snapshot["raw_detection_count"], len(malformed))
        self.assertEqual(len(snapshot["warnings"]), len(malformed))

    def test_low_confidence_and_other_classes_do_not_count(self):
        snapshot = build_inventory([detection(confidence=0.49), detection(label="person")], calibration(), {"a": "red"})
        self.assertEqual(snapshot["detections"], [])

    def test_no_slots_exposes_raw_stems_without_invented_candidates(self):
        config = calibration()
        config["slots"] = []
        snapshot = build_inventory([detection()], config)
        self.assertEqual(snapshot["candidates"], [])
        self.assertEqual(len(snapshot["detections"]), 1)
        self.assertTrue(snapshot["detections"][0]["blockers"])
        self.assertEqual(snapshot["unassigned_detection_count"], 1)
        self.assertFalse(snapshot["ready"])

    def test_frame_context_blocker_excludes_all_candidates(self):
        snapshot = build_inventory([detection()], calibration(), {"a": "red"}, ["Arm moved since scan."])
        self.assertFalse(snapshot["ready"])
        self.assertFalse(snapshot["candidates"][0]["pickable"])

    def test_inventory_builder_does_not_mutate_inputs(self):
        config = calibration()
        raw = [detection()]
        before = copy.deepcopy((config, raw))
        build_inventory(raw, config, {"a": "red"})
        self.assertEqual((config, raw), before)


class OrderTests(unittest.TestCase):
    def test_shortage_prevents_even_partial_assignment(self):
        result = plan_order({"items": [{"color": "red", "quantity": 3}]}, inventory())
        self.assertFalse(result["ready"])
        self.assertEqual(result["assignments"], [])

    def test_duplicate_color_rows_are_merged(self):
        result = plan_order({"items": [{"color": "red", "quantity": 1}, {"color": "red", "quantity": 1}]}, inventory())
        self.assertTrue(result["ready"])
        self.assertEqual(result["requested_total"], 2)
        self.assertEqual(result["items"], [{"color": "red", "quantity": 2}])

    def test_left_to_right_is_deterministic(self):
        result = plan_order({"items": [{"color": "red", "quantity": 2}], "rules": {"selection": "left_to_right"}}, inventory())
        self.assertEqual([row["slot_id"] for row in result["assignments"]], ["a", "b"])

    def test_invalid_quantities_are_not_coerced(self):
        for quantity in (0, -1, True, 1.5, "2", math.nan, math.inf, None):
            with self.subTest(quantity=quantity):
                result = plan_order({"items": [{"color": "red", "quantity": quantity}]}, inventory())
                self.assertFalse(result["ready"])
                self.assertEqual(result["assignments"], [])

    def test_limit_and_unsupported_fields_or_rules_are_rejected(self):
        payloads = [
            {"items": [{"color": "red", "quantity": 13}]},
            {"items": [{"color": "red", "quantity": 1}], "rules": {"selection": "random"}},
            {"items": [{"color": "red", "quantity": 1}], "rules": {"ignore_collisions": True}},
            {"items": [{"color": "red", "quantity": 1}], "move_arm": True},
            {"items": [{"color": "red", "quantity": 1, "type": "rose"}]},
            {"items": [{"color": "green", "quantity": 1}]},
            {"items": []},
            None,
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                self.assertFalse(plan_order(payload, inventory())["ready"])

    def test_forged_duplicate_slot_is_rejected(self):
        snapshot = inventory()
        snapshot["candidates"][1]["slot_id"] = "a"
        result = plan_order({"items": [{"color": "red", "quantity": 2}]}, snapshot)
        self.assertFalse(result["ready"])
        self.assertEqual(result["assignments"], [])

    def test_invalid_candidate_pose_or_confidence_rejected_at_plan_time(self):
        for field in ("pose", "confidence"):
            snapshot = inventory()
            if field == "pose":
                snapshot["candidates"][0]["pickup_poses"]["lift"]["theta"] = math.nan
            else:
                snapshot["candidates"][0]["confidence"] = math.nan
            self.assertFalse(plan_order({"items": [{"color": "red", "quantity": 1}]}, snapshot)["ready"])


class BlossomColorTests(unittest.TestCase):
    def test_reliable_red_and_yellow(self):
        self.assertEqual(classify_bloom_pixels([(220, 15, 15)] * 40)["color"], "red")
        self.assertEqual(classify_bloom_pixels([(240, 230, 10)] * 40)["color"], "yellow")

    def test_green_and_white_background_remain_unknown(self):
        for pixels in ([(20, 220, 20)] * 50, [(255, 255, 255)] * 50,
                       [(220, 15, 15)] * 3 + [(255, 255, 255)] * 97):
            self.assertEqual(classify_bloom_pixels(pixels)["color"], "unknown")

    def test_mixed_blossoms_are_unknown(self):
        pixels = [(220, 15, 15)] * 30 + [(240, 230, 10)] * 30
        self.assertEqual(classify_bloom_pixels(pixels)["color"], "unknown")

    def test_malformed_pixels_and_empty_input_are_unknown(self):
        for pixels in ([], [(math.nan, 0, 0)], [(256, 0, 0)], [(1, 2)], [None]):
            self.assertEqual(classify_bloom_pixels(pixels)["color"], "unknown")


if __name__ == "__main__":
    unittest.main()
