"""Regressions for yellow grasp tape being mistaken for a blossom."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw
from viam.proto.common import Pose
from viam.spatialmath import Quaternion

from bouquet_localization import table_inventory
from test_bouquet_localization import calibration, geometry, detection, rose_image


def marked_calibration():
    config = calibration()
    config.update(grasp_mode="yellow_band", image_workspace_polygon=[[20, 10], [300, 10], [300, 245], [20, 245]])
    config["reference"]["pixel"] = [80, 151]
    return config


def marked_image(color=(220, 10, 20)):
    image = rose_image(blossom_color=color)
    ImageDraw.Draw(image).rectangle((76, 141, 84, 161), fill=(235, 190, 10))
    return image


class MarkerInventoryTests(unittest.TestCase):
    def inventory(self, image=None, config=None, detections=None):
        return table_inventory([detection()] if detections is None else detections,
                               marked_image() if image is None else image,
                               marked_calibration() if config is None else config, geometry())

    def test_grasp_uses_band_instead_of_sixty_percent_of_stem(self):
        result = self.inventory()
        self.assertTrue(result["ready"], result)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["color"], "red")
        self.assertEqual(candidate["grasp_source"], "yellow_band")
        self.assertAlmostEqual(candidate["grasp_pixel"][0], 80)
        self.assertAlmostEqual(candidate["grasp_pixel"][1], 151)
        self.assertEqual(len(candidate["grasp_axis_pixels"]), 2)

    def test_dark_red_blossom_is_red_and_yellow_tape_is_excluded(self):
        result = self.inventory(marked_image((65, 3, 8)))
        self.assertTrue(result["ready"], result)
        self.assertEqual(result["candidates"][0]["color"], "red")
        self.assertFalse(any(b["color"] == "yellow" for b in result["blossoms"]))

    def test_yellow_rose_and_yellow_grasp_band_are_different_objects(self):
        result = self.inventory(marked_image((240, 205, 10)))
        self.assertTrue(result["ready"], result)
        self.assertEqual(result["candidates"][0]["color"], "yellow")

    def test_border_tape_and_outside_roses_do_not_enter_inventory(self):
        image = marked_image()
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 15, 259), fill="yellow")
        draw.rectangle((305, 0, 319, 259), fill="yellow")
        draw.ellipse((1, 25, 17, 60), fill="yellow")
        result = self.inventory(image, detections=[detection(), {"bbox": [0, 65, 15, 220], "confidence": .9, "class_name": "stem"}])
        self.assertTrue(result["ready"], result)
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["candidates"][0]["color"], "red")

    def test_marker_mode_without_marker_never_falls_back_to_fraction(self):
        result = self.inventory(rose_image())
        self.assertFalse(result["ready"])
        candidate = result["candidates"][0]
        self.assertIsNone(candidate["grasp_pixel"])
        self.assertIn("exactly one", " ".join(candidate["blockers"]))

    def test_two_bands_on_same_detected_stem_are_ambiguous(self):
        image = marked_image()
        ImageDraw.Draw(image).rectangle((76, 95, 84, 115), fill=(235, 190, 10))
        result = self.inventory(image)
        self.assertFalse(result["ready"])
        self.assertIn("exactly one", " ".join(result["candidates"][0]["blockers"]))

    def test_band_clipped_by_image_workspace_has_no_grasp_center(self):
        config = marked_calibration()
        config["image_workspace_polygon"] = [[80, 10], [300, 10], [300, 245], [80, 245]]
        result = self.inventory(config=config)
        self.assertFalse(result["ready"])
        self.assertIsNone(result["candidates"][0]["grasp_pixel"])

    def test_detector_box_must_include_the_whole_band(self):
        cut_box = {"bbox": [80, 65, 100, 220], "confidence": .9, "class_name": "stem"}
        result = self.inventory(detections=[cut_box])
        self.assertFalse(result["ready"])
        self.assertIsNone(result["candidates"][0]["grasp_pixel"])

    def test_full_rose_extent_must_fit_world_bounds(self):
        config = marked_calibration()
        config["reference"]["axis_pixels"] = [[80, 185], [80, 116]]
        config["workspace_bounds"]["y"] = [-100, 20]
        result = self.inventory(config=config)
        self.assertFalse(result["ready"])
        self.assertTrue(any("outside" in b for b in result["candidates"][0]["blockers"]))

    def test_missing_blossom_does_not_assign_color_from_band(self):
        image = marked_image("white")
        result = self.inventory(image)
        self.assertFalse(result["ready"])
        self.assertEqual(result["candidates"][0]["color"], "unknown")

    def test_disconnected_red_blossom_is_not_assigned_to_marked_stem(self):
        image = marked_image()
        ImageDraw.Draw(image).rectangle((60, 76, 100, 106), fill="white")
        result = self.inventory(image)
        self.assertFalse(result["ready"])
        self.assertEqual(result["candidates"][0]["color"], "unknown")

    def test_small_red_fleck_on_stem_is_not_a_second_blossom(self):
        image = marked_image()
        ImageDraw.Draw(image).rectangle((79, 94, 81, 103), fill=(65, 3, 8))
        result = self.inventory(image)
        self.assertTrue(result["ready"], result)
        self.assertEqual(result["candidates"][0]["color"], "red")

    def test_two_visible_heads_on_one_marked_stem_remain_ambiguous(self):
        image = marked_image()
        draw = ImageDraw.Draw(image)
        draw.rectangle((50, 20, 110, 64), fill="white")
        draw.line((80, 110, 65, 55), fill=(25, 140, 30), width=5)
        draw.line((80, 110, 95, 55), fill=(25, 140, 30), width=5)
        draw.ellipse((54, 27, 76, 57), fill=(220, 10, 20))
        draw.ellipse((84, 27, 106, 57), fill=(220, 10, 20))
        result = self.inventory(image)
        self.assertFalse(result["ready"], result)
        self.assertIn("No unique blossom", " ".join(result["candidates"][0]["blockers"]))

    def test_shared_band_cannot_supply_two_rose_candidates(self):
        other = {"bbox": [70, 100, 125, 220], "confidence": .85, "class_name": "stem"}
        result = self.inventory(detections=[detection(), other])
        self.assertFalse(result["ready"])
        self.assertEqual(len(result["candidates"]), 2)
        self.assertTrue(all(not c["pickable"] for c in result["candidates"]))
        self.assertTrue(any("shared" in reason for c in result["candidates"] for reason in c["blockers"]))

    def test_stem_must_continue_both_sides_of_a_marker(self):
        image = marked_image()
        ImageDraw.Draw(image).rectangle((65, 162, 95, 235), fill="white")
        result = self.inventory(image)
        self.assertFalse(result["ready"])
        self.assertIsNone(result["candidates"][0]["grasp_pixel"])

    def test_nearly_black_petals_do_not_provide_color_evidence(self):
        result = self.inventory(marked_image((10, 0, 0)))
        self.assertFalse(result["ready"])
        self.assertEqual(result["candidates"][0]["color"], "unknown")

    def test_crossing_through_marker_blocks_grasp(self):
        image = marked_image()
        ImageDraw.Draw(image).line((55, 125, 105, 180), fill=(25, 140, 30), width=5)
        result = self.inventory(image)
        self.assertFalse(result["ready"], result)

    def test_missing_or_invalid_polygon_blocks_marker_mode(self):
        for polygon in (None, [[0, 0]] * 4, [[20, 10], [300, 245], [300, 10], [20, 245]],
                        [[20, 10], [320, 10], [300, 245], [20, 245]]):
            config = marked_calibration()
            config["image_workspace_polygon"] = polygon
            with self.subTest(polygon=polygon):
                self.assertFalse(self.inventory(config=config)["ready"])

    def test_unverified_calibration_never_enables_marker_grasp(self):
        config = marked_calibration()
        config["reference"]["verified"] = False
        result = self.inventory(config=config)
        self.assertFalse(result["ready"])
        self.assertFalse(result["candidates"][0]["pickable"])
        self.assertEqual(result["candidates"][0]["color"], "red")

    def test_unknown_mode_never_enables_motion(self):
        config = marked_calibration()
        config["grasp_mode"] = "automatic"
        self.assertFalse(self.inventory(config=config)["ready"])

    def test_actual_onsite_reference_image_uses_band_and_red_blossom(self):
        folder = Path(__file__).parent / "fixtures"
        metadata = json.loads((folder / "marked_reference.json").read_text())
        image = Image.open(folder / "marked_reference.jpg").convert("RGB")
        camera = metadata["camera_pose"]
        g = {"intrinsics": metadata["intrinsics"], "position": [camera[k] for k in "xyz"],
             "rotation": Quaternion.from_pose(Pose(**camera)).to_rotation_matrix().elements}
        config = marked_calibration()
        config.update(image_size=list(image.size), table_plane_z_mm=metadata["table_z_estimate_mm"],
                      image_workspace_polygon=metadata["image_workspace_polygon"], workspace_bounds=None)
        config["reference"]["verified"] = False
        config["reference"]["pixel"] = metadata["reference_pixel"]
        config["reference"]["axis_pixels"] = metadata["reference_axis"]
        result = table_inventory(metadata["detections"], image, config, g)
        self.assertFalse(result["ready"])
        self.assertEqual(len(result["candidates"]), 1)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["color"], "red", candidate)
        self.assertEqual(candidate["grasp_source"], "yellow_band")
        self.assertLess(sum((a - b) ** 2 for a, b in zip(candidate["grasp_pixel"], metadata["reference_pixel"])), 9)
        self.assertFalse(candidate["pickable"])

    def test_shaded_band_does_not_make_exposed_stem_appear_crossed(self):
        folder = Path(__file__).parent / "fixtures"
        metadata = json.loads((folder / "marked_reference_shadowed.json").read_text())
        image = Image.open(folder / "marked_reference_shadowed.jpg").convert("RGB")
        camera = metadata["camera_pose"]
        g = {"intrinsics": metadata["intrinsics"], "position": [camera[k] for k in "xyz"],
             "rotation": Quaternion.from_pose(Pose(**camera)).to_rotation_matrix().elements}
        config = marked_calibration()
        config.update(image_size=list(image.size), table_plane_z_mm=metadata["table_z_estimate_mm"],
                      image_workspace_polygon=metadata["image_workspace_polygon"], workspace_bounds=None)
        config["reference"].update(verified=False, pixel=metadata["reference_pixel"],
                                   axis_pixels=metadata["reference_axis"])
        result = table_inventory(metadata["detections"], image, config, g)
        self.assertEqual(len(result["candidates"]), 1)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["color"], "red", candidate)
        self.assertEqual(candidate["grasp_source"], "yellow_band")
        self.assertLess(sum((a - b) ** 2 for a, b in zip(candidate["grasp_pixel"], metadata["expected_band_center"])), 1)
        self.assertEqual(len(candidate["pickup_poses"]), 3)
        self.assertTrue(all("unverified" in b or "workspace_bounds" in b for b in candidate["blockers"]), candidate)
        self.assertFalse(candidate["pickable"])
        self.assertFalse(result["ready"])

    def test_onsite_shifted_rose_uses_head_instead_of_red_stem_fleck(self):
        folder = Path(__file__).parent / "fixtures"
        metadata = json.loads((folder / "marked_reference_shifted.json").read_text())
        image = Image.open(folder / "marked_reference_shifted.jpg").convert("RGB")
        camera = metadata["camera_pose"]
        g = {"intrinsics": metadata["intrinsics"], "position": [camera[k] for k in "xyz"],
             "rotation": Quaternion.from_pose(Pose(**camera)).to_rotation_matrix().elements}
        config = marked_calibration()
        config.update(image_size=list(image.size), table_plane_z_mm=metadata["table_z_estimate_mm"],
                      image_workspace_polygon=metadata["image_workspace_polygon"], workspace_bounds=None)
        config["reference"].update(verified=False, pixel=metadata["reference_pixel"],
                                   axis_pixels=metadata["reference_axis"])
        result = table_inventory(metadata["detections"], image, config, g)
        self.assertEqual(len(result["candidates"]), 1)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["color"], "red", candidate)
        self.assertEqual(candidate["grasp_source"], "yellow_band")
        self.assertLess(sum((a - b) ** 2 for a, b in zip(candidate["grasp_pixel"], metadata["expected_band_center"])), 1)
        self.assertEqual(len(candidate["pickup_poses"]), 3)
        self.assertTrue(all("unverified" in b or "workspace_bounds" in b for b in candidate["blockers"]), candidate)
        self.assertFalse(result["ready"])


if __name__ == "__main__":
    unittest.main()
